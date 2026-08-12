"""Bound PostgreSQL EXPLAIN JSON to the public query-plan contract."""

import json
import math
from dataclasses import dataclass
from typing import Any

from data_copilot.databases.constants import MAX_PLAN_DEPTH, MAX_PLAN_NODES
from data_copilot.databases.plan_models import QueryPlanNode, QueryPlanResult
from data_copilot.errors import ExplainQueryError


@dataclass(slots=True)
class _ParseState:
    node_count: int = 0
    node_limit_reached: bool = False
    depth_limit_reached: bool = False


def parse_query_plan(database_id: str, raw_plan: object) -> QueryPlanResult:
    """Parse one PostgreSQL JSON plan and discard unapproved raw fields."""

    document = _json_document(raw_plan)
    if (
        not isinstance(document, list)
        or len(document) != 1
        or not isinstance(document[0], dict)
        or not isinstance(document[0].get("Plan"), dict)
    ):
        raise ExplainQueryError("PostgreSQL returned an invalid query plan.")

    state = _ParseState()
    root = _parse_node(document[0]["Plan"], depth=0, state=state)
    if root is None:
        raise ExplainQueryError("PostgreSQL returned an invalid query plan.")

    warnings: list[str] = []
    if state.node_limit_reached:
        warnings.append(
            f"Query plan was truncated to MAX_PLAN_NODES={MAX_PLAN_NODES}."
        )
    if state.depth_limit_reached:
        warnings.append(
            f"Query plan was truncated at MAX_PLAN_DEPTH={MAX_PLAN_DEPTH}."
        )
    return QueryPlanResult(
        database_id=database_id,
        root=root,
        node_count=state.node_count,
        truncated=bool(warnings),
        warnings=tuple(warnings),
    )


def _json_document(raw_plan: object) -> object:
    if isinstance(raw_plan, str):
        try:
            return json.loads(raw_plan)
        except (json.JSONDecodeError, TypeError, ValueError):
            raise ExplainQueryError(
                "PostgreSQL returned an invalid query plan."
            ) from None
    return raw_plan


def _parse_node(
    raw_node: dict[str, Any],
    *,
    depth: int,
    state: _ParseState,
) -> QueryPlanNode | None:
    if state.node_count >= MAX_PLAN_NODES:
        state.node_limit_reached = True
        return None
    state.node_count += 1

    raw_children = raw_node.get("Plans", [])
    if not isinstance(raw_children, list) or not all(
        isinstance(child, dict) for child in raw_children
    ):
        raise ExplainQueryError("PostgreSQL returned an invalid query plan.")

    children: list[QueryPlanNode] = []
    if raw_children and depth >= MAX_PLAN_DEPTH:
        state.depth_limit_reached = True
    else:
        for raw_child in raw_children:
            child = _parse_node(raw_child, depth=depth + 1, state=state)
            if child is None:
                break
            children.append(child)

    return QueryPlanNode(
        node_type=_required_text(raw_node, "Node Type"),
        relation_name=_optional_text(raw_node, "Relation Name"),
        alias=_optional_text(raw_node, "Alias"),
        join_type=_optional_text(raw_node, "Join Type"),
        startup_cost=_optional_float(raw_node, "Startup Cost"),
        total_cost=_optional_float(raw_node, "Total Cost"),
        plan_rows=_optional_int(raw_node, "Plan Rows"),
        plan_width=_optional_int(raw_node, "Plan Width"),
        filter=_optional_text(raw_node, "Filter"),
        index_name=_optional_text(raw_node, "Index Name"),
        children=tuple(children),
    )


def _required_text(raw_node: dict[str, Any], key: str) -> str:
    value = _optional_text(raw_node, key)
    if value is None or not value.strip():
        raise ExplainQueryError("PostgreSQL returned an invalid query plan.")
    return value


def _optional_text(raw_node: dict[str, Any], key: str) -> str | None:
    value = raw_node.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ExplainQueryError("PostgreSQL returned an invalid query plan.")
    return value


def _optional_float(raw_node: dict[str, Any], key: str) -> float | None:
    value = raw_node.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ExplainQueryError("PostgreSQL returned an invalid query plan.")
    converted = float(value)
    if not math.isfinite(converted):
        raise ExplainQueryError("PostgreSQL returned an invalid query plan.")
    return converted


def _optional_int(raw_node: dict[str, Any], key: str) -> int | None:
    value = raw_node.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ExplainQueryError("PostgreSQL returned an invalid query plan.")
    return value
