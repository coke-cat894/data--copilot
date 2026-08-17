from pathlib import Path

import pytest

from data_copilot.diagnostics import (
    PipelineFindingType,
    PipelineRun,
    PipelineRunLoader,
    PipelineStepRun,
    compare_pipeline_runs,
)
from data_copilot.errors import PipelineComparisonError


FIXTURE_DIRECTORY = Path(__file__).parent / "fixtures" / "pipeline"


def _run(
    run_id: str,
    *,
    status: str = "success",
    steps: tuple[PipelineStepRun, ...] = (),
    pipeline_id: str = "daily_orders",
) -> PipelineRun:
    return PipelineRun(
        pipeline_id=pipeline_id,
        run_id=run_id,
        status=status,
        steps=steps,
        provenance={"logical_source": "synthetic.json", "record_index": 0},
    )


def _step(step_id: str, ordinal: int, **values: object) -> PipelineStepRun:
    return PipelineStepRun(
        step_id=step_id,
        name=step_id.replace("_", " "),
        ordinal=ordinal,
        status=values.pop("status", "success"),
        **values,
    )


def test_realistic_runs_report_only_observed_factual_changes() -> None:
    healthy = PipelineRunLoader(
        FIXTURE_DIRECTORY / "healthy_run.json",
        allowed_roots=[FIXTURE_DIRECTORY],
    ).load()[0]
    failed = PipelineRunLoader(
        FIXTURE_DIRECTORY / "incident_runs.jsonl",
        allowed_roots=[FIXTURE_DIRECTORY],
    ).load()[0]

    comparison = compare_pipeline_runs(healthy, failed)
    types = [finding.finding_type for finding in comparison.findings]

    assert types == [
        PipelineFindingType.OVERALL_STATUS_CHANGED,
        PipelineFindingType.STEP_STATUS_CHANGED,
        PipelineFindingType.STEP_DURATION_CHANGED,
        PipelineFindingType.INPUT_ROWS_CHANGED,
        PipelineFindingType.OUTPUT_ROWS_CHANGED,
        PipelineFindingType.OUTPUT_ROWS_CHANGED,
        PipelineFindingType.WARNING_EVENT_COUNT_CHANGED,
        PipelineFindingType.ERROR_EVENT_COUNT_CHANGED,
    ]
    assert comparison.findings[0].before_value == "success"
    assert comparison.findings[0].after_value == "failed"
    assert any(
        finding.step_id == "transform_orders"
        and finding.finding_type is PipelineFindingType.OUTPUT_ROWS_CHANGED
        and finding.absolute_delta == -420
        for finding in comparison.findings
    )
    assert all("cause" not in finding.description.lower() for finding in comparison.findings)
    assert all("root" not in finding.description.lower() for finding in comparison.findings)


def test_added_missing_and_early_stop_are_separate_observations() -> None:
    before = _run(
        "before",
        steps=(
            _step("extract", 0),
            _step("transform", 1),
            _step("load", 2),
            _step("publish", 3),
        ),
    )
    after = _run(
        "after",
        status="failed",
        steps=(
            _step("extract", 0),
            _step("validate", 1),
            _step("transform", 2, status="failed"),
        ),
    )

    comparison = compare_pipeline_runs(before, after)
    types = [finding.finding_type for finding in comparison.findings]

    assert PipelineFindingType.STEP_ADDED in types
    assert types.count(PipelineFindingType.STEP_MISSING) == 2
    assert types[-1] is PipelineFindingType.PIPELINE_STOPPED_EARLY
    early = comparison.findings[-1]
    assert early.step_id == "transform"
    assert early.before_value == 2
    assert "later baseline step(s) were not observed" in early.description


def test_unknown_numeric_values_are_not_reported_as_changes() -> None:
    before = _run("before", steps=(_step("extract", 0, input_rows=None),))
    after = _run("after", steps=(_step("extract", 0, input_rows=10),))

    comparison = compare_pipeline_runs(before, after)

    assert comparison.findings == ()


def test_zero_is_compared_as_a_known_value() -> None:
    before = _run("before", steps=(_step("extract", 0, output_rows=0),))
    after = _run("after", steps=(_step("extract", 0, output_rows=5),))

    finding = compare_pipeline_runs(before, after).findings[0]

    assert finding.finding_type is PipelineFindingType.OUTPUT_ROWS_CHANGED
    assert finding.before_value == 0
    assert finding.absolute_delta == 5


def test_different_pipeline_identities_fail_closed() -> None:
    with pytest.raises(PipelineComparisonError, match="different pipeline"):
        compare_pipeline_runs(
            _run("before", pipeline_id="one"),
            _run("after", pipeline_id="two"),
        )


def test_identical_observations_are_deterministic_and_empty() -> None:
    before = _run("before", steps=(_step("extract", 0, input_rows=10),))
    after = _run("after", steps=(_step("extract", 0, input_rows=10),))

    first = compare_pipeline_runs(before, after)
    second = compare_pipeline_runs(before, after)

    assert first == second
    assert first.findings == ()
    assert first.before_run_id == "before"
    assert first.after_run_id == "after"
