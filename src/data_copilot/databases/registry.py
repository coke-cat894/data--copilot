"""Explicit, in-memory registration of PostgreSQL connections."""

import secrets

from data_copilot.databases.constants import MAX_POSTGRES_CONNECT_TIMEOUT_SECONDS
from data_copilot.databases.models import (
    Database,
    DatabaseType,
    PostgresConnectionConfig,
)
from data_copilot.errors import (
    DatabaseConfigurationError,
    DatabaseNotFoundError,
    UnsupportedDatabaseError,
)


class DatabaseRegistry:
    """Register PostgreSQL configuration and resolve opaque database IDs."""

    def __init__(self) -> None:
        self._databases: dict[str, Database] = {}
        self._database_ids_by_config: dict[PostgresConnectionConfig, str] = {}

    def register(
        self,
        connection_config: PostgresConnectionConfig,
        *,
        display_name: str | None = None,
    ) -> Database:
        """Register one validated PostgreSQL config, deduplicating exact matches."""

        if not isinstance(connection_config, PostgresConnectionConfig):
            raise UnsupportedDatabaseError("Unsupported database type.")
        if not connection_config.dsn.strip():
            raise DatabaseConfigurationError("PostgreSQL DSN cannot be empty.")
        if not connection_config.database_name.strip():
            raise DatabaseConfigurationError("Database name cannot be empty.")
        if not (
            1
            <= connection_config.connect_timeout_seconds
            <= MAX_POSTGRES_CONNECT_TIMEOUT_SECONDS
        ):
            raise DatabaseConfigurationError(
                "PostgreSQL connect timeout is outside the allowed range."
            )
        resolved_display_name = (
            connection_config.database_name
            if display_name is None
            else display_name.strip()
        )
        if not resolved_display_name:
            raise DatabaseConfigurationError("Database display name cannot be empty.")

        existing_id = self._database_ids_by_config.get(connection_config)
        if existing_id is not None:
            existing = self._databases[existing_id]
            if existing.display_name != resolved_display_name:
                raise DatabaseConfigurationError(
                    "Equivalent database configuration is already registered "
                    "with a different display name."
                )
            return existing

        database = Database(
            database_id=self._new_database_id(),
            database_type=DatabaseType.POSTGRESQL,
            database_name=connection_config.database_name,
            display_name=resolved_display_name,
            connection_config=connection_config,
        )
        self._databases[database.database_id] = database
        self._database_ids_by_config[connection_config] = database.database_id
        return database

    def get(self, database_id: str) -> Database:
        """Resolve one opaque database ID without accepting connection details."""

        if not isinstance(database_id, str):
            raise DatabaseNotFoundError("Unknown database ID.")
        database = self._databases.get(database_id)
        if database is None:
            raise DatabaseNotFoundError("Unknown database ID.")
        return database

    def _new_database_id(self) -> str:
        while True:
            database_id = f"db_{secrets.token_hex(4)}"
            if database_id not in self._databases:
                return database_id
