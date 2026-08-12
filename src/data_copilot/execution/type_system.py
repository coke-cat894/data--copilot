"""Small DuckDB physical-to-logical type classification."""

from data_copilot.execution.models import LogicalColumnType


_NUMERIC_TYPES = {
    "TINYINT",
    "SMALLINT",
    "INTEGER",
    "BIGINT",
    "HUGEINT",
    "UTINYINT",
    "USMALLINT",
    "UINTEGER",
    "UBIGINT",
    "UHUGEINT",
    "FLOAT",
    "DOUBLE",
    "REAL",
}

_CATEGORICAL_TYPES = {
    "VARCHAR",
    "CHAR",
    "BPCHAR",
    "TEXT",
    "UUID",
}

_TEMPORAL_TYPES = {
    "DATE",
    "TIME",
    "TIME WITH TIME ZONE",
    "TIMESTAMP",
    "TIMESTAMP WITH TIME ZONE",
    "TIMESTAMP_S",
    "TIMESTAMP_MS",
    "TIMESTAMP_NS",
}


def classify_duckdb_type(duckdb_type: str) -> LogicalColumnType:
    """Classify common scalar DuckDB types and fail safe to OTHER."""

    normalized_type = duckdb_type.upper()
    if normalized_type.endswith("[]"):
        return LogicalColumnType.OTHER
    if (
        normalized_type in _NUMERIC_TYPES
        or normalized_type == "DECIMAL"
        or normalized_type.startswith("DECIMAL(")
    ):
        return LogicalColumnType.NUMERIC
    if normalized_type == "BOOLEAN":
        return LogicalColumnType.BOOLEAN
    if normalized_type in _TEMPORAL_TYPES:
        return LogicalColumnType.DATETIME
    if normalized_type in _CATEGORICAL_TYPES or normalized_type.startswith("ENUM("):
        return LogicalColumnType.CATEGORICAL
    return LogicalColumnType.OTHER
