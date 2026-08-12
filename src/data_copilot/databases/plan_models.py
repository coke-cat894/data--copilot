"""Typed bounded PostgreSQL query-plan facts."""

from pydantic import BaseModel, ConfigDict


class QueryPlanNode(BaseModel):
    """Small stable subset of one PostgreSQL JSON plan node."""

    model_config = ConfigDict(frozen=True)

    node_type: str
    relation_name: str | None = None
    alias: str | None = None
    join_type: str | None = None
    startup_cost: float | None = None
    total_cost: float | None = None
    plan_rows: int | None = None
    plan_width: int | None = None
    filter: str | None = None
    index_name: str | None = None
    children: tuple["QueryPlanNode", ...] = ()


class QueryPlanResult(BaseModel):
    """Bounded program-owned EXPLAIN result for one registered database."""

    model_config = ConfigDict(frozen=True)

    database_id: str
    root: QueryPlanNode
    node_count: int
    truncated: bool
    warnings: tuple[str, ...] = ()
