from collections.abc import Sequence
from unittest.mock import MagicMock, PropertyMock, call, patch

import psycopg
import pytest

from data_copilot.databases import (
    DatabaseRegistry,
    PostgresConnectionConfig,
    RelationshipDirection,
    TableType,
)
from data_copilot.databases.constants import (
    MAX_DATABASE_TABLES,
    MAX_INDEXES,
    MAX_RELATIONSHIPS,
    MAX_TABLE_COLUMNS,
)
from data_copilot.errors import (
    DatabaseMetadataError,
    DatabaseNotFoundError,
    SchemaNotFoundError,
    TableNotFoundError,
)
from data_copilot.execution.postgres_engine import PostgresEngine
from data_copilot.execution.postgres_metadata_queries import (
    LIST_COLUMNS_SQL,
    LIST_INDEXES_SQL,
    LIST_RELATIONSHIPS_SQL,
    LIST_TABLES_SQL,
    LOOKUP_TABLE_SQL,
    OUTBOUND_FOREIGN_KEYS_SQL,
    PRIMARY_KEY_SQL,
)


def test_optional_schema_filter_has_explicit_postgres_type_context() -> None:
    assert "%s::text IS NULL" in LIST_TABLES_SQL
    assert "pg_toast%%" in LIST_TABLES_SQL
    assert "pg_temp_%%" in LIST_TABLES_SQL


DSN = "postgresql://analyst:super-secret@db.example:5432/analytics"


def _engine() -> tuple[PostgresEngine, str]:
    registry = DatabaseRegistry()
    database = registry.register(
        PostgresConnectionConfig(
            dsn=DSN,
            database_name="analytics",
            connect_timeout_seconds=7,
        )
    )
    return PostgresEngine(registry), database.database_id


def _connection(
    *,
    fetchone_results: Sequence[object] = (),
    fetchall_results: Sequence[object] = (),
) -> tuple[MagicMock, MagicMock, MagicMock]:
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    cursor.fetchone.side_effect = list(fetchone_results)
    cursor.fetchall.side_effect = list(fetchall_results)
    context = MagicMock()
    context.__enter__.return_value = connection
    return context, connection, cursor


def test_list_tables_returns_multiple_schemas_and_excludes_system_schemas() -> None:
    engine, database_id = _engine()
    context, connection, cursor = _connection(
        fetchall_results=[
            [
                ("analytics", "daily_sales", "materialized_view"),
                ("public", "orders", "table"),
            ]
        ]
    )

    with patch(
        "data_copilot.execution.postgres_engine.psycopg.connect",
        return_value=context,
    ) as connect:
        result = engine.list_tables(database_id)

    connect.assert_called_once_with(DSN, connect_timeout=7)
    assert connection.read_only is True
    cursor.execute.assert_called_once_with(
        LIST_TABLES_SQL, (None, None, MAX_DATABASE_TABLES + 1)
    )
    assert "pg_catalog" in LIST_TABLES_SQL
    assert "information_schema" in LIST_TABLES_SQL
    assert [(table.schema_name, table.table_name) for table in result.tables] == [
        ("analytics", "daily_sales"),
        ("public", "orders"),
    ]
    assert result.tables[0].table_type is TableType.MATERIALIZED_VIEW
    assert result.truncated is False


def test_list_tables_uses_bound_optional_schema_filter() -> None:
    engine, database_id = _engine()
    hostile_schema = "tenant'; DROP SCHEMA public;--"
    context, _, cursor = _connection(fetchall_results=[[]])

    with patch(
        "data_copilot.execution.postgres_engine.psycopg.connect",
        return_value=context,
    ):
        result = engine.list_tables(database_id, schema=hostile_schema)

    cursor.execute.assert_called_once_with(
        LIST_TABLES_SQL,
        (hostile_schema, hostile_schema, MAX_DATABASE_TABLES + 1),
    )
    assert hostile_schema not in LIST_TABLES_SQL
    assert result.tables == ()
    assert result.truncated is False


def test_list_tables_empty_database() -> None:
    engine, database_id = _engine()
    context, _, _ = _connection(fetchall_results=[[]])

    with patch(
        "data_copilot.execution.postgres_engine.psycopg.connect",
        return_value=context,
    ):
        result = engine.list_tables(database_id)

    assert result.tables == ()
    assert result.warnings == ()


def test_list_tables_reports_resource_limit() -> None:
    engine, database_id = _engine()
    rows = [("public", f"table_{index:03}", "table") for index in range(201)]
    context, _, _ = _connection(fetchall_results=[rows])

    with patch(
        "data_copilot.execution.postgres_engine.psycopg.connect",
        return_value=context,
    ):
        result = engine.list_tables(database_id)

    assert len(result.tables) == MAX_DATABASE_TABLES
    assert result.truncated is True
    assert result.warnings == (
        "Table metadata was truncated to 200 entries.",
    )


def test_inspect_table_returns_declared_columns_composite_keys_and_indexes() -> None:
    engine, database_id = _engine()
    context, connection, cursor = _connection(
        fetchone_results=[(True, 42, "table")],
        fetchall_results=[
            [
                ("tenant_id", "integer", False),
                ("order_id", "bigint", False),
                ("customer_id", "bigint", True),
                ("amount", "numeric(12,2)", True),
            ],
            [("tenant_id",), ("order_id",)],
            [
                (
                    "orders_customer_fk",
                    ["tenant_id", "customer_id"],
                    "crm",
                    "customers",
                    ["tenant_id", "customer_id"],
                )
            ],
            [
                (
                    "orders_pkey",
                    ["tenant_id", "order_id"],
                    True,
                    True,
                ),
                ("orders_customer_idx", ["customer_id"], False, False),
            ],
        ],
    )

    with patch(
        "data_copilot.execution.postgres_engine.psycopg.connect",
        return_value=context,
    ):
        result = engine.inspect_table(
            database_id,
            schema_name="sales",
            table_name="orders",
        )

    assert connection.read_only is True
    assert cursor.execute.call_args_list == [
        call(LOOKUP_TABLE_SQL, ("sales", "sales", "orders")),
        call(LIST_COLUMNS_SQL, (42, MAX_TABLE_COLUMNS + 1)),
        call(PRIMARY_KEY_SQL, (42, MAX_TABLE_COLUMNS + 1)),
        call(OUTBOUND_FOREIGN_KEYS_SQL, (42, MAX_RELATIONSHIPS + 1)),
        call(LIST_INDEXES_SQL, (42, MAX_INDEXES + 1)),
    ]
    assert result.schema_name == "sales"
    assert result.table_name == "orders"
    assert [column.nullable for column in result.columns] == [False, False, True, True]
    assert result.columns[3].postgres_type == "numeric(12,2)"
    assert result.primary_key == ("tenant_id", "order_id")
    assert result.foreign_keys[0].source_columns == (
        "tenant_id",
        "customer_id",
    )
    assert result.foreign_keys[0].target_schema_name == "crm"
    assert result.foreign_keys[0].target_columns == (
        "tenant_id",
        "customer_id",
    )
    assert result.basic_indexes[0].primary is True
    assert result.basic_indexes[1].unique is False
    assert result.truncated is False


@pytest.mark.parametrize(
    ("lookup_row", "error_type", "message"),
    [
        ((False, None, None), SchemaNotFoundError, "Unknown schema"),
        ((True, None, None), TableNotFoundError, "Unknown table"),
    ],
)
def test_inspect_table_rejects_unknown_schema_or_table(
    lookup_row: tuple[object, ...],
    error_type: type[Exception],
    message: str,
) -> None:
    engine, database_id = _engine()
    context, _, cursor = _connection(fetchone_results=[lookup_row])

    with patch(
        "data_copilot.execution.postgres_engine.psycopg.connect",
        return_value=context,
    ):
        with pytest.raises(error_type, match=message):
            engine.inspect_table(
                database_id,
                schema_name="private_sales",
                table_name="missing",
            )

    assert cursor.execute.call_count == 1


def test_inspect_table_reports_each_resource_limit() -> None:
    engine, database_id = _engine()
    columns = [(f"column_{index}", "text", True) for index in range(201)]
    primary_key = [(f"column_{index}",) for index in range(201)]
    foreign_keys = [
        (f"fk_{index}", ["id"], "public", "parent", ["id"])
        for index in range(201)
    ]
    indexes = [
        (f"idx_{index}", ["id"], False, False) for index in range(101)
    ]
    context, _, _ = _connection(
        fetchone_results=[(True, 42, "table")],
        fetchall_results=[columns, primary_key, foreign_keys, indexes],
    )

    with patch(
        "data_copilot.execution.postgres_engine.psycopg.connect",
        return_value=context,
    ):
        result = engine.inspect_table(
            database_id,
            schema_name="public",
            table_name="wide_table",
        )

    assert len(result.columns) == MAX_TABLE_COLUMNS
    assert len(result.primary_key) == MAX_TABLE_COLUMNS
    assert len(result.foreign_keys) == MAX_RELATIONSHIPS
    assert len(result.basic_indexes) == MAX_INDEXES
    assert result.truncated is True
    assert len(result.warnings) == 4


def test_get_relationships_returns_outbound_inbound_and_composite_fk() -> None:
    engine, database_id = _engine()
    rows = [
        (
            "outbound",
            "orders_customer_fk",
            "sales",
            "orders",
            ["tenant_id", "customer_id"],
            "crm",
            "customers",
            ["tenant_id", "customer_id"],
        ),
        (
            "inbound",
            "items_order_fk",
            "sales",
            "order_items",
            ["tenant_id", "order_id"],
            "sales",
            "orders",
            ["tenant_id", "order_id"],
        ),
    ]
    context, connection, cursor = _connection(
        fetchone_results=[(True, 42, "table")],
        fetchall_results=[rows],
    )

    with patch(
        "data_copilot.execution.postgres_engine.psycopg.connect",
        return_value=context,
    ):
        result = engine.get_relationships(
            database_id,
            schema_name="sales",
            table_name="orders",
        )

    assert connection.read_only is True
    assert cursor.execute.call_args_list == [
        call(LOOKUP_TABLE_SQL, ("sales", "sales", "orders")),
        call(
            LIST_RELATIONSHIPS_SQL,
            (42, 42, 42, 42, MAX_RELATIONSHIPS + 1),
        ),
    ]
    assert result.relationships[0].direction is RelationshipDirection.OUTBOUND
    assert result.relationships[0].source_columns == (
        "tenant_id",
        "customer_id",
    )
    assert result.relationships[1].direction is RelationshipDirection.INBOUND
    assert result.relationships[1].target_table_name == "orders"


def test_get_relationships_can_return_no_declared_relationships() -> None:
    engine, database_id = _engine()
    context, _, _ = _connection(
        fetchone_results=[(True, 42, "table")],
        fetchall_results=[[]],
    )

    with patch(
        "data_copilot.execution.postgres_engine.psycopg.connect",
        return_value=context,
    ):
        result = engine.get_relationships(
            database_id,
            schema_name="public",
            table_name="standalone",
        )

    assert result.relationships == ()
    assert result.truncated is False


def test_get_relationships_reports_resource_limit() -> None:
    engine, database_id = _engine()
    rows = [
        (
            "inbound",
            f"fk_{index}",
            "public",
            f"source_{index}",
            ["id"],
            "public",
            "target",
            ["id"],
        )
        for index in range(201)
    ]
    context, _, _ = _connection(
        fetchone_results=[(True, 42, "table")],
        fetchall_results=[rows],
    )

    with patch(
        "data_copilot.execution.postgres_engine.psycopg.connect",
        return_value=context,
    ):
        result = engine.get_relationships(
            database_id,
            schema_name="public",
            table_name="target",
        )

    assert len(result.relationships) == MAX_RELATIONSHIPS
    assert result.truncated is True
    assert result.warnings == (
        "Relationship metadata was truncated to 200 entries.",
    )


@pytest.mark.parametrize(
    ("operation", "arguments"),
    [
        ("list_tables", {}),
        ("inspect_table", {"schema_name": "public", "table_name": "orders"}),
        (
            "get_relationships",
            {"schema_name": "public", "table_name": "orders"},
        ),
    ],
)
def test_each_metadata_operation_fails_closed_when_read_only_setup_fails(
    operation: str,
    arguments: dict[str, str],
) -> None:
    engine, database_id = _engine()
    context, connection, cursor = _connection()
    type(connection).read_only = PropertyMock(
        side_effect=psycopg.OperationalError("read-only setup failed")
    )

    with patch(
        "data_copilot.execution.postgres_engine.psycopg.connect",
        return_value=context,
    ):
        with pytest.raises(DatabaseMetadataError):
            getattr(engine, operation)(database_id, **arguments)

    cursor.execute.assert_not_called()


def test_metadata_failure_does_not_expose_credentials_or_internal_sql() -> None:
    engine, database_id = _engine()

    with patch(
        "data_copilot.execution.postgres_engine.psycopg.connect",
        side_effect=psycopg.OperationalError(
            f"failed {DSN} while running {LIST_TABLES_SQL}"
        ),
    ):
        with pytest.raises(DatabaseMetadataError) as captured:
            engine.list_tables(database_id)

    message = str(captured.value)
    assert database_id in message
    assert "super-secret" not in message
    assert "SELECT" not in message
    assert captured.value.__cause__ is None


def test_invalid_catalog_result_fails_closed_without_validation_traceback() -> None:
    engine, database_id = _engine()
    context, _, _ = _connection(
        fetchall_results=[[('public', 'orders', 'unsupported_relation_kind')]]
    )

    with patch(
        "data_copilot.execution.postgres_engine.psycopg.connect",
        return_value=context,
    ):
        with pytest.raises(DatabaseMetadataError, match="invalid table metadata"):
            engine.list_tables(database_id)


@pytest.mark.parametrize(
    ("operation", "arguments"),
    [
        ("list_tables", {}),
        ("inspect_table", {"schema_name": "public", "table_name": "orders"}),
        (
            "get_relationships",
            {"schema_name": "public", "table_name": "orders"},
        ),
    ],
)
def test_unknown_database_id_never_connects(
    operation: str,
    arguments: dict[str, str],
) -> None:
    engine = PostgresEngine(DatabaseRegistry())

    with patch("data_copilot.execution.postgres_engine.psycopg.connect") as connect:
        with pytest.raises(DatabaseNotFoundError):
            getattr(engine, operation)("db_unknown", **arguments)

    connect.assert_not_called()


def test_metadata_models_do_not_expose_credentials_or_internal_sql() -> None:
    engine, database_id = _engine()
    context, _, _ = _connection(fetchall_results=[[('public', 'orders', 'table')]])

    with patch(
        "data_copilot.execution.postgres_engine.psycopg.connect",
        return_value=context,
    ):
        result = engine.list_tables(database_id)

    serialized = result.model_dump_json()
    assert "super-secret" not in serialized
    assert "SELECT" not in serialized
    assert "dsn" not in serialized.lower()


def test_engine_still_exposes_no_generic_sql_api() -> None:
    engine, _ = _engine()

    assert not hasattr(engine, "execute_sql")
    assert not hasattr(engine, "run_sql")
    assert not hasattr(engine, "execute")
