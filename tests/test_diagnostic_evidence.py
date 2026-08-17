from datetime import datetime, timezone

import pytest

from data_copilot.diagnostics import (
    ColumnSnapshot,
    DatasetSnapshot,
    DiagnosticEvidenceBuilder,
    DiagnosticEvidenceFormatter,
    PostgresDiagnosticResult,
    compare_snapshots,
)
from data_copilot.errors import (
    DiagnosticEvidenceBuildError,
    DiagnosticEvidenceLimitError,
)


def _snapshot(snapshot_id: str, row_count: int) -> DatasetSnapshot:
    return DatasetSnapshot(
        dataset_id="sales.orders",
        snapshot_id=snapshot_id,
        captured_at=datetime(2026, 8, 13, tzinfo=timezone.utc),
        row_count=row_count,
        columns=(
            ColumnSnapshot(
                name="customer_region",
                data_type="text",
                nullable=True,
                null_count=2 if row_count == 1200 else 133,
                null_rate=0.002 if row_count == 1200 else 0.17,
                distinct_count=4,
            ),
        ),
        duplicate_count=0,
        duplicate_rate=0.0,
    )


def test_snapshot_evidence_is_distinct_bounded_and_path_free() -> None:
    result = PostgresDiagnosticResult(
        snapshot=_snapshot("before", 1200),
        warnings=("Optional range was unavailable.",),
    )

    evidence = DiagnosticEvidenceBuilder().build_snapshot("db_1", result)
    formatted = DiagnosticEvidenceFormatter().format(evidence)

    assert formatted.startswith("DIAGNOSTIC_EVIDENCE\n")
    assert '"row_count":1200' in formatted
    assert "Optional range was unavailable" in formatted
    assert "PIPELINE_EVIDENCE" not in formatted
    assert "/Users/" not in formatted


def test_comparison_uses_program_computed_deltas() -> None:
    report = compare_snapshots(_snapshot("before", 1200), _snapshot("after", 780))

    evidence = DiagnosticEvidenceBuilder().build_comparison("db_1", report)

    assert evidence.comparison is not None
    row_finding = next(
        finding
        for finding in evidence.comparison.findings
        if finding.drift_type.value == "row_count_changed"
    )
    assert row_finding.absolute_delta == -420
    assert row_finding.percentage_delta == -35.0
    null_finding = next(
        finding
        for finding in evidence.comparison.findings
        if finding.drift_type.value == "null_rate_changed"
    )
    assert null_finding.percentage_point_delta == 16.8


def test_snapshot_without_logical_id_fails_closed() -> None:
    result = PostgresDiagnosticResult(
        snapshot=_snapshot("before", 1200).model_copy(update={"snapshot_id": None})
    )

    with pytest.raises(DiagnosticEvidenceBuildError, match="snapshot ID"):
        DiagnosticEvidenceBuilder().build_snapshot("db_1", result)


def test_total_size_reduces_whole_records_or_fails_closed() -> None:
    result = PostgresDiagnosticResult(snapshot=_snapshot("before", 1200))
    evidence = DiagnosticEvidenceBuilder(max_chars=380).build_snapshot("db_1", result)

    assert evidence.truncated is True
    assert evidence.snapshot is not None
    assert evidence.snapshot.columns == ()
    assert any("character limit" in value for value in evidence.warnings)

    with pytest.raises(DiagnosticEvidenceLimitError, match="cannot fit"):
        DiagnosticEvidenceBuilder(max_chars=1).build_snapshot("db_1", result)


@pytest.mark.parametrize("value", [0, -1, True])
def test_invalid_builder_bounds_fail_closed(value: object) -> None:
    with pytest.raises(DiagnosticEvidenceLimitError):
        DiagnosticEvidenceBuilder(max_columns=value)  # type: ignore[arg-type]


def test_builder_rejects_configuration_above_evidence_model_cap() -> None:
    with pytest.raises(DiagnosticEvidenceLimitError, match="hard limit"):
        DiagnosticEvidenceBuilder(max_columns=51)
