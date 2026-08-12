"""Compact results produced by the local execution layer."""

from datetime import date, datetime, time
from decimal import Decimal
from enum import Enum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict
from pydantic import Field as PydanticField


class ColumnMetadata(BaseModel):
    """DuckDB's name and inferred type for one dataset column."""

    model_config = ConfigDict(frozen=True)

    name: str
    duckdb_type: str


class DatasetInspection(BaseModel):
    """The bounded inspection result required by Phase 1.1."""

    model_config = ConfigDict(frozen=True)

    row_count: int
    column_count: int
    columns: tuple[ColumnMetadata, ...]


class LogicalColumnType(str, Enum):
    """Small logical type set used to choose Phase 1.2 profile semantics."""

    NUMERIC = "NUMERIC"
    CATEGORICAL = "CATEGORICAL"
    DATETIME = "DATETIME"
    BOOLEAN = "BOOLEAN"
    OTHER = "OTHER"


class ColumnProfileBase(BaseModel):
    """Statistics shared by every profile category."""

    model_config = ConfigDict(frozen=True)

    name: str
    type: str
    logical_type: LogicalColumnType
    null_count: int
    null_rate: float


NumericValue = int | float | Decimal
TemporalValue = date | datetime | time


class NumericColumnProfile(ColumnProfileBase):
    """Exact aggregate statistics for a numeric column."""

    logical_type: Literal[LogicalColumnType.NUMERIC] = LogicalColumnType.NUMERIC
    distinct_count: int
    min: NumericValue | None
    max: NumericValue | None
    mean: NumericValue | None
    median: NumericValue | None
    p25: NumericValue | None
    p75: NumericValue | None


class TopValue(BaseModel):
    """One non-null categorical value and its dataset-level frequency."""

    model_config = ConfigDict(frozen=True)

    value: str
    count: int
    rate: float


class CategoricalColumnProfile(ColumnProfileBase):
    """Exact cardinality and bounded top values for a categorical column."""

    logical_type: Literal[LogicalColumnType.CATEGORICAL] = (
        LogicalColumnType.CATEGORICAL
    )
    distinct_count: int
    top_values: tuple[TopValue, ...]


class DatetimeColumnProfile(ColumnProfileBase):
    """Exact bounds and cardinality for a temporal column."""

    logical_type: Literal[LogicalColumnType.DATETIME] = LogicalColumnType.DATETIME
    distinct_count: int
    min: TemporalValue | None
    max: TemporalValue | None


class BooleanColumnProfile(ColumnProfileBase):
    """Null, true, false, and exact distinct counts for a boolean column."""

    logical_type: Literal[LogicalColumnType.BOOLEAN] = LogicalColumnType.BOOLEAN
    distinct_count: int
    true_count: int
    false_count: int


class OtherColumnProfile(ColumnProfileBase):
    """Null statistics for uncommon types without unsafe assumptions."""

    logical_type: Literal[LogicalColumnType.OTHER] = LogicalColumnType.OTHER


ColumnProfile = Annotated[
    NumericColumnProfile
    | CategoricalColumnProfile
    | DatetimeColumnProfile
    | BooleanColumnProfile
    | OtherColumnProfile,
    PydanticField(discriminator="logical_type"),
]


class ProfileExecutionResult(BaseModel):
    """Bounded aggregate result produced wholly through DuckDB scans."""

    model_config = ConfigDict(frozen=True)

    row_count: int
    column_count: int
    columns: tuple[ColumnProfile, ...]
    warnings: tuple[str, ...] = ()
