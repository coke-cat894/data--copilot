import pytest

from data_copilot.databases import (
    DatabaseRegistry,
    DatabaseType,
    PostgresConnectionConfig,
)
from data_copilot.errors import (
    DatabaseConfigurationError,
    DatabaseNotFoundError,
    UnsupportedDatabaseError,
)


def _config() -> PostgresConnectionConfig:
    return PostgresConnectionConfig(
        dsn="postgresql://analyst:super-secret@db.example:5432/analytics",
        database_name="analytics",
        connect_timeout_seconds=5,
    )


def test_register_postgresql_and_get_by_opaque_id() -> None:
    registry = DatabaseRegistry()

    database = registry.register(_config(), display_name="Analytics")

    assert database.database_id.startswith("db_")
    assert len(database.database_id) == 11
    assert database.database_type is DatabaseType.POSTGRESQL
    assert database.database_name == "analytics"
    assert registry.get(database.database_id) is database


def test_duplicate_equivalent_registration_returns_existing_database() -> None:
    registry = DatabaseRegistry()

    first = registry.register(_config())
    second = registry.register(_config())

    assert second is first


def test_duplicate_config_with_different_name_fails_closed() -> None:
    registry = DatabaseRegistry()
    registry.register(_config(), display_name="Analytics")

    with pytest.raises(DatabaseConfigurationError, match="already registered"):
        registry.register(_config(), display_name="Other")


@pytest.mark.parametrize("database_id", ["db_unknown", None, 123])
def test_unknown_database_id_fails_closed(database_id: object) -> None:
    registry = DatabaseRegistry()

    with pytest.raises(DatabaseNotFoundError, match="Unknown database ID"):
        registry.get(database_id)  # type: ignore[arg-type]


def test_registry_rejects_unknown_connection_config_type() -> None:
    registry = DatabaseRegistry()

    with pytest.raises(UnsupportedDatabaseError, match="Unsupported"):
        registry.register(object())  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "config",
    [
        PostgresConnectionConfig("", "analytics", 5),
        PostgresConnectionConfig("postgresql://db.example/analytics", "", 5),
        PostgresConnectionConfig("postgresql://db.example/analytics", "analytics", 0),
        PostgresConnectionConfig(
            "postgresql://db.example/analytics", "analytics", 61
        ),
    ],
)
def test_registry_revalidates_programmatic_config(
    config: PostgresConnectionConfig,
) -> None:
    with pytest.raises(DatabaseConfigurationError):
        DatabaseRegistry().register(config)


def test_public_metadata_omits_connection_config_and_credentials() -> None:
    database = DatabaseRegistry().register(_config(), display_name="Analytics")

    public = database.to_public_metadata()
    dumped = public.model_dump()

    assert dumped == {
        "database_id": database.database_id,
        "database_type": DatabaseType.POSTGRESQL,
        "display_name": "Analytics",
    }
    assert "connection_config" not in dumped
    assert "database_name" not in dumped
    assert "super-secret" not in repr(public)
    assert "super-secret" not in repr(database)
