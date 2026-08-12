"""Agent-facing database Tool results with opaque source identity."""

from pydantic import BaseModel, ConfigDict

from data_copilot.databases import (
    ColumnMetadata,
    ForeignKeyMetadata,
    IndexMetadata,
    RelationshipMetadata,
    TableMetadata,
    TableType,
)


class ListTablesResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    database_id: str
    tables: tuple[TableMetadata, ...]
    truncated: bool
    warnings: tuple[str, ...] = ()


class InspectTableResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    database_id: str
    schema_name: str
    table_name: str
    table_type: TableType
    columns: tuple[ColumnMetadata, ...]
    primary_key: tuple[str, ...]
    foreign_keys: tuple[ForeignKeyMetadata, ...]
    basic_indexes: tuple[IndexMetadata, ...]
    truncated: bool
    warnings: tuple[str, ...] = ()


class GetRelationshipsResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    database_id: str
    schema_name: str
    table_name: str
    relationships: tuple[RelationshipMetadata, ...]
    truncated: bool
    warnings: tuple[str, ...] = ()
