"""Strict immutable models for observed pipeline and job execution facts."""

from datetime import datetime, timezone
from enum import Enum
import math
from pathlib import PurePath
from typing import Annotated, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from data_copilot.diagnostics.pipeline_constants import (
    MAX_DURATION_SECONDS,
    MAX_EVENT_CATEGORY_CHARS,
    MAX_EVENT_CODE_CHARS,
    MAX_EVENT_MESSAGE_CHARS,
    MAX_EVENTS_PER_STEP,
    MAX_LOGICAL_SOURCE_CHARS,
    MAX_PIPELINE_COUNT,
    MAX_PIPELINE_FINDING_DESCRIPTION_CHARS,
    MAX_PIPELINE_FINDINGS,
    MAX_PIPELINE_ID_CHARS,
    MAX_RUN_EVENTS,
    MAX_RUN_ID_CHARS,
    MAX_STEP_ID_CHARS,
    MAX_STEP_NAME_CHARS,
    MAX_STEPS_PER_RUN,
    MAX_TOTAL_EVENTS_PER_RUN,
)


PipelineCount = Annotated[int, Field(ge=0, le=MAX_PIPELINE_COUNT)]
DurationSeconds = Annotated[
    float, Field(ge=0, le=MAX_DURATION_SECONDS, allow_inf_nan=False)
]
FindingValue: TypeAlias = str | int | float


class _PipelineModel(BaseModel):
    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        strict=True,
        str_strip_whitespace=True,
    )


def _validate_inert_text(value: str, *, field_name: str) -> str:
    if any(ord(character) < 32 and character not in "\n\t" for character in value):
        raise ValueError(f"{field_name} contains invalid control characters")
    if "\x7f" in value:
        raise ValueError(f"{field_name} contains invalid control characters")
    return value


def _validate_logical_identity(value: str, *, field_name: str) -> str:
    _validate_inert_text(value, field_name=field_name)
    if "/" in value or "\\" in value:
        raise ValueError(f"{field_name} must be a logical identity, not a path")
    return value


def _parse_datetime(value: object, *, field_name: str) -> object:
    if value is None or isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            raise ValueError(f"{field_name} must use ISO 8601 format") from None
    else:
        return value
    if parsed is not None and (
        parsed.tzinfo is None or parsed.utcoffset() is None
    ):
        raise ValueError(f"{field_name} must be timezone-aware")
    return parsed


class PipelineRunStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"
    SKIPPED = "skipped"
    UNKNOWN = "unknown"


class PipelineEventLevel(str, Enum):
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


def _normalize_enum(value: object, enum_type: type[Enum], field_name: str) -> object:
    if isinstance(value, enum_type):
        return value
    if isinstance(value, str):
        normalized = value.strip().casefold()
        try:
            return enum_type(normalized)
        except ValueError:
            raise ValueError(f"unsupported {field_name}") from None
    return value


class PipelineProvenance(_PipelineModel):
    """Path-free source location for one structured run record."""

    logical_source: Annotated[
        str, Field(min_length=1, max_length=MAX_LOGICAL_SOURCE_CHARS)
    ]
    record_index: Annotated[int, Field(ge=0)]

    @field_validator("logical_source")
    @classmethod
    def validate_logical_source(cls, value: str) -> str:
        if (
            PurePath(value).name != value
            or "/" in value
            or "\\" in value
            or value.startswith(".")
        ):
            raise ValueError("logical_source must be a safe logical file name")
        return _validate_inert_text(value, field_name="logical_source")


class PipelineEvent(_PipelineModel):
    """One bounded inert event observed in a pipeline record."""

    timestamp: datetime | None = None
    level: PipelineEventLevel
    step_id: Annotated[
        str, Field(min_length=1, max_length=MAX_STEP_ID_CHARS)
    ] | None = None
    message: Annotated[
        str, Field(min_length=1, max_length=MAX_EVENT_MESSAGE_CHARS)
    ]
    event_code: Annotated[
        str, Field(min_length=1, max_length=MAX_EVENT_CODE_CHARS)
    ] | None = None
    category: Annotated[
        str, Field(min_length=1, max_length=MAX_EVENT_CATEGORY_CHARS)
    ] | None = None

    @field_validator("timestamp", mode="before")
    @classmethod
    def parse_timestamp(cls, value: object) -> object:
        return _parse_datetime(value, field_name="event timestamp")

    @field_validator("level", mode="before")
    @classmethod
    def normalize_level(cls, value: object) -> object:
        return _normalize_enum(value, PipelineEventLevel, "event level")

    @field_validator("step_id")
    @classmethod
    def validate_step_id(cls, value: str | None) -> str | None:
        if value is None:
            return value
        return _validate_logical_identity(value, field_name="step_id")

    @field_validator("message", "event_code", "category")
    @classmethod
    def validate_text(cls, value: str | None, info: object) -> str | None:
        if value is None:
            return value
        return _validate_inert_text(
            value,
            field_name=getattr(info, "field_name", "event text"),
        )


_LEVEL_ORDER = {
    PipelineEventLevel.DEBUG: 0,
    PipelineEventLevel.INFO: 1,
    PipelineEventLevel.WARNING: 2,
    PipelineEventLevel.ERROR: 3,
    PipelineEventLevel.CRITICAL: 4,
}


def pipeline_event_sort_key(event: PipelineEvent) -> tuple[object, ...]:
    timestamp = event.timestamp or datetime.max.replace(tzinfo=timezone.utc)
    return (
        event.timestamp is None,
        timestamp,
        _LEVEL_ORDER[event.level],
        event.step_id or "",
        event.event_code or "",
        event.category or "",
        event.message,
    )


class PipelineStepRun(_PipelineModel):
    """One ordered step observation with optional reported counts."""

    step_id: Annotated[str, Field(min_length=1, max_length=MAX_STEP_ID_CHARS)]
    name: Annotated[str, Field(min_length=1, max_length=MAX_STEP_NAME_CHARS)]
    ordinal: Annotated[int, Field(ge=0, le=MAX_STEPS_PER_RUN - 1)]
    status: PipelineRunStatus
    start_time: datetime | None = None
    end_time: datetime | None = None
    duration_seconds: DurationSeconds | None = None
    input_rows: PipelineCount | None = None
    output_rows: PipelineCount | None = None
    rejected_rows: PipelineCount | None = None
    events: Annotated[
        tuple[PipelineEvent, ...], Field(max_length=MAX_EVENTS_PER_STEP)
    ] = ()

    @field_validator("step_id")
    @classmethod
    def validate_step_id(cls, value: str) -> str:
        return _validate_logical_identity(value, field_name="step_id")

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        return _validate_inert_text(value, field_name="step name")

    @field_validator("status", mode="before")
    @classmethod
    def normalize_status(cls, value: object) -> object:
        return _normalize_enum(value, PipelineRunStatus, "pipeline status")

    @field_validator("start_time", "end_time", mode="before")
    @classmethod
    def parse_time(cls, value: object, info: object) -> object:
        return _parse_datetime(
            value,
            field_name=getattr(info, "field_name", "step timestamp"),
        )

    @field_validator("duration_seconds", mode="before")
    @classmethod
    def validate_duration_scalar(cls, value: object) -> object:
        if isinstance(value, bool):
            raise ValueError("duration_seconds cannot be a boolean")
        if isinstance(value, (int, float)) and not math.isfinite(float(value)):
            raise ValueError("duration_seconds must be finite")
        return value

    @field_validator("events")
    @classmethod
    def order_events(
        cls, values: tuple[PipelineEvent, ...]
    ) -> tuple[PipelineEvent, ...]:
        return tuple(sorted(values, key=pipeline_event_sort_key))

    @field_validator("events", mode="before")
    @classmethod
    def normalize_event_collection(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value

    @model_validator(mode="after")
    def validate_timing_counts_and_events(self) -> "PipelineStepRun":
        if (
            self.start_time is not None
            and self.end_time is not None
            and self.end_time < self.start_time
        ):
            raise ValueError("step end_time cannot precede start_time")
        derived: float | None = None
        if self.start_time is not None and self.end_time is not None:
            derived = (self.end_time - self.start_time).total_seconds()
            if derived > MAX_DURATION_SECONDS:
                raise ValueError("derived step duration exceeds the supported bound")
        if self.duration_seconds is None and derived is not None:
            object.__setattr__(self, "duration_seconds", derived)
        elif (
            self.duration_seconds is not None
            and derived is not None
            and not math.isclose(self.duration_seconds, derived, abs_tol=1e-6)
        ):
            raise ValueError("duration_seconds conflicts with step timestamps")
        if (
            self.rejected_rows is not None
            and self.input_rows is not None
            and self.rejected_rows > self.input_rows
        ):
            raise ValueError("rejected_rows cannot exceed input_rows")
        normalized_events: list[PipelineEvent] = []
        for event in self.events:
            if event.step_id not in (None, self.step_id):
                raise ValueError("step event association must match its containing step")
            normalized_events.append(
                event
                if event.step_id == self.step_id
                else event.model_copy(update={"step_id": self.step_id})
            )
        object.__setattr__(
            self,
            "events",
            tuple(sorted(normalized_events, key=pipeline_event_sort_key)),
        )
        return self


class PipelineRun(_PipelineModel):
    """One deterministic normalized observation of a pipeline execution."""

    pipeline_id: Annotated[
        str, Field(min_length=1, max_length=MAX_PIPELINE_ID_CHARS)
    ]
    run_id: Annotated[str, Field(min_length=1, max_length=MAX_RUN_ID_CHARS)]
    execution_time: datetime | None = None
    start_time: datetime | None = None
    end_time: datetime | None = None
    status: PipelineRunStatus
    steps: Annotated[
        tuple[PipelineStepRun, ...], Field(max_length=MAX_STEPS_PER_RUN)
    ] = ()
    events: Annotated[tuple[PipelineEvent, ...], Field(max_length=MAX_RUN_EVENTS)] = ()
    provenance: PipelineProvenance

    @field_validator("pipeline_id", "run_id")
    @classmethod
    def validate_identity(cls, value: str, info: object) -> str:
        return _validate_logical_identity(
            value,
            field_name=getattr(info, "field_name", "run identity"),
        )

    @field_validator("execution_time", "start_time", "end_time", mode="before")
    @classmethod
    def parse_time(cls, value: object, info: object) -> object:
        return _parse_datetime(
            value,
            field_name=getattr(info, "field_name", "run timestamp"),
        )

    @field_validator("status", mode="before")
    @classmethod
    def normalize_status(cls, value: object) -> object:
        return _normalize_enum(value, PipelineRunStatus, "pipeline status")

    @field_validator("steps")
    @classmethod
    def order_steps(
        cls, values: tuple[PipelineStepRun, ...]
    ) -> tuple[PipelineStepRun, ...]:
        identities = [step.step_id for step in values]
        ordinals = [step.ordinal for step in values]
        if len(identities) != len(set(identities)):
            raise ValueError("step_id values must be unique within a run")
        if len(ordinals) != len(set(ordinals)):
            raise ValueError("step ordinals must be unique within a run")
        return tuple(sorted(values, key=lambda step: (step.ordinal, step.step_id)))

    @field_validator("steps", "events", mode="before")
    @classmethod
    def normalize_collections(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value

    @field_validator("events")
    @classmethod
    def order_events(
        cls, values: tuple[PipelineEvent, ...]
    ) -> tuple[PipelineEvent, ...]:
        return tuple(sorted(values, key=pipeline_event_sort_key))

    @model_validator(mode="after")
    def validate_timing_and_events(self) -> "PipelineRun":
        if (
            self.start_time is not None
            and self.end_time is not None
            and self.end_time < self.start_time
        ):
            raise ValueError("run end_time cannot precede start_time")
        step_ids = {step.step_id for step in self.steps}
        if any(
            event.step_id is not None and event.step_id not in step_ids
            for event in self.events
        ):
            raise ValueError("run event references an unknown step_id")
        total_events = len(self.events) + sum(len(step.events) for step in self.steps)
        if total_events > MAX_TOTAL_EVENTS_PER_RUN:
            raise ValueError("pipeline run contains too many total events")
        return self


class PipelineFindingType(str, Enum):
    OVERALL_STATUS_CHANGED = "overall_status_changed"
    STEP_ADDED = "step_added"
    STEP_MISSING = "step_missing"
    STEP_STATUS_CHANGED = "step_status_changed"
    STEP_DURATION_CHANGED = "step_duration_changed"
    INPUT_ROWS_CHANGED = "input_rows_changed"
    OUTPUT_ROWS_CHANGED = "output_rows_changed"
    REJECTED_ROWS_CHANGED = "rejected_rows_changed"
    WARNING_EVENT_COUNT_CHANGED = "warning_event_count_changed"
    ERROR_EVENT_COUNT_CHANGED = "error_event_count_changed"
    PIPELINE_STOPPED_EARLY = "pipeline_stopped_early"


class PipelineFinding(_PipelineModel):
    """One factual difference between compatible pipeline runs."""

    finding_type: PipelineFindingType
    step_id: Annotated[
        str, Field(min_length=1, max_length=MAX_STEP_ID_CHARS)
    ] | None = None
    before_value: FindingValue | None = None
    after_value: FindingValue | None = None
    absolute_delta: int | float | None = None
    description: Annotated[
        str,
        Field(min_length=1, max_length=MAX_PIPELINE_FINDING_DESCRIPTION_CHARS),
    ]

    @field_validator("step_id")
    @classmethod
    def validate_step_id(cls, value: str | None) -> str | None:
        if value is None:
            return value
        return _validate_logical_identity(value, field_name="step_id")

    @field_validator("absolute_delta", mode="before")
    @classmethod
    def validate_delta(cls, value: object) -> object:
        if isinstance(value, bool):
            raise ValueError("absolute_delta cannot be a boolean")
        if isinstance(value, (int, float)) and not math.isfinite(float(value)):
            raise ValueError("absolute_delta must be finite")
        return value

    @field_validator("description")
    @classmethod
    def validate_description(cls, value: str) -> str:
        return _validate_inert_text(value, field_name="description")


class PipelineComparison(_PipelineModel):
    """Canonical factual comparison between two runs of one pipeline."""

    pipeline_id: Annotated[
        str, Field(min_length=1, max_length=MAX_PIPELINE_ID_CHARS)
    ]
    before_run_id: Annotated[str, Field(min_length=1, max_length=MAX_RUN_ID_CHARS)]
    after_run_id: Annotated[str, Field(min_length=1, max_length=MAX_RUN_ID_CHARS)]
    findings: Annotated[
        tuple[PipelineFinding, ...], Field(max_length=MAX_PIPELINE_FINDINGS)
    ] = ()

    @property
    def has_changes(self) -> bool:
        return bool(self.findings)
