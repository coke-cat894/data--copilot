from collections.abc import Callable
from pathlib import Path

import pytest

from data_copilot.config import MAX_RESULT_COLUMNS, MAX_SAMPLE_ROWS
from data_copilot.datasets import DatasetRegistry
from data_copilot.errors import (
    ColumnNotFoundError,
    InvalidProjectionError,
    InvalidSampleRequestError,
    ResourceLimitError,
)
from data_copilot.tools import SampleDatasetResult, SampleDatasetTool


@pytest.mark.parametrize("key", ["csv", "parquet", "jsonl"])
def test_sample_supported_formats(
    query_sample_files: dict[str, Path], tmp_path: Path, key: str
) -> None:
    registry = DatasetRegistry(allowed_roots=[tmp_path])
    dataset = registry.register(query_sample_files[key])

    result = SampleDatasetTool(registry)(dataset.dataset_id, size=3, seed=42)

    assert isinstance(result, SampleDatasetResult)
    assert result.dataset_id == dataset.dataset_id
    assert result.row_count == 3
    assert result.requested_size == 3
    assert result.seed == 42
    assert result.columns == (
        "id",
        "user_id",
        "region",
        "status",
        "amount",
        "created_at",
        "optional_note",
        "active",
    )
    assert all(tuple(row) == result.columns for row in result.rows)
    assert str(query_sample_files[key]) not in result.model_dump_json()


def test_sample_returns_all_rows_when_dataset_is_smaller_than_size(
    query_sample_files: dict[str, Path], tmp_path: Path
) -> None:
    registry = DatasetRegistry(allowed_roots=[tmp_path])
    dataset = registry.register(query_sample_files["parquet"])

    result = SampleDatasetTool(registry)(dataset.dataset_id, size=20, seed=7)

    assert result.row_count == 8


def test_sample_seed_is_reproducible_and_can_change_selection(
    tmp_path: Path, parquet_factory: Callable[[Path, str], Path]
) -> None:
    path = parquet_factory(
        tmp_path / "hundred.parquet",
        "SELECT i::INTEGER AS id FROM range(100) AS rows(i)",
    )
    registry = DatasetRegistry(allowed_roots=[tmp_path])
    dataset = registry.register(path)
    tool = SampleDatasetTool(registry)

    first = tool(dataset.dataset_id, size=10, seed=42)
    repeated = tool(dataset.dataset_id, size=10, seed=42)
    different = tool(dataset.dataset_id, size=10, seed=43)

    assert first.rows == repeated.rows
    assert first.rows != different.rows


def test_sample_selected_columns_preserve_requested_order(
    query_sample_files: dict[str, Path], tmp_path: Path
) -> None:
    registry = DatasetRegistry(allowed_roots=[tmp_path])
    dataset = registry.register(query_sample_files["csv"])

    result = SampleDatasetTool(registry)(
        dataset.dataset_id, columns=["status", "id"], size=4
    )

    assert result.columns == ("status", "id")
    assert all(tuple(row) == ("status", "id") for row in result.rows)


def test_sample_rejects_unknown_and_duplicate_columns(
    query_sample_files: dict[str, Path], tmp_path: Path
) -> None:
    registry = DatasetRegistry(allowed_roots=[tmp_path])
    dataset = registry.register(query_sample_files["csv"])
    tool = SampleDatasetTool(registry)

    with pytest.raises(ColumnNotFoundError):
        tool(dataset.dataset_id, columns=["missing"])
    with pytest.raises(InvalidProjectionError, match="Duplicate"):
        tool(dataset.dataset_id, columns=["id", "id"])


def test_sample_size_and_seed_validation(
    query_sample_files: dict[str, Path], tmp_path: Path
) -> None:
    registry = DatasetRegistry(allowed_roots=[tmp_path])
    dataset = registry.register(query_sample_files["csv"])
    tool = SampleDatasetTool(registry)

    for invalid_size in (0, -1, True, 1.5):
        with pytest.raises(InvalidSampleRequestError):
            tool(dataset.dataset_id, size=invalid_size)  # type: ignore[arg-type]
    with pytest.raises(ResourceLimitError, match="MAX_SAMPLE_ROWS=100"):
        tool(dataset.dataset_id, size=MAX_SAMPLE_ROWS + 1)
    for invalid_seed in (-1, True, 1.5, 2_147_483_648):
        with pytest.raises(InvalidSampleRequestError):
            tool(dataset.dataset_id, seed=invalid_seed)  # type: ignore[arg-type]


def test_sample_wide_dataset_is_column_bounded_with_warning(
    tmp_path: Path, parquet_factory: Callable[[Path, str], Path]
) -> None:
    aliases = ", ".join(f"{index} AS c{index}" for index in range(51))
    path = parquet_factory(tmp_path / "wide.parquet", f"SELECT {aliases}")
    registry = DatasetRegistry(allowed_roots=[tmp_path])
    dataset = registry.register(path)

    result = SampleDatasetTool(registry)(dataset.dataset_id, size=1)

    assert len(result.columns) == MAX_RESULT_COLUMNS
    assert result.warnings == (
        "Dataset has 51 columns. 50 columns were returned because "
        "MAX_RESULT_COLUMNS=50.",
    )
    with pytest.raises(ResourceLimitError, match="MAX_RESULT_COLUMNS=50"):
        SampleDatasetTool(registry)(
            dataset.dataset_id, columns=[f"c{index}" for index in range(51)]
        )


def test_sample_tool_accepts_no_path_or_sql_arguments(
    query_sample_files: dict[str, Path], tmp_path: Path
) -> None:
    registry = DatasetRegistry(allowed_roots=[tmp_path])
    dataset = registry.register(query_sample_files["csv"])
    tool = SampleDatasetTool(registry)

    with pytest.raises(TypeError):
        tool(dataset.dataset_id, path=query_sample_files["csv"])  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        tool(dataset.dataset_id, sql="SELECT 1")  # type: ignore[call-arg]
