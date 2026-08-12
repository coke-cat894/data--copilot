from pathlib import Path

import pytest

from data_copilot.datasets import DatasetRegistry
from data_copilot.errors import DatasetNotFoundError
from data_copilot.tools import InspectDatasetResult, InspectDatasetTool


@pytest.mark.parametrize("key", ["csv", "parquet", "jsonl"])
def test_inspect_dataset_tool_returns_typed_public_result(
    sample_files: dict[str, Path], tmp_path: Path, key: str
) -> None:
    registry = DatasetRegistry(allowed_roots=[tmp_path])
    dataset = registry.register(sample_files[key])

    result = InspectDatasetTool(registry)(dataset.dataset_id)

    assert isinstance(result, InspectDatasetResult)
    assert result.dataset_id == dataset.dataset_id
    assert result.display_name == dataset.display_name
    assert result.format == dataset.format
    assert result.file_size_bytes == dataset.file_size_bytes
    assert result.row_count == 3
    assert result.column_count == 3
    assert [column.name for column in result.columns] == [
        "order_id",
        "amount",
        "region",
    ]
    public_output = result.model_dump(mode="json")
    assert "resolved_path" not in public_output
    assert str(sample_files[key]) not in result.model_dump_json()


def test_inspect_dataset_tool_unknown_id_fails_closed(tmp_path: Path) -> None:
    tool = InspectDatasetTool(DatasetRegistry(allowed_roots=[tmp_path]))

    with pytest.raises(DatasetNotFoundError):
        tool("ds_unknown")


def test_inspect_dataset_tool_accepts_no_path_or_sql_arguments(tmp_path: Path) -> None:
    tool = InspectDatasetTool(DatasetRegistry(allowed_roots=[tmp_path]))

    with pytest.raises(TypeError):
        tool(dataset_id="ds_unknown", path=tmp_path / "sample.csv")  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        tool(dataset_id="ds_unknown", sql="SELECT 1")  # type: ignore[call-arg]
