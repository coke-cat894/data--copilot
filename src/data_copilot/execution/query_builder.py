"""Closed, validated SQL builder for Phase 1.3 structured requests."""

import re
from collections.abc import Sequence
from datetime import date, datetime, time
from decimal import Decimal

from data_copilot.config import (
    MAX_FILTERS,
    MAX_GROUP_BY_DIMENSIONS,
    MAX_METRICS,
    MAX_RESULT_COLUMNS,
    MAX_RESULT_ROWS,
    MAX_SAMPLE_ROWS,
)
from data_copilot.errors import (
    ColumnNotFoundError,
    InvalidDimensionError,
    InvalidFilterError,
    InvalidMetricError,
    InvalidProjectionError,
    InvalidSampleRequestError,
    InvalidSortError,
    ResourceLimitError,
)
from data_copilot.execution.models import LogicalColumnType
from data_copilot.execution.query_models import (
    AggregateFunction,
    AggregateSortSpec,
    BuiltQuery,
    DimensionSpec,
    FilterCondition,
    FilterOperator,
    MetricSpec,
    QueryScalar,
    SortDirection,
    SortSpec,
    TimeGrain,
)
from data_copilot.execution.type_system import classify_duckdb_type


QUERY_SOURCE_VIEW = "_data_copilot_query_source"
_ALIAS_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
_SCALAR_TYPES = (str, bool, int, float, Decimal, date, datetime, time)


def quote_identifier(identifier: str) -> str:
    """Quote a validated DuckDB identifier, including embedded quotes."""

    return '"' + identifier.replace('"', '""') + '"'


def build_sample_query(
    schema: Sequence[tuple[str, str]],
    *,
    columns: Sequence[str] | None,
    size: int,
    seed: int,
) -> BuiltQuery:
    _validate_sample_arguments(size, seed)
    selected_columns, warnings = _select_projection(schema, columns)
    projection = _projection_sql(selected_columns)
    view = quote_identifier(QUERY_SOURCE_VIEW)
    sql = (
        f"SELECT {projection} FROM {view} "
        f"USING SAMPLE reservoir({size} ROWS) REPEATABLE ({seed}) "
        f"LIMIT {size}"
    )
    return BuiltQuery(
        sql=sql,
        parameters=(),
        columns=selected_columns,
        return_limit=size,
        detect_truncation=False,
        warnings=warnings,
    )


def build_filter_query(
    schema: Sequence[tuple[str, str]],
    *,
    columns: Sequence[str] | None,
    filters: Sequence[FilterCondition],
    order_by: Sequence[SortSpec] | None,
    limit: int,
) -> BuiltQuery:
    _validate_result_limit(limit)
    selected_columns, warnings = _select_projection(schema, columns)
    where_sql, parameters = _build_filters(schema, filters)
    order_sql = _build_source_order(schema, order_by or ())
    projection = _projection_sql(selected_columns)
    sql = (
        f"SELECT {projection} FROM {quote_identifier(QUERY_SOURCE_VIEW)}"
        f"{where_sql}{order_sql} LIMIT {limit + 1}"
    )
    return BuiltQuery(
        sql=sql,
        parameters=parameters,
        columns=selected_columns,
        return_limit=limit,
        detect_truncation=True,
        warnings=warnings,
    )


def build_aggregate_query(
    schema: Sequence[tuple[str, str]],
    *,
    dimensions: Sequence[DimensionSpec],
    metrics: Sequence[MetricSpec],
    filters: Sequence[FilterCondition],
    order_by: Sequence[AggregateSortSpec],
    limit: int,
) -> BuiltQuery:
    _validate_result_limit(limit)
    dimensions_tuple = _as_typed_sequence(
        dimensions, DimensionSpec, InvalidDimensionError, "dimensions"
    )
    metrics_tuple = _as_typed_sequence(
        metrics, MetricSpec, InvalidMetricError, "metrics"
    )
    if len(dimensions_tuple) > MAX_GROUP_BY_DIMENSIONS:
        raise ResourceLimitError(
            "dimensions exceed "
            f"MAX_GROUP_BY_DIMENSIONS={MAX_GROUP_BY_DIMENSIONS}."
        )
    if not metrics_tuple:
        raise InvalidMetricError("At least one metric is required.")
    if len(metrics_tuple) > MAX_METRICS:
        raise ResourceLimitError(f"metrics exceed MAX_METRICS={MAX_METRICS}.")

    types_by_name = dict(schema)
    dimension_sql = tuple(
        _build_dimension(dimension, types_by_name)
        for dimension in dimensions_tuple
    )
    metric_sql = tuple(
        _build_metric(metric, types_by_name) for metric in metrics_tuple
    )
    aliases = tuple(dimension.name for dimension in dimensions_tuple) + tuple(
        metric.name for metric in metrics_tuple
    )
    _validate_unique_aliases(aliases)

    where_sql, parameters = _build_filters(schema, filters)
    order_sql = _build_aggregate_order(aliases, order_by)
    select_sql = ", ".join(dimension_sql + metric_sql)
    group_sql = (
        " GROUP BY "
        + ", ".join(str(index) for index in range(1, len(dimension_sql) + 1))
        if dimension_sql
        else ""
    )
    sql = (
        f"SELECT {select_sql} FROM {quote_identifier(QUERY_SOURCE_VIEW)}"
        f"{where_sql}{group_sql}{order_sql} LIMIT {limit + 1}"
    )
    return BuiltQuery(
        sql=sql,
        parameters=parameters,
        columns=aliases,
        return_limit=limit,
        detect_truncation=True,
    )


def _validate_sample_arguments(size: int, seed: int) -> None:
    if isinstance(size, bool) or not isinstance(size, int) or size <= 0:
        raise InvalidSampleRequestError("size must be a positive integer.")
    if size > MAX_SAMPLE_ROWS:
        raise ResourceLimitError(f"size exceeds MAX_SAMPLE_ROWS={MAX_SAMPLE_ROWS}.")
    if (
        isinstance(seed, bool)
        or not isinstance(seed, int)
        or seed < 0
        or seed > 2_147_483_647
    ):
        raise InvalidSampleRequestError(
            "seed must be an integer between 0 and 2147483647."
        )


def _validate_result_limit(limit: int) -> None:
    if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
        raise InvalidProjectionError("limit must be a positive integer.")
    if limit > MAX_RESULT_ROWS:
        raise ResourceLimitError(
            f"limit exceeds MAX_RESULT_ROWS={MAX_RESULT_ROWS}."
        )


def _select_projection(
    schema: Sequence[tuple[str, str]], columns: Sequence[str] | None
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    schema_names = tuple(name for name, _ in schema)
    if columns is None:
        selected = schema_names[:MAX_RESULT_COLUMNS]
        if len(schema_names) <= MAX_RESULT_COLUMNS:
            return selected, ()
        warning = (
            f"Dataset has {len(schema_names)} columns. {MAX_RESULT_COLUMNS} columns "
            f"were returned because MAX_RESULT_COLUMNS={MAX_RESULT_COLUMNS}."
        )
        return selected, (warning,)
    if isinstance(columns, (str, bytes)):
        raise InvalidProjectionError("columns must be a sequence of names.")

    selected = tuple(columns)
    if not selected:
        raise InvalidProjectionError("columns cannot be empty when provided.")
    if any(not isinstance(column, str) for column in selected):
        raise InvalidProjectionError("Every projected column must be a string.")
    if len(selected) > MAX_RESULT_COLUMNS:
        raise ResourceLimitError(
            "projection exceeds "
            f"MAX_RESULT_COLUMNS={MAX_RESULT_COLUMNS}."
        )
    if len(set(selected)) != len(selected):
        raise InvalidProjectionError("Duplicate projected columns are not allowed.")
    _validate_source_columns(selected, schema_names)
    return selected, ()


def _projection_sql(columns: Sequence[str]) -> str:
    return ", ".join(quote_identifier(column) for column in columns)


def _build_filters(
    schema: Sequence[tuple[str, str]], filters: Sequence[FilterCondition]
) -> tuple[str, tuple[QueryScalar, ...]]:
    filters_tuple = _as_typed_sequence(
        filters, FilterCondition, InvalidFilterError, "filters"
    )
    if len(filters_tuple) > MAX_FILTERS:
        raise ResourceLimitError(f"filters exceed MAX_FILTERS={MAX_FILTERS}.")
    if not filters_tuple:
        return "", ()

    schema_names = tuple(name for name, _ in schema)
    predicates: list[str] = []
    parameters: list[QueryScalar] = []
    for condition in filters_tuple:
        if not isinstance(condition.column, str) or condition.column not in schema_names:
            raise ColumnNotFoundError(
                f"Unknown filter column: {condition.column!r}."
            )
        if not isinstance(condition.operator, FilterOperator):
            raise InvalidFilterError("Filter operator is not supported.")
        predicate, values = _build_filter_predicate(condition)
        predicates.append(predicate)
        parameters.extend(values)
    return " WHERE " + " AND ".join(predicates), tuple(parameters)


def _build_filter_predicate(
    condition: FilterCondition,
) -> tuple[str, tuple[QueryScalar, ...]]:
    column = quote_identifier(condition.column)
    operator = condition.operator
    value = condition.value

    if operator in {FilterOperator.IS_NULL, FilterOperator.IS_NOT_NULL}:
        if value is not None:
            raise InvalidFilterError(f"{operator.value} does not accept a value.")
        suffix = "IS NULL" if operator is FilterOperator.IS_NULL else "IS NOT NULL"
        return f"{column} {suffix}", ()

    if operator in {FilterOperator.IN, FilterOperator.NOT_IN}:
        values = _validate_value_sequence(value, operator=operator, expected_size=None)
        placeholders = ", ".join("?" for _ in values)
        keyword = "IN" if operator is FilterOperator.IN else "NOT IN"
        return f"{column} {keyword} ({placeholders})", values

    if operator is FilterOperator.BETWEEN:
        values = _validate_value_sequence(value, operator=operator, expected_size=2)
        return f"{column} BETWEEN ? AND ?", values

    scalar = _validate_scalar(value, operator)
    sql_operator = {
        FilterOperator.EQ: "=",
        FilterOperator.NE: "!=",
        FilterOperator.GT: ">",
        FilterOperator.GTE: ">=",
        FilterOperator.LT: "<",
        FilterOperator.LTE: "<=",
    }.get(operator)
    if sql_operator is None:
        raise InvalidFilterError("Filter operator is not supported.")
    return f"{column} {sql_operator} ?", (scalar,)


def _validate_scalar(value: object, operator: FilterOperator) -> QueryScalar:
    if value is None:
        raise InvalidFilterError(
            f"{operator.value} does not accept NULL; use a NULL operator."
        )
    if not isinstance(value, _SCALAR_TYPES):
        raise InvalidFilterError(f"{operator.value} requires one scalar value.")
    return value


def _validate_value_sequence(
    value: object,
    *,
    operator: FilterOperator,
    expected_size: int | None,
) -> tuple[QueryScalar, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise InvalidFilterError(f"{operator.value} requires a value sequence.")
    values = tuple(value)
    if not values:
        raise InvalidFilterError(f"{operator.value} requires a non-empty sequence.")
    if expected_size is not None and len(values) != expected_size:
        raise InvalidFilterError(
            f"{operator.value} requires exactly {expected_size} values."
        )
    return tuple(_validate_scalar(item, operator) for item in values)


def _build_source_order(
    schema: Sequence[tuple[str, str]], order_by: Sequence[SortSpec]
) -> str:
    order_tuple = _as_typed_sequence(
        order_by, SortSpec, InvalidSortError, "order_by"
    )
    if not order_tuple:
        return ""
    schema_names = tuple(name for name, _ in schema)
    columns: list[str] = []
    expressions: list[str] = []
    for spec in order_tuple:
        if not isinstance(spec.column, str) or spec.column not in schema_names:
            raise ColumnNotFoundError(f"Unknown sort column: {spec.column!r}.")
        if not isinstance(spec.direction, SortDirection):
            raise InvalidSortError("Sort direction is not supported.")
        columns.append(spec.column)
        expressions.append(
            f"{quote_identifier(spec.column)} {spec.direction.value.upper()}"
        )
    if len(set(columns)) != len(columns):
        raise InvalidSortError("Duplicate sort columns are not allowed.")
    return " ORDER BY " + ", ".join(expressions)


def _build_dimension(
    dimension: DimensionSpec, types_by_name: dict[str, str]
) -> str:
    _validate_alias(dimension.name, InvalidDimensionError, "dimension")
    if not isinstance(dimension.column, str) or dimension.column not in types_by_name:
        raise ColumnNotFoundError(
            f"Unknown dimension column: {dimension.column!r}."
        )
    column = quote_identifier(dimension.column)
    if dimension.time_grain is None:
        expression = column
    else:
        if not isinstance(dimension.time_grain, TimeGrain):
            raise InvalidDimensionError("Time grain is not supported.")
        duckdb_type = types_by_name[dimension.column].upper()
        logical_type = classify_duckdb_type(duckdb_type)
        if (
            logical_type is not LogicalColumnType.DATETIME
            or (
                duckdb_type.startswith("TIME")
                and not duckdb_type.startswith("TIMESTAMP")
            )
        ):
            raise InvalidDimensionError(
                "time_grain requires a DATE or TIMESTAMP column."
            )
        expression = f"date_trunc('{dimension.time_grain.value}', {column})"
    return f"{expression} AS {quote_identifier(dimension.name)}"


def _build_metric(metric: MetricSpec, types_by_name: dict[str, str]) -> str:
    _validate_alias(metric.name, InvalidMetricError, "metric")
    if not isinstance(metric.function, AggregateFunction):
        raise InvalidMetricError("Aggregate function is not supported.")
    function = metric.function

    if function is AggregateFunction.COUNT and metric.column is None:
        expression = "count(*)"
    else:
        if metric.column is None:
            raise InvalidMetricError(
                f"{function.value} requires a source column."
            )
        if not isinstance(metric.column, str) or metric.column not in types_by_name:
            raise ColumnNotFoundError(f"Unknown metric column: {metric.column!r}.")
        column = quote_identifier(metric.column)
        logical_type = classify_duckdb_type(types_by_name[metric.column])
        if function is AggregateFunction.COUNT:
            expression = f"count({column})"
        elif function is AggregateFunction.COUNT_DISTINCT:
            expression = f"count(DISTINCT {column})"
        elif function in {
            AggregateFunction.SUM,
            AggregateFunction.AVG,
            AggregateFunction.MEDIAN,
        }:
            if logical_type is not LogicalColumnType.NUMERIC:
                raise InvalidMetricError(
                    f"{function.value} requires a numeric column."
                )
            expression = f"{function.value}({column})"
        elif function in {AggregateFunction.MIN, AggregateFunction.MAX}:
            if logical_type not in {
                LogicalColumnType.NUMERIC,
                LogicalColumnType.DATETIME,
            }:
                raise InvalidMetricError(
                    f"{function.value} requires a numeric or temporal column."
                )
            expression = f"{function.value}({column})"
        else:
            raise InvalidMetricError("Aggregate function is not supported.")
    return f"{expression} AS {quote_identifier(metric.name)}"


def _validate_alias(
    alias: object, error_type: type[Exception], subject: str
) -> None:
    if not isinstance(alias, str) or _ALIAS_PATTERN.fullmatch(alias) is None:
        raise error_type(
            f"{subject} name must match ^[A-Za-z_][A-Za-z0-9_]{{0,63}}$."
        )


def _validate_unique_aliases(aliases: Sequence[str]) -> None:
    normalized = tuple(alias.casefold() for alias in aliases)
    if len(set(normalized)) != len(normalized):
        raise InvalidDimensionError(
            "Dimension and metric names must be globally unique."
        )


def _build_aggregate_order(
    aliases: Sequence[str], order_by: Sequence[AggregateSortSpec]
) -> str:
    order_tuple = _as_typed_sequence(
        order_by, AggregateSortSpec, InvalidSortError, "order_by"
    )
    if not order_tuple:
        return ""
    expressions: list[str] = []
    fields: list[str] = []
    for spec in order_tuple:
        if not isinstance(spec.field, str) or spec.field not in aliases:
            raise InvalidSortError(
                f"Unknown aggregate sort field: {spec.field!r}."
            )
        if not isinstance(spec.direction, SortDirection):
            raise InvalidSortError("Sort direction is not supported.")
        fields.append(spec.field)
        expressions.append(
            f"{quote_identifier(spec.field)} {spec.direction.value.upper()}"
        )
    if len(set(fields)) != len(fields):
        raise InvalidSortError("Duplicate aggregate sort fields are not allowed.")
    return " ORDER BY " + ", ".join(expressions)


def _validate_source_columns(
    requested_columns: Sequence[str], schema_names: Sequence[str]
) -> None:
    missing = [column for column in requested_columns if column not in schema_names]
    if missing:
        names = ", ".join(repr(column) for column in missing)
        raise ColumnNotFoundError(f"Unknown projected column(s): {names}.")


def _as_typed_sequence(
    value: object,
    expected_type: type,
    error_type: type[Exception],
    field_name: str,
) -> tuple:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise error_type(f"{field_name} must be a sequence.")
    items = tuple(value)
    if any(not isinstance(item, expected_type) for item in items):
        raise error_type(f"Every {field_name} item must be typed.")
    return items
