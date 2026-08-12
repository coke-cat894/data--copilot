from collections.abc import Callable
from datetime import date
from pathlib import Path

import pytest

from data_copilot.config import (
    MAX_FILTERS,
    MAX_GROUP_BY_DIMENSIONS,
    MAX_METRICS,
    MAX_RESULT_ROWS,
)
from data_copilot.datasets import DatasetRegistry
from data_copilot.errors import (
    ColumnNotFoundError,
    InvalidDimensionError,
    InvalidMetricError,
    InvalidProjectionError,
    InvalidSortError,
    QueryBuildError,
    ResourceLimitError,
)
from data_copilot.tools import (
    AggregateDatasetResult,
    AggregateDatasetTool,
    AggregateFunction,
    AggregateSortSpec,
    DimensionSpec,
    FilterCondition,
    FilterOperator,
    MetricSpec,
    SortDirection,
    TimeGrain,
)


def _aggregate_tool(
    query_sample_files: dict[str, Path], tmp_path: Path
) -> tuple[AggregateDatasetTool, str]:
    registry = DatasetRegistry(allowed_roots=[tmp_path])
    dataset = registry.register(query_sample_files["parquet"])
    return AggregateDatasetTool(registry), dataset.dataset_id


def test_all_aggregate_functions_without_dimensions(
    query_sample_files: dict[str, Path], tmp_path: Path
) -> None:
    tool, dataset_id = _aggregate_tool(query_sample_files, tmp_path)

    result = tool(
        dataset_id,
        metrics=[
            MetricSpec("rows", AggregateFunction.COUNT),
            MetricSpec("notes", AggregateFunction.COUNT, "optional_note"),
            MetricSpec("users", AggregateFunction.COUNT_DISTINCT, "user_id"),
            MetricSpec("total", AggregateFunction.SUM, "amount"),
            MetricSpec("average", AggregateFunction.AVG, "amount"),
            MetricSpec("middle", AggregateFunction.MEDIAN, "amount"),
            MetricSpec("minimum", AggregateFunction.MIN, "amount"),
            MetricSpec("maximum", AggregateFunction.MAX, "amount"),
            MetricSpec("first_date", AggregateFunction.MIN, "created_at"),
            MetricSpec("last_date", AggregateFunction.MAX, "created_at"),
        ],
    )

    assert isinstance(result, AggregateDatasetResult)
    assert result.columns == (
        "rows",
        "notes",
        "users",
        "total",
        "average",
        "middle",
        "minimum",
        "maximum",
        "first_date",
        "last_date",
    )
    assert result.row_count == 1
    assert result.truncated is False
    row = result.rows[0]
    assert row == {
        "rows": 8,
        "notes": 5,
        "users": 7,
        "total": 205,
        "average": pytest.approx(25.625),
        "middle": pytest.approx(25.0),
        "minimum": -5,
        "maximum": 60,
        "first_date": date(2024, 1, 5),
        "last_date": date(2024, 6, 1),
    }


def test_single_dimension_and_metric_alias_sort(
    query_sample_files: dict[str, Path], tmp_path: Path
) -> None:
    tool, dataset_id = _aggregate_tool(query_sample_files, tmp_path)

    result = tool(
        dataset_id,
        dimensions=[DimensionSpec("region_name", "region")],
        metrics=[
            MetricSpec("revenue", AggregateFunction.SUM, "amount"),
            MetricSpec("orders", AggregateFunction.COUNT),
        ],
        order_by=[AggregateSortSpec("revenue", SortDirection.DESC)],
    )

    assert result.rows == (
        {"region_name": "north", "revenue": 100, "orders": 4},
        {"region_name": "south", "revenue": 60, "orders": 2},
        {"region_name": "west", "revenue": 50, "orders": 1},
        {"region_name": "east", "revenue": -5, "orders": 1},
    )


def test_multiple_dimensions_and_dimension_alias_sort(
    query_sample_files: dict[str, Path], tmp_path: Path
) -> None:
    tool, dataset_id = _aggregate_tool(query_sample_files, tmp_path)

    result = tool(
        dataset_id,
        dimensions=[
            DimensionSpec("region_name", "region"),
            DimensionSpec("status_name", "status"),
        ],
        metrics=[MetricSpec("orders", AggregateFunction.COUNT)],
        order_by=[
            AggregateSortSpec("region_name"),
            AggregateSortSpec("status_name"),
        ],
    )

    assert result.columns == ("region_name", "status_name", "orders")
    assert result.row_count == 6
    assert result.rows[0] == {
        "region_name": "east",
        "status_name": "completed",
        "orders": 1,
    }


def test_filter_and_aggregate_use_and_semantics(
    query_sample_files: dict[str, Path], tmp_path: Path
) -> None:
    tool, dataset_id = _aggregate_tool(query_sample_files, tmp_path)

    result = tool(
        dataset_id,
        dimensions=[DimensionSpec("region_name", "region")],
        metrics=[MetricSpec("revenue", AggregateFunction.SUM, "amount")],
        filters=[
            FilterCondition("status", FilterOperator.EQ, "completed"),
            FilterCondition("amount", FilterOperator.GT, 0),
        ],
        order_by=[AggregateSortSpec("revenue", SortDirection.DESC)],
    )

    assert result.rows == (
        {"region_name": "north", "revenue": 70},
        {"region_name": "south", "revenue": 60},
    )


def test_empty_aggregate_preserves_duckdb_count_and_sum_semantics(
    query_sample_files: dict[str, Path], tmp_path: Path
) -> None:
    tool, dataset_id = _aggregate_tool(query_sample_files, tmp_path)

    result = tool(
        dataset_id,
        metrics=[
            MetricSpec("rows", AggregateFunction.COUNT),
            MetricSpec("total", AggregateFunction.SUM, "amount"),
        ],
        filters=[FilterCondition("id", FilterOperator.GT, 999)],
    )

    assert result.rows == ({"rows": 0, "total": None},)


@pytest.mark.parametrize(
    ("grain", "expected_groups"),
    [
        (TimeGrain.YEAR, 3),
        (TimeGrain.QUARTER, 4),
        (TimeGrain.MONTH, 5),
        (TimeGrain.WEEK, 5),
        (TimeGrain.DAY, 6),
    ],
)
@pytest.mark.parametrize("column", ["event_date", "event_at"])
def test_all_time_grains_for_date_and_timestamp(
    tmp_path: Path,
    parquet_factory: Callable[[Path, str], Path],
    grain: TimeGrain,
    expected_groups: int,
    column: str,
) -> None:
    path = parquet_factory(
        tmp_path / "time.parquet",
        """
        SELECT event_date, event_date::TIMESTAMP + INTERVAL '12 hours' AS event_at
        FROM (VALUES
            (DATE '2023-12-31'),
            (DATE '2024-01-01'),
            (DATE '2024-02-15'),
            (DATE '2024-04-01'),
            (DATE '2024-04-02'),
            (DATE '2025-01-01')
        ) AS rows(event_date)
        """,
    )
    registry = DatasetRegistry(allowed_roots=[tmp_path])
    dataset = registry.register(path)

    result = AggregateDatasetTool(registry)(
        dataset.dataset_id,
        dimensions=[DimensionSpec("bucket", column, grain)],
        metrics=[MetricSpec("events", AggregateFunction.COUNT)],
        order_by=[AggregateSortSpec("bucket")],
    )

    assert result.row_count == expected_groups
    assert sum(row["events"] for row in result.rows) == 6


def test_time_grain_rejects_non_temporal_and_time_only_columns(
    tmp_path: Path, parquet_factory: Callable[[Path, str], Path]
) -> None:
    path = parquet_factory(
        tmp_path / "invalid_time.parquet",
        "SELECT 1 AS amount, TIME '12:00:00' AS clock_time",
    )
    registry = DatasetRegistry(allowed_roots=[tmp_path])
    dataset = registry.register(path)
    tool = AggregateDatasetTool(registry)

    for column in ("amount", "clock_time"):
        with pytest.raises(InvalidDimensionError, match="DATE or TIMESTAMP"):
            tool(
                dataset.dataset_id,
                dimensions=[DimensionSpec("month", column, TimeGrain.MONTH)],
                metrics=[MetricSpec("rows", AggregateFunction.COUNT)],
            )


def test_invalid_time_grain_and_unknown_dimension_fail_closed(
    query_sample_files: dict[str, Path], tmp_path: Path
) -> None:
    tool, dataset_id = _aggregate_tool(query_sample_files, tmp_path)
    metric = MetricSpec("rows", AggregateFunction.COUNT)

    with pytest.raises(InvalidDimensionError, match="Time grain"):
        tool(
            dataset_id,
            dimensions=[
                DimensionSpec("bucket", "created_at", "hour")  # type: ignore[arg-type]
            ],
            metrics=[metric],
        )
    with pytest.raises(ColumnNotFoundError):
        tool(
            dataset_id,
            dimensions=[DimensionSpec("missing_dim", "missing")],
            metrics=[metric],
        )


def test_metric_validation_is_conservative(
    query_sample_files: dict[str, Path], tmp_path: Path
) -> None:
    tool, dataset_id = _aggregate_tool(query_sample_files, tmp_path)
    invalid_metrics = [
        MetricSpec("missing_column", AggregateFunction.SUM),
        MetricSpec("sum_region", AggregateFunction.SUM, "region"),
        MetricSpec("avg_region", AggregateFunction.AVG, "region"),
        MetricSpec("median_region", AggregateFunction.MEDIAN, "region"),
        MetricSpec("min_region", AggregateFunction.MIN, "region"),
        MetricSpec("distinct_missing", AggregateFunction.COUNT_DISTINCT),
        MetricSpec("bad", "variance", "amount"),  # type: ignore[arg-type]
    ]

    for metric in invalid_metrics:
        with pytest.raises(InvalidMetricError):
            tool(dataset_id, metrics=[metric])
    with pytest.raises(ColumnNotFoundError):
        tool(
            dataset_id,
            metrics=[MetricSpec("total", AggregateFunction.SUM, "unknown")],
        )


def test_alias_validation_and_global_uniqueness(
    query_sample_files: dict[str, Path], tmp_path: Path
) -> None:
    tool, dataset_id = _aggregate_tool(query_sample_files, tmp_path)

    with pytest.raises(InvalidDimensionError):
        tool(
            dataset_id,
            dimensions=[DimensionSpec("bad-name", "region")],
            metrics=[MetricSpec("rows", AggregateFunction.COUNT)],
        )
    with pytest.raises(InvalidMetricError):
        tool(dataset_id, metrics=[MetricSpec("drop table", AggregateFunction.COUNT)])
    with pytest.raises(QueryBuildError, match="globally unique"):
        tool(
            dataset_id,
            dimensions=[DimensionSpec("result", "region")],
            metrics=[MetricSpec("RESULT", AggregateFunction.COUNT)],
        )


def test_aggregate_sort_validation(
    query_sample_files: dict[str, Path], tmp_path: Path
) -> None:
    tool, dataset_id = _aggregate_tool(query_sample_files, tmp_path)
    dimensions = [DimensionSpec("region_name", "region")]
    metrics = [MetricSpec("orders", AggregateFunction.COUNT)]

    with pytest.raises(InvalidSortError):
        tool(
            dataset_id,
            dimensions=dimensions,
            metrics=metrics,
            order_by=[AggregateSortSpec("unknown")],
        )
    with pytest.raises(InvalidSortError):
        tool(
            dataset_id,
            dimensions=dimensions,
            metrics=metrics,
            order_by=[AggregateSortSpec("orders", "sideways")],  # type: ignore[arg-type]
        )


@pytest.mark.parametrize(
    ("limit", "expected_count", "expected_truncated"),
    [(5, 4, False), (4, 4, False), (3, 3, True)],
)
def test_aggregate_truncation_semantics(
    query_sample_files: dict[str, Path],
    tmp_path: Path,
    limit: int,
    expected_count: int,
    expected_truncated: bool,
) -> None:
    tool, dataset_id = _aggregate_tool(query_sample_files, tmp_path)

    result = tool(
        dataset_id,
        dimensions=[DimensionSpec("region_name", "region")],
        metrics=[MetricSpec("orders", AggregateFunction.COUNT)],
        order_by=[AggregateSortSpec("region_name")],
        limit=limit,
    )

    assert result.row_count == expected_count
    assert result.truncated is expected_truncated


def test_aggregate_resource_limits_fail_closed(
    query_sample_files: dict[str, Path], tmp_path: Path
) -> None:
    tool, dataset_id = _aggregate_tool(query_sample_files, tmp_path)
    count_metric = MetricSpec("rows", AggregateFunction.COUNT)

    with pytest.raises(ResourceLimitError, match="MAX_GROUP_BY_DIMENSIONS=5"):
        tool(
            dataset_id,
            dimensions=[
                DimensionSpec(f"d{index}", "region")
                for index in range(MAX_GROUP_BY_DIMENSIONS + 1)
            ],
            metrics=[count_metric],
        )
    with pytest.raises(ResourceLimitError, match="MAX_METRICS=10"):
        tool(
            dataset_id,
            metrics=[
                MetricSpec(f"m{index}", AggregateFunction.COUNT)
                for index in range(MAX_METRICS + 1)
            ],
        )
    with pytest.raises(ResourceLimitError, match="MAX_FILTERS=20"):
        tool(
            dataset_id,
            metrics=[count_metric],
            filters=[
                FilterCondition("id", FilterOperator.GTE, 0)
                for _ in range(MAX_FILTERS + 1)
            ],
        )
    with pytest.raises(ResourceLimitError, match="MAX_RESULT_ROWS=200"):
        tool(dataset_id, metrics=[count_metric], limit=MAX_RESULT_ROWS + 1)
    for invalid_limit in (0, -1, True, 1.5):
        with pytest.raises(InvalidProjectionError):
            tool(dataset_id, metrics=[count_metric], limit=invalid_limit)  # type: ignore[arg-type]


def test_aggregate_requires_at_least_one_metric(
    query_sample_files: dict[str, Path], tmp_path: Path
) -> None:
    tool, dataset_id = _aggregate_tool(query_sample_files, tmp_path)

    with pytest.raises(InvalidMetricError, match="At least one"):
        tool(dataset_id, metrics=[])


def test_identifier_safety_across_filter_dimension_metric_and_sort(
    tmp_path: Path, parquet_factory: Callable[[Path, str], Path]
) -> None:
    path = parquet_factory(
        tmp_path / "identifiers.parquet",
        """
        SELECT * FROM (VALUES
            (1, 'yes', 'Ada', 10, 'a'),
            (2, 'no', 'Bob', 20, 'b')
        ) AS rows("order", "select", "user name", "amount$", "quote""column")
        """,
    )
    registry = DatasetRegistry(allowed_roots=[tmp_path])
    dataset = registry.register(path)

    result = AggregateDatasetTool(registry)(
        dataset.dataset_id,
        dimensions=[DimensionSpec("order_group", "order")],
        metrics=[MetricSpec("total_amount", AggregateFunction.SUM, "amount$")],
        filters=[FilterCondition("user name", FilterOperator.EQ, "Ada")],
        order_by=[AggregateSortSpec("total_amount", SortDirection.DESC)],
    )

    assert result.rows == ({"order_group": 1, "total_amount": 10},)


def test_aggregate_tool_accepts_no_path_or_sql_arguments(
    query_sample_files: dict[str, Path], tmp_path: Path
) -> None:
    tool, dataset_id = _aggregate_tool(query_sample_files, tmp_path)
    metrics = [MetricSpec("rows", AggregateFunction.COUNT)]

    with pytest.raises(TypeError):
        tool(dataset_id, metrics=metrics, path=query_sample_files["csv"])  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        tool(dataset_id, metrics=metrics, sql="SELECT 1")  # type: ignore[call-arg]
