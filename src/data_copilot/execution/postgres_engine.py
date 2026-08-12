"""Minimal read-only PostgreSQL connectivity through opaque database IDs."""

import psycopg
from pydantic import BaseModel, ConfigDict

from data_copilot.databases import DatabaseRegistry, DatabaseType
from data_copilot.errors import DatabaseConnectionError


_HEALTH_CHECK_SQL = "SELECT 1"


class PostgresPingResult(BaseModel):
    """Compact result of the program-owned PostgreSQL health check."""

    model_config = ConfigDict(frozen=True)

    connected: bool
    database_type: DatabaseType
    database_name: str


class PostgresEngine:
    """Connect to registered PostgreSQL databases; never execute caller SQL."""

    def __init__(self, registry: DatabaseRegistry) -> None:
        self._registry = registry

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
