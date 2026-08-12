"""Typed aggregate results for deterministic data-quality checks."""

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class QualityClassification(str, Enum):
    OBJECTIVE = "objective"
    HEURISTIC = "heuristic"


class QualityCheck(str, Enum):
    NULL_VALUES = "null_values"
    DUPLICATE_ROWS = "duplicate_rows"
    ALL_NULL_COLUMN = "all_null_column"
    CONSTANT_COLUMN = "constant_column"
    NEGATIVE_NUMERIC_VALUES = "negative_numeric_values"
    FUTURE_DATETIME_VALUES = "future_datetime_values"


class DataQualityIssue(BaseModel):
    """One computed observation with explicit objective/heuristic status."""

    model_config = ConfigDict(frozen=True)

    check: QualityCheck
    classification: QualityClassification
    column: str | None
    count: int
    rate: float
    details: dict[str, object] = Field(default_factory=dict)


class DataQualityExecutionResult(BaseModel):
    """Path-free aggregate quality observations from DuckDB."""

    model_config = ConfigDict(frozen=True)

    row_count: int
    column_count: int
    checked_column_count: int
    issues: tuple[DataQualityIssue, ...]
    warnings: tuple[str, ...] = ()
