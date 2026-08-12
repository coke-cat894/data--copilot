from collections.abc import Callable
from pathlib import Path

import pytest

from data_copilot.config import MAX_FILTERS, MAX_RESULT_ROWS
from data_copilot.datasets import DatasetRegistry
from data_copilot.errors import (
    ColumnNotFoundError,
    InvalidFilterError,
    InvalidProjectionError,
    InvalidSortError,
    ResourceLimitError,
)
from data_copilot.tools import (
    FilterCondition,
    FilterDatasetResult,
    FilterDatasetTool,
    FilterOperator,
    SortDirection,
    SortSpec,
)


def _filter_tool(
    query_sample_files: dict[str, Path], tmp_path: Path
) -> tuple[FilterDatasetTool, str]:
    registry = DatasetRegistry(allowed_roots=[tmp_path])
    dataset = registry.register(query_sample_files["parquet"])
    return FilterDatasetTool(registry), dataset.dataset_id


@pytest.mark.parametrize(
    ("condition", "expected_ids"),
    [
        (FilterCondition("status", FilterOperator.EQ, "completed"), [1, 2, 4, 5, 8]),
        (FilterCondition("status", FilterOperator.NE, "completed"), [3, 6, 7]),
        (FilterCondition("amount", FilterOperator.GT, 20), [3, 5, 7, 8]),
        (FilterCondition("amount", FilterOperator.GTE, 20), [2, 3, 5, 7, 8]),
        (FilterCondition("amount", FilterOperator.LT, 10), [4, 6]),
        (FilterCondition("amount", FilterOperator.LTE, 10), [1, 4, 6]),
        (
            FilterCondition("region", FilterOperator.IN, ["north", "east"]),
            [1, 3, 4, 6, 8],
        ),
        (
            FilterCondition("region", FilterOperator.NOT_IN, ["north", "east"]),
            [2, 5, 7],
        ),
        (FilterCondition("amount", FilterOperator.BETWEEN, [10, 30]), [1, 2, 3]),
        (FilterCondition("optional_note", FilterOperator.IS_NULL), [2, 4, 8]),
        (
            FilterCondition("optional_note", FilterOperator.IS_NOT_NULL),
            [1, 3, 5, 6, 7],
        ),
    ],
)
def test_all_filter_operators(
    query_sample_files: dict[str, Path],
    tmp_path: Path,
    condition: FilterCondition,
    expected_ids: list[int],
) -> None:
    tool, dataset_id = _filter_tool(query_sample_files, tmp_path)

    result = tool(
        dataset_id,
        columns=["id"],
        filters=[condition],
        order_by=[SortSpec("id")],
    )

    assert isinstance(result, FilterDatasetResult)
    assert [row["id"] for row in result.rows] == expected_ids
    assert result.row_count == len(expected_ids)
    assert result.truncated is False


def test_multiple_filters_use_and(
    query_sample_files: dict[str, Path], tmp_path: Path
) -> None:
    tool, dataset_id = _filter_tool(query_sample_files, tmp_path)

    result = tool(
        dataset_id,
        columns=["id", "amount"],
        filters=[
            FilterCondition("region", FilterOperator.EQ, "north"),
            FilterCondition("amount", FilterOperator.GT, 20),
        ],
        order_by=[SortSpec("id")],
    )

    assert [row["id"] for row in result.rows] == [3, 8]


def test_filter_values_are_bound_parameters_not_sql(
    query_sample_files: dict[str, Path], tmp_path: Path
) -> None:
    tool, dataset_id = _filter_tool(query_sample_files, tmp_path)
    injection_like_value = "Robert'); DROP TABLE x;--"

    matched = tool(
        dataset_id,
        columns=["id", "status"],
        filters=[
            FilterCondition("status", FilterOperator.EQ, injection_like_value)
        ],
    )
    still_queryable = tool(dataset_id, columns=["id"], order_by=[SortSpec("id")])

    assert matched.rows == ({"id": 7, "status": injection_like_value},)
    assert still_queryable.row_count == 8


def test_invalid_filter_operator_and_value_shapes_fail_closed(
    query_sample_files: dict[str, Path], tmp_path: Path
) -> None:
    tool, dataset_id = _filter_tool(query_sample_files, tmp_path)
    invalid_conditions = [
        FilterCondition("status", "like", "complete%"),  # type: ignore[arg-type]
        FilterCondition("amount", FilterOperator.GT, [10]),
        FilterCondition("amount", FilterOperator.BETWEEN, [10]),
        FilterCondition("amount", FilterOperator.IN, []),
        FilterCondition("amount", FilterOperator.IN, 10),
        FilterCondition("amount", FilterOperator.IS_NULL, 10),
        FilterCondition("amount", FilterOperator.EQ, None),
        FilterCondition("amount", FilterOperator.IN, [1, None]),  # type: ignore[list-item]
    ]

    for condition in invalid_conditions:
        with pytest.raises(InvalidFilterError):
            tool(dataset_id, filters=[condition])


def test_unknown_filter_column_fails_closed(
    query_sample_files: dict[str, Path], tmp_path: Path
) -> None:
    tool, dataset_id = _filter_tool(query_sample_files, tmp_path)

    with pytest.raises(ColumnNotFoundError):
        tool(
            dataset_id,
            filters=[FilterCondition("missing", FilterOperator.EQ, 1)],
        )


def test_filter_sorting_asc_desc_and_multiple_fields(
    query_sample_files: dict[str, Path], tmp_path: Path
) -> None:
    tool, dataset_id = _filter_tool(query_sample_files, tmp_path)

    descending = tool(
        dataset_id,
        columns=["id", "amount"],
        order_by=[SortSpec("amount", SortDirection.DESC)],
    )
    multiple = tool(
        dataset_id,
        columns=["id", "region", "amount"],
        order_by=[
            SortSpec("region", SortDirection.ASC),
            SortSpec("amount", SortDirection.DESC),
        ],
    )

    assert [row["id"] for row in descending.rows] == [8, 7, 5, 3, 2, 1, 6, 4]
    assert [row["id"] for row in multiple.rows] == [4, 8, 3, 1, 6, 5, 2, 7]


def test_invalid_sort_direction_unknown_and_duplicate_columns_fail_closed(
    query_sample_files: dict[str, Path], tmp_path: Path
) -> None:
    tool, dataset_id = _filter_tool(query_sample_files, tmp_path)

    with pytest.raises(InvalidSortError):
        tool(
            dataset_id,
            order_by=[SortSpec("id", "sideways")],  # type: ignore[arg-type]
        )
    with pytest.raises(ColumnNotFoundError):
        tool(dataset_id, order_by=[SortSpec("missing")])
    with pytest.raises(InvalidSortError, match="Duplicate"):
        tool(dataset_id, order_by=[SortSpec("id"), SortSpec("id")])


@pytest.mark.parametrize(
    ("limit", "expected_count", "expected_truncated"),
    [(10, 8, False), (8, 8, False), (7, 7, True)],
)
def test_filter_truncation_semantics(
    query_sample_files: dict[str, Path],
    tmp_path: Path,
    limit: int,
    expected_count: int,
    expected_truncated: bool,
) -> None:
    tool, dataset_id = _filter_tool(query_sample_files, tmp_path)

    result = tool(dataset_id, columns=["id"], order_by=[SortSpec("id")], limit=limit)

    assert result.row_count == expected_count
    assert result.truncated is expected_truncated


def test_filter_limits_fail_closed(
    query_sample_files: dict[str, Path], tmp_path: Path
) -> None:
    tool, dataset_id = _filter_tool(query_sample_files, tmp_path)

    with pytest.raises(ResourceLimitError, match="MAX_RESULT_ROWS=200"):
        tool(dataset_id, limit=MAX_RESULT_ROWS + 1)
    for invalid_limit in (0, -1, True, 1.5):
        with pytest.raises(InvalidProjectionError):
            tool(dataset_id, limit=invalid_limit)  # type: ignore[arg-type]
    with pytest.raises(ResourceLimitError, match="MAX_FILTERS=20"):
        tool(
            dataset_id,
            filters=[
                FilterCondition("id", FilterOperator.GTE, 0)
                for _ in range(MAX_FILTERS + 1)
            ],
        )


def test_filter_tool_accepts_no_path_or_sql_arguments(
    query_sample_files: dict[str, Path], tmp_path: Path
) -> None:
    tool, dataset_id = _filter_tool(query_sample_files, tmp_path)

    with pytest.raises(TypeError):
        tool(dataset_id, path=query_sample_files["csv"])  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        tool(dataset_id, sql="SELECT 1")  # type: ignore[call-arg]


def test_filter_and_sort_quote_unusual_source_identifiers(
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

    result = FilterDatasetTool(registry)(
        dataset.dataset_id,
        columns=["order", "select", 'quote"column'],
        filters=[FilterCondition("user name", FilterOperator.EQ, "Ada")],
        order_by=[SortSpec("amount$", SortDirection.DESC)],
    )

    assert result.rows == (
        {"order": 1, "select": "yes", 'quote"column': "a"},
    )
