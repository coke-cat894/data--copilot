import json
from unittest.mock import MagicMock

import pytest

from data_copilot.diagnostics import (
    ColumnSnapshot,
    DatasetSnapshot,
    PipelineEvent,
    PipelineRun,
    PipelineStepRun,
    PostgresDiagnosticCollector,
    PostgresDiagnosticResult,
    TroubleshootingResources,
)
from data_copilot.errors import DiagnosticResourceError, UnknownToolError
from data_copilot.tools import TroubleshootingToolSet


def _snapshot(snapshot_id: str, rows: int) -> DatasetSnapshot:
    return DatasetSnapshot(
        dataset_id="sales.orders",
        snapshot_id=snapshot_id,
        row_count=rows,
        columns=(ColumnSnapshot(name="id", data_type="bigint", nullable=False),),
    )


def _run(run_id: str, status: str, output_rows: int) -> PipelineRun:
    event = (
        PipelineEvent(
            level="error",
            message="password=secret postgresql://user:pass@db/orders",
        ),
    ) if status == "failed" else ()
    return PipelineRun(
        pipeline_id="daily_orders",
        run_id=run_id,
        status=status,
        steps=(
            PipelineStepRun(
                step_id="load_orders",
                name="Load orders",
                ordinal=0,
                status=status,
                output_rows=output_rows,
                events=event,
            ),
        ),
        provenance={"logical_source": "runs.json", "record_index": 0},
    )


def test_tool_availability_follows_explicit_resources() -> None:
    collector = MagicMock(spec=PostgresDiagnosticCollector)
    resources = TroubleshootingResources(
        collector=collector,
        snapshots=(_snapshot("before", 1200),),
        pipeline_runs=(_run("before", "success", 1200), _run("after", "failed", 0)),
    )

    names = tuple(
        schema.name for schema in TroubleshootingToolSet("db_1", resources).schemas
    )

    assert names == (
        "collect_table_diagnostics",
        "compare_table_snapshots",
        "inspect_pipeline_run",
        "compare_pipeline_runs",
    )
    parameter_names = {
        property_name
        for schema in TroubleshootingToolSet("db_1", resources).schemas
        for property_name in schema.parameters["properties"]
    }
    assert parameter_names.isdisjoint(
        {"dsn", "sql", "password", "timeout", "credentials", "path"}
    )


def test_collection_reuses_equivalent_snapshot() -> None:
    collector = MagicMock(spec=PostgresDiagnosticCollector)
    collector.collect.return_value = PostgresDiagnosticResult(
        snapshot=_snapshot("driver-id", 780).model_copy(update={"snapshot_id": None})
    )
    tools = TroubleshootingToolSet(
        "db_1",
        TroubleshootingResources(collector=collector),
    )
    arguments = json.dumps({"schema_name": "sales", "table_name": "orders"})

    first = tools.dispatch("collect_table_diagnostics", arguments)
    second = tools.dispatch("collect_table_diagnostics", arguments)

    assert first == second
    assert first.snapshot is not None  # type: ignore[union-attr]
    assert first.snapshot.snapshot_id.startswith("collected:")  # type: ignore[union-attr]
    collector.collect.assert_called_once_with(
        "db_1", schema_name="sales", table_name="orders"
    )


def test_snapshot_and_pipeline_comparisons_are_deterministic() -> None:
    resources = TroubleshootingResources(
        snapshots=(_snapshot("before", 1200), _snapshot("after", 780)),
        pipeline_runs=(_run("before", "success", 1200), _run("after", "failed", 780)),
    )
    tools = TroubleshootingToolSet("db_1", resources)

    diagnostic = tools.dispatch(
        "compare_table_snapshots",
        json.dumps({"before_snapshot_id": "before", "after_snapshot_id": "after"}),
    )
    pipeline = tools.dispatch(
        "compare_pipeline_runs",
        json.dumps(
            {
                "pipeline_id": "daily_orders",
                "before_run_id": "before",
                "after_run_id": "after",
            }
        ),
    )

    assert diagnostic.comparison is not None  # type: ignore[union-attr]
    assert diagnostic.comparison.findings[0].absolute_delta == -420  # type: ignore[union-attr]
    assert pipeline.run.run_id == "after"  # type: ignore[union-attr]
    assert pipeline.findings  # type: ignore[union-attr]
    assert "secret" not in pipeline.events[0].message  # type: ignore[union-attr]


def test_missing_resource_and_unconfigured_tool_fail_closed() -> None:
    tools = TroubleshootingToolSet(
        "db_1",
        TroubleshootingResources(snapshots=(_snapshot("only", 1),)),
    )

    with pytest.raises(UnknownToolError):
        tools.dispatch(
            "compare_table_snapshots",
            json.dumps({"before_snapshot_id": "missing", "after_snapshot_id": "only"}),
        )


def test_resource_metadata_reports_missing_baseline_without_exposing_values() -> None:
    resources = TroubleshootingResources(
        snapshots=(_snapshot("current", 780),)
    )

    assert resources.to_public_metadata()["snapshot_comparison_state"] == [
        {
            "dataset_id": "sales.orders",
            "snapshot_count": 1,
            "comparison_available": False,
            "unavailable_reason": "baseline_or_before_snapshot_unavailable",
        }
    ]


def test_resource_index_rejects_missing_or_duplicate_identities() -> None:
    with pytest.raises(DiagnosticResourceError, match="require logical"):
        TroubleshootingResources(
            snapshots=(_snapshot("one", 1).model_copy(update={"snapshot_id": None}),)
        )
    with pytest.raises(DiagnosticResourceError, match="unique"):
        TroubleshootingResources(
            snapshots=(_snapshot("same", 1), _snapshot("same", 2))
        )
    with pytest.raises(DiagnosticResourceError, match="path-free"):
        TroubleshootingResources(snapshots=(_snapshot("/private/baseline", 1),))
    with pytest.raises(DiagnosticResourceError, match="secret-like"):
        TroubleshootingResources(snapshots=(_snapshot("password=secret", 1),))
