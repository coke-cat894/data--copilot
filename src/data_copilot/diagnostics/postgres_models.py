"""Bounded public models for PostgreSQL diagnostic collection."""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, model_validator

from data_copilot.diagnostics.models import DatasetSnapshot


DEFAULT_MAX_PROFILED_COLUMNS = 50
DEFAULT_MAX_DISTINCT_COLUMNS = 20
DEFAULT_MAX_RANGE_COLUMNS = 20
DEFAULT_MAX_DUPLICATE_ROWS = 10_000
DEFAULT_MAX_DIAGNOSTIC_WARNINGS = 20

MAX_CONFIGURED_PROFILED_COLUMNS = 200
MAX_CONFIGURED_STAT_COLUMNS = 50
MAX_CONFIGURED_DUPLICATE_ROWS = 1_000_000
MAX_CONFIGURED_DIAGNOSTIC_WARNINGS = 50
MAX_DIAGNOSTIC_WARNING_CHARS = 500


class _PostgresDiagnosticModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)


class PostgresDiagnosticLimits(_PostgresDiagnosticModel):
    """Explicit resource limits for one table-health observation."""

    max_profiled_columns: Annotated[
        int, Field(ge=1, le=MAX_CONFIGURED_PROFILED_COLUMNS)
    ] = DEFAULT_MAX_PROFILED_COLUMNS
    max_distinct_columns: Annotated[
        int, Field(ge=0, le=MAX_CONFIGURED_STAT_COLUMNS)
    ] = DEFAULT_MAX_DISTINCT_COLUMNS
    max_range_columns: Annotated[
        int, Field(ge=0, le=MAX_CONFIGURED_STAT_COLUMNS)
    ] = DEFAULT_MAX_RANGE_COLUMNS
    max_duplicate_rows: Annotated[
        int, Field(ge=0, le=MAX_CONFIGURED_DUPLICATE_ROWS)
    ] = DEFAULT_MAX_DUPLICATE_ROWS
    max_warnings: Annotated[
        int, Field(ge=1, le=MAX_CONFIGURED_DIAGNOSTIC_WARNINGS)
    ] = DEFAULT_MAX_DIAGNOSTIC_WARNINGS

    @model_validator(mode="after")
    def validate_statistic_scopes(self) -> "PostgresDiagnosticLimits":
        if self.max_distinct_columns > self.max_profiled_columns:
            raise ValueError(
                "max_distinct_columns cannot exceed max_profiled_columns"
            )
        if self.max_range_columns > self.max_profiled_columns:
            raise ValueError("max_range_columns cannot exceed max_profiled_columns")
        return self


class PostgresDiagnosticResult(_PostgresDiagnosticModel):
    """A Phase 4.1 snapshot plus sanitized partial-measurement warnings."""

    snapshot: DatasetSnapshot
    warnings: Annotated[
        tuple[
            Annotated[
                str,
                Field(min_length=1, max_length=MAX_DIAGNOSTIC_WARNING_CHARS),
            ],
            ...,
        ],
        Field(max_length=MAX_CONFIGURED_DIAGNOSTIC_WARNINGS),
    ] = ()

    @property
    def partial(self) -> bool:
        return bool(self.warnings)
