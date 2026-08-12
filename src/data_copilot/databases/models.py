"""Typed internal and public models for registered databases."""

from dataclasses import dataclass, field
from enum import Enum

from pydantic import BaseModel, ConfigDict


class DatabaseType(str, Enum):
    """Database types explicitly supported in Phase 2.1."""

    POSTGRESQL = "postgresql"


@dataclass(frozen=True)
class PostgresConnectionConfig:
    """Internal PostgreSQL credentials and deterministic connection limits."""

    dsn: str = field(repr=False)
    database_name: str
    connect_timeout_seconds: int
    statement_timeout_ms: int = 15000


class PublicDatabaseMetadata(BaseModel):
    """Database metadata safe for a future Agent-facing boundary."""

    model_config = ConfigDict(frozen=True)

    database_id: str
    database_type: DatabaseType
    display_name: str


@dataclass(frozen=True)
class Database:
    """Internal registered database, including program-only connection data."""

    database_id: str
    database_type: DatabaseType
    database_name: str
    display_name: str
    connection_config: PostgresConnectionConfig = field(repr=False)

    def to_public_metadata(self) -> PublicDatabaseMetadata:
        """Return metadata that deliberately omits all connection details."""

        return PublicDatabaseMetadata(
            database_id=self.database_id,
            database_type=self.database_type,
            display_name=self.display_name,
        )
