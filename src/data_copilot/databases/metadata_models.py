"""Public, bounded PostgreSQL catalog metadata models."""

from enum import Enum

from pydantic import BaseModel, ConfigDict


class TableType(str, Enum):
    """Supported PostgreSQL relation kinds exposed as metadata."""

    TABLE = "table"
    PARTITIONED_TABLE = "partitioned_table"
    VIEW = "view"
    MATERIALIZED_VIEW = "materialized_view"
    FOREIGN_TABLE = "foreign_table"


class RelationshipDirection(str, Enum):
    """Direction of a declared foreign key relative to the inspected table."""

    OUTBOUND = "outbound"
    INBOUND = "inbound"


class TableMetadata(BaseModel):
    """Compact identity and type for one visible PostgreSQL relation."""

    model_config = ConfigDict(frozen=True)

    schema_name: str
    table_name: str
    table_type: TableType


class TableListResult(BaseModel):
    """Bounded table-list metadata."""

    model_config = ConfigDict(frozen=True)

    tables: tuple[TableMetadata, ...]
    truncated: bool
    warnings: tuple[str, ...] = ()


class ColumnMetadata(BaseModel):
    """Declared PostgreSQL column metadata."""

    model_config = ConfigDict(frozen=True)

    name: str
    postgres_type: str
    nullable: bool


class ForeignKeyMetadata(BaseModel):
    """One declared outbound foreign-key constraint."""

    model_config = ConfigDict(frozen=True)

    constraint_name: str
    source_columns: tuple[str, ...]
    target_schema_name: str
    target_table_name: str
    target_columns: tuple[str, ...]


class IndexMetadata(BaseModel):
    """Basic facts for one PostgreSQL index."""

    model_config = ConfigDict(frozen=True)

    index_name: str
    columns: tuple[str, ...]
    unique: bool
    primary: bool


class TableInspectionResult(BaseModel):
    """Bounded declared metadata for one schema-qualified table."""

    model_config = ConfigDict(frozen=True)

    schema_name: str
    table_name: str
    table_type: TableType
    columns: tuple[ColumnMetadata, ...]
    primary_key: tuple[str, ...]
    foreign_keys: tuple[ForeignKeyMetadata, ...]
    basic_indexes: tuple[IndexMetadata, ...]
    truncated: bool
    warnings: tuple[str, ...] = ()


class RelationshipMetadata(BaseModel):
    """One directional view of a declared PostgreSQL foreign key."""

    model_config = ConfigDict(frozen=True)

    direction: RelationshipDirection
    constraint_name: str
    source_schema_name: str
    source_table_name: str
    source_columns: tuple[str, ...]
    target_schema_name: str
    target_table_name: str
    target_columns: tuple[str, ...]


class RelationshipListResult(BaseModel):
    """Bounded declared relationships for one schema-qualified table."""

    model_config = ConfigDict(frozen=True)

    schema_name: str
    table_name: str
    relationships: tuple[RelationshipMetadata, ...]
    truncated: bool
    warnings: tuple[str, ...] = ()
