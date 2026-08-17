"""Typed, bounded models for inert data-health snapshots and drift facts."""

from datetime import date, datetime
from enum import Enum
import math
from typing import Annotated, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from data_copilot.diagnostics.constants import (
    MAX_COLUMN_NAME_CHARS,
    MAX_COUNT,
    MAX_DATASET_ID_CHARS,
    MAX_DATA_TYPE_CHARS,
    MAX_DRIFT_FINDINGS,
    MAX_SNAPSHOT_COLUMNS,
    MAX_SNAPSHOT_ID_CHARS,
)


BoundedCount = Annotated[int, Field(ge=0, le=MAX_COUNT)]
BoundedRate = Annotated[float, Field(ge=0.0, le=1.0, allow_inf_nan=False)]
RangeValue: TypeAlias = int | float | datetime | date
FindingValue: TypeAlias = str | bool | int | float | datetime | date


class _DiagnosticModel(BaseModel):
    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        strict=True,
        str_strip_whitespace=True,
    )


def _reject_control_characters(value: str, *, field_name: str) -> str:
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise ValueError(f"{field_name} cannot contain control characters")
    return value


def _range_kind(value: RangeValue) -> str:
    if isinstance(value, bool):
        raise ValueError("range values cannot be booleans")
    if isinstance(value, datetime):
        return "datetime"
    if isinstance(value, date):
        return "date"
    if isinstance(value, (int, float)):
        return "numeric"
    raise ValueError("range values must be numeric, date, or datetime values")


class ColumnSnapshot(_DiagnosticModel):
    """Bounded observed metadata for one logical column."""

    name: Annotated[str, Field(min_length=1, max_length=MAX_COLUMN_NAME_CHARS)]
    data_type: Annotated[str, Field(min_length=1, max_length=MAX_DATA_TYPE_CHARS)]
    nullable: bool | None = None
    null_count: BoundedCount | None = None
    null_rate: BoundedRate | None = None
    distinct_count: BoundedCount | None = None
    min_value: RangeValue | None = None
    max_value: RangeValue | None = None

    @field_validator("name", "data_type")
    @classmethod
    def validate_bounded_text(cls, value: str, info: object) -> str:
        field_name = getattr(info, "field_name", "text")
        return _reject_control_characters(value, field_name=field_name)

    @field_validator("min_value", "max_value", mode="before")
    @classmethod
    def validate_range_scalar(cls, value: object) -> object:
        if value is None:
            return value
        if isinstance(value, bool):
            raise ValueError("range values cannot be booleans")
        if isinstance(value, int) and not -MAX_COUNT <= value <= MAX_COUNT:
            raise ValueError("integer range values exceed the supported bound")
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError("range values must be finite")
        return value

    @model_validator(mode="after")
    def validate_range(self) -> "ColumnSnapshot":
        if self.min_value is None or self.max_value is None:
            return self
        min_kind = _range_kind(self.min_value)
        max_kind = _range_kind(self.max_value)
        if min_kind != max_kind:
            raise ValueError("min_value and max_value must have compatible types")
        if min_kind == "datetime":
            min_aware = self.min_value.tzinfo is not None  # type: ignore[union-attr]
            max_aware = self.max_value.tzinfo is not None  # type: ignore[union-attr]
            if min_aware != max_aware:
                raise ValueError(
                    "datetime min_value and max_value must use compatible timezones"
                )
        try:
            if self.min_value > self.max_value:
                raise ValueError("min_value cannot exceed max_value")
        except TypeError:
            raise ValueError(
                "min_value and max_value must have compatible types"
            ) from None
        return self


class DatasetSnapshot(_DiagnosticModel):
    """A path-free, bounded set of observed facts for one logical dataset.

    Duplicate fields use the existing Phase 2 definition: exact full-row
    duplicates beyond the first occurrence. Unknown measurements remain None.
    """

    dataset_id: Annotated[str, Field(min_length=1, max_length=MAX_DATASET_ID_CHARS)]
    snapshot_id: Annotated[
        str, Field(min_length=1, max_length=MAX_SNAPSHOT_ID_CHARS)
    ] | None = None
    captured_at: datetime | None = None
    row_count: BoundedCount
    columns: Annotated[
        tuple[ColumnSnapshot, ...], Field(max_length=MAX_SNAPSHOT_COLUMNS)
    ] = ()
    duplicate_count: BoundedCount | None = None
    duplicate_rate: BoundedRate | None = None

    @field_validator("dataset_id")
    @classmethod
    def validate_dataset_id(cls, value: str) -> str:
        _reject_control_characters(value, field_name="dataset_id")
        if "/" in value or "\\" in value:
            raise ValueError("dataset_id must be a logical identity, not a path")
        return value

    @field_validator("snapshot_id")
    @classmethod
    def validate_snapshot_id(cls, value: str | None) -> str | None:
        if value is None:
            return value
        return _reject_control_characters(value, field_name="snapshot_id")

    @field_validator("columns")
    @classmethod
    def validate_and_order_columns(
        cls, values: tuple[ColumnSnapshot, ...]
    ) -> tuple[ColumnSnapshot, ...]:
        names = [column.name for column in values]
        if len(names) != len(set(names)):
            raise ValueError("column names must be unique within a snapshot")
        return tuple(sorted(values, key=lambda column: column.name))

    @model_validator(mode="after")
    def validate_counts_against_rows(self) -> "DatasetSnapshot":
        for column in self.columns:
            if column.null_count is not None and column.null_count > self.row_count:
                raise ValueError(
                    f"null_count for column {column.name!r} cannot exceed row_count"
                )
            if (
                column.distinct_count is not None
                and column.distinct_count > self.row_count
            ):
                raise ValueError(
                    f"distinct_count for column {column.name!r} cannot exceed row_count"
                )
            if self.row_count == 0 and column.null_rate not in (None, 0.0):
                raise ValueError("null_rate must be zero or unknown when row_count is zero")
        if self.duplicate_count is not None and self.duplicate_count > self.row_count:
            raise ValueError("duplicate_count cannot exceed row_count")
        if self.row_count == 0 and self.duplicate_rate not in (None, 0.0):
            raise ValueError("duplicate_rate must be zero or unknown when row_count is zero")
        return self


class DriftType(str, Enum):
    COLUMN_ADDED = "column_added"
    COLUMN_REMOVED = "column_removed"
    DATA_TYPE_CHANGED = "data_type_changed"
    NULLABLE_CHANGED = "nullable_changed"
    ROW_COUNT_CHANGED = "row_count_changed"
    NULL_COUNT_CHANGED = "null_count_changed"
    NULL_RATE_CHANGED = "null_rate_changed"
    DISTINCT_COUNT_CHANGED = "distinct_count_changed"
    DUPLICATE_COUNT_CHANGED = "duplicate_count_changed"
    DUPLICATE_RATE_CHANGED = "duplicate_rate_changed"
    MIN_VALUE_CHANGED = "min_value_changed"
    MAX_VALUE_CHANGED = "max_value_changed"


_COLUMN_DRIFT_TYPES = {
    DriftType.COLUMN_ADDED,
    DriftType.COLUMN_REMOVED,
    DriftType.DATA_TYPE_CHANGED,
    DriftType.NULLABLE_CHANGED,
    DriftType.NULL_COUNT_CHANGED,
    DriftType.NULL_RATE_CHANGED,
    DriftType.DISTINCT_COUNT_CHANGED,
    DriftType.MIN_VALUE_CHANGED,
    DriftType.MAX_VALUE_CHANGED,
}


class DriftFinding(_DiagnosticModel):
    """One observed change, without causal or business interpretation."""

    drift_type: DriftType
    column_name: Annotated[
        str, Field(min_length=1, max_length=MAX_COLUMN_NAME_CHARS)
    ] | None = None
    before_value: FindingValue | None = None
    after_value: FindingValue | None = None
    absolute_delta: int | float | None = None
    percentage_delta: float | None = None
    percentage_point_delta: float | None = None
    description: Annotated[str, Field(min_length=1, max_length=1000)]

    @field_validator("column_name", "description")
    @classmethod
    def validate_text(cls, value: str | None, info: object) -> str | None:
        if value is None:
            return value
        field_name = getattr(info, "field_name", "text")
        return _reject_control_characters(value, field_name=field_name)

    @field_validator(
        "absolute_delta",
        "percentage_delta",
        "percentage_point_delta",
        mode="before",
    )
    @classmethod
    def validate_finite_delta(cls, value: object) -> object:
        if isinstance(value, bool):
            raise ValueError("numeric deltas cannot be booleans")
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError("numeric deltas must be finite")
        return value

    @model_validator(mode="after")
    def validate_column_scope(self) -> "DriftFinding":
        requires_column = self.drift_type in _COLUMN_DRIFT_TYPES
        if requires_column != (self.column_name is not None):
            raise ValueError("column_name must match the drift type scope")
        return self


class DriftReport(_DiagnosticModel):
    """Canonical comparison result for two snapshots of the same dataset."""

    dataset_id: Annotated[str, Field(min_length=1, max_length=MAX_DATASET_ID_CHARS)]
    before_snapshot_id: Annotated[
        str, Field(min_length=1, max_length=MAX_SNAPSHOT_ID_CHARS)
    ] | None = None
    after_snapshot_id: Annotated[
        str, Field(min_length=1, max_length=MAX_SNAPSHOT_ID_CHARS)
    ] | None = None
    before_captured_at: datetime | None = None
    after_captured_at: datetime | None = None
    findings: Annotated[
        tuple[DriftFinding, ...], Field(max_length=MAX_DRIFT_FINDINGS)
    ] = ()

    @property
    def has_drift(self) -> bool:
        return bool(self.findings)
