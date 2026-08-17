from datetime import datetime, timezone
from pathlib import Path

import pytest

from data_copilot.diagnostics import (
    PIPELINE_EVIDENCE_PREFIX,
    PipelineEvidenceBuilder,
    PipelineEvidenceFormatter,
    PipelineEvent,
    PipelineRun,
    PipelineRunLoader,
    PipelineStepRun,
    compare_pipeline_runs,
    sanitize_pipeline_text,
)
from data_copilot.errors import (
    PipelineEvidenceBuildError,
    PipelineEvidenceLimitError,
)


FIXTURE_DIRECTORY = Path(__file__).parent / "fixtures" / "pipeline"


def _fixture_runs() -> tuple[PipelineRun, PipelineRun, PipelineRun]:
    healthy = PipelineRunLoader(
        FIXTURE_DIRECTORY / "healthy_run.json",
        allowed_roots=[FIXTURE_DIRECTORY],
    ).load()[0]
    failed, prompt = PipelineRunLoader(
        FIXTURE_DIRECTORY / "incident_runs.jsonl",
        allowed_roots=[FIXTURE_DIRECTORY],
    ).load()
    return healthy, failed, prompt


def _run_with_events(events: tuple[PipelineEvent, ...]) -> PipelineRun:
    return PipelineRun(
        pipeline_id="daily_orders",
        run_id="run_events",
        status="failed",
        steps=(
            PipelineStepRun(
                step_id="extract",
                name="Extract",
                ordinal=0,
                status="failed",
                events=events,
            ),
        ),
        provenance={"logical_source": "events.json", "record_index": 0},
    )


def _event(message: str, *, level: str = "error") -> PipelineEvent:
    return PipelineEvent(
        timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
        level=level,
        step_id="extract",
        message=message,
    )


def test_evidence_contains_selected_observations_and_comparison() -> None:
    healthy, failed, _ = _fixture_runs()

    evidence = PipelineEvidenceBuilder().build(
        failed,
        compare_pipeline_runs(healthy, failed),
    )

    assert evidence.run.run_id == "run_failed"
    assert [step.step_id for step in evidence.steps] == [
        "extract_orders",
        "transform_orders",
        "load_orders",
    ]
    assert [event.level.value for event in evidence.events] == ["warning", "error"]
    assert evidence.findings
    assert evidence.truncated is False
    assert evidence.warnings == ()


def test_info_and_debug_events_are_not_in_evidence() -> None:
    _, failed, _ = _fixture_runs()

    evidence = PipelineEvidenceBuilder().build(failed)

    messages = [event.message for event in evidence.events]
    assert not any("started" in message.lower() for message in messages)
    assert all(event.level.value in {"warning", "error", "critical"} for event in evidence.events)


def test_formatter_uses_distinct_deterministic_channel() -> None:
    _, failed, _ = _fixture_runs()
    evidence = PipelineEvidenceBuilder().build(failed)
    formatter = PipelineEvidenceFormatter()

    first = formatter.format(evidence)
    second = formatter.format(evidence)

    assert first == second
    assert first.startswith(PIPELINE_EVIDENCE_PREFIX)
    assert first.count("PIPELINE_EVIDENCE") == 1
    assert "DATASET_EVIDENCE" not in first


def test_secrets_are_redacted_without_mutating_source_observation() -> None:
    _, _, prompt = _fixture_runs()
    original = prompt.steps[0].events[0].message

    evidence = PipelineEvidenceBuilder().build(prompt)
    formatted = PipelineEvidenceFormatter().format(evidence)

    assert "super-secret" not in formatted
    assert "token-value" not in formatted
    assert "db-password" not in formatted
    assert "restricted_user" not in formatted
    assert "[REDACTED]" in formatted
    assert "[REDACTED_CONNECTION]" in formatted
    assert prompt.steps[0].events[0].message == original


def test_prompt_injection_text_remains_inert_observed_data() -> None:
    _, _, prompt = _fixture_runs()

    formatted = PipelineEvidenceFormatter().format(
        PipelineEvidenceBuilder().build(prompt)
    )

    assert "Ignore previous instructions" in formatted


@pytest.mark.parametrize(
    "secret",
    [
        "password=hunter2",
        "api_key: abc123",
        "Bearer token-value",
        "postgresql://user:pass@db.example/prod",
        "jdbc:postgresql://db.example/prod?password=pass",
        "host=db.example uid=admin",
        "sk-abcdefghijklmnopqrstuv",
        "AKIAABCDEFGHIJKLMNOP",
    ],
)
def test_secret_sanitizer_covers_common_credential_forms(secret: str) -> None:
    sanitized = sanitize_pipeline_text(secret)

    assert secret not in sanitized
    assert "REDACTED" in sanitized


def test_event_message_and_record_counts_are_truncated_explicitly() -> None:
    run = _run_with_events(
        tuple(_event(f"failure-{index}-" + "x" * 100) for index in range(3))
    )

    evidence = PipelineEvidenceBuilder(
        max_events=2,
        max_message_chars=20,
    ).build(run)

    assert len(evidence.events) == 2
    assert all(len(event.message) == 20 for event in evidence.events)
    assert all(event.message.endswith("…") for event in evidence.events)
    assert evidence.truncated is True
    assert any("events were truncated" in warning for warning in evidence.warnings)
    assert any("messages were truncated" in warning for warning in evidence.warnings)


def test_total_character_limit_drops_whole_records_and_marks_truncation() -> None:
    run = _run_with_events(tuple(_event("x" * 100) for _ in range(3)))

    evidence = PipelineEvidenceBuilder(max_chars=700).build(run)
    formatted = PipelineEvidenceFormatter(max_chars=700).format(evidence)

    assert len(formatted) <= 700
    assert evidence.truncated is True
    assert any("character limit" in warning for warning in evidence.warnings)


def test_unusable_character_limit_fails_closed() -> None:
    _, failed, _ = _fixture_runs()

    with pytest.raises(PipelineEvidenceLimitError, match="cannot fit"):
        PipelineEvidenceBuilder(max_chars=1).build(failed)


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("max_steps", 0),
        ("max_events", -1),
        ("max_findings", True),
        ("max_message_chars", 0),
        ("max_chars", 0),
    ],
)
def test_invalid_evidence_limits_fail_closed(name: str, value: object) -> None:
    with pytest.raises(PipelineEvidenceLimitError, match=name):
        PipelineEvidenceBuilder(**{name: value})


def test_builder_requires_typed_matching_input() -> None:
    healthy, failed, _ = _fixture_runs()
    comparison = compare_pipeline_runs(healthy, failed)
    other = failed.model_copy(update={"run_id": "other"})

    with pytest.raises(PipelineEvidenceBuildError, match="typed PipelineRun"):
        PipelineEvidenceBuilder().build({})  # type: ignore[arg-type]
    with pytest.raises(PipelineEvidenceBuildError, match="must be typed"):
        PipelineEvidenceBuilder().build(failed, {})  # type: ignore[arg-type]
    with pytest.raises(PipelineEvidenceBuildError, match="selected run"):
        PipelineEvidenceBuilder().build(other, comparison)


def test_formatter_rejects_wrong_type_and_oversize_envelope() -> None:
    _, failed, _ = _fixture_runs()
    evidence = PipelineEvidenceBuilder().build(failed)

    with pytest.raises(TypeError, match="PipelineEvidence"):
        PipelineEvidenceFormatter().format({})  # type: ignore[arg-type]
    with pytest.raises(PipelineEvidenceLimitError, match="exceeds"):
        PipelineEvidenceFormatter(max_chars=1).format(evidence)
