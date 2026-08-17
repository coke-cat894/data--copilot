"""Typed bounded models for the distinct DIAGNOSTIC_EVIDENCE channel."""

from datetime import date, datetime
from enum import Enum
from typing import Annotated, Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, model_validator

from data_copilot.diagnostics.constants import (
    MAX_COLUMN_NAME_CHARS,
    MAX_COUNT,
    MAX_DATASET_ID_CHARS,
    MAX_DATA_TYPE_CHARS,
    MAX_SNAPSHOT_ID_CHARS,
)
from data_copilot.diagnostics.models import DriftType


MAX_DIAGNOSTIC_EVIDENCE_COLUMNS = 50
MAX_DIAGNOSTIC_EVIDENCE_FINDINGS = 100
MAX_DIAGNOSTIC_EVIDENCE_WARNINGS = 20
MAX_DIAGNOSTIC_EVIDENCE_WARNING_CHARS = 500
MAX_DIAGNOSTIC_EVIDENCE_CHARS = 16_000

DiagnosticValue: TypeAlias = str | bool | int | float | datetime | date


class DiagnosticEvidenceKind(str, Enum):
    SNAPSHOT = "snapshot"
    COMPARISON = "comparison"


class _DiagnosticEvidenceModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)


class DiagnosticEvidenceColumn(_DiagnosticEvidenceModel):
    name: Annotated[str, Field(min_length=1, max_length=MAX_COLUMN_NAME_CHARS)]
    data_type: Annotated[str, Field(min_length=1, max_length=MAX_DATA_TYPE_CHARS)]
    nullable: bool | None = None
    null_count: Annotated[int, Field(ge=0, le=MAX_COUNT)] | None = None
    null_rate: Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)] | None = None
    distinct_count: Annotated[int, Field(ge=0, le=MAX_COUNT)] | None = None
    min_value: DiagnosticValue | None = None
    max_value: DiagnosticValue | None = None


class DiagnosticEvidenceSnapshot(_DiagnosticEvidenceModel):
    dataset_id: Annotated[str, Field(min_length=1, max_length=MAX_DATASET_ID_CHARS)]
    snapshot_id: Annotated[str, Field(min_length=1, max_length=MAX_SNAPSHOT_ID_CHARS)]
    captured_at: datetime | None = None
    row_count: Annotated[int, Field(ge=0, le=MAX_COUNT)]
    columns: Annotated[
        tuple[DiagnosticEvidenceColumn, ...],
        Field(max_length=MAX_DIAGNOSTIC_EVIDENCE_COLUMNS),
    ] = ()
    duplicate_count: Annotated[int, Field(ge=0, le=MAX_COUNT)] | None = None
    duplicate_rate: Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)] | None = None


class DiagnosticEvidenceFinding(_DiagnosticEvidenceModel):
    drift_type: DriftType
    column_name: Annotated[
        str, Field(min_length=1, max_length=MAX_COLUMN_NAME_CHARS)
    ] | None = None
    before_value: DiagnosticValue | None = None
    after_value: DiagnosticValue | None = None
    absolute_delta: int | float | None = Field(default=None, allow_inf_nan=False)
    percentage_delta: float | None = Field(default=None, allow_inf_nan=False)
    percentage_point_delta: float | None = Field(default=None, allow_inf_nan=False)
    description: Annotated[str, Field(min_length=1, max_length=1000)]


class DiagnosticEvidenceComparison(_DiagnosticEvidenceModel):
    dataset_id: Annotated[str, Field(min_length=1, max_length=MAX_DATASET_ID_CHARS)]
    before_snapshot_id: Annotated[
        str, Field(min_length=1, max_length=MAX_SNAPSHOT_ID_CHARS)
    ]
    after_snapshot_id: Annotated[
        str, Field(min_length=1, max_length=MAX_SNAPSHOT_ID_CHARS)
    ]
    before_captured_at: datetime | None = None
    after_captured_at: datetime | None = None
    findings: Annotated[
        tuple[DiagnosticEvidenceFinding, ...],
        Field(max_length=MAX_DIAGNOSTIC_EVIDENCE_FINDINGS),
    ] = ()


class DiagnosticEvidence(_DiagnosticEvidenceModel):
    """Selected observed snapshot or drift facts for Agent context."""

    schema_version: Literal[1] = 1
    kind: DiagnosticEvidenceKind
    database_id: Annotated[str, Field(min_length=1, max_length=255)]
    snapshot: DiagnosticEvidenceSnapshot | None = None
    comparison: DiagnosticEvidenceComparison | None = None
    truncated: bool
    warnings: Annotated[
        tuple[
            Annotated[
                str,
                Field(
                    min_length=1,
                    max_length=MAX_DIAGNOSTIC_EVIDENCE_WARNING_CHARS,
                ),
            ],
            ...,
        ],
        Field(max_length=MAX_DIAGNOSTIC_EVIDENCE_WARNINGS),
    ] = ()

    @model_validator(mode="after")
    def validate_payload(self) -> "DiagnosticEvidence":
        if self.kind is DiagnosticEvidenceKind.SNAPSHOT:
            if self.snapshot is None or self.comparison is not None:
                raise ValueError("snapshot evidence must contain only a snapshot")
        elif self.comparison is None or self.snapshot is not None:
            raise ValueError("comparison evidence must contain only a comparison")
        return self
