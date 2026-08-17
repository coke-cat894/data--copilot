"""Static five-tool dispatch for one registered PostgreSQL database."""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from data_copilot.databases import (
    DatabaseQueryResult,
    DatabaseRegistry,
    QueryPlanResult,
)
from data_copilot.errors import ToolArgumentError, UnknownToolError
from data_copilot.execution import PostgresEngine
from data_copilot.llm.models import ToolDefinition
from data_copilot.tools.database_models import (
    GetRelationshipsResult,
    InspectTableResult,
    ListTablesResult,
)


DatabaseToolResult = (
    ListTablesResult
    | InspectTableResult
    | GetRelationshipsResult
    | DatabaseQueryResult
    | QueryPlanResult
)


class _Arguments(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ListTablesArguments(_Arguments):
    schema_name: str | None = Field(
        default=None,
        alias="schema",
        description="Exact PostgreSQL schema name, or null for all non-system schemas.",
    )


class InspectTableArguments(_Arguments):
    schema_name: str = Field(description="Exact PostgreSQL schema name.")
    table_name: str = Field(description="Exact table or view name.")


class GetRelationshipsArguments(InspectTableArguments):
    pass


class ExecuteReadQueryArguments(_Arguments):
    sql: str = Field(
        description="Exactly one PostgreSQL read-only SELECT query."
    )


class ExplainQueryArguments(_Arguments):
    sql: str = Field(
        description=(
            "Exactly one underlying PostgreSQL read-only query; do not include "
            "EXPLAIN."
        )
    )


_ARGUMENT_MODELS: dict[str, type[_Arguments]] = {
    "list_tables": ListTablesArguments,
    "inspect_table": InspectTableArguments,
    "get_relationships": GetRelationshipsArguments,
    "execute_read_query": ExecuteReadQueryArguments,
    "explain_query": ExplainQueryArguments,
}

_DESCRIPTIONS = {
    "list_tables": (
        "List bounded non-system PostgreSQL tables/views when the table is unknown."
    ),
    "inspect_table": (
        "Return one table's exact PostgreSQL columns, types, nullability, declared "
        "keys, and basic indexes."
    ),
    "get_relationships": (
        "Return declared inbound/outbound foreign keys for one table; never infer "
        "relationships from names."
    ),
    "execute_read_query": (
        "Execute exactly one PostgreSQL read-only SELECT/WITH/set query. Mutations "
        "and EXPLAIN are forbidden; results are bounded. Compute aggregates in SQL, "
        "project needed fields, and avoid SELECT *."
    ),
    "explain_query": (
        "Return PostgreSQL's bounded estimated plan for one read-only query passed "
        "without EXPLAIN. The program adds EXPLAIN JSON; ANALYZE/execution are forbidden."
    ),
}


class DatabaseToolDispatcher:
    """Bind exactly five database Tools to one program-owned database ID."""

    def __init__(
        self,
        registry: DatabaseRegistry,
        database_id: str,
        *,
        engine: PostgresEngine | None = None,
    ) -> None:
        registry.get(database_id)
        self._database_id = database_id
        self._engine = engine or PostgresEngine(registry)
        self._schemas = tuple(
            ToolDefinition(
                name=name,
                description=_DESCRIPTIONS[name],
                parameters=_strict_json_schema(model),
            )
            for name, model in _ARGUMENT_MODELS.items()
        )

    @property
    def schemas(self) -> tuple[ToolDefinition, ...]:
        return self._schemas

    @property
    def allowed_tool_names(self) -> frozenset[str]:
        return frozenset(_ARGUMENT_MODELS)

    def dispatch(self, name: str, arguments: str) -> DatabaseToolResult:
        model = _ARGUMENT_MODELS.get(name)
        if model is None:
            raise UnknownToolError("Unsupported tool.")
        try:
            parsed = model.model_validate_json(arguments, strict=True)
        except (ValidationError, ValueError, TypeError):
            raise ToolArgumentError("Tool arguments are invalid.") from None
        return self._invoke(name, parsed)

    def _invoke(self, name: str, arguments: _Arguments) -> DatabaseToolResult:
        if name == "list_tables" and isinstance(arguments, ListTablesArguments):
            result = self._engine.list_tables(
                self._database_id, schema=arguments.schema_name
            )
            return ListTablesResult(
                database_id=self._database_id,
                **result.model_dump(mode="python"),
            )
        if name == "inspect_table" and isinstance(
            arguments, InspectTableArguments
        ):
            result = self._engine.inspect_table(
                self._database_id,
                schema_name=arguments.schema_name,
                table_name=arguments.table_name,
            )
            return InspectTableResult(
                database_id=self._database_id,
                **result.model_dump(mode="python"),
            )
        if name == "get_relationships" and isinstance(
            arguments, GetRelationshipsArguments
        ):
            result = self._engine.get_relationships(
                self._database_id,
                schema_name=arguments.schema_name,
                table_name=arguments.table_name,
            )
            return GetRelationshipsResult(
                database_id=self._database_id,
                **result.model_dump(mode="python"),
            )
        if name == "execute_read_query" and isinstance(
            arguments, ExecuteReadQueryArguments
        ):
            return self._engine.execute_read_query(
                self._database_id, arguments.sql
            )
        if name == "explain_query" and isinstance(
            arguments, ExplainQueryArguments
        ):
            return self._engine.explain_query(self._database_id, arguments.sql)
        raise ToolArgumentError("Tool arguments do not match the requested Tool.")


def _strict_json_schema(model: type[_Arguments]) -> dict[str, Any]:
    schema = model.model_json_schema()

    def make_strict(node: Any) -> None:
        if isinstance(node, dict):
            node.pop("default", None)
            node.pop("title", None)
            if node.get("type") == "object":
                properties = node.get("properties", {})
                if isinstance(properties, dict):
                    node["required"] = list(properties)
                node["additionalProperties"] = False
            for value in node.values():
                make_strict(value)
        elif isinstance(node, list):
            for value in node:
                make_strict(value)

    make_strict(schema)
    return schema
