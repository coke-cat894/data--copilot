from unittest.mock import MagicMock, PropertyMock, call, patch

import psycopg
import pytest

from data_copilot.databases import DatabaseRegistry, PostgresConnectionConfig
from data_copilot.errors import (
    ExplainQueryError,
    QueryTimeoutError,
    SQLObjectNotFoundError,
    SQLAmbiguousColumnError,
    SQLGroupingError,
    SQLTypeMismatchError,
    UnsafeSQLError,
)
from data_copilot.execution import PostgresEngine


DSN = "postgresql://analyst:super-secret@db.example:5432/analytics"
SIMPLE_PLAN = [
    {
        "Plan": {
            "Node Type": "Seq Scan",
            "Relation Name": "orders",
            "Alias": "o",
            "Startup Cost": 0.0,
            "Total Cost": 100.5,
            "Plan Rows": 5000,
            "Plan Width": 32,
        }
    }
]


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
    row: tuple[object, ...] | None = (SIMPLE_PLAN,),
) -> tuple[MagicMock, MagicMock, MagicMock]:
    connection = MagicMock()
    cursor = MagicMock()
    cursor.fetchone.return_value = row
    cursor_context = MagicMock()
    cursor_context.__enter__.return_value = cursor
    connection.cursor.return_value = cursor_context
    connection_context = MagicMock()
    connection_context.__enter__.return_value = connection
    return connection_context, connection, cursor


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM orders",
        "WITH recent AS (SELECT * FROM orders) SELECT * FROM recent",
        "SELECT id FROM orders UNION SELECT id FROM archived_orders",
    ],
)
def test_valid_query_uses_program_owned_json_explain_without_execution(
    sql: str,
) -> None:
    engine, database_id = _engine()
    context, connection, cursor = _connection()

    with patch(
        "data_copilot.execution.postgres_engine.psycopg.connect",
        return_value=context,
    ) as connect:
        result = engine.explain_query(database_id, sql)

    connect.assert_called_once_with(DSN, connect_timeout=7)
    assert connection.read_only is True
    assert cursor.execute.call_args_list[0] == call(
        "SELECT pg_catalog.set_config('statement_timeout', %s, TRUE)",
        ("12000",),
    )
    explained_sql = cursor.execute.call_args_list[1].args[0]
    assert explained_sql.startswith("EXPLAIN (FORMAT JSON) ")
    assert "ANALYZE" not in explained_sql
    assert explained_sql.endswith(("orders", "recent", "archived_orders"))
    assert result.database_id == database_id
    assert result.root.node_type == "Seq Scan"
    assert result.node_count == 1


def test_validator_rejects_mutation_before_registry_or_connection() -> None:
    engine = PostgresEngine(DatabaseRegistry())

    with patch("data_copilot.execution.postgres_engine.psycopg.connect") as connect:
        with pytest.raises(UnsafeSQLError):
            engine.explain_query("db_unknown", "DELETE FROM orders")

    connect.assert_not_called()


@pytest.mark.parametrize(
    "sql",
    [
        "WITH changed AS (DELETE FROM orders RETURNING *) SELECT * FROM changed",
        "EXPLAIN SELECT * FROM orders",
        "EXPLAIN ANALYZE SELECT * FROM orders",
    ],
)
def test_nested_mutation_and_user_supplied_explain_never_reach_database(
    sql: str,
) -> None:
    engine, database_id = _engine()

    with patch("data_copilot.execution.postgres_engine.psycopg.connect") as connect:
        with pytest.raises((UnsafeSQLError, ExplainQueryError)):
            engine.explain_query(database_id, sql)

    connect.assert_not_called()


def test_read_only_setup_failure_prevents_timeout_and_explain() -> None:
    engine, database_id = _engine()
    context, connection, cursor = _connection()
    type(connection).read_only = PropertyMock(
        side_effect=psycopg.OperationalError("read-only failed with secret")
    )

    with patch(
        "data_copilot.execution.postgres_engine.psycopg.connect",
        return_value=context,
    ):
        with pytest.raises(ExplainQueryError):
            engine.explain_query(database_id, "SELECT 1")

    cursor.execute.assert_not_called()


def test_timeout_and_driver_errors_are_sanitized() -> None:
    engine, database_id = _engine()
    context, _, cursor = _connection()
    cursor.execute.side_effect = [None, psycopg.errors.QueryCanceled("raw secret")]

    with patch(
        "data_copilot.execution.postgres_engine.psycopg.connect",
        return_value=context,
    ):
        with pytest.raises(QueryTimeoutError) as captured:
            engine.explain_query(database_id, "SELECT * FROM orders")

    assert "raw secret" not in str(captured.value)
    assert "super-secret" not in str(captured.value)
    assert captured.value.__cause__ is None

    context, _, cursor = _connection()
    cursor.execute.side_effect = [None, psycopg.OperationalError(DSN)]
    with patch(
        "data_copilot.execution.postgres_engine.psycopg.connect",
        return_value=context,
    ):
        with pytest.raises(ExplainQueryError) as captured:
            engine.explain_query(database_id, "SELECT * FROM orders")

    assert "super-secret" not in str(captured.value)
    assert "SELECT" not in str(captured.value)
    assert captured.value.__cause__ is None


def test_unknown_object_uses_existing_safe_recoverable_error() -> None:
    engine, database_id = _engine()
    context, _, cursor = _connection()
    cursor.execute.side_effect = [None, psycopg.errors.UndefinedColumn("raw")]

    with patch(
        "data_copilot.execution.postgres_engine.psycopg.connect",
        return_value=context,
    ):
        with pytest.raises(SQLObjectNotFoundError, match="table or column"):
            engine.explain_query(database_id, "SELECT missing FROM orders")


@pytest.mark.parametrize(
    ("driver_error", "expected_error"),
    [
        (psycopg.errors.AmbiguousColumn("raw secret"), SQLAmbiguousColumnError),
        (psycopg.errors.DatatypeMismatch("raw secret"), SQLTypeMismatchError),
        (psycopg.errors.GroupingError("raw secret"), SQLGroupingError),
    ],
)
def test_explain_preserves_safe_actionable_error_category(
    driver_error: psycopg.Error,
    expected_error: type[Exception],
) -> None:
    engine, database_id = _engine()
    context, _, cursor = _connection()
    cursor.execute.side_effect = [None, driver_error]

    with patch(
        "data_copilot.execution.postgres_engine.psycopg.connect",
        return_value=context,
    ):
        with pytest.raises(expected_error) as captured:
            engine.explain_query(database_id, "SELECT value FROM a JOIN b ON true")

    assert "raw secret" not in str(captured.value)
    assert captured.value.__cause__ is None


@pytest.mark.parametrize("row", [None, (), (SIMPLE_PLAN, "extra")])
def test_invalid_explain_row_fails_closed(row: tuple[object, ...] | None) -> None:
    engine, database_id = _engine()
    context, _, _ = _connection(row=row)

    with patch(
        "data_copilot.execution.postgres_engine.psycopg.connect",
        return_value=context,
    ):
        with pytest.raises(ExplainQueryError, match="invalid query plan"):
            engine.explain_query(database_id, "SELECT 1")
