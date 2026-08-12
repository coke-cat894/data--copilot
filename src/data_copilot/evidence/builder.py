"""Convert bounded typed Tool Results into stricter compact evidence."""

import math
import secrets
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime, time
from decimal import Decimal
from enum import Enum

from pydantic import BaseModel, JsonValue

from data_copilot.config import (
    MAX_CELL_CHARS,
    MAX_EVIDENCE_CHARS,
    MAX_EVIDENCE_COLUMNS,
    MAX_EVIDENCE_ROWS,
)
from data_copilot.errors import EvidenceBuildError, EvidenceLimitError
from data_copilot.evidence.formatter import EVIDENCE_PREFIX, serialize_evidence
from data_copilot.evidence.models import (
    Evidence,
    EvidenceMetadata,
    EvidenceOperation,
)
from data_copilot.tools.models import (
    AggregateDatasetResult,
    DataQualityResult,
    FilterDatasetResult,
    InspectDatasetResult,
    ProfileDatasetResult,
    SampleDatasetResult,
)


ToolResult = (
    InspectDatasetResult
    | ProfileDatasetResult
    | SampleDatasetResult
    | FilterDatasetResult
    | AggregateDatasetResult
    | DataQualityResult
)


@dataclass(frozen=True, slots=True)
class _EvidenceDraft:
    dataset_id: str
    operation: EvidenceOperation
    summary: dict[str, object]
    columns: tuple[str, ...]
    records: tuple[object, ...]
    source_row_count: int
    source_column_count: int
    source_truncated: bool
    warnings: tuple[str, ...]
    column_aligned_records: bool
    tabular_records: bool


class EvidenceBuilder:
    """Normalize and bound Tool Results without any dataset access."""

    def __init__(
        self,
        *,
        max_rows: int = MAX_EVIDENCE_ROWS,
        max_columns: int = MAX_EVIDENCE_COLUMNS,
        max_cell_chars: int = MAX_CELL_CHARS,
        max_chars: int = MAX_EVIDENCE_CHARS,
    ) -> None:
        self._max_rows = _positive_limit("max_rows", max_rows)
        self._max_columns = _positive_limit("max_columns", max_columns)
        self._max_cell_chars = _positive_limit("max_cell_chars", max_cell_chars)
        self._max_chars = _positive_limit("max_chars", max_chars)

    def build(self, result: ToolResult) -> Evidence:
        """Build bounded evidence for one of the six approved Tool Results."""

        draft = _draft_from_result(result)
        generated_warnings: list[str] = []
        evidence_truncated = False

        draft, columns_truncated = self._apply_column_limit(draft)
        if columns_truncated:
            evidence_truncated = True
            generated_warnings.append(
                f"Evidence columns truncated from {columns_truncated[0]} to "
                f"{columns_truncated[1]} because "
                f"MAX_EVIDENCE_COLUMNS={self._max_columns}."
            )

        original_record_count = len(draft.records)
        if original_record_count > self._max_rows:
            draft = replace(draft, records=draft.records[: self._max_rows])
            evidence_truncated = True
            generated_warnings.append(
                f"Evidence records truncated from {original_record_count} to "
                f"{self._max_rows} because MAX_EVIDENCE_ROWS={self._max_rows}."
            )

        normalization_warnings: set[str] = set()
        summary = _normalize_value(
            draft.summary,
            max_cell_chars=self._max_cell_chars,
            warnings=normalization_warnings,
        )
        columns_value = _normalize_value(
            draft.columns,
            max_cell_chars=self._max_cell_chars,
            warnings=normalization_warnings,
        )
        records_value = _normalize_value(
            draft.records,
            max_cell_chars=self._max_cell_chars,
            warnings=normalization_warnings,
        )
        if normalization_warnings:
            evidence_truncated = True
            generated_warnings.extend(sorted(normalization_warnings))

        if not isinstance(summary, dict):
            raise EvidenceBuildError("Evidence summary normalization failed.")
        if not isinstance(columns_value, list) or not all(
            isinstance(column, str) for column in columns_value
        ):
            raise EvidenceBuildError("Evidence column normalization failed.")
        if not isinstance(records_value, list):
            raise EvidenceBuildError("Evidence record normalization failed.")

        warnings = _deduplicate(
            tuple(draft.warnings) + tuple(generated_warnings)
        )
        evidence = _make_evidence(
            dataset_id=draft.dataset_id,
            operation=draft.operation,
            summary=summary,
            columns=tuple(columns_value),
            records=tuple(records_value),
            source_row_count=draft.source_row_count,
            source_column_count=draft.source_column_count,
            source_truncated=draft.source_truncated,
            evidence_truncated=evidence_truncated,
            warnings=warnings,
        )
        return self._fit_total_size(evidence)

    def _apply_column_limit(
        self, draft: _EvidenceDraft
    ) -> tuple[_EvidenceDraft, tuple[int, int] | None]:
        if len(draft.columns) <= self._max_columns:
            return draft, None
        original_count = len(draft.columns)
        columns = draft.columns[: self._max_columns]
        records = draft.records
        if draft.tabular_records:
            records = tuple(
                tuple(record)[: self._max_columns]
                if isinstance(record, Sequence)
                and not isinstance(record, (str, bytes))
                else record
                for record in records
            )
        elif draft.column_aligned_records:
            records = records[: self._max_columns]
        elif draft.operation is EvidenceOperation.CHECK_DATA_QUALITY:
            allowed_columns = set(columns)
            records = tuple(
                record
                for record in records
                if isinstance(record, dict)
                and (
                    record.get("column") is None
                    or record.get("column") in allowed_columns
                )
            )
        return (
            replace(draft, columns=columns, records=records),
            (original_count, len(columns)),
        )

    def _fit_total_size(self, evidence: Evidence) -> Evidence:
        reduced_for_size = False
        current = evidence
        while _formatted_length(current) > self._max_chars and current.records:
            reduced_for_size = True
            warnings = current.warnings
            warning = (
                "Evidence records were reduced to satisfy "
                f"MAX_EVIDENCE_CHARS={self._max_chars}."
            )
            if warning not in warnings:
                warnings = warnings + (warning,)
            current = current.model_copy(
                update={
                    "records": current.records[:-1],
                    "evidence_truncated": True,
                    "warnings": warnings,
                    "metadata": current.metadata.model_copy(
                        update={
                            "evidence_record_count": len(current.records) - 1
                        }
                    ),
                }
            )
        if _formatted_length(current) > self._max_chars:
            raise EvidenceLimitError(
                "Evidence envelope cannot fit the configured total character limit."
            )
        if reduced_for_size and not current.evidence_truncated:
            raise EvidenceBuildError("Evidence total-size truncation was not recorded.")
        return current


def _draft_from_result(result: ToolResult) -> _EvidenceDraft:
    if isinstance(result, InspectDatasetResult):
        return _EvidenceDraft(
            dataset_id=result.dataset_id,
            operation=EvidenceOperation.INSPECT_DATASET,
            summary={
                "display_name": result.display_name,
                "format": result.format,
                "file_size_bytes": result.file_size_bytes,
                "row_count": result.row_count,
                "column_count": result.column_count,
            },
            columns=tuple(column.name for column in result.columns),
            records=tuple(column.model_dump(mode="python") for column in result.columns),
            source_row_count=result.row_count,
            source_column_count=result.column_count,
            source_truncated=False,
            warnings=(),
            column_aligned_records=True,
            tabular_records=False,
        )
    if isinstance(result, ProfileDatasetResult):
        return _EvidenceDraft(
            dataset_id=result.dataset_id,
            operation=EvidenceOperation.PROFILE_DATASET,
            summary={
                "display_name": result.display_name,
                "format": result.format,
                "row_count": result.row_count,
                "column_count": result.column_count,
                "profiled_column_count": result.profiled_column_count,
            },
            columns=tuple(profile.name for profile in result.columns),
            records=tuple(
                profile.model_dump(mode="python") for profile in result.columns
            ),
            source_row_count=result.row_count,
            source_column_count=result.profiled_column_count,
            source_truncated=False,
            warnings=result.warnings,
            column_aligned_records=True,
            tabular_records=False,
        )
    if isinstance(result, SampleDatasetResult):
        return _tabular_draft(
            result,
            operation=EvidenceOperation.SAMPLE_DATASET,
            summary={"requested_size": result.requested_size, "seed": result.seed},
            source_truncated=False,
            warnings=result.warnings,
        )
    if isinstance(result, FilterDatasetResult):
        return _tabular_draft(
            result,
            operation=EvidenceOperation.FILTER_DATASET,
            summary={},
            source_truncated=result.truncated,
            warnings=result.warnings,
        )
    if isinstance(result, AggregateDatasetResult):
        return _tabular_draft(
            result,
            operation=EvidenceOperation.AGGREGATE_DATASET,
            summary={},
            source_truncated=result.truncated,
            warnings=(),
        )
    if isinstance(result, DataQualityResult):
        issue_columns = tuple(
            dict.fromkeys(
                issue.column for issue in result.issues if issue.column is not None
            )
        )
        return _EvidenceDraft(
            dataset_id=result.dataset_id,
            operation=EvidenceOperation.CHECK_DATA_QUALITY,
            summary={
                "display_name": result.display_name,
                "row_count": result.row_count,
                "column_count": result.column_count,
                "checked_column_count": result.checked_column_count,
                "issue_count": len(result.issues),
            },
            columns=issue_columns,
            records=tuple(
                issue.model_dump(mode="python") for issue in result.issues
            ),
            source_row_count=result.row_count,
            source_column_count=result.checked_column_count,
            source_truncated=False,
            warnings=result.warnings,
            column_aligned_records=False,
            tabular_records=False,
        )
    raise EvidenceBuildError(
        f"Unsupported Tool Result type: {type(result).__name__}."
    )


def _tabular_draft(
    result: SampleDatasetResult | FilterDatasetResult | AggregateDatasetResult,
    *,
    operation: EvidenceOperation,
    summary: dict[str, object],
    source_truncated: bool,
    warnings: tuple[str, ...],
) -> _EvidenceDraft:
    records = tuple(
        tuple(row.get(column) for column in result.columns) for row in result.rows
    )
    return _EvidenceDraft(
        dataset_id=result.dataset_id,
        operation=operation,
        summary=summary,
        columns=result.columns,
        records=records,
        source_row_count=result.row_count,
        source_column_count=len(result.columns),
        source_truncated=source_truncated,
        warnings=warnings,
        column_aligned_records=False,
        tabular_records=True,
    )


def _normalize_value(
    value: object,
    *,
    max_cell_chars: int,
    warnings: set[str],
) -> JsonValue:
    if isinstance(value, BaseModel):
        return _normalize_value(
            value.model_dump(mode="python"),
            max_cell_chars=max_cell_chars,
            warnings=warnings,
        )
    if isinstance(value, Enum):
        return _normalize_value(
            value.value,
            max_cell_chars=max_cell_chars,
            warnings=warnings,
        )
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            warnings.add("Non-finite floating-point values were converted to null.")
            return None
        return value
    if isinstance(value, Decimal):
        return _normalize_value(
            str(value),
            max_cell_chars=max_cell_chars,
            warnings=warnings,
        )
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, str):
        if len(value) <= max_cell_chars:
            return value
        warnings.add(
            "One or more cell values were truncated because "
            f"MAX_CELL_CHARS={max_cell_chars}."
        )
        if max_cell_chars == 1:
            return "…"
        return value[: max_cell_chars - 1] + "…"
    if isinstance(value, dict):
        return {
            str(key): _normalize_value(
                item,
                max_cell_chars=max_cell_chars,
                warnings=warnings,
            )
            for key, item in value.items()
        }
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return [
            _normalize_value(
                item,
                max_cell_chars=max_cell_chars,
                warnings=warnings,
            )
            for item in value
        ]
    return _normalize_value(
        str(value), max_cell_chars=max_cell_chars, warnings=warnings
    )


def _make_evidence(
    *,
    dataset_id: str,
    operation: EvidenceOperation,
    summary: dict[str, JsonValue],
    columns: tuple[str, ...],
    records: tuple[JsonValue, ...],
    source_row_count: int,
    source_column_count: int,
    source_truncated: bool,
    evidence_truncated: bool,
    warnings: tuple[str, ...],
) -> Evidence:
    return Evidence(
        evidence_id=f"ev_{secrets.token_hex(4)}",
        dataset_id=dataset_id,
        operation=operation,
        summary=summary,
        columns=columns,
        records=records,
        source_truncated=source_truncated,
        evidence_truncated=evidence_truncated,
        warnings=warnings,
        metadata=EvidenceMetadata(
            source_row_count=source_row_count,
            evidence_record_count=len(records),
            source_column_count=source_column_count,
            evidence_column_count=len(columns),
        ),
    )


def _formatted_length(evidence: Evidence) -> int:
    return len(EVIDENCE_PREFIX) + len(serialize_evidence(evidence))


def _positive_limit(name: str, value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise EvidenceLimitError(f"{name} must be a positive integer.")
    return value


def _deduplicate(values: Sequence[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(values))
