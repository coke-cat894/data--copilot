from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

import pytest

from data_copilot.config import MAX_QUALITY_COLUMNS
from data_copilot.datasets import DatasetRegistry
from data_copilot.errors import (
    ColumnNotFoundError,
    InvalidQualityRequestError,
    ResourceLimitError,
)
from data_copilot.execution import QualityCheck, QualityClassification
from data_copilot.tools import CheckDataQualityTool, DataQualityResult


REFERENCE_TIME = datetime(2025, 1, 1, 12, tzinfo=timezone.utc)


def _quality_result(
    tmp_path: Path,
    parquet_factory: Callable[[Path, str], Path],
    query: str,
    *,
    columns: list[str] | None = None,
) -> DataQualityResult:
    path = parquet_factory(tmp_path / "quality.parquet", query)
    registry = DatasetRegistry(allowed_roots=[tmp_path])
    dataset = registry.register(path)
    return CheckDataQualityTool(registry)(
        dataset.dataset_id,
        columns=columns,
        reference_time=REFERENCE_TIME,
    )


def _issues_by_check(result: DataQualityResult, check: QualityCheck) -> list:
    return [issue for issue in result.issues if issue.check is check]


def test_null_all_null_constant_and_negative_checks_are_typed(
    tmp_path: Path, parquet_factory: Callable[[Path, str], Path]
) -> None:
    result = _quality_result(
        tmp_path,
        parquet_factory,
        """
        SELECT * FROM (VALUES
            (1, NULL::VARCHAR, 'same', 5),
            (2, NULL::VARCHAR, 'same', -2),
            (NULL::INTEGER, NULL::VARCHAR, 'same', -7)
        ) AS rows(id, all_null, constant_value, amount)
        """,
    )

    assert result.row_count == 3
    assert result.column_count == 4
    assert result.checked_column_count == 4

    null_issues = _issues_by_check(result, QualityCheck.NULL_VALUES)
    assert {(issue.column, issue.count) for issue in null_issues} == {
        ("id", 1),
        ("all_null", 3),
    }
    assert all(
        issue.classification is QualityClassification.OBJECTIVE
        for issue in null_issues
    )

    all_null = _issues_by_check(result, QualityCheck.ALL_NULL_COLUMN)
    assert len(all_null) == 1
    assert all_null[0].column == "all_null"
    assert all_null[0].rate == 1.0

    constant = _issues_by_check(result, QualityCheck.CONSTANT_COLUMN)
    assert [(issue.column, issue.count) for issue in constant] == [
        ("constant_value", 3)
    ]

    negative = _issues_by_check(result, QualityCheck.NEGATIVE_NUMERIC_VALUES)
    assert len(negative) == 1
    assert negative[0].classification is QualityClassification.HEURISTIC
    assert negative[0].column == "amount"
    assert negative[0].count == 2
    assert negative[0].rate == pytest.approx(2 / 3)
    assert negative[0].details["min_value"] == -7


def test_clean_columns_produce_no_null_or_duplicate_issues(
    tmp_path: Path, parquet_factory: Callable[[Path, str], Path]
) -> None:
    result = _quality_result(
        tmp_path,
        parquet_factory,
        "SELECT i::INTEGER AS id FROM range(3) AS rows(i)",
    )

    assert _issues_by_check(result, QualityCheck.NULL_VALUES) == []
    assert _issues_by_check(result, QualityCheck.DUPLICATE_ROWS) == []


def test_duplicate_rows_mean_exact_full_row_duplicates_beyond_first(
    tmp_path: Path, parquet_factory: Callable[[Path, str], Path]
) -> None:
    result = _quality_result(
        tmp_path,
        parquet_factory,
        """
        SELECT * FROM (VALUES
            (1, 'a'), (1, 'a'), (1, 'a'), (2, 'a')
        ) AS rows(id, label)
        """,
        columns=["id"],
    )

    duplicate = _issues_by_check(result, QualityCheck.DUPLICATE_ROWS)
    assert len(duplicate) == 1
    assert duplicate[0].column is None
    assert duplicate[0].classification is QualityClassification.OBJECTIVE
    assert duplicate[0].count == 2
    assert duplicate[0].rate == 0.5
    assert duplicate[0].details == {
        "semantics": "exact_full_row_duplicates_beyond_first"
    }


def test_empty_dataset_does_not_mark_columns_all_null_or_constant(
    tmp_path: Path, parquet_factory: Callable[[Path, str], Path]
) -> None:
    result = _quality_result(
        tmp_path,
        parquet_factory,
        """
        SELECT NULL::INTEGER AS id, NULL::VARCHAR AS note WHERE FALSE
        """,
    )

    assert result.row_count == 0
    assert result.issues == ()


def test_one_row_dataset_does_not_mark_columns_constant(
    tmp_path: Path, parquet_factory: Callable[[Path, str], Path]
) -> None:
    result = _quality_result(
        tmp_path,
        parquet_factory,
        "SELECT 1 AS id, 'only' AS label",
    )

    assert _issues_by_check(result, QualityCheck.CONSTANT_COLUMN) == []


def test_future_date_and_timestamp_are_heuristic_but_time_is_excluded(
    tmp_path: Path, parquet_factory: Callable[[Path, str], Path]
) -> None:
    result = _quality_result(
        tmp_path,
        parquet_factory,
        """
        SELECT * FROM (VALUES
            (DATE '2024-12-31', TIMESTAMP '2025-01-01 11:00:00', TIME '23:59:59'),
            (DATE '2025-01-02', TIMESTAMP '2025-01-01 13:00:00', TIME '00:00:01')
        ) AS rows(event_date, event_at, clock_time)
        """,
    )

    future = _issues_by_check(result, QualityCheck.FUTURE_DATETIME_VALUES)
    assert [(issue.column, issue.count) for issue in future] == [
        ("event_date", 1),
        ("event_at", 1),
    ]
    assert all(
        issue.classification is QualityClassification.HEURISTIC
        for issue in future
    )
    assert all(issue.column != "clock_time" for issue in future)
    assert future[0].details["reference_time"] == REFERENCE_TIME


def test_future_timestamp_with_timezone_uses_utc_reference(
    tmp_path: Path, parquet_factory: Callable[[Path, str], Path]
) -> None:
    result = _quality_result(
        tmp_path,
        parquet_factory,
        """
        SELECT * FROM (VALUES
            (TIMESTAMPTZ '2025-01-01 11:00:00+00'),
            (TIMESTAMPTZ '2025-01-01 13:00:00+00')
        ) AS rows(event_at)
        """,
    )

    future = _issues_by_check(result, QualityCheck.FUTURE_DATETIME_VALUES)
    assert len(future) == 1
    assert future[0].column == "event_at"
    assert future[0].count == 1


def test_selected_columns_limit_column_checks_but_not_duplicate_semantics(
    tmp_path: Path, parquet_factory: Callable[[Path, str], Path]
) -> None:
    result = _quality_result(
        tmp_path,
        parquet_factory,
        """
        SELECT * FROM (VALUES
            (1, NULL::VARCHAR), (1, NULL::VARCHAR)
        ) AS rows(id, note)
        """,
        columns=["id"],
    )

    assert result.checked_column_count == 1
    assert all(issue.column != "note" for issue in result.issues)
    assert len(_issues_by_check(result, QualityCheck.DUPLICATE_ROWS)) == 1


def test_quality_column_validation_and_reference_time_fail_closed(
    tmp_path: Path, parquet_factory: Callable[[Path, str], Path]
) -> None:
    path = parquet_factory(tmp_path / "simple.parquet", "SELECT 1 AS id")
    registry = DatasetRegistry(allowed_roots=[tmp_path])
    dataset = registry.register(path)
    tool = CheckDataQualityTool(registry)

    with pytest.raises(ColumnNotFoundError):
        tool(dataset.dataset_id, columns=["missing"], reference_time=REFERENCE_TIME)
    with pytest.raises(InvalidQualityRequestError, match="Duplicate"):
        tool(
            dataset.dataset_id,
            columns=["id", "id"],
            reference_time=REFERENCE_TIME,
        )
    with pytest.raises(InvalidQualityRequestError, match="cannot be empty"):
        tool(dataset.dataset_id, columns=[], reference_time=REFERENCE_TIME)
    with pytest.raises(InvalidQualityRequestError, match="timezone-aware"):
        tool(dataset.dataset_id, reference_time=datetime(2025, 1, 1))


def test_quality_wide_dataset_caps_implicit_and_rejects_explicit_overflow(
    tmp_path: Path, parquet_factory: Callable[[Path, str], Path]
) -> None:
    aliases = ", ".join(f"{index} AS c{index}" for index in range(51))
    path = parquet_factory(tmp_path / "wide.parquet", f"SELECT {aliases}")
    registry = DatasetRegistry(allowed_roots=[tmp_path])
    dataset = registry.register(path)
    tool = CheckDataQualityTool(registry)

    result = tool(dataset.dataset_id, reference_time=REFERENCE_TIME)

    assert result.column_count == 51
    assert result.checked_column_count == MAX_QUALITY_COLUMNS
    assert result.warnings == (
        "Dataset has 51 columns. 50 columns were checked because "
        "MAX_QUALITY_COLUMNS=50.",
    )
    with pytest.raises(ResourceLimitError, match="MAX_QUALITY_COLUMNS=50"):
        tool(
            dataset.dataset_id,
            columns=[f"c{index}" for index in range(51)],
            reference_time=REFERENCE_TIME,
        )


def test_quality_result_is_path_free_and_tool_accepts_no_path_or_sql(
    tmp_path: Path, parquet_factory: Callable[[Path, str], Path]
) -> None:
    path = parquet_factory(tmp_path / "simple.parquet", "SELECT -1 AS amount")
    registry = DatasetRegistry(allowed_roots=[tmp_path])
    dataset = registry.register(path)
    tool = CheckDataQualityTool(registry)

    result = tool(dataset.dataset_id, reference_time=REFERENCE_TIME)

    assert str(path) not in result.model_dump_json()
    with pytest.raises(TypeError):
        tool(dataset.dataset_id, path=path)  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        tool(dataset.dataset_id, sql="SELECT 1")  # type: ignore[call-arg]
