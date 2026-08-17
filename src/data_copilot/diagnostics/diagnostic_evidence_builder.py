"""Build bounded DIAGNOSTIC_EVIDENCE from existing deterministic results."""

from data_copilot.diagnostics.diagnostic_evidence_formatter import (
    DIAGNOSTIC_EVIDENCE_PREFIX,
    serialize_diagnostic_evidence,
)
from data_copilot.diagnostics.diagnostic_evidence_models import (
    MAX_DIAGNOSTIC_EVIDENCE_CHARS,
    MAX_DIAGNOSTIC_EVIDENCE_COLUMNS,
    MAX_DIAGNOSTIC_EVIDENCE_FINDINGS,
    MAX_DIAGNOSTIC_EVIDENCE_WARNINGS,
    DiagnosticEvidence,
    DiagnosticEvidenceColumn,
    DiagnosticEvidenceComparison,
    DiagnosticEvidenceFinding,
    DiagnosticEvidenceKind,
    DiagnosticEvidenceSnapshot,
)
from data_copilot.diagnostics.models import DriftReport
from data_copilot.diagnostics.pipeline_evidence_builder import sanitize_pipeline_text
from data_copilot.diagnostics.postgres_models import PostgresDiagnosticResult
from data_copilot.errors import (
    DiagnosticEvidenceBuildError,
    DiagnosticEvidenceLimitError,
)


class DiagnosticEvidenceBuilder:
    """Select bounded observed data-health facts without interpretation."""

    def __init__(
        self,
        *,
        max_columns: int = MAX_DIAGNOSTIC_EVIDENCE_COLUMNS,
        max_findings: int = MAX_DIAGNOSTIC_EVIDENCE_FINDINGS,
        max_chars: int = MAX_DIAGNOSTIC_EVIDENCE_CHARS,
    ) -> None:
        self._max_columns = _bounded_limit(
            "max_columns", max_columns, MAX_DIAGNOSTIC_EVIDENCE_COLUMNS
        )
        self._max_findings = _bounded_limit(
            "max_findings", max_findings, MAX_DIAGNOSTIC_EVIDENCE_FINDINGS
        )
        self._max_chars = _positive_limit("max_chars", max_chars)

    def build_snapshot(
        self,
        database_id: str,
        result: PostgresDiagnosticResult,
    ) -> DiagnosticEvidence:
        if not isinstance(result, PostgresDiagnosticResult):
            raise DiagnosticEvidenceBuildError(
                "Diagnostic snapshot evidence requires a typed result."
            )
        snapshot = result.snapshot
        if snapshot.snapshot_id is None:
            raise DiagnosticEvidenceBuildError(
                "Diagnostic snapshot evidence requires a logical snapshot ID."
            )
        columns = snapshot.columns[: self._max_columns]
        source_warnings = [sanitize_pipeline_text(value) for value in result.warnings]
        truncated = len(columns) < len(snapshot.columns)
        required_warnings: list[str] = []
        if truncated:
            required_warnings.append(
                f"Diagnostic evidence columns were truncated to {self._max_columns}.",
            )
        if len(source_warnings) > (
            MAX_DIAGNOSTIC_EVIDENCE_WARNINGS - len(required_warnings)
        ):
            required_warnings.insert(
                0,
                "Diagnostic collection warnings were truncated for evidence.",
            )
        warning_capacity = MAX_DIAGNOSTIC_EVIDENCE_WARNINGS - len(required_warnings)
        warnings = source_warnings[:warning_capacity] + required_warnings
        evidence = DiagnosticEvidence(
            kind=DiagnosticEvidenceKind.SNAPSHOT,
            database_id=sanitize_pipeline_text(database_id),
            snapshot=DiagnosticEvidenceSnapshot(
                dataset_id=sanitize_pipeline_text(snapshot.dataset_id),
                snapshot_id=snapshot.snapshot_id,
                captured_at=snapshot.captured_at,
                row_count=snapshot.row_count,
                columns=tuple(
                    DiagnosticEvidenceColumn(
                        **{
                            **column.model_dump(mode="python"),
                            "name": sanitize_pipeline_text(column.name),
                            "data_type": sanitize_pipeline_text(column.data_type),
                        }
                    )
                    for column in columns
                ),
                duplicate_count=snapshot.duplicate_count,
                duplicate_rate=snapshot.duplicate_rate,
            ),
            truncated=truncated,
            warnings=tuple(warnings[:MAX_DIAGNOSTIC_EVIDENCE_WARNINGS]),
        )
        return self._fit_total_size(evidence)

    def build_comparison(
        self,
        database_id: str,
        report: DriftReport,
    ) -> DiagnosticEvidence:
        if not isinstance(report, DriftReport):
            raise DiagnosticEvidenceBuildError(
                "Diagnostic comparison evidence requires a typed DriftReport."
            )
        if report.before_snapshot_id is None or report.after_snapshot_id is None:
            raise DiagnosticEvidenceBuildError(
                "Diagnostic comparison evidence requires logical snapshot IDs."
            )
        findings = report.findings[: self._max_findings]
        warnings: list[str] = []
        truncated = len(findings) < len(report.findings)
        if truncated:
            _add_warning(
                warnings,
                f"Diagnostic evidence findings were truncated to {self._max_findings}.",
            )
        evidence = DiagnosticEvidence(
            kind=DiagnosticEvidenceKind.COMPARISON,
            database_id=sanitize_pipeline_text(database_id),
            comparison=DiagnosticEvidenceComparison(
                dataset_id=sanitize_pipeline_text(report.dataset_id),
                before_snapshot_id=report.before_snapshot_id,
                after_snapshot_id=report.after_snapshot_id,
                before_captured_at=report.before_captured_at,
                after_captured_at=report.after_captured_at,
                findings=tuple(
                    _evidence_finding(finding.model_dump(mode="python"))
                    for finding in findings
                ),
            ),
            truncated=truncated,
            warnings=tuple(warnings),
        )
        return self._fit_total_size(evidence)

    def _fit_total_size(self, evidence: DiagnosticEvidence) -> DiagnosticEvidence:
        current = evidence
        warning = (
            "Diagnostic evidence records were reduced to satisfy the total "
            "character limit."
        )
        while _formatted_length(current) > self._max_chars:
            warnings = list(current.warnings)
            _add_warning(warnings, warning)
            if current.snapshot is not None and current.snapshot.columns:
                snapshot = current.snapshot.model_copy(
                    update={"columns": current.snapshot.columns[:-1]}
                )
                current = current.model_copy(
                    update={
                        "snapshot": snapshot,
                        "truncated": True,
                        "warnings": tuple(warnings),
                    }
                )
                continue
            if current.comparison is not None and current.comparison.findings:
                comparison = current.comparison.model_copy(
                    update={"findings": current.comparison.findings[:-1]}
                )
                current = current.model_copy(
                    update={
                        "comparison": comparison,
                        "truncated": True,
                        "warnings": tuple(warnings),
                    }
                )
                continue
            raise DiagnosticEvidenceLimitError(
                "Diagnostic evidence envelope cannot fit the character limit."
            )
        return current


def _formatted_length(evidence: DiagnosticEvidence) -> int:
    return len(DIAGNOSTIC_EVIDENCE_PREFIX + serialize_diagnostic_evidence(evidence))


def _add_warning(warnings: list[str], warning: str) -> None:
    if warning in warnings:
        return
    if len(warnings) < MAX_DIAGNOSTIC_EVIDENCE_WARNINGS:
        warnings.append(warning)
    elif warnings:
        warnings[-1] = warning


def _evidence_finding(values: dict[str, object]) -> DiagnosticEvidenceFinding:
    before = values.get("before_value")
    after = values.get("after_value")
    return DiagnosticEvidenceFinding(
        **{
            **values,
            "column_name": _sanitize_optional(values.get("column_name")),
            "before_value": (
                sanitize_pipeline_text(before) if isinstance(before, str) else before
            ),
            "after_value": (
                sanitize_pipeline_text(after) if isinstance(after, str) else after
            ),
            "description": sanitize_pipeline_text(str(values["description"])),
        }
    )


def _sanitize_optional(value: object) -> str | None:
    if value is None:
        return None
    return sanitize_pipeline_text(str(value))


def _positive_limit(name: str, value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise DiagnosticEvidenceLimitError(f"{name} must be a positive integer.")
    return value


def _bounded_limit(name: str, value: int, maximum: int) -> int:
    resolved = _positive_limit(name, value)
    if resolved > maximum:
        raise DiagnosticEvidenceLimitError(
            f"{name} cannot exceed the evidence hard limit."
        )
    return resolved
