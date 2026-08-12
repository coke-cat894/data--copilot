import json

import pytest

from data_copilot.databases.constants import MAX_PLAN_DEPTH, MAX_PLAN_NODES
from data_copilot.errors import ExplainQueryError
from data_copilot.execution.postgres_plan_parser import parse_query_plan


def _node(node_type: str, **fields: object) -> dict[str, object]:
    return {"Node Type": node_type, **fields}


@pytest.mark.parametrize(
    ("node", "expected"),
    [
        (
            _node(
                "Seq Scan",
                **{
                    "Relation Name": "orders",
                    "Alias": "o",
                    "Startup Cost": 0.0,
                    "Total Cost": 42.5,
                    "Plan Rows": 100,
                    "Plan Width": 24,
                    "Filter": "(status = 'open'::text)",
                },
            ),
            ("Seq Scan", "orders", None),
        ),
        (
            _node(
                "Index Scan",
                **{
                    "Relation Name": "customers",
                    "Index Name": "customers_pkey",
                },
            ),
            ("Index Scan", "customers", "customers_pkey"),
        ),
        (_node("Aggregate", **{"Plan Rows": 10}), ("Aggregate", None, None)),
        (_node("Sort", **{"Total Cost": 9.5}), ("Sort", None, None)),
    ],
)
def test_parses_representative_plan_nodes(
    node: dict[str, object],
    expected: tuple[str, str | None, str | None],
) -> None:
    result = parse_query_plan("db_12345678", [{"Plan": node}])

    assert (
        result.root.node_type,
        result.root.relation_name,
        result.root.index_name,
    ) == expected
    assert result.node_count == 1
    assert result.truncated is False


@pytest.mark.parametrize("join_type", ["Nested Loop", "Hash Join", "Merge Join"])
def test_parses_join_structure_and_nested_children(join_type: str) -> None:
    root = _node(
        join_type,
        **{
            "Join Type": "Inner",
            "Plans": [
                _node("Seq Scan", **{"Relation Name": "orders"}),
                _node(
                    "Index Scan",
                    **{
                        "Relation Name": "customers",
                        "Index Name": "customers_pkey",
                        "Plans": [_node("Bitmap Index Scan")],
                    },
                ),
            ],
        },
    )

    result = parse_query_plan("db_12345678", json.dumps([{"Plan": root}]))

    assert result.root.join_type == "Inner"
    assert tuple(child.node_type for child in result.root.children) == (
        "Seq Scan",
        "Index Scan",
    )
    assert result.root.children[1].children[0].node_type == "Bitmap Index Scan"
    assert result.node_count == 4


def test_node_limit_truncates_with_explicit_warning() -> None:
    root = _node(
        "Append",
        **{
            "Plans": [
                _node("Seq Scan", **{"Relation Name": f"table_{index}"})
                for index in range(MAX_PLAN_NODES + 5)
            ]
        },
    )

    result = parse_query_plan("db_12345678", [{"Plan": root}])

    assert result.node_count == MAX_PLAN_NODES
    assert result.truncated is True
    assert result.warnings == (
        f"Query plan was truncated to MAX_PLAN_NODES={MAX_PLAN_NODES}.",
    )


def test_depth_limit_truncates_children_with_explicit_warning() -> None:
    root = _node("Result")
    current = root
    for _ in range(MAX_PLAN_DEPTH + 5):
        child = _node("Result")
        current["Plans"] = [child]
        current = child

    result = parse_query_plan("db_12345678", [{"Plan": root}])

    assert result.node_count == MAX_PLAN_DEPTH + 1
    assert result.truncated is True
    assert result.warnings == (
        f"Query plan was truncated at MAX_PLAN_DEPTH={MAX_PLAN_DEPTH}.",
    )


@pytest.mark.parametrize(
    "raw_plan",
    [
        None,
        {},
        [],
        [{"Not Plan": {}}],
        [{"Plan": {}}],
        [{"Plan": {"Node Type": 5}}],
        [{"Plan": {"Node Type": "Seq Scan", "Plans": "not-a-list"}}],
        "not-json",
    ],
)
def test_invalid_or_untyped_raw_plan_fails_closed(raw_plan: object) -> None:
    with pytest.raises(ExplainQueryError, match="invalid query plan"):
        parse_query_plan("db_12345678", raw_plan)
