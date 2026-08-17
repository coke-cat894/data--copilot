"""Build sanitized bounded evidence from typed pipeline observations."""

from collections.abc import Iterable, Sequence
import re

from data_copilot.diagnostics.pipeline_constants import (
    MAX_PIPELINE_EVIDENCE_CHARS,
    MAX_PIPELINE_EVIDENCE_EVENTS,
    MAX_PIPELINE_EVIDENCE_FINDINGS,
    MAX_PIPELINE_EVIDENCE_MESSAGE_CHARS,
    MAX_PIPELINE_EVIDENCE_STEPS,
    MAX_PIPELINE_EVIDENCE_WARNINGS,
)
from data_copilot.diagnostics.pipeline_evidence_formatter import (
    PIPELINE_EVIDENCE_PREFIX,
    serialize_pipeline_evidence,
)
from data_copilot.diagnostics.pipeline_evidence_models import (
    PipelineEvidence,
    PipelineEvidenceEvent,
    PipelineEvidenceFinding,
    PipelineEvidenceProvenance,
    PipelineEvidenceRun,
    PipelineEvidenceStep,
)
from data_copilot.diagnostics.pipeline_models import (
    PipelineComparison,
    PipelineEvent,
    PipelineEventLevel,
    PipelineFinding,
    PipelineRun,
    pipeline_event_sort_key,
)
from data_copilot.errors import (
    PipelineEvidenceBuildError,
    PipelineEvidenceLimitError,
)


_URI_SECRET = re.compile(
    r"(?i)\b(?:jdbc:|postgres(?:ql)?://|mysql://|mariadb://|mongodb(?:\+srv)?://|"
    r"redis://|amqps?://|https?://)[^\s\"']+"
)
_BEARER_SECRET = re.compile(r"(?i)\bbearer\s+[^\s,;]+")
_KEY_VALUE_SECRET = re.compile(
    r"(?i)\b(password|passwd|pwd|api[_-]?key|access[_-]?token|refresh[_-]?token|"
    r"authorization|client[_-]?secret|secret)\b\s*[:=]\s*"
    r"(?:\"[^\"]*\"|'[^']*'|[^\s,;]+)"
)
_CONNECTION_PART = re.compile(
    r"(?i)\b(server|host|data\s+source|user\s+id|uid)\b\s*=\s*[^\s;]+"
)
_OPENAI_STYLE_KEY = re.compile(r"\bsk-[A-Za-z0-9_-]{12,}\b")
_AWS_ACCESS_KEY = re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b")


def sanitize_pipeline_text(value: str) -> str:
    """Conservatively redact common secret forms without mutating source models."""

    sanitized = _URI_SECRET.sub("[REDACTED_CONNECTION]", value)
    sanitized = _BEARER_SECRET.sub("Bearer [REDACTED]", sanitized)
    sanitized = _KEY_VALUE_SECRET.sub(
        lambda match: f"{match.group(1)}=[REDACTED]",
        sanitized,
    )
    sanitized = _CONNECTION_PART.sub(
        lambda match: f"{match.group(1)}=[REDACTED]",
        sanitized,
    )
    sanitized = _OPENAI_STYLE_KEY.sub("[REDACTED_API_KEY]", sanitized)
    return _AWS_ACCESS_KEY.sub("[REDACTED_ACCESS_KEY]", sanitized)


class PipelineEvidenceBuilder:
    """Select high-signal facts, sanitize text, and enforce context bounds."""

    def __init__(
        self,
        *,
        max_steps: int = MAX_PIPELINE_EVIDENCE_STEPS,
        max_events: int = MAX_PIPELINE_EVIDENCE_EVENTS,
        max_findings: int = MAX_PIPELINE_EVIDENCE_FINDINGS,
        max_message_chars: int = MAX_PIPELINE_EVIDENCE_MESSAGE_CHARS,
        max_chars: int = MAX_PIPELINE_EVIDENCE_CHARS,
    ) -> None:
        self._max_steps = _positive_limit("max_steps", max_steps)
        self._max_events = _positive_limit("max_events", max_events)
        self._max_findings = _positive_limit("max_findings", max_findings)
        self._max_message_chars = _positive_limit(
            "max_message_chars", max_message_chars
        )
        self._max_chars = _positive_limit("max_chars", max_chars)

    def build(
        self,
        run: PipelineRun,
        comparison: PipelineComparison | None = None,
    ) -> PipelineEvidence:
        if not isinstance(run, PipelineRun):
            raise PipelineEvidenceBuildError(
                "Pipeline evidence requires a typed PipelineRun."
            )
        if comparison is not None and not isinstance(comparison, PipelineComparison):
            raise PipelineEvidenceBuildError(
                "Pipeline evidence comparison must be typed."
            )
        if comparison is not None and (
            comparison.pipeline_id != run.pipeline_id
            or comparison.after_run_id != run.run_id
        ):
            raise PipelineEvidenceBuildError(
                "Pipeline comparison does not describe the selected run."
            )

        warnings: list[str] = []
        truncated = False
        selected_steps = run.steps
        if len(selected_steps) > self._max_steps:
            selected_steps = selected_steps[: self._max_steps]
            truncated = True
            _add_warning(
                warnings,
                f"Pipeline evidence steps were truncated to {self._max_steps}.",
            )

        relevant_events = tuple(
            sorted(
                (
                    event
                    for event in _all_events(run)
                    if event.level
                    in {
                        PipelineEventLevel.WARNING,
                        PipelineEventLevel.ERROR,
                        PipelineEventLevel.CRITICAL,
                    }
                ),
                key=pipeline_event_sort_key,
            )
        )
        if len(relevant_events) > self._max_events:
            relevant_events = relevant_events[: self._max_events]
            truncated = True
            _add_warning(
                warnings,
                f"Pipeline evidence events were truncated to {self._max_events}.",
            )

        findings: tuple[PipelineFinding, ...] = (
            comparison.findings if comparison is not None else ()
        )
        if len(findings) > self._max_findings:
            findings = findings[: self._max_findings]
            truncated = True
            _add_warning(
                warnings,
                f"Pipeline evidence findings were truncated to {self._max_findings}.",
            )

        events: list[PipelineEvidenceEvent] = []
        for event in relevant_events:
            message = sanitize_pipeline_text(event.message)
            if len(message) > self._max_message_chars:
                message = _truncate(message, self._max_message_chars)
                truncated = True
                _add_warning(
                    warnings,
                    "One or more pipeline event messages were truncated.",
                )
            events.append(
                PipelineEvidenceEvent(
                    timestamp=event.timestamp,
                    level=event.level,
                    step_id=_sanitize_optional(event.step_id),
                    message=message,
                    event_code=_sanitize_optional(event.event_code),
                    category=_sanitize_optional(event.category),
                )
            )

        evidence = PipelineEvidence(
            run=PipelineEvidenceRun(
                pipeline_id=sanitize_pipeline_text(run.pipeline_id),
                run_id=sanitize_pipeline_text(run.run_id),
                execution_time=run.execution_time,
                start_time=run.start_time,
                end_time=run.end_time,
                status=run.status,
                provenance=PipelineEvidenceProvenance(
                    logical_source=sanitize_pipeline_text(
                        run.provenance.logical_source
                    ),
                    record_index=run.provenance.record_index,
                ),
            ),
            steps=tuple(
                PipelineEvidenceStep(
                    step_id=sanitize_pipeline_text(step.step_id),
                    name=sanitize_pipeline_text(step.name),
                    ordinal=step.ordinal,
                    status=step.status,
                    start_time=step.start_time,
                    end_time=step.end_time,
                    duration_seconds=step.duration_seconds,
                    input_rows=step.input_rows,
                    output_rows=step.output_rows,
                    rejected_rows=step.rejected_rows,
                )
                for step in selected_steps
            ),
            events=tuple(events),
            findings=tuple(_evidence_finding(finding) for finding in findings),
            truncated=truncated,
            warnings=tuple(warnings),
        )
        return self._fit_total_size(evidence)

    def _fit_total_size(self, evidence: PipelineEvidence) -> PipelineEvidence:
        current = evidence
        warning = (
            "Pipeline evidence records were reduced to satisfy the total "
            "character limit."
        )
        while self._formatted_length(current) > self._max_chars:
            update: dict[str, object]
            if current.events:
                update = {"events": current.events[:-1]}
            elif current.steps:
                update = {"steps": current.steps[:-1]}
            elif current.findings:
                update = {"findings": current.findings[:-1]}
            else:
                raise PipelineEvidenceLimitError(
                    "Pipeline evidence envelope cannot fit the character limit."
                )
            warnings = list(current.warnings)
            _add_warning(warnings, warning)
            update.update({"truncated": True, "warnings": tuple(warnings)})
            current = current.model_copy(update=update)
        return current

    @staticmethod
    def _formatted_length(evidence: PipelineEvidence) -> int:
        return len(PIPELINE_EVIDENCE_PREFIX + serialize_pipeline_evidence(evidence))


def _all_events(run: PipelineRun) -> Iterable[PipelineEvent]:
    yield from run.events
    for step in run.steps:
        yield from step.events


def _evidence_finding(finding: PipelineFinding) -> PipelineEvidenceFinding:
    return PipelineEvidenceFinding(
        finding_type=finding.finding_type,
        step_id=_sanitize_optional(finding.step_id),
        before_value=_sanitize_finding_value(finding.before_value),
        after_value=_sanitize_finding_value(finding.after_value),
        absolute_delta=finding.absolute_delta,
        description=sanitize_pipeline_text(finding.description),
    )


def _sanitize_finding_value(value: str | int | float | None) -> str | int | float | None:
    return sanitize_pipeline_text(value) if isinstance(value, str) else value


def _sanitize_optional(value: str | None) -> str | None:
    return sanitize_pipeline_text(value) if value is not None else None


def _truncate(value: str, maximum: int) -> str:
    if len(value) <= maximum:
        return value
    return "…" if maximum == 1 else value[: maximum - 1] + "…"


def _add_warning(warnings: list[str], warning: str) -> None:
    if warning in warnings:
        return
    if len(warnings) < MAX_PIPELINE_EVIDENCE_WARNINGS:
        warnings.append(warning)


def _positive_limit(name: str, value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise PipelineEvidenceLimitError(f"{name} must be a positive integer.")
    return value
