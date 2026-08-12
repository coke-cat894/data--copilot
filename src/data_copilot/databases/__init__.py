"""Safe PostgreSQL registration models and boundaries."""

from data_copilot.databases.models import (
    Database,
    DatabaseType,
    PostgresConnectionConfig,
    PublicDatabaseMetadata,
)
from data_copilot.databases.metadata_models import (
    ColumnMetadata,
    ForeignKeyMetadata,
    IndexMetadata,
    RelationshipDirection,
    RelationshipListResult,
    RelationshipMetadata,
    TableInspectionResult,
    TableListResult,
    TableMetadata,
    TableType,
)
from data_copilot.databases.registry import DatabaseRegistry
from data_copilot.databases.query_models import DatabaseQueryResult
from data_copilot.databases.plan_models import QueryPlanNode, QueryPlanResult

__all__ = [
    "Database",
    "DatabaseRegistry",
    "DatabaseQueryResult",
    "DatabaseType",
    "ColumnMetadata",
    "ForeignKeyMetadata",
    "IndexMetadata",
    "PostgresConnectionConfig",
    "PublicDatabaseMetadata",
    "QueryPlanNode",
    "QueryPlanResult",
    "RelationshipDirection",
    "RelationshipListResult",
    "RelationshipMetadata",
    "TableInspectionResult",
    "TableListResult",
    "TableMetadata",
    "TableType",
]
