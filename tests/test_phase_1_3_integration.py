from pathlib import Path

import pytest

from data_copilot.datasets import DatasetRegistry
from data_copilot.execution import NumericColumnProfile
from data_copilot.tools import (
    AggregateDatasetTool,
    AggregateFunction,
    AggregateSortSpec,
    DimensionSpec,
    FilterCondition,
    FilterDatasetTool,
    FilterOperator,
    InspectDatasetTool,
    MetricSpec,
    ProfileDatasetTool,
    SampleDatasetTool,
    SortSpec,
)


@pytest.mark.parametrize("key", ["csv", "parquet", "jsonl"])
def test_full_phase_1_local_data_flow_for_each_format(
    query_sample_files: dict[str, Path], tmp_path: Path, key: str
) -> None:
    registry = DatasetRegistry(allowed_roots=[tmp_path])
    dataset = registry.register(query_sample_files[key])

    inspection = InspectDatasetTool(registry)(dataset.dataset_id)
    profile = ProfileDatasetTool(registry)(
        dataset.dataset_id, columns=["amount"]
    )
    sample = SampleDatasetTool(registry)(
        dataset.dataset_id, columns=["id", "region"], size=2, seed=42
    )
    filtered = FilterDatasetTool(registry)(
        dataset.dataset_id,
        columns=["id"],
        filters=[FilterCondition("status", FilterOperator.EQ, "completed")],
        order_by=[SortSpec("id")],
    )
    aggregated = AggregateDatasetTool(registry)(
        dataset.dataset_id,
        dimensions=[DimensionSpec("region_name", "region")],
        metrics=[MetricSpec("revenue", AggregateFunction.SUM, "amount")],
        order_by=[AggregateSortSpec("region_name")],
    )

    assert inspection.row_count == 8
    assert inspection.column_count == 8
    assert isinstance(profile.columns[0], NumericColumnProfile)
    assert profile.columns[0].min == -5
    assert profile.columns[0].max == 60
    assert sample.row_count == 2
    assert sample.columns == ("id", "region")
    assert [row["id"] for row in filtered.rows] == [1, 2, 4, 5, 8]
    assert aggregated.rows == (
        {"region_name": "east", "revenue": -5},
        {"region_name": "north", "revenue": 100},
        {"region_name": "south", "revenue": 60},
        {"region_name": "west", "revenue": 50},
    )
    for result in (inspection, profile, sample, filtered, aggregated):
        assert str(query_sample_files[key]) not in result.model_dump_json()
