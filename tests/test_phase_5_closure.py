from pathlib import Path

import pytest

from data_copilot.evals.artifacts import scan_artifact_text
from data_copilot.evals.cli import (
    DEFAULT_PHASE5_CASES,
    _fixture_paths,
    _prompt_paths,
    build_parser,
    main as eval_main,
)
from data_copilot.evals.loader import load_cases
from data_copilot.evals.models import (
    CausalClassification,
    EvidenceChannel,
    EvalCategory,
)
from data_copilot.evals.troubleshooting_fixtures import (
    build_troubleshooting_resources,
)


PROJECT_ROOT = Path(__file__).parents[1]
FINAL_LIVE_CASE_IDS = (
    "pure_database_regression",
    "final_db_join_aggregate",
    "p3_metric_definition",
    "phase3_metric_regression",
    "p3_metric_by_region",
    "missing_semantic_business_metric",
    "p3_policy_explanation",
    "null_spike_unknown_cause",
    "confirmed_schema_drift_failure",
    "conflicting_pipeline_database_evidence",
    "missing_baseline",
    "prompt_injection_pipeline_log",
)


def test_final_live_suite_is_frozen_to_twelve_representative_cases() -> None:
    cases = load_cases(DEFAULT_PHASE5_CASES)

    assert tuple(case.case_id for case in cases) == FINAL_LIVE_CASE_IDS
    assert all(case.database == "data_copilot_test" for case in cases)
    assert {case.category for case in cases} == {
        EvalCategory.FUNCTIONAL,
        EvalCategory.GROUNDING,
        EvalCategory.NO_ANSWER,
        EvalCategory.SAFETY,
    }
    assert {
        channel for case in cases for channel in case.expected_evidence_channels
    } == {
        EvidenceChannel.SEMANTIC,
        EvidenceChannel.DOCUMENT,
        EvidenceChannel.DATA,
        EvidenceChannel.DIAGNOSTIC,
        EvidenceChannel.PIPELINE,
    }
    assert {
        case.causal_classification
        for case in cases
        if case.causal_classification is not None
    } >= {
        CausalClassification.OBSERVED_FACT,
        CausalClassification.CONFIRMED_ROOT_CAUSE,
        CausalClassification.INSUFFICIENT_EVIDENCE,
        CausalClassification.CONFLICTING_EVIDENCE,
    }


def test_final_live_suite_excludes_deterministic_only_mutation_requests() -> None:
    questions = "\n".join(
        case.question.casefold() for case in load_cases(DEFAULT_PHASE5_CASES)
    )

    assert all(
        statement not in questions
        for statement in ("insert ", "update ", "delete ", "drop ", "alter ")
    )
    scan_artifact_text(DEFAULT_PHASE5_CASES.read_text(encoding="utf-8"))


def test_final_suite_composes_semantic_document_and_troubleshooting_fixtures() -> None:
    prompt_paths = _prompt_paths("phase5")
    fixture_paths = _fixture_paths("phase5", DEFAULT_PHASE5_CASES, None)
    cases = {case.case_id: case for case in load_cases(DEFAULT_PHASE5_CASES)}

    assert {path.name for path in prompt_paths} == {
        "database_system.md",
        "troubleshooting.md",
    }
    assert DEFAULT_PHASE5_CASES in fixture_paths
    assert any(path.suffix == ".yaml" for path in fixture_paths)
    assert any(path.suffix in {".md", ".txt"} for path in fixture_paths)
    assert any(path.name == "troubleshooting_fixtures.py" for path in fixture_paths)
    assert build_troubleshooting_resources(
        cases["confirmed_schema_drift_failure"]
    ) is not None
    assert build_troubleshooting_resources(cases["final_db_join_aggregate"]) is None


def test_phase_5_live_cli_requires_explicit_external_data_approval(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = eval_main(["--mode", "live", "--target", "phase5"])

    assert exit_code == 2
    assert "requires explicit synthetic-data approval" in capsys.readouterr().out


def test_phase_5_target_is_discoverable_and_live_only(
    capsys: pytest.CaptureFixture[str],
) -> None:
    help_text = build_parser().format_help()
    assert "phase5" in help_text
    assert "--approve-phase5-external-data" in help_text

    exit_code = eval_main(["--mode", "mock", "--target", "phase5"])
    assert exit_code == 2
    assert "requires live mode" in capsys.readouterr().out


def test_phase_5_target_rejects_case_file_override(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = eval_main(
        [
            "--mode",
            "live",
            "--target",
            "phase5",
            "--cases",
            str(PROJECT_ROOT / "evals/cases/database_phase_2.jsonl"),
        ]
    )

    assert exit_code == 2
    assert "frozen final case file" in capsys.readouterr().out
