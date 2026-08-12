from types import SimpleNamespace
from unittest.mock import MagicMock, PropertyMock, call, patch

import psycopg
import pytest

from data_copilot.databases import DatabaseRegistry, PostgresConnectionConfig
from data_copilot.databases.constants import MAX_QUERY_COLUMNS, MAX_QUERY_ROWS
from data_copilot.errors import (
    DatabaseNotFoundError,
    QueryResultTooWideError,
    QueryTimeoutError,
    SQLAmbiguousColumnError,
    SQLExecutionError,
    SQLGroupingError,
    SQLObjectNotFoundError,
    SQLTypeMismatchError,
    UnsafeSQLError,
)
from data_copilot.execution.postgres_engine import PostgresEngine


DSN = "postgresql://analyst:super-secret@db.example:5432/analytics"


def _engine() -> tuple[PostgresEngine, str]:
    registry = DatabaseRegistry()
    database = registry.register(
        PostgresConnectionConfig(
            dsn=DSN,
            database_name="analytics",
            connect_timeout_seconds=7,
            statement_timeout_ms=12000,
        )
    )
    return PostgresEngine(registry), database.database_id


def _connection(
    *,
    columns: tuple[str, ...] = ("value",),
    rows: list[tuple[object, ...]] | None = None,
) -> tuple[MagicMock, MagicMock, MagicMock, MagicMock]:
    connection = MagicMock()
    control_cursor = MagicMock()
    query_cursor = MagicMock()
    control_context = MagicMock()
    query_context = MagicMock()
    control_context.__enter__.return_value = control_cursor
    query_context.__enter__.return_value = query_cursor
    connection.cursor.side_effect = lambda *args, **kwargs: (
        query_context if kwargs.get("name") else control_context
    )
    query_cursor.description = tuple(SimpleNamespace(name=name) for name in columns)
    query_cursor.fetchmany.return_value = [(1,)] if rows is None else rows
    context = MagicMock()
    context.__enter__.return_value = connection
    return context, connection, control_cursor, query_cursor


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT id, amount FROM orders",
        "WITH completed AS (SELECT amount FROM orders WHERE status = 'done') "
        "SELECT SUM(amount) AS total FROM completed",
        "SELECT region, COUNT(*) AS count FROM orders GROUP BY region",
    ],
)
def test_valid_read_query_executes_with_read_only_timeout_and_bounded_fetch(
    sql: str,
) -> None:
    engine, database_id = _engine()
    context, connection, control_cursor, cursor = _connection(
        columns=("region", "count"),
        rows=[("north", 3), ("south", 2)],
    )

    with patch(
        "data_copilot.execution.postgres_engine.psycopg.connect",
        return_value=context,
    ) as connect:
        result = engine.execute_read_query(database_id, sql)

    connect.assert_called_once_with(DSN, connect_timeout=7)
    assert connection.read_only is True
    control_cursor.execute.assert_called_once_with(
        "SELECT pg_catalog.set_config('statement_timeout', %s, TRUE)",
        ("12000",),
    )
    connection.cursor.assert_any_call(name="_data_copilot_read_query")
    assert cursor.execute.call_args_list[0].args[0].startswith(("SELECT", "WITH"))
    cursor.fetchmany.assert_called_once_with(MAX_QUERY_ROWS + 1)
    assert result.columns == ("region", "count")
    assert result.rows == (("north", 3), ("south", 2))
    assert result.row_count == 2
    assert result.truncated is False


def test_validator_rejection_happens_before_registry_or_connection() -> None:
    engine = PostgresEngine(DatabaseRegistry())

    with patch("data_copilot.execution.postgres_engine.psycopg.connect") as connect:
        with pytest.raises(UnsafeSQLError):
            engine.execute_read_query("db_unknown", "DELETE FROM orders")

    connect.assert_not_called()


def test_explain_is_validated_then_rejected_before_connection() -> None:
    engine, database_id = _engine()

    with patch("data_copilot.execution.postgres_engine.psycopg.connect") as connect:
        with pytest.raises(SQLExecutionError, match="EXPLAIN"):
            engine.execute_read_query(database_id, "EXPLAIN SELECT 1")

    connect.assert_not_called()


def test_unknown_database_id_does_not_connect_after_valid_sql() -> None:
    engine = PostgresEngine(DatabaseRegistry())

    with patch("data_copilot.execution.postgres_engine.psycopg.connect") as connect:
        with pytest.raises(DatabaseNotFoundError):
            engine.execute_read_query("db_unknown", "SELECT 1")

    connect.assert_not_called()


def test_read_only_setup_failure_prevents_timeout_and_query() -> None:
    engine, database_id = _engine()
    context, connection, control_cursor, cursor = _connection()
    type(connection).read_only = PropertyMock(
        side_effect=psycopg.OperationalError("read-only failed")
    )

    with patch(
        "data_copilot.execution.postgres_engine.psycopg.connect",
        return_value=context,
    ):
        with pytest.raises(SQLExecutionError):
            engine.execute_read_query(database_id, "SELECT 1")

    control_cursor.execute.assert_not_called()
    cursor.execute.assert_not_called()


def test_query_timeout_is_sanitized() -> None:
    engine, database_id = _engine()
    context, _, _, cursor = _connection()
    cursor.execute.side_effect = psycopg.errors.QueryCanceled("raw SQL secret")

    with patch(
        "data_copilot.execution.postgres_engine.psycopg.connect",
        return_value=context,
    ):
        with pytest.raises(QueryTimeoutError) as captured:
            engine.execute_read_query(
                database_id,
                "SELECT COUNT(*) FROM orders a CROSS JOIN orders b",
            )

    assert "raw SQL secret" not in str(captured.value)
    assert "super-secret" not in str(captured.value)
    assert captured.value.__cause__ is None


@pytest.mark.parametrize(
    "driver_error",
    [psycopg.errors.UndefinedColumn(), psycopg.errors.UndefinedTable()],
)
def test_unknown_table_or_column_has_safe_recoverable_error(
    driver_error: psycopg.Error,
) -> None:
    engine, database_id = _engine()
    context, _, _, cursor = _connection()
    cursor.execute.side_effect = driver_error

    with patch(
        "data_copilot.execution.postgres_engine.psycopg.connect",
        return_value=context,
    ):
        with pytest.raises(SQLObjectNotFoundError, match="table or column"):
            engine.execute_read_query(database_id, "SELECT missing FROM unknown")


@pytest.mark.parametrize(
    ("driver_error", "expected_error", "public_message"),
    [
        (
            psycopg.errors.AmbiguousColumn("raw secret"),
            SQLAmbiguousColumnError,
            "ambiguous",
        ),
        (
            psycopg.errors.DatatypeMismatch("raw secret"),
            SQLTypeMismatchError,
            "incompatible PostgreSQL data types",
        ),
        (
            psycopg.errors.GroupingError("raw secret"),
            SQLGroupingError,
            "invalid grouping",
        ),
    ],
)
def test_actionable_sql_error_categories_are_sanitized(
    driver_error: psycopg.Error,
    expected_error: type[SQLExecutionError],
    public_message: str,
) -> None:
    engine, database_id = _engine()
    context, _, _, cursor = _connection()
    cursor.execute.side_effect = driver_error

    with patch(
        "data_copilot.execution.postgres_engine.psycopg.connect",
        return_value=context,
    ):
        with pytest.raises(expected_error) as captured:
            engine.execute_read_query(database_id, "SELECT value FROM a JOIN b ON true")

    assert public_message in str(captured.value)
    assert "raw secret" not in str(captured.value)
    assert captured.value.__cause__ is None


def test_connection_failure_is_sanitized() -> None:
    engine, database_id = _engine()

    with patch(
        "data_copilot.execution.postgres_engine.psycopg.connect",
        side_effect=psycopg.OperationalError(DSN),
    ):
        with pytest.raises(SQLExecutionError) as captured:
            engine.execute_read_query(database_id, "SELECT 1")

    assert "super-secret" not in str(captured.value)
    assert "SELECT" not in str(captured.value)


def test_row_fetch_is_truncated_with_explicit_warning() -> None:
    engine, database_id = _engine()
    context, _, _, _ = _connection(
        rows=[(index,) for index in range(MAX_QUERY_ROWS + 1)]
    )

    with patch(
        "data_copilot.execution.postgres_engine.psycopg.connect",
        return_value=context,
    ):
        result = engine.execute_read_query(database_id, "SELECT id FROM orders")

    assert len(result.rows) == MAX_QUERY_ROWS
    assert result.truncated is True
    assert result.warnings == (
        "Query rows were truncated to MAX_QUERY_ROWS=200.",
    )


def test_result_too_wide_fails_before_fetching_rows() -> None:
    engine, database_id = _engine()
    context, _, _, cursor = _connection(
        columns=tuple(f"column_{index}" for index in range(MAX_QUERY_COLUMNS + 1))
    )

    with patch(
        "data_copilot.execution.postgres_engine.psycopg.connect",
        return_value=context,
    ):
        with pytest.raises(QueryResultTooWideError, match="MAX_QUERY_COLUMNS=50"):
            engine.execute_read_query(database_id, "SELECT * FROM wide_table")

    cursor.fetchmany.assert_not_called()
