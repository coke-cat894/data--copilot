"""DuckDB-backed inspection for explicitly registered local datasets."""

from collections.abc import Callable, Sequence
from pathlib import Path

import duckdb

from data_copilot.config import (
    DEFAULT_RESULT_ROWS,
    DEFAULT_SAMPLE_ROWS,
    DEFAULT_TOP_VALUES,
    MAX_PROFILE_COLUMNS,
    MAX_TOP_VALUES,
)
from data_copilot.datasets.models import Dataset, DatasetFormat
from data_copilot.datasets.registry import DatasetRegistry
from data_copilot.errors import (
    ColumnNotFoundError,
    DataCopilotError,
    DatasetExecutionError,
    InvalidProfileRequestError,
    ResourceLimitError,
)
from data_copilot.execution.models import (
    BooleanColumnProfile,
    CategoricalColumnProfile,
    ColumnMetadata,
    ColumnProfile,
    DatasetInspection,
    DatetimeColumnProfile,
    LogicalColumnType,
    NumericColumnProfile,
    OtherColumnProfile,
    ProfileExecutionResult,
    TopValue,
)
from data_copilot.execution.query_builder import (
    QUERY_SOURCE_VIEW,
    build_aggregate_query,
    build_filter_query,
    build_sample_query,
    quote_identifier,
)
from data_copilot.execution.query_models import (
    AggregateSortSpec,
    BuiltQuery,
    DimensionSpec,
    FilterCondition,
    MetricSpec,
    QueryExecutionResult,
    SortSpec,
)
from data_copilot.execution.type_system import classify_duckdb_type


_PROFILE_VIEW_NAME = "_data_copilot_profile_source"

class DuckDBEngine:
    """Inspect registered datasets without exposing arbitrary SQL or paths."""

    def __init__(self, registry: DatasetRegistry) -> None:
        self._registry = registry

    def inspect(self, dataset_id: str) -> DatasetInspection:
        """Return row count and schema for a registered dataset ID."""

        dataset = self._registry.get(dataset_id)
        connection = duckdb.connect(database=":memory:")
        try:
            relation = self._scan(connection, dataset)
            columns = tuple(
                ColumnMetadata(name=name, duckdb_type=str(duckdb_type))
                for name, duckdb_type in zip(
                    relation.columns, relation.types, strict=True
                )
            )
            row = relation.aggregate("count(*) AS row_count").fetchone()
            if row is None:
                raise DatasetExecutionError("DuckDB returned no inspection result.")
            return DatasetInspection(
                row_count=int(row[0]),
                column_count=len(columns),
                columns=columns,
            )
        except DatasetExecutionError:
            raise
        except (duckdb.Error, OSError, ValueError) as exc:
            raise DatasetExecutionError(
                f"DuckDB could not inspect dataset {dataset.dataset_id!r}."
            ) from exc
        finally:
            connection.close()

    def sample(
        self,
        dataset_id: str,
        *,
        columns: Sequence[str] | None = None,
        size: int = DEFAULT_SAMPLE_ROWS,
        seed: int = 42,
    ) -> QueryExecutionResult:
        """Return a bounded reproducible random sample."""

        return self._execute_structured_query(
            dataset_id,
            lambda schema: build_sample_query(
                schema, columns=columns, size=size, seed=seed
            ),
        )

    def filter(
        self,
        dataset_id: str,
        *,
        columns: Sequence[str] | None = None,
        filters: Sequence[FilterCondition] = (),
        order_by: Sequence[SortSpec] | None = None,
        limit: int = DEFAULT_RESULT_ROWS,
    ) -> QueryExecutionResult:
        """Return bounded source rows matching validated AND filters."""

        return self._execute_structured_query(
            dataset_id,
            lambda schema: build_filter_query(
                schema,
                columns=columns,
                filters=filters,
                order_by=order_by,
                limit=limit,
            ),
        )

    def aggregate(
        self,
        dataset_id: str,
        *,
        dimensions: Sequence[DimensionSpec] = (),
        metrics: Sequence[MetricSpec],
        filters: Sequence[FilterCondition] = (),
        order_by: Sequence[AggregateSortSpec] = (),
        limit: int = DEFAULT_RESULT_ROWS,
    ) -> QueryExecutionResult:
        """Return bounded grouped or whole-dataset aggregate rows."""

        return self._execute_structured_query(
            dataset_id,
            lambda schema: build_aggregate_query(
                schema,
                dimensions=dimensions,
                metrics=metrics,
                filters=filters,
                order_by=order_by,
                limit=limit,
            ),
        )

    def _execute_structured_query(
        self,
        dataset_id: str,
        builder: Callable[[tuple[tuple[str, str], ...]], BuiltQuery],
    ) -> QueryExecutionResult:
        dataset = self._registry.get(dataset_id)
        connection = duckdb.connect(database=":memory:")
        try:
            relation = self._scan(connection, dataset)
            relation.create_view(QUERY_SOURCE_VIEW, replace=True)
            schema = tuple(
                zip(
                    relation.columns,
                    (str(duckdb_type) for duckdb_type in relation.types),
                    strict=True,
                )
            )
            query = builder(schema)
            cursor = (
                connection.execute(query.sql, query.parameters)
                if query.parameters
                else connection.execute(query.sql)
            )
            fetched_rows = cursor.fetchall()
            truncated = query.detect_truncation and len(fetched_rows) > query.return_limit
            returned_rows = fetched_rows[: query.return_limit]
            rows = tuple(
                dict(zip(query.columns, row, strict=True)) for row in returned_rows
            )
            return QueryExecutionResult(
                columns=query.columns,
                rows=rows,
                row_count=len(rows),
                truncated=truncated,
                warnings=query.warnings,
            )
        except DataCopilotError:
            raise
        except (duckdb.Error, OSError, TypeError, ValueError) as exc:
            raise DatasetExecutionError(
                f"DuckDB could not query dataset {dataset.dataset_id!r}."
            ) from exc
        finally:
            connection.close()

    def profile(
        self,
        dataset_id: str,
        *,
        columns: Sequence[str] | None = None,
        top_k: int = DEFAULT_TOP_VALUES,
    ) -> ProfileExecutionResult:
        """Compute bounded per-column aggregates for a registered dataset."""

        requested_columns = _validate_profile_request(columns, top_k)
        dataset = self._registry.get(dataset_id)
        connection = duckdb.connect(database=":memory:")
        try:
            relation = self._scan(connection, dataset)
            relation.create_view(_PROFILE_VIEW_NAME, replace=True)
            schema = tuple(
                zip(
                    relation.columns,
                    (str(duckdb_type) for duckdb_type in relation.types),
                    strict=True,
                )
            )
            selected_schema, warnings = _select_profile_columns(
                schema, requested_columns
            )
            row = relation.aggregate("count(*) AS row_count").fetchone()
            if row is None:
                raise DatasetExecutionError("DuckDB returned no profile row count.")
            row_count = int(row[0])
            profiles = tuple(
                self._profile_column(
                    connection,
                    name=name,
                    duckdb_type=duckdb_type,
                    row_count=row_count,
                    top_k=top_k,
                )
                for name, duckdb_type in selected_schema
            )
            return ProfileExecutionResult(
                row_count=row_count,
                column_count=len(schema),
                columns=profiles,
                warnings=warnings,
            )
        except DataCopilotError:
            raise
        except (duckdb.Error, OSError, TypeError, ValueError) as exc:
            raise DatasetExecutionError(
                f"DuckDB could not profile dataset {dataset.dataset_id!r}."
            ) from exc
        finally:
            connection.close()

    @staticmethod
    def _profile_column(
        connection: duckdb.DuckDBPyConnection,
        *,
        name: str,
        duckdb_type: str,
        row_count: int,
        top_k: int,
    ) -> ColumnProfile:
        logical_type = classify_duckdb_type(duckdb_type)
        if logical_type is LogicalColumnType.NUMERIC:
            return _profile_numeric(
                connection, name, duckdb_type, row_count=row_count
            )
        if logical_type is LogicalColumnType.CATEGORICAL:
            return _profile_categorical(
                connection,
                name,
                duckdb_type,
                row_count=row_count,
                top_k=top_k,
            )
        if logical_type is LogicalColumnType.DATETIME:
            return _profile_datetime(
                connection, name, duckdb_type, row_count=row_count
            )
        if logical_type is LogicalColumnType.BOOLEAN:
            return _profile_boolean(
                connection, name, duckdb_type, row_count=row_count
            )
        return _profile_other(connection, name, duckdb_type, row_count=row_count)

    @staticmethod
    def _scan(
        connection: duckdb.DuckDBPyConnection, dataset: Dataset
    ) -> duckdb.DuckDBPyRelation:
        path = _path_for_duckdb(dataset.resolved_path)
        if dataset.format is DatasetFormat.CSV:
            return connection.read_csv(path, header=True)
        if dataset.format is DatasetFormat.PARQUET:
            return connection.read_parquet(path)
        if dataset.format is DatasetFormat.JSONL:
            return connection.read_json(path, format="newline_delimited")
        raise DatasetExecutionError("Registered dataset format is not supported.")


def _path_for_duckdb(path: Path) -> str:
    """Convert an already validated internal path for DuckDB's Python API."""

    return str(path)


def _validate_profile_request(
    columns: Sequence[str] | None, top_k: int
) -> tuple[str, ...] | None:
    if isinstance(top_k, bool) or not isinstance(top_k, int) or top_k < 1:
        raise InvalidProfileRequestError("top_k must be a positive integer.")
    if top_k > MAX_TOP_VALUES:
        raise ResourceLimitError(
            f"top_k exceeds MAX_TOP_VALUES={MAX_TOP_VALUES}."
        )
    if columns is None:
        return None
    if isinstance(columns, (str, bytes)):
        raise InvalidProfileRequestError("columns must be a sequence of names.")

    requested_columns = tuple(columns)
    if not requested_columns:
        raise InvalidProfileRequestError("columns cannot be empty when provided.")
    if any(not isinstance(column, str) for column in requested_columns):
        raise InvalidProfileRequestError("Every requested column must be a string.")
    if len(requested_columns) > MAX_PROFILE_COLUMNS:
        raise ResourceLimitError(
            f"Explicit request exceeds MAX_PROFILE_COLUMNS={MAX_PROFILE_COLUMNS}."
        )
    if len(set(requested_columns)) != len(requested_columns):
        raise InvalidProfileRequestError("Duplicate requested columns are not allowed.")
    return requested_columns


def _select_profile_columns(
    schema: tuple[tuple[str, str], ...], requested_columns: tuple[str, ...] | None
) -> tuple[tuple[tuple[str, str], ...], tuple[str, ...]]:
    if requested_columns is None:
        selected_schema = schema[:MAX_PROFILE_COLUMNS]
        if len(schema) <= MAX_PROFILE_COLUMNS:
            return selected_schema, ()
        warning = (
            f"Dataset has {len(schema)} columns. {MAX_PROFILE_COLUMNS} columns were "
            f"profiled because MAX_PROFILE_COLUMNS={MAX_PROFILE_COLUMNS}."
        )
        return selected_schema, (warning,)

    types_by_name = dict(schema)
    missing_columns = [
        column for column in requested_columns if column not in types_by_name
    ]
    if missing_columns:
        missing = ", ".join(repr(column) for column in missing_columns)
        raise ColumnNotFoundError(f"Unknown profile column(s): {missing}.")
    return tuple(
        (column, types_by_name[column]) for column in requested_columns
    ), ()


def _null_rate(null_count: int, row_count: int) -> float:
    return null_count / row_count if row_count else 0.0


def _profile_numeric(
    connection: duckdb.DuckDBPyConnection,
    name: str,
    duckdb_type: str,
    *,
    row_count: int,
) -> NumericColumnProfile:
    column = quote_identifier(name)
    row = connection.execute(
        f"""
        SELECT
            count(*) - count({column}),
            count(DISTINCT {column}),
            min({column}),
            max({column}),
            avg({column}),
            median({column}),
            quantile_cont({column}, 0.25),
            quantile_cont({column}, 0.75)
        FROM {quote_identifier(_PROFILE_VIEW_NAME)}
        """
    ).fetchone()
    if row is None:
        raise DatasetExecutionError("DuckDB returned no numeric profile result.")
    null_count = int(row[0])
    return NumericColumnProfile(
        name=name,
        type=duckdb_type,
        null_count=null_count,
        null_rate=_null_rate(null_count, row_count),
        distinct_count=int(row[1]),
        min=row[2],
        max=row[3],
        mean=row[4],
        median=row[5],
        p25=row[6],
        p75=row[7],
    )


def _profile_categorical(
    connection: duckdb.DuckDBPyConnection,
    name: str,
    duckdb_type: str,
    *,
    row_count: int,
    top_k: int,
) -> CategoricalColumnProfile:
    column = quote_identifier(name)
    view = quote_identifier(_PROFILE_VIEW_NAME)
    base_row = connection.execute(
        f"""
        SELECT count(*) - count({column}), count(DISTINCT {column})
        FROM {view}
        """
    ).fetchone()
    if base_row is None:
        raise DatasetExecutionError("DuckDB returned no categorical profile result.")
    top_rows = connection.execute(
        f"""
        SELECT CAST({column} AS VARCHAR) AS value, count(*) AS value_count
        FROM {view}
        WHERE {column} IS NOT NULL
        GROUP BY {column}
        ORDER BY value_count DESC, value ASC
        LIMIT {top_k}
        """
    ).fetchall()
    null_count = int(base_row[0])
    return CategoricalColumnProfile(
        name=name,
        type=duckdb_type,
        null_count=null_count,
        null_rate=_null_rate(null_count, row_count),
        distinct_count=int(base_row[1]),
        top_values=tuple(
            TopValue(
                value=str(value),
                count=int(count),
                rate=count / row_count if row_count else 0.0,
            )
            for value, count in top_rows
        ),
    )


def _profile_datetime(
    connection: duckdb.DuckDBPyConnection,
    name: str,
    duckdb_type: str,
    *,
    row_count: int,
) -> DatetimeColumnProfile:
    column = quote_identifier(name)
    row = connection.execute(
        f"""
        SELECT
            count(*) - count({column}),
            count(DISTINCT {column}),
            min({column}),
            max({column})
        FROM {quote_identifier(_PROFILE_VIEW_NAME)}
        """
    ).fetchone()
    if row is None:
        raise DatasetExecutionError("DuckDB returned no datetime profile result.")
    null_count = int(row[0])
    return DatetimeColumnProfile(
        name=name,
        type=duckdb_type,
        null_count=null_count,
        null_rate=_null_rate(null_count, row_count),
        distinct_count=int(row[1]),
        min=row[2],
        max=row[3],
    )


def _profile_boolean(
    connection: duckdb.DuckDBPyConnection,
    name: str,
    duckdb_type: str,
    *,
    row_count: int,
) -> BooleanColumnProfile:
    column = quote_identifier(name)
    row = connection.execute(
        f"""
        SELECT
            count(*) - count({column}),
            count(DISTINCT {column}),
            count(*) FILTER (WHERE {column} IS TRUE),
            count(*) FILTER (WHERE {column} IS FALSE)
        FROM {quote_identifier(_PROFILE_VIEW_NAME)}
        """
    ).fetchone()
    if row is None:
        raise DatasetExecutionError("DuckDB returned no boolean profile result.")
    null_count = int(row[0])
    return BooleanColumnProfile(
        name=name,
        type=duckdb_type,
        null_count=null_count,
        null_rate=_null_rate(null_count, row_count),
        distinct_count=int(row[1]),
        true_count=int(row[2]),
        false_count=int(row[3]),
    )


def _profile_other(
    connection: duckdb.DuckDBPyConnection,
    name: str,
    duckdb_type: str,
    *,
    row_count: int,
) -> OtherColumnProfile:
    column = quote_identifier(name)
    row = connection.execute(
        f"""
        SELECT count(*) - count({column})
        FROM {quote_identifier(_PROFILE_VIEW_NAME)}
        """
    ).fetchone()
    if row is None:
        raise DatasetExecutionError("DuckDB returned no basic profile result.")
    null_count = int(row[0])
    return OtherColumnProfile(
        name=name,
        type=duckdb_type,
        null_count=null_count,
        null_rate=_null_rate(null_count, row_count),
    )
