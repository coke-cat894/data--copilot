from unittest.mock import MagicMock, PropertyMock, patch

import psycopg
import pytest

from data_copilot.databases import DatabaseRegistry, PostgresConnectionConfig
from data_copilot.errors import DatabaseConnectionError, DatabaseNotFoundError
from data_copilot.execution.postgres_engine import PostgresEngine


DSN = "postgresql://analyst:super-secret@db.example:5432/analytics"


def _registered() -> tuple[DatabaseRegistry, str]:
    registry = DatabaseRegistry()
    database = registry.register(
        PostgresConnectionConfig(
            dsn=DSN,
            database_name="analytics",
            connect_timeout_seconds=7,
        )
    )
    return registry, database.database_id


def _mock_connection(row: tuple[int] | None = (1,)) -> tuple[MagicMock, MagicMock]:
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    cursor.fetchone.return_value = row
    return connection, cursor


def test_ping_connects_by_id_sets_read_only_and_executes_fixed_health_check() -> None:
    registry, database_id = _registered()
    connection, cursor = _mock_connection()
    connect_context = MagicMock()
    connect_context.__enter__.return_value = connection

    with patch("data_copilot.execution.postgres_engine.psycopg.connect") as connect:
        connect.return_value = connect_context
        result = PostgresEngine(registry).ping(database_id)

    connect.assert_called_once_with(DSN, connect_timeout=7)
    assert connection.read_only is True
    cursor.execute.assert_called_once_with("SELECT 1")
    cursor.fetchone.assert_called_once_with()
    assert result.connected is True
    assert result.database_type.value == "postgresql"
    assert result.database_name == "analytics"


def test_connection_failure_is_sanitized() -> None:
    registry, database_id = _registered()

    with patch(
        "data_copilot.execution.postgres_engine.psycopg.connect",
        side_effect=psycopg.OperationalError(f"could not connect using {DSN}"),
    ):
        with pytest.raises(DatabaseConnectionError) as captured:
            PostgresEngine(registry).ping(database_id)

    assert database_id in str(captured.value)
    assert "super-secret" not in str(captured.value)
    assert "super-secret" not in repr(captured.value)
    assert captured.value.__cause__ is None


def test_read_only_setup_failure_fails_closed_without_querying() -> None:
    registry, database_id = _registered()
    connection, cursor = _mock_connection()
    type(connection).read_only = PropertyMock(
        side_effect=psycopg.OperationalError("read-only setup failed")
    )
    connect_context = MagicMock()
    connect_context.__enter__.return_value = connection

    with patch(
        "data_copilot.execution.postgres_engine.psycopg.connect",
        return_value=connect_context,
    ):
        with pytest.raises(DatabaseConnectionError):
            PostgresEngine(registry).ping(database_id)

    cursor.execute.assert_not_called()


def test_invalid_health_check_response_fails_closed() -> None:
    registry, database_id = _registered()
    connection, _ = _mock_connection((2,))
    connect_context = MagicMock()
    connect_context.__enter__.return_value = connection

    with patch(
        "data_copilot.execution.postgres_engine.psycopg.connect",
        return_value=connect_context,
    ):
        with pytest.raises(DatabaseConnectionError, match="invalid health-check"):
            PostgresEngine(registry).ping(database_id)


def test_unknown_database_id_does_not_attempt_connection() -> None:
    registry = DatabaseRegistry()

    with patch("data_copilot.execution.postgres_engine.psycopg.connect") as connect:
        with pytest.raises(DatabaseNotFoundError):
            PostgresEngine(registry).ping("db_unknown")

    connect.assert_not_called()


def test_engine_exposes_no_generic_sql_api() -> None:
    engine = PostgresEngine(DatabaseRegistry())

    assert not hasattr(engine, "execute_sql")
    assert not hasattr(engine, "run_sql")
    assert not hasattr(engine, "execute")
