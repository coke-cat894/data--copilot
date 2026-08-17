"""Read-only PostgreSQL collection for Phase 4.1 diagnostic snapshots."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from enum import Enum
import math
import re

import psycopg
from psycopg import sql
from pydantic import ValidationError

from data_copilot.databases import ColumnMetadata, DatabaseRegistry, TableType
from data_copilot.databases.constants import MAX_TABLE_COLUMNS
from data_copilot.diagnostics.constants import MAX_COUNT
from data_copilot.diagnostics.models import ColumnSnapshot, DatasetSnapshot, RangeValue
from data_copilot.diagnostics.postgres_models import (
    PostgresDiagnosticLimits,
    PostgresDiagnosticResult,
)
from data_copilot.errors import (
    DatabaseMetadataError,
    DiagnosticCollectionError,
    DiagnosticTimeoutError,
    SchemaNotFoundError,
    TableNotFoundError,
)
from data_copilot.execution.postgres_metadata_queries import (
    LIST_COLUMNS_SQL,
    LOOKUP_TABLE_SQL,
)


_SET_STATEMENT_TIMEOUT_SQL = (
    "SELECT pg_catalog.set_config('statement_timeout', %s, TRUE)"
)


class _RangeKind(str, Enum):
    NUMERIC = "numeric"
    DATE = "date"
    DATETIME = "datetime"


@dataclass(frozen=True)
class _ColumnCapabilities:
    supports_distinct: bool
    supports_grouping: bool
    range_kind: _RangeKind | None


@dataclass(frozen=True)
class _ColumnStatisticPlan:
    metadata: ColumnMetadata
    null_count_index: int
    distinct_count_index: int | None
    minimum_index: int | None
    maximum_index: int | None


@dataclass(frozen=True)
class _StatisticsQueryPlan:
    query: sql.Composed
    columns: tuple[_ColumnStatisticPlan, ...]
    expected_value_count: int


class PostgresDiagnosticCollector:
    """Collect one transactionally consistent, bounded table-health snapshot."""

    def __init__(
        self,
        registry: DatabaseRegistry,
        *,
        limits: PostgresDiagnosticLimits | None = None,
    ) -> None:
        self._registry = registry
        self._limits = limits or PostgresDiagnosticLimits()

    def collect(
        self,
        database_id: str,
        *,
        schema_name: str,
        table_name: str,
    ) -> PostgresDiagnosticResult:
        """Observe one table through program-owned queries and an opaque ID."""

        validated_schema = _required_identifier(schema_name, "Schema")
        validated_table = _required_identifier(table_name, "Table")
        database = self._registry.get(database_id)
        config = database.connection_config
        warnings: list[str] = []

        try:
            with psycopg.connect(
                config.dsn,
                connect_timeout=config.connect_timeout_seconds,
            ) as connection:
                connection.read_only = True
                connection.isolation_level = psycopg.IsolationLevel.REPEATABLE_READ
                with connection.cursor() as cursor:
                    cursor.execute(
                        _SET_STATEMENT_TIMEOUT_SQL,
                        (str(config.statement_timeout_ms),),
                    )
                    relation_oid, _ = _lookup_table(
                        cursor,
                        validated_schema,
                        validated_table,
                    )
                    columns, metadata_truncated = _load_columns(cursor, relation_oid)
                    if metadata_truncated:
                        warnings.append(
                            f"Column metadata was truncated to {MAX_TABLE_COLUMNS} "
                            "entries; omitted columns are not represented."
                        )

                    query_plan, plan_warnings = _build_statistics_query(
                        validated_schema,
                        validated_table,
                        columns,
                        self._limits,
                    )
                    warnings.extend(plan_warnings)
                    cursor.execute(query_plan.query)
                    statistic_row = cursor.fetchone()
                    row_count, snapshot_columns, range_warning = _parse_statistics(
                        statistic_row,
                        columns,
                        query_plan,
                    )
                    if range_warning is not None:
                        warnings.append(range_warning)

                    duplicate_count: int | None = None
                    duplicate_rate: float | None = None
                    if metadata_truncated:
                        warnings.append(
                            "Exact full-row duplicate statistics were skipped because "
                            "column metadata was truncated."
                        )
                    elif any(
                        not _classify_postgres_type(column.postgres_type).supports_grouping
                        for column in columns
                    ):
                        warnings.append(
                            "Exact full-row duplicate statistics were skipped because "
                            "one or more PostgreSQL column types do not support safe "
                            "grouping."
                        )
                    elif row_count > self._limits.max_duplicate_rows:
                        warnings.append(
                            "Exact full-row duplicate statistics were skipped because "
                            f"row_count={row_count} exceeds max_duplicate_rows="
                            f"{self._limits.max_duplicate_rows}."
                        )
                    else:
                        cursor.execute(
                            _build_duplicate_query(
                                validated_schema,
                                validated_table,
                                columns,
                            )
                        )
                        duplicate_row = cursor.fetchone()
                        duplicate_count = _parse_single_count(
                            duplicate_row,
                            label="duplicate count",
                        )
                        if duplicate_count > row_count:
                            raise DiagnosticCollectionError(
                                "PostgreSQL returned an invalid duplicate count."
                            )
                        duplicate_rate = (
                            duplicate_count / row_count if row_count else 0.0
                        )
        except (SchemaNotFoundError, TableNotFoundError, DiagnosticCollectionError):
            raise
        except psycopg.errors.QueryCanceled:
            raise DiagnosticTimeoutError(
                "Diagnostic collection exceeded the configured statement timeout "
                f"for database {database.database_id!r}."
            ) from None
        except psycopg.Error:
            raise DiagnosticCollectionError(
                "Could not collect diagnostics for registered database "
                f"{database.database_id!r}."
            ) from None

        try:
            snapshot = DatasetSnapshot(
                dataset_id=f"{validated_schema}.{validated_table}",
                captured_at=datetime.now(timezone.utc),
                row_count=row_count,
                columns=snapshot_columns,
                duplicate_count=duplicate_count,
                duplicate_rate=duplicate_rate,
            )
            return PostgresDiagnosticResult(
                snapshot=snapshot,
                warnings=_bounded_warnings(warnings, self._limits.max_warnings),
            )
        except ValidationError:
            raise DiagnosticCollectionError(
                "PostgreSQL diagnostic observations violated the snapshot contract."
            ) from None


def _required_identifier(value: str, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DatabaseMetadataError(f"{label} name cannot be empty.")
    stripped = value.strip()
    if len(stripped) > 255 or "/" in stripped or "\\" in stripped:
        raise DatabaseMetadataError(f"{label} name is not a valid logical identity.")
    if any(ord(character) < 32 or ord(character) == 127 for character in stripped):
        raise DatabaseMetadataError(f"{label} name contains invalid characters.")
    return stripped


def _lookup_table(
    cursor: psycopg.Cursor[object],
    schema_name: str,
    table_name: str,
) -> tuple[int, TableType]:
    cursor.execute(LOOKUP_TABLE_SQL, (schema_name, schema_name, table_name))
    row = cursor.fetchone()
    if row is None or len(row) < 3:
        raise DiagnosticCollectionError(
            "PostgreSQL returned invalid table identity metadata."
        )
    if not row[0]:
        raise SchemaNotFoundError(f"Unknown schema {schema_name!r}.")
    if row[1] is None:
        raise TableNotFoundError(f"Unknown table {schema_name!r}.{table_name!r}.")
    try:
        return int(row[1]), TableType(row[2])
    except (TypeError, ValueError):
        raise DiagnosticCollectionError(
            "PostgreSQL returned invalid table identity metadata."
        ) from None


def _load_columns(
    cursor: psycopg.Cursor[object], relation_oid: int
) -> tuple[tuple[ColumnMetadata, ...], bool]:
    cursor.execute(LIST_COLUMNS_SQL, (relation_oid, MAX_TABLE_COLUMNS + 1))
    rows = cursor.fetchall()
    truncated = len(rows) > MAX_TABLE_COLUMNS
    try:
        columns = tuple(
            ColumnMetadata(
                name=row[0],
                postgres_type=row[1],
                nullable=row[2],
            )
            for row in rows[:MAX_TABLE_COLUMNS]
        )
    except (IndexError, TypeError, ValueError, ValidationError):
        raise DiagnosticCollectionError(
            "PostgreSQL returned invalid column metadata."
        ) from None
    return columns, truncated


def _build_statistics_query(
    schema_name: str,
    table_name: str,
    columns: tuple[ColumnMetadata, ...],
    limits: PostgresDiagnosticLimits,
) -> tuple[_StatisticsQueryPlan, tuple[str, ...]]:
    profiled = columns[: limits.max_profiled_columns]
    capabilities = {
        column.name: _classify_postgres_type(column.postgres_type)
        for column in profiled
    }
    distinct_candidates = tuple(
        column
        for column in profiled
        if capabilities[column.name].supports_distinct
    )
    range_candidates = tuple(
        column
        for column in profiled
        if capabilities[column.name].range_kind is not None
    )
    distinct_names = {
        column.name for column in distinct_candidates[: limits.max_distinct_columns]
    }
    range_names = {
        column.name for column in range_candidates[: limits.max_range_columns]
    }

    expressions: list[sql.Composable] = [sql.SQL("COUNT(*)::bigint")]
    plans: list[_ColumnStatisticPlan] = []
    next_index = 1
    for column in profiled:
        identifier = sql.Identifier(column.name)
        null_index = next_index
        expressions.append(
            sql.SQL("COUNT(*) FILTER (WHERE {} IS NULL)::bigint").format(identifier)
        )
        next_index += 1

        distinct_index: int | None = None
        if column.name in distinct_names:
            distinct_index = next_index
            expressions.append(
                sql.SQL("COUNT(DISTINCT {})::bigint").format(identifier)
            )
            next_index += 1

        minimum_index: int | None = None
        maximum_index: int | None = None
        if column.name in range_names:
            minimum_index = next_index
            maximum_index = next_index + 1
            expressions.extend(
                (
                    sql.SQL("MIN({})").format(identifier),
                    sql.SQL("MAX({})").format(identifier),
                )
            )
            next_index += 2
        plans.append(
            _ColumnStatisticPlan(
                metadata=column,
                null_count_index=null_index,
                distinct_count_index=distinct_index,
                minimum_index=minimum_index,
                maximum_index=maximum_index,
            )
        )

    query = sql.SQL("SELECT {} FROM {}").format(
        sql.SQL(", ").join(expressions),
        sql.Identifier(schema_name, table_name),
    )
    warnings: list[str] = []
    if len(columns) > len(profiled):
        warnings.append(
            f"Optional statistics were limited to the first {len(profiled)} of "
            f"{len(columns)} represented columns."
        )
    unsupported_distinct = len(profiled) - len(distinct_candidates)
    if unsupported_distinct:
        warnings.append(
            "Exact distinct counts are unavailable for "
            f"{unsupported_distinct} profiled columns with unsupported "
            "PostgreSQL types."
        )
    if len(distinct_candidates) > len(distinct_names):
        warnings.append(
            "Exact distinct counts were limited to the first "
            f"{len(distinct_names)} supported profiled columns."
        )
    unsupported_ranges = len(profiled) - len(range_candidates)
    if unsupported_ranges:
        warnings.append(
            "Range statistics are unavailable for "
            f"{unsupported_ranges} profiled columns with unsupported "
            "PostgreSQL types."
        )
    if len(range_candidates) > len(range_names):
        warnings.append(
            "Range statistics were limited to the first "
            f"{len(range_names)} supported profiled columns."
        )
    return (
        _StatisticsQueryPlan(
            query=query,
            columns=tuple(plans),
            expected_value_count=next_index,
        ),
        tuple(warnings),
    )


def _parse_statistics(
    row: Sequence[object] | None,
    all_columns: tuple[ColumnMetadata, ...],
    plan: _StatisticsQueryPlan,
) -> tuple[int, tuple[ColumnSnapshot, ...], str | None]:
    if row is None or len(row) != plan.expected_value_count:
        raise DiagnosticCollectionError(
            "PostgreSQL returned invalid diagnostic statistics."
        )
    row_count = _parse_count(row[0], label="row count")
    snapshots_by_name: dict[str, ColumnSnapshot] = {}
    invalid_range_count = 0
    for column_plan in plan.columns:
        metadata = column_plan.metadata
        null_count = _parse_count(
            row[column_plan.null_count_index],
            label="null count",
        )
        if null_count > row_count:
            raise DiagnosticCollectionError(
                "PostgreSQL returned a null count greater than row count."
            )
        distinct_count = (
            _parse_count(
                row[column_plan.distinct_count_index],
                label="distinct count",
            )
            if column_plan.distinct_count_index is not None
            else None
        )
        if distinct_count is not None and distinct_count > row_count:
            raise DiagnosticCollectionError(
                "PostgreSQL returned a distinct count greater than row count."
            )

        minimum: RangeValue | None = None
        maximum: RangeValue | None = None
        if column_plan.minimum_index is not None:
            minimum, maximum, valid_range = _normalize_range_pair(
                row[column_plan.minimum_index],
                row[column_plan.maximum_index],  # type: ignore[index]
            )
            if not valid_range:
                invalid_range_count += 1
        snapshots_by_name[metadata.name] = ColumnSnapshot(
            name=metadata.name,
            data_type=metadata.postgres_type,
            nullable=metadata.nullable,
            null_count=null_count,
            null_rate=(null_count / row_count if row_count else 0.0),
            distinct_count=distinct_count,
            min_value=minimum,
            max_value=maximum,
        )

    for metadata in all_columns[len(plan.columns) :]:
        snapshots_by_name[metadata.name] = ColumnSnapshot(
            name=metadata.name,
            data_type=metadata.postgres_type,
            nullable=metadata.nullable,
        )
    warning = (
        "Range statistics were unavailable for "
        f"{invalid_range_count} columns whose observed bounds could not be "
        "represented safely."
        if invalid_range_count
        else None
    )
    return row_count, tuple(snapshots_by_name.values()), warning


def _normalize_range_pair(
    minimum: object,
    maximum: object,
) -> tuple[RangeValue | None, RangeValue | None, bool]:
    if minimum is None and maximum is None:
        return None, None, True
    normalized_minimum = _normalize_range_value(minimum)
    normalized_maximum = _normalize_range_value(maximum)
    if normalized_minimum is None or normalized_maximum is None:
        return None, None, False
    return normalized_minimum, normalized_maximum, True


def _normalize_range_value(value: object) -> RangeValue | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (datetime, date)):
        return value
    if isinstance(value, int):
        return value if -MAX_COUNT <= value <= MAX_COUNT else None
    if isinstance(value, Decimal):
        try:
            value = float(value)
        except (OverflowError, ValueError):
            return None
    if isinstance(value, float) and math.isfinite(value):
        return value
    return None


def _parse_single_count(
    row: Sequence[object] | None,
    *,
    label: str,
) -> int:
    if row is None or len(row) != 1:
        raise DiagnosticCollectionError(
            f"PostgreSQL returned an invalid {label}."
        )
    return _parse_count(row[0], label=label)


def _parse_count(value: object, *, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise DiagnosticCollectionError(
            f"PostgreSQL returned an invalid {label}."
        )
    return value


def _build_duplicate_query(
    schema_name: str,
    table_name: str,
    columns: tuple[ColumnMetadata, ...],
) -> sql.Composed:
    relation = sql.Identifier(schema_name, table_name)
    if not columns:
        return sql.SQL(
            "SELECT GREATEST(COUNT(*) - 1, 0)::bigint FROM {}"
        ).format(relation)
    identifiers = sql.SQL(", ").join(
        sql.Identifier(column.name) for column in columns
    )
    return sql.SQL(
        "SELECT COALESCE(SUM(group_count - 1), 0)::bigint "
        "FROM (SELECT COUNT(*)::bigint AS group_count FROM {} "
        "GROUP BY {} HAVING COUNT(*) > 1) AS duplicate_groups"
    ).format(relation, identifiers)


def _classify_postgres_type(postgres_type: str) -> _ColumnCapabilities:
    normalized = re.sub(r"\([^)]*\)", "", postgres_type.casefold())
    normalized = " ".join(normalized.split())
    numeric_types = {
        "smallint",
        "integer",
        "bigint",
        "real",
        "double precision",
        "numeric",
        "decimal",
    }
    datetime_types = {
        "timestamp without time zone",
        "timestamp with time zone",
        "timestamp",
        "timestamptz",
    }
    distinct_only_types = {
        "boolean",
        "text",
        "character varying",
        "character",
        "uuid",
        "bytea",
        "time without time zone",
        "time with time zone",
        "jsonb",
    }
    if normalized in numeric_types:
        return _ColumnCapabilities(True, True, _RangeKind.NUMERIC)
    if normalized == "date":
        return _ColumnCapabilities(True, True, _RangeKind.DATE)
    if normalized in datetime_types:
        return _ColumnCapabilities(True, True, _RangeKind.DATETIME)
    supports_grouping = normalized in distinct_only_types
    return _ColumnCapabilities(supports_grouping, supports_grouping, None)


def _bounded_warnings(warnings: list[str], maximum: int) -> tuple[str, ...]:
    if len(warnings) <= maximum:
        return tuple(warnings)
    truncation_warning = (
        "Additional diagnostic warnings were omitted due to the configured "
        "warning bound."
    )
    if maximum == 1:
        return (truncation_warning,)
    return tuple(warnings[: maximum - 1]) + (truncation_warning,)
