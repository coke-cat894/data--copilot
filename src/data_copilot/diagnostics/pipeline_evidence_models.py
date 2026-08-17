"""Typed bounded models for the distinct PIPELINE_EVIDENCE channel."""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from data_copilot.diagnostics.pipeline_constants import (
    MAX_EVENT_CATEGORY_CHARS,
    MAX_EVENT_CODE_CHARS,
    MAX_LOGICAL_SOURCE_CHARS,
    MAX_PIPELINE_EVIDENCE_EVENTS,
    MAX_PIPELINE_EVIDENCE_FINDINGS,
    MAX_PIPELINE_EVIDENCE_MESSAGE_CHARS,
    MAX_PIPELINE_EVIDENCE_STEPS,
    MAX_PIPELINE_EVIDENCE_WARNINGS,
    MAX_PIPELINE_FINDING_DESCRIPTION_CHARS,
    MAX_PIPELINE_ID_CHARS,
    MAX_RUN_ID_CHARS,
    MAX_STEP_ID_CHARS,
    MAX_STEP_NAME_CHARS,
)
from data_copilot.diagnostics.pipeline_models import (
    PipelineEventLevel,
    PipelineFindingType,
    PipelineRunStatus,
)


class _PipelineEvidenceModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)


class PipelineEvidenceProvenance(_PipelineEvidenceModel):
    logical_source: Annotated[
        str, Field(min_length=1, max_length=MAX_LOGICAL_SOURCE_CHARS)
    ]
    record_index: Annotated[int, Field(ge=0)]


class PipelineEvidenceRun(_PipelineEvidenceModel):
    pipeline_id: Annotated[
        str, Field(min_length=1, max_length=MAX_PIPELINE_ID_CHARS)
    ]
    run_id: Annotated[str, Field(min_length=1, max_length=MAX_RUN_ID_CHARS)]
    execution_time: datetime | None = None
    start_time: datetime | None = None
    end_time: datetime | None = None
    status: PipelineRunStatus
    provenance: PipelineEvidenceProvenance


class PipelineEvidenceStep(_PipelineEvidenceModel):
    step_id: Annotated[str, Field(min_length=1, max_length=MAX_STEP_ID_CHARS)]
    name: Annotated[str, Field(min_length=1, max_length=MAX_STEP_NAME_CHARS)]
    ordinal: int = Field(ge=0)
    status: PipelineRunStatus
    start_time: datetime | None = None
    end_time: datetime | None = None
    duration_seconds: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    input_rows: int | None = Field(default=None, ge=0)
    output_rows: int | None = Field(default=None, ge=0)
    rejected_rows: int | None = Field(default=None, ge=0)


class PipelineEvidenceEvent(_PipelineEvidenceModel):
    timestamp: datetime | None = None
    level: PipelineEventLevel
    step_id: Annotated[
        str, Field(min_length=1, max_length=MAX_STEP_ID_CHARS)
    ] | None = None
    message: Annotated[
        str, Field(min_length=1, max_length=MAX_PIPELINE_EVIDENCE_MESSAGE_CHARS)
    ]
    event_code: Annotated[
        str, Field(min_length=1, max_length=MAX_EVENT_CODE_CHARS)
    ] | None = None
    category: Annotated[
        str, Field(min_length=1, max_length=MAX_EVENT_CATEGORY_CHARS)
    ] | None = None


class PipelineEvidenceFinding(_PipelineEvidenceModel):
    finding_type: PipelineFindingType
    step_id: Annotated[
        str, Field(min_length=1, max_length=MAX_STEP_ID_CHARS)
    ] | None = None
    before_value: str | int | float | None = None
    after_value: str | int | float | None = None
    absolute_delta: int | float | None = Field(default=None, allow_inf_nan=False)
    description: Annotated[
        str,
        Field(min_length=1, max_length=MAX_PIPELINE_FINDING_DESCRIPTION_CHARS),
    ]


class PipelineEvidence(_PipelineEvidenceModel):
    """Only selected sanitized observed pipeline facts for future context."""

    schema_version: Literal[1] = 1
    run: PipelineEvidenceRun
    steps: Annotated[
        tuple[PipelineEvidenceStep, ...],
        Field(max_length=MAX_PIPELINE_EVIDENCE_STEPS),
    ]
    events: Annotated[
        tuple[PipelineEvidenceEvent, ...],
        Field(max_length=MAX_PIPELINE_EVIDENCE_EVENTS),
    ]
    findings: Annotated[
        tuple[PipelineEvidenceFinding, ...],
        Field(max_length=MAX_PIPELINE_EVIDENCE_FINDINGS),
    ]
    truncated: bool
    warnings: Annotated[
        tuple[str, ...], Field(max_length=MAX_PIPELINE_EVIDENCE_WARNINGS)
    ]
