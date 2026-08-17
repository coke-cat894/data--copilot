"""Pure deterministic comparison of compatible pipeline run observations."""

from collections.abc import Iterable

from data_copilot.diagnostics.pipeline_models import (
    PipelineComparison,
    PipelineEvent,
    PipelineEventLevel,
    PipelineFinding,
    PipelineFindingType,
    PipelineRun,
    PipelineStepRun,
)
from data_copilot.errors import PipelineComparisonError


def compare_pipeline_runs(
    before: PipelineRun,
    after: PipelineRun,
) -> PipelineComparison:
    """Return every comparable factual difference in canonical order."""

    if before.pipeline_id != after.pipeline_id:
        raise PipelineComparisonError(
            "Cannot compare runs with different pipeline identities."
        )
    findings: list[PipelineFinding] = []
    if before.status != after.status:
        findings.append(
            _finding(
                PipelineFindingType.OVERALL_STATUS_CHANGED,
                before_value=before.status.value,
                after_value=after.status.value,
                description=(
                    f"pipeline status changed from {before.status.value} "
                    f"to {after.status.value}"
                ),
            )
        )

    before_steps = {step.step_id: step for step in before.steps}
    after_steps = {step.step_id: step for step in after.steps}
    before_ids = set(before_steps)
    after_ids = set(after_steps)
    common_ids = before_ids & after_ids

    for step in after.steps:
        if step.step_id not in before_ids:
            findings.append(
                _finding(
                    PipelineFindingType.STEP_ADDED,
                    step_id=step.step_id,
                    before_value=None,
                    after_value=step.status.value,
                    description=(
                        f"step {_quote(step.step_id)} was observed with status "
                        f"{step.status.value}"
                    ),
                )
            )
    for step in before.steps:
        if step.step_id not in after_ids:
            findings.append(
                _finding(
                    PipelineFindingType.STEP_MISSING,
                    step_id=step.step_id,
                    before_value=step.status.value,
                    after_value=None,
                    description=(
                        f"step {_quote(step.step_id)} from the baseline run was "
                        "not observed"
                    ),
                )
            )

    ordered_common = tuple(
        step.step_id for step in before.steps if step.step_id in common_ids
    )
    for step_id in ordered_common:
        old = before_steps[step_id]
        new = after_steps[step_id]
        if old.status != new.status:
            findings.append(
                _finding(
                    PipelineFindingType.STEP_STATUS_CHANGED,
                    step_id=step_id,
                    before_value=old.status.value,
                    after_value=new.status.value,
                    description=(
                        f"step {_quote(step_id)} status changed from "
                        f"{old.status.value} to {new.status.value}"
                    ),
                )
            )
    for step_id in ordered_common:
        _append_numeric_change(
            findings,
            PipelineFindingType.STEP_DURATION_CHANGED,
            "duration_seconds",
            before_steps[step_id],
            after_steps[step_id],
            step_id,
        )
    for finding_type, attribute in (
        (PipelineFindingType.INPUT_ROWS_CHANGED, "input_rows"),
        (PipelineFindingType.OUTPUT_ROWS_CHANGED, "output_rows"),
        (PipelineFindingType.REJECTED_ROWS_CHANGED, "rejected_rows"),
    ):
        for step_id in ordered_common:
            _append_numeric_change(
                findings,
                finding_type,
                attribute,
                before_steps[step_id],
                after_steps[step_id],
                step_id,
            )

    before_events = tuple(_all_events(before))
    after_events = tuple(_all_events(after))
    for finding_type, label, levels in (
        (
            PipelineFindingType.WARNING_EVENT_COUNT_CHANGED,
            "WARNING event count",
            {PipelineEventLevel.WARNING},
        ),
        (
            PipelineFindingType.ERROR_EVENT_COUNT_CHANGED,
            "ERROR/CRITICAL event count",
            {PipelineEventLevel.ERROR, PipelineEventLevel.CRITICAL},
        ),
    ):
        old_count = sum(event.level in levels for event in before_events)
        new_count = sum(event.level in levels for event in after_events)
        if old_count != new_count:
            findings.append(
                _finding(
                    finding_type,
                    before_value=old_count,
                    after_value=new_count,
                    absolute_delta=new_count - old_count,
                    description=(
                        f"{label} changed from {old_count} to {new_count} "
                        f"({_signed(new_count - old_count)})"
                    ),
                )
            )

    if after.steps:
        last_after = max(after.steps, key=lambda step: (step.ordinal, step.step_id))
        baseline_last = before_steps.get(last_after.step_id)
        later_missing = (
            tuple(
                step
                for step in before.steps
                if step.step_id not in after_ids
                and step.ordinal > baseline_last.ordinal
            )
            if baseline_last is not None
            else ()
        )
        if baseline_last is not None and later_missing:
            findings.append(
                _finding(
                    PipelineFindingType.PIPELINE_STOPPED_EARLY,
                    step_id=last_after.step_id,
                    before_value=len(later_missing),
                    after_value=0,
                    description=(
                        f"pipeline stopped after observed step "
                        f"{_quote(last_after.step_id)}; {len(later_missing)} later "
                        "baseline step(s) were not observed"
                    ),
                )
            )

    return PipelineComparison(
        pipeline_id=before.pipeline_id,
        before_run_id=before.run_id,
        after_run_id=after.run_id,
        findings=tuple(findings),
    )


def _append_numeric_change(
    findings: list[PipelineFinding],
    finding_type: PipelineFindingType,
    attribute: str,
    before: PipelineStepRun,
    after: PipelineStepRun,
    step_id: str,
) -> None:
    old_value = getattr(before, attribute)
    new_value = getattr(after, attribute)
    if old_value is None or new_value is None or old_value == new_value:
        return
    delta = new_value - old_value
    findings.append(
        _finding(
            finding_type,
            step_id=step_id,
            before_value=old_value,
            after_value=new_value,
            absolute_delta=delta,
            description=(
                f"step {_quote(step_id)} {attribute} changed from "
                f"{_number(old_value)} to {_number(new_value)} ({_signed(delta)})"
            ),
        )
    )


def _all_events(run: PipelineRun) -> Iterable[PipelineEvent]:
    yield from run.events
    for step in run.steps:
        yield from step.events


def _finding(
    finding_type: PipelineFindingType,
    *,
    before_value: str | int | float | None,
    after_value: str | int | float | None,
    description: str,
    step_id: str | None = None,
    absolute_delta: int | float | None = None,
) -> PipelineFinding:
    return PipelineFinding(
        finding_type=finding_type,
        step_id=step_id,
        before_value=before_value,
        after_value=after_value,
        absolute_delta=absolute_delta,
        description=description,
    )


def _quote(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace("'", "\\'")
    return f"'{escaped}'"


def _number(value: int | float) -> str:
    if isinstance(value, int):
        return f"{value:,}"
    return f"{value:.12g}"


def _signed(value: int | float) -> str:
    prefix = "+" if value > 0 else ""
    return prefix + _number(value)
