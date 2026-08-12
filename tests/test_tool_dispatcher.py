import json
from pathlib import Path

import pytest

from data_copilot.datasets import DatasetRegistry
from data_copilot.errors import (
    ResourceLimitError,
    ToolArgumentError,
    UnknownToolError,
)
from data_copilot.execution import (
    AggregateFunction,
    FilterOperator,
    SortDirection,
    TimeGrain,
)
from data_copilot.tools import (
    AggregateDatasetResult,
    DataQualityResult,
    FilterDatasetResult,
    InspectDatasetResult,
    ProfileDatasetResult,
    SampleDatasetResult,
    ToolDispatcher,
)


@pytest.fixture
def dispatcher(
    query_sample_files: dict[str, Path], tmp_path: Path
) -> ToolDispatcher:
    registry = DatasetRegistry(allowed_roots=[tmp_path])
    dataset = registry.register(query_sample_files["csv"])
    return ToolDispatcher(registry, dataset.dataset_id)


def test_schemas_are_static_strict_and_expose_no_capability_fields(
    dispatcher: ToolDispatcher,
) -> None:
    schemas = dispatcher.schemas

    assert tuple(schema.name for schema in schemas) == (
        "inspect_dataset",
        "profile_dataset",
        "sample_dataset",
        "filter_dataset",
        "aggregate_dataset",
        "check_data_quality",
    )
    assert dispatcher.allowed_tool_names == frozenset(schema.name for schema in schemas)
    for schema in schemas:
        serialized = json.dumps(schema.model_dump(mode="json")).lower()
        assert schema.strict is True
        assert schema.parameters["additionalProperties"] is False
        assert schema.parameters["required"] == list(
            schema.parameters["properties"]
        )
        assert "dataset_id" not in serialized
        assert "path" not in serialized
        assert "sql" not in serialized
        assert "expression" not in serialized


def test_schema_enums_track_execution_enums(dispatcher: ToolDispatcher) -> None:
    serialized = json.dumps(
        [schema.model_dump(mode="json") for schema in dispatcher.schemas]
    )

    for enum_type in (
        FilterOperator,
        AggregateFunction,
        TimeGrain,
        SortDirection,
    ):
        for member in enum_type:
            assert f'"{member.value}"' in serialized


def test_dispatcher_executes_all_six_existing_tools(
    dispatcher: ToolDispatcher,
) -> None:
    results = (
        dispatcher.dispatch("inspect_dataset", "{}"),
        dispatcher.dispatch(
            "profile_dataset", '{"columns":["amount"],"top_k":5}'
        ),
        dispatcher.dispatch(
            "sample_dataset", '{"columns":["id"],"size":2,"seed":7}'
        ),
        dispatcher.dispatch(
            "filter_dataset",
            json.dumps(
                {
                    "columns": ["id", "amount"],
                    "filters": [
                        {"column": "amount", "operator": "gt", "value": 10}
                    ],
                    "order_by": [{"column": "amount", "direction": "desc"}],
                    "limit": 3,
                }
            ),
        ),
        dispatcher.dispatch(
            "aggregate_dataset",
            json.dumps(
                {
                    "dimensions": [
                        {"name": "region_name", "column": "region", "time_grain": None}
                    ],
                    "metrics": [
                        {"name": "avg_amount", "function": "avg", "column": "amount"}
                    ],
                    "filters": [],
                    "order_by": [{"field": "avg_amount", "direction": "desc"}],
                    "limit": 10,
                }
            ),
        ),
        dispatcher.dispatch("check_data_quality", '{"columns":["amount"]}'),
    )

    assert tuple(type(result) for result in results) == (
        InspectDatasetResult,
        ProfileDatasetResult,
        SampleDatasetResult,
        FilterDatasetResult,
        AggregateDatasetResult,
        DataQualityResult,
    )


def test_unknown_malformed_and_capability_arguments_fail_closed(
    dispatcher: ToolDispatcher,
) -> None:
    with pytest.raises(UnknownToolError, match="Unsupported"):
        dispatcher.dispatch("run_sql", '{"sql":"DROP TABLE x"}')
    with pytest.raises(ToolArgumentError, match="invalid"):
        dispatcher.dispatch("inspect_dataset", "not-json")
    with pytest.raises(ToolArgumentError, match="invalid"):
        dispatcher.dispatch("inspect_dataset", '{"dataset_id":"ds_other"}')
    with pytest.raises(ToolArgumentError, match="invalid"):
        dispatcher.dispatch("filter_dataset", '{"path":"/tmp/x"}')
    with pytest.raises(ToolArgumentError, match="invalid"):
        dispatcher.dispatch(
            "sample_dataset", '{"columns":null,"size":"20","seed":42}'
        )
    with pytest.raises(ToolArgumentError, match="invalid"):
        dispatcher.dispatch(
            "filter_dataset",
            '{"columns":null,"filters":[{"column":"amount",'
            '"operator":"gt","value":NaN}],"order_by":null,"limit":10}',
        )


def test_existing_resource_limits_remain_authoritative(
    dispatcher: ToolDispatcher,
) -> None:
    arguments = json.dumps(
        {"columns": None, "filters": [], "order_by": None, "limit": 201}
    )

    with pytest.raises(ResourceLimitError, match="MAX_RESULT_ROWS=200"):
        dispatcher.dispatch("filter_dataset", arguments)
