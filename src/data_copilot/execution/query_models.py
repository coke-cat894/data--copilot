"""Typed structured query specifications and bounded internal results."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal
from enum import Enum
from typing import TypeAlias

from pydantic import BaseModel, ConfigDict


class FilterOperator(str, Enum):
    EQ = "eq"
    NE = "ne"
    GT = "gt"
    GTE = "gte"
    LT = "lt"
    LTE = "lte"
    IN = "in"
    NOT_IN = "not_in"
    BETWEEN = "between"
    IS_NULL = "is_null"
    IS_NOT_NULL = "is_not_null"


class SortDirection(str, Enum):
    ASC = "asc"
    DESC = "desc"


class TimeGrain(str, Enum):
    YEAR = "year"
    QUARTER = "quarter"
    MONTH = "month"
    WEEK = "week"
    DAY = "day"


class AggregateFunction(str, Enum):
    COUNT = "count"
    COUNT_DISTINCT = "count_distinct"
    SUM = "sum"
    AVG = "avg"
    MEDIAN = "median"
    MIN = "min"
    MAX = "max"


QueryScalar: TypeAlias = str | bool | int | float | Decimal | date | datetime | time
FilterValue: TypeAlias = QueryScalar | Sequence[QueryScalar] | None


@dataclass(frozen=True, slots=True)
class FilterCondition:
    column: str
    operator: FilterOperator
    value: FilterValue = None


@dataclass(frozen=True, slots=True)
class SortSpec:
    column: str
    direction: SortDirection = SortDirection.ASC


@dataclass(frozen=True, slots=True)
class DimensionSpec:
    name: str
    column: str
    time_grain: TimeGrain | None = None


@dataclass(frozen=True, slots=True)
class MetricSpec:
    name: str
    function: AggregateFunction
    column: str | None = None


@dataclass(frozen=True, slots=True)
class AggregateSortSpec:
    field: str
    direction: SortDirection = SortDirection.ASC


@dataclass(frozen=True, slots=True)
class BuiltQuery:
    sql: str
    parameters: tuple[QueryScalar, ...]
    columns: tuple[str, ...]
    return_limit: int
    detect_truncation: bool
    warnings: tuple[str, ...] = ()


class QueryExecutionResult(BaseModel):
    """Bounded rows returned by one generated read-only query."""

    model_config = ConfigDict(frozen=True)

    columns: tuple[str, ...]
    rows: tuple[dict[str, object], ...]
    row_count: int
    truncated: bool
    warnings: tuple[str, ...] = ()
