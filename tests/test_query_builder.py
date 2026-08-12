from pydantic import TypeAdapter

from data_copilot.execution.query_builder import (
    build_aggregate_query,
    build_filter_query,
    quote_identifier,
)
from data_copilot.tools import (
    AggregateFunction,
    DimensionSpec,
    FilterCondition,
    FilterOperator,
    MetricSpec,
    SortSpec,
)


def test_filter_query_parameterizes_every_user_value() -> None:
    injection_like_value = "Robert'); DROP TABLE x;--"
    query = build_filter_query(
        [("status", "VARCHAR"), ("amount", "INTEGER")],
        columns=["status"],
        filters=[
            FilterCondition("status", FilterOperator.EQ, injection_like_value),
            FilterCondition("amount", FilterOperator.BETWEEN, [10, 20]),
        ],
        order_by=[SortSpec("status")],
        limit=50,
    )

    assert query.sql.startswith("SELECT ")
    assert injection_like_value not in query.sql
    assert "?" in query.sql
    assert query.parameters == (injection_like_value, 10, 20)
    assert query.return_limit == 50
    assert query.detect_truncation is True


def test_aggregate_query_only_interpolates_controlled_expressions() -> None:
    query = build_aggregate_query(
        [("region", "VARCHAR"), ("amount", "INTEGER"), ("status", "VARCHAR")],
        dimensions=[DimensionSpec("region_name", "region")],
        metrics=[MetricSpec("revenue", AggregateFunction.SUM, "amount")],
        filters=[FilterCondition("status", FilterOperator.EQ, "completed")],
        order_by=[],
        limit=20,
    )

    assert query.sql.startswith("SELECT ")
    assert query.parameters == ("completed",)
    assert "sum(\"amount\")" in query.sql
    assert "GROUP BY 1" in query.sql
    assert query.columns == ("region_name", "revenue")


def test_identifier_quoting_escapes_embedded_quotes() -> None:
    assert quote_identifier('quote"column') == '"quote""column"'


def test_typed_request_models_are_json_serializable() -> None:
    condition = FilterCondition("amount", FilterOperator.BETWEEN, [1, 2])

    assert TypeAdapter(FilterCondition).dump_json(condition) == (
        b'{"column":"amount","operator":"between","value":[1,2]}'
    )
