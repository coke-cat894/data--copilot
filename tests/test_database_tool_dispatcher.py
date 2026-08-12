import json
from unittest.mock import MagicMock

import pytest

from data_copilot.databases import (
    ColumnMetadata,
    DatabaseQueryResult,
    DatabaseRegistry,
    ForeignKeyMetadata,
    IndexMetadata,
    PostgresConnectionConfig,
    QueryPlanNode,
    QueryPlanResult,
    RelationshipDirection,
    RelationshipListResult,
    RelationshipMetadata,
    TableInspectionResult,
    TableListResult,
    TableMetadata,
    TableType,
)
from data_copilot.errors import ToolArgumentError, UnknownToolError
from data_copilot.execution import PostgresEngine
from data_copilot.tools import (
    DatabaseToolDispatcher,
    GetRelationshipsResult,
    InspectTableResult,
    ListTablesResult,
)


@pytest.fixture
def database_dispatcher() -> tuple[DatabaseToolDispatcher, MagicMock, str]:
    registry = DatabaseRegistry()
    database = registry.register(
        PostgresConnectionConfig(
            "postgresql://user:secret@localhost/analytics",
            "analytics",
            5,
        )
    )
    engine = MagicMock(spec=PostgresEngine)
    engine.list_tables.return_value = TableListResult(
        tables=(TableMetadata(schema_name="public", table_name="orders", table_type=TableType.TABLE),),
        truncated=False,
    )
    engine.inspect_table.return_value = TableInspectionResult(
        schema_name="public",
        table_name="orders",
        table_type=TableType.TABLE,
        columns=(ColumnMetadata(name="id", postgres_type="bigint", nullable=False),),
        primary_key=("id",),
        foreign_keys=(
            ForeignKeyMetadata(
                constraint_name="orders_customer_fk",
                source_columns=("customer_id",),
                target_schema_name="public",
                target_table_name="customers",
                target_columns=("id",),
            ),
        ),
        basic_indexes=(IndexMetadata(index_name="orders_pkey", columns=("id",), unique=True, primary=True),),
        truncated=False,
    )
    engine.get_relationships.return_value = RelationshipListResult(
        schema_name="public",
        table_name="orders",
        relationships=(
            RelationshipMetadata(
                direction=RelationshipDirection.OUTBOUND,
                constraint_name="orders_customer_fk",
                source_schema_name="public",
                source_table_name="orders",
                source_columns=("customer_id",),
                target_schema_name="public",
                target_table_name="customers",
                target_columns=("id",),
            ),
        ),
        truncated=False,
    )
    engine.execute_read_query.return_value = DatabaseQueryResult(
        database_id=database.database_id,
        columns=("total",),
        rows=((3,),),
        row_count=1,
        truncated=False,
    )
    engine.explain_query.return_value = QueryPlanResult(
        database_id=database.database_id,
        root=QueryPlanNode(node_type="Seq Scan", relation_name="orders"),
        node_count=1,
        truncated=False,
    )
    return (
        DatabaseToolDispatcher(
            registry, database.database_id, engine=engine
        ),
        engine,
        database.database_id,
    )


def test_database_tool_schemas_are_static_strict_and_hide_database_id(
    database_dispatcher: tuple[DatabaseToolDispatcher, MagicMock, str],
) -> None:
    dispatcher, _, _ = database_dispatcher

    assert tuple(schema.name for schema in dispatcher.schemas) == (
        "list_tables",
        "inspect_table",
        "get_relationships",
        "execute_read_query",
        "explain_query",
    )
    for schema in dispatcher.schemas:
        serialized = json.dumps(schema.model_dump(mode="json")).casefold()
        assert schema.strict is True
        assert schema.parameters["additionalProperties"] is False
        assert schema.parameters["required"] == list(schema.parameters["properties"])
        assert "database_id" not in serialized
        assert "dsn" not in serialized
        assert "credential" not in serialized
    descriptions = {schema.name: schema.description for schema in dispatcher.schemas}
    query_description = descriptions["execute_read_query"]
    for phrase in (
        "exactly one",
        "PostgreSQL",
        "read-only",
        "Mutations",
        "EXPLAIN",
        "bounded",
        "aggregates",
        "SELECT *",
    ):
        assert phrase in query_description
    explain_description = descriptions["explain_query"]
    for phrase in ("PostgreSQL", "read-only", "without EXPLAIN", "ANALYZE"):
        assert phrase in explain_description


def test_dispatcher_invokes_all_five_tools_with_injected_database_id(
    database_dispatcher: tuple[DatabaseToolDispatcher, MagicMock, str],
) -> None:
    dispatcher, engine, database_id = database_dispatcher

    results = (
        dispatcher.dispatch("list_tables", '{"schema":null}'),
        dispatcher.dispatch(
            "inspect_table",
            '{"schema_name":"public","table_name":"orders"}',
        ),
        dispatcher.dispatch(
            "get_relationships",
            '{"schema_name":"public","table_name":"orders"}',
        ),
        dispatcher.dispatch(
            "execute_read_query",
            '{"sql":"SELECT COUNT(*) AS total FROM public.orders"}',
        ),
        dispatcher.dispatch(
            "explain_query",
            '{"sql":"SELECT * FROM public.orders"}',
        ),
    )

    assert tuple(type(result) for result in results) == (
        ListTablesResult,
        InspectTableResult,
        GetRelationshipsResult,
        DatabaseQueryResult,
        QueryPlanResult,
    )
    engine.list_tables.assert_called_once_with(database_id, schema=None)
    engine.inspect_table.assert_called_once_with(
        database_id, schema_name="public", table_name="orders"
    )
    engine.get_relationships.assert_called_once_with(
        database_id, schema_name="public", table_name="orders"
    )
    engine.execute_read_query.assert_called_once_with(
        database_id, "SELECT COUNT(*) AS total FROM public.orders"
    )
    engine.explain_query.assert_called_once_with(
        database_id, "SELECT * FROM public.orders"
    )


def test_dispatcher_rejects_unknown_malformed_and_capability_arguments(
    database_dispatcher: tuple[DatabaseToolDispatcher, MagicMock, str],
) -> None:
    dispatcher, engine, _ = database_dispatcher

    with pytest.raises(UnknownToolError):
        dispatcher.dispatch("run_sql", '{"sql":"SELECT 1"}')
    with pytest.raises(UnknownToolError):
        dispatcher.dispatch("validate_sql", '{"sql":"SELECT 1"}')
    with pytest.raises(ToolArgumentError):
        dispatcher.dispatch("list_tables", "not-json")
    with pytest.raises(ToolArgumentError):
        dispatcher.dispatch("list_tables", '{"database_id":"db_other","schema":null}')
    with pytest.raises(ToolArgumentError):
        dispatcher.dispatch("execute_read_query", '{"sql":"SELECT 1","dsn":"secret"}')
    with pytest.raises(ToolArgumentError):
        dispatcher.dispatch(
            "explain_query", '{"database_id":"db_other","sql":"SELECT 1"}'
        )

    engine.execute_read_query.assert_not_called()
    engine.explain_query.assert_not_called()
