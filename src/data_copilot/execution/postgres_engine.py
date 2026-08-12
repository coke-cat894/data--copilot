"""Read-only PostgreSQL health and bounded metadata discovery."""

import psycopg
from pydantic import BaseModel, ConfigDict, ValidationError

from data_copilot.databases import (
    ColumnMetadata,
    DatabaseQueryResult,
    DatabaseRegistry,
    DatabaseType,
    ForeignKeyMetadata,
    IndexMetadata,
    QueryPlanResult,
    RelationshipListResult,
    RelationshipMetadata,
    TableInspectionResult,
    TableListResult,
    TableMetadata,
    TableType,
)
from data_copilot.databases.constants import (
    MAX_DATABASE_TABLES,
    MAX_INDEXES,
    MAX_QUERY_COLUMNS,
    MAX_QUERY_ROWS,
    MAX_RELATIONSHIPS,
    MAX_TABLE_COLUMNS,
)
from data_copilot.errors import (
    DatabaseConnectionError,
    DatabaseMetadataError,
    ExplainQueryError,
    QueryResultTooWideError,
    QueryTimeoutError,
    SchemaNotFoundError,
    SQLAmbiguousColumnError,
    SQLExecutionError,
    SQLGroupingError,
    SQLObjectNotFoundError,
    SQLTypeMismatchError,
    TableNotFoundError,
)
from data_copilot.execution.postgres_metadata_queries import (
    LIST_COLUMNS_SQL,
    LIST_INDEXES_SQL,
    LIST_RELATIONSHIPS_SQL,
    LIST_TABLES_SQL,
    LOOKUP_TABLE_SQL,
    OUTBOUND_FOREIGN_KEYS_SQL,
    PRIMARY_KEY_SQL,
)
from data_copilot.execution.postgres_plan_parser import parse_query_plan
from data_copilot.sql import SQLValidator


_HEALTH_CHECK_SQL = "SELECT 1"
_SET_STATEMENT_TIMEOUT_SQL = (
    "SELECT pg_catalog.set_config('statement_timeout', %s, TRUE)"
)
_QUERY_CURSOR_NAME = "_data_copilot_read_query"
_EXPLAIN_PREFIX = "EXPLAIN (FORMAT JSON) "


class PostgresPingResult(BaseModel):
    """Compact result of the program-owned PostgreSQL health check."""

    model_config = ConfigDict(frozen=True)

    connected: bool
    database_type: DatabaseType
    database_name: str


class PostgresEngine:
    """Run only program-owned PostgreSQL health and metadata queries."""

    def __init__(
        self,
        registry: DatabaseRegistry,
    ) -> None:
        self._registry = registry
        self._sql_validator = SQLValidator()

    def ping(self, database_id: str) -> PostgresPingResult:
        """Verify a registered database using only a fixed read-only query."""

        database = self._registry.get(database_id)
        config = database.connection_config
        try:
            with psycopg.connect(
                config.dsn,
                connect_timeout=config.connect_timeout_seconds,
            ) as connection:
                connection.read_only = True
                with connection.cursor() as cursor:
                    cursor.execute(_HEALTH_CHECK_SQL)
                    row = cursor.fetchone()
        except psycopg.Error:
            raise DatabaseConnectionError(
                f"Could not connect to registered database {database.database_id!r}."
            ) from None

        if row != (1,):
            raise DatabaseConnectionError(
                f"Registered database {database.database_id!r} returned an "
                "invalid health-check response."
            )
        return PostgresPingResult(
            connected=True,
            database_type=database.database_type,
            database_name=database.database_name,
        )

    def list_tables(
        self,
        database_id: str,
        *,
        schema: str | None = None,
    ) -> TableListResult:
        """List a bounded set of non-system relations using a bound filter."""

        schema_filter = _optional_name(schema, "Schema")
        database = self._registry.get(database_id)
        try:
            with psycopg.connect(
                database.connection_config.dsn,
                connect_timeout=database.connection_config.connect_timeout_seconds,
            ) as connection:
                connection.read_only = True
                with connection.cursor() as cursor:
                    cursor.execute(
                        LIST_TABLES_SQL,
                        (schema_filter, schema_filter, MAX_DATABASE_TABLES + 1),
                    )
                    rows = cursor.fetchall()
        except psycopg.Error:
            raise DatabaseMetadataError(
                f"Could not list metadata for registered database "
                f"{database.database_id!r}."
            ) from None

        try:
            truncated = len(rows) > MAX_DATABASE_TABLES
            tables = tuple(
                TableMetadata(
                    schema_name=row[0],
                    table_name=row[1],
                    table_type=TableType(row[2]),
                )
                for row in rows[:MAX_DATABASE_TABLES]
            )
        except (IndexError, TypeError, ValueError, ValidationError):
            raise DatabaseMetadataError(
                f"Registered database {database.database_id!r} returned invalid "
                "table metadata."
            ) from None
        return TableListResult(
            tables=tables,
            truncated=truncated,
            warnings=(
                (f"Table metadata was truncated to {MAX_DATABASE_TABLES} entries.",)
                if truncated
                else ()
            ),
        )

    def inspect_table(
        self,
        database_id: str,
        *,
        schema_name: str,
        table_name: str,
    ) -> TableInspectionResult:
        """Inspect bounded declared metadata for a schema-qualified relation."""

        validated_schema = _required_name(schema_name, "Schema")
        validated_table = _required_name(table_name, "Table")
        database = self._registry.get(database_id)
        try:
            with psycopg.connect(
                database.connection_config.dsn,
                connect_timeout=database.connection_config.connect_timeout_seconds,
            ) as connection:
                connection.read_only = True
                with connection.cursor() as cursor:
                    relation_oid, table_type = _lookup_table(
                        cursor, validated_schema, validated_table
                    )
                    cursor.execute(
                        LIST_COLUMNS_SQL,
                        (relation_oid, MAX_TABLE_COLUMNS + 1),
                    )
                    column_rows = cursor.fetchall()
                    cursor.execute(
                        PRIMARY_KEY_SQL,
                        (relation_oid, MAX_TABLE_COLUMNS + 1),
                    )
                    primary_key_rows = cursor.fetchall()
                    cursor.execute(
                        OUTBOUND_FOREIGN_KEYS_SQL,
                        (relation_oid, MAX_RELATIONSHIPS + 1),
                    )
                    foreign_key_rows = cursor.fetchall()
                    cursor.execute(
                        LIST_INDEXES_SQL,
                        (relation_oid, MAX_INDEXES + 1),
                    )
                    index_rows = cursor.fetchall()
        except (SchemaNotFoundError, TableNotFoundError):
            raise
        except psycopg.Error:
            raise DatabaseMetadataError(
                f"Could not inspect metadata for registered database "
                f"{database.database_id!r}."
            ) from None

        column_truncated = len(column_rows) > MAX_TABLE_COLUMNS
        primary_key_truncated = len(primary_key_rows) > MAX_TABLE_COLUMNS
        foreign_keys_truncated = len(foreign_key_rows) > MAX_RELATIONSHIPS
        indexes_truncated = len(index_rows) > MAX_INDEXES
        warnings = _inspection_warnings(
            column_truncated=column_truncated,
            primary_key_truncated=primary_key_truncated,
            foreign_keys_truncated=foreign_keys_truncated,
            indexes_truncated=indexes_truncated,
        )
        try:
            return TableInspectionResult(
                schema_name=validated_schema,
                table_name=validated_table,
                table_type=table_type,
                columns=tuple(
                    ColumnMetadata(
                        name=row[0],
                        postgres_type=row[1],
                        nullable=row[2],
                    )
                    for row in column_rows[:MAX_TABLE_COLUMNS]
                ),
                primary_key=tuple(
                    row[0] for row in primary_key_rows[:MAX_TABLE_COLUMNS]
                ),
                foreign_keys=tuple(
                    ForeignKeyMetadata(
                        constraint_name=row[0],
                        source_columns=tuple(row[1]),
                        target_schema_name=row[2],
                        target_table_name=row[3],
                        target_columns=tuple(row[4]),
                    )
                    for row in foreign_key_rows[:MAX_RELATIONSHIPS]
                ),
                basic_indexes=tuple(
                    IndexMetadata(
                        index_name=row[0],
                        columns=tuple(row[1]),
                        unique=row[2],
                        primary=row[3],
                    )
                    for row in index_rows[:MAX_INDEXES]
                ),
                truncated=bool(warnings),
                warnings=warnings,
            )
        except (IndexError, TypeError, ValueError, ValidationError):
            raise DatabaseMetadataError(
                f"Registered database {database.database_id!r} returned invalid "
                "table inspection metadata."
            ) from None

    def get_relationships(
        self,
        database_id: str,
        *,
        schema_name: str,
        table_name: str,
    ) -> RelationshipListResult:
        """Return bounded inbound and outbound declared foreign keys."""

        validated_schema = _required_name(schema_name, "Schema")
        validated_table = _required_name(table_name, "Table")
        database = self._registry.get(database_id)
        try:
            with psycopg.connect(
                database.connection_config.dsn,
                connect_timeout=database.connection_config.connect_timeout_seconds,
            ) as connection:
                connection.read_only = True
                with connection.cursor() as cursor:
                    relation_oid, _ = _lookup_table(
                        cursor, validated_schema, validated_table
                    )
                    cursor.execute(
                        LIST_RELATIONSHIPS_SQL,
                        (
                            relation_oid,
                            relation_oid,
                            relation_oid,
                            relation_oid,
                            MAX_RELATIONSHIPS + 1,
                        ),
                    )
                    rows = cursor.fetchall()
        except (SchemaNotFoundError, TableNotFoundError):
            raise
        except psycopg.Error:
            raise DatabaseMetadataError(
                f"Could not inspect relationships for registered database "
                f"{database.database_id!r}."
            ) from None

        truncated = len(rows) > MAX_RELATIONSHIPS
        try:
            return RelationshipListResult(
                schema_name=validated_schema,
                table_name=validated_table,
                relationships=tuple(
                    RelationshipMetadata(
                        direction=row[0],
                        constraint_name=row[1],
                        source_schema_name=row[2],
                        source_table_name=row[3],
                        source_columns=tuple(row[4]),
                        target_schema_name=row[5],
                        target_table_name=row[6],
                        target_columns=tuple(row[7]),
                    )
                    for row in rows[:MAX_RELATIONSHIPS]
                ),
                truncated=truncated,
                warnings=(
                    (
                        f"Relationship metadata was truncated to "
                        f"{MAX_RELATIONSHIPS} entries.",
                    )
                    if truncated
                    else ()
                ),
            )
        except (IndexError, TypeError, ValueError, ValidationError):
            raise DatabaseMetadataError(
                f"Registered database {database.database_id!r} returned invalid "
                "relationship metadata."
            ) from None

    def execute_read_query(
        self,
        database_id: str,
        sql: str,
    ) -> DatabaseQueryResult:
        """Validate then execute one bounded read query through an opaque ID."""

        validated_sql = self._sql_validator.validate(sql)
        if validated_sql.is_explain:
            raise SQLExecutionError("EXPLAIN execution is not supported.")

        database = self._registry.get(database_id)
        config = database.connection_config
        try:
            with psycopg.connect(
                config.dsn,
                connect_timeout=config.connect_timeout_seconds,
            ) as connection:
                connection.read_only = True
                with connection.cursor() as control_cursor:
                    control_cursor.execute(
                        _SET_STATEMENT_TIMEOUT_SQL,
                        (str(config.statement_timeout_ms),),
                    )
                with connection.cursor(name=_QUERY_CURSOR_NAME) as cursor:
                    cursor.execute(validated_sql.normalized_sql)
                    columns = _query_columns(cursor)
                    if len(columns) > MAX_QUERY_COLUMNS:
                        raise QueryResultTooWideError(
                            f"Query result exceeds MAX_QUERY_COLUMNS={MAX_QUERY_COLUMNS}."
                        )
                    rows = cursor.fetchmany(MAX_QUERY_ROWS + 1)
        except QueryResultTooWideError:
            raise
        except psycopg.errors.QueryCanceled:
            raise QueryTimeoutError(
                f"Query exceeded the configured statement timeout for "
                f"database {database.database_id!r}."
            ) from None
        except (psycopg.errors.UndefinedColumn, psycopg.errors.UndefinedTable):
            raise SQLObjectNotFoundError(
                "Query references a table or column that does not exist."
            ) from None
        except psycopg.errors.AmbiguousColumn:
            raise SQLAmbiguousColumnError(
                "Query contains a column reference that is ambiguous."
            ) from None
        except psycopg.errors.DatatypeMismatch:
            raise SQLTypeMismatchError(
                "Query contains incompatible PostgreSQL data types."
            ) from None
        except psycopg.errors.GroupingError:
            raise SQLGroupingError(
                "Query contains invalid grouping or aggregate semantics."
            ) from None
        except psycopg.Error:
            raise SQLExecutionError(
                f"Read query failed for registered database {database.database_id!r}."
            ) from None

        truncated = len(rows) > MAX_QUERY_ROWS
        returned_rows = tuple(tuple(row) for row in rows[:MAX_QUERY_ROWS])
        return DatabaseQueryResult(
            database_id=database.database_id,
            columns=columns,
            rows=returned_rows,
            row_count=len(returned_rows),
            truncated=truncated,
            warnings=(
                (f"Query rows were truncated to MAX_QUERY_ROWS={MAX_QUERY_ROWS}.",)
                if truncated
                else ()
            ),
        )

    def explain_query(
        self,
        database_id: str,
        sql: str,
    ) -> QueryPlanResult:
        """Validate a normal read query and obtain a bounded program-owned plan."""

        validated_sql = self._sql_validator.validate(sql)
        if validated_sql.is_explain:
            raise ExplainQueryError(
                "explain_query requires the underlying read-only query, not EXPLAIN."
            )

        database = self._registry.get(database_id)
        config = database.connection_config
        try:
            with psycopg.connect(
                config.dsn,
                connect_timeout=config.connect_timeout_seconds,
            ) as connection:
                connection.read_only = True
                with connection.cursor() as cursor:
                    cursor.execute(
                        _SET_STATEMENT_TIMEOUT_SQL,
                        (str(config.statement_timeout_ms),),
                    )
                    cursor.execute(_EXPLAIN_PREFIX + validated_sql.normalized_sql)
                    row = cursor.fetchone()
        except psycopg.errors.QueryCanceled:
            raise QueryTimeoutError(
                f"Query planning exceeded the configured statement timeout for "
                f"database {database.database_id!r}."
            ) from None
        except (psycopg.errors.UndefinedColumn, psycopg.errors.UndefinedTable):
            raise SQLObjectNotFoundError(
                "Query references a table or column that does not exist."
            ) from None
        except psycopg.errors.AmbiguousColumn:
            raise SQLAmbiguousColumnError(
                "Query contains a column reference that is ambiguous."
            ) from None
        except psycopg.errors.DatatypeMismatch:
            raise SQLTypeMismatchError(
                "Query contains incompatible PostgreSQL data types."
            ) from None
        except psycopg.errors.GroupingError:
            raise SQLGroupingError(
                "Query contains invalid grouping or aggregate semantics."
            ) from None
        except psycopg.Error:
            raise ExplainQueryError(
                f"Could not explain query for registered database "
                f"{database.database_id!r}."
            ) from None

        if row is None or len(row) != 1:
            raise ExplainQueryError("PostgreSQL returned an invalid query plan.")
        return parse_query_plan(database.database_id, row[0])


def _optional_name(value: str | None, label: str) -> str | None:
    if value is None:
        return None
    return _required_name(value, label)


def _required_name(value: str, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DatabaseMetadataError(f"{label} name cannot be empty.")
    return value.strip()


def _lookup_table(
    cursor: psycopg.Cursor[object],
    schema_name: str,
    table_name: str,
) -> tuple[int, TableType]:
    cursor.execute(LOOKUP_TABLE_SQL, (schema_name, schema_name, table_name))
    row = cursor.fetchone()
    if row is None or len(row) < 3:
        raise DatabaseMetadataError(
            "PostgreSQL returned invalid table identity metadata."
        )
    if not row[0]:
        raise SchemaNotFoundError(f"Unknown schema {schema_name!r}.")
    if row[1] is None:
        raise TableNotFoundError(
            f"Unknown table {schema_name!r}.{table_name!r}."
        )
    try:
        return int(row[1]), TableType(row[2])
    except (IndexError, TypeError, ValueError):
        raise DatabaseMetadataError(
            "PostgreSQL returned invalid table identity metadata."
        ) from None


def _inspection_warnings(
    *,
    column_truncated: bool,
    primary_key_truncated: bool,
    foreign_keys_truncated: bool,
    indexes_truncated: bool,
) -> tuple[str, ...]:
    warnings: list[str] = []
    if column_truncated:
        warnings.append(
            f"Column metadata was truncated to {MAX_TABLE_COLUMNS} entries."
        )
    if primary_key_truncated:
        warnings.append(
            f"Primary-key metadata was truncated to {MAX_TABLE_COLUMNS} columns."
        )
    if foreign_keys_truncated:
        warnings.append(
            f"Foreign-key metadata was truncated to {MAX_RELATIONSHIPS} entries."
        )
    if indexes_truncated:
        warnings.append(
            f"Index metadata was truncated to {MAX_INDEXES} entries."
        )
    return tuple(warnings)


def _query_columns(cursor: psycopg.Cursor[object]) -> tuple[str, ...]:
    description = cursor.description
    if description is None:
        raise SQLExecutionError("Read query returned no tabular result.")
    return tuple(column.name for column in description)
