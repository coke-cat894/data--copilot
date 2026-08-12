from pathlib import Path

import pytest

from data_copilot.config import read_postgres_config
from data_copilot.errors import DatabaseConfigurationError


DSN = "postgresql://analyst:super-secret@db.example:5432/analytics"


def test_valid_postgres_config_is_typed_and_bounded() -> None:
    config = read_postgres_config(
        {
            "DATA_COPILOT_POSTGRES_DSN": DSN,
            "POSTGRES_CONNECT_TIMEOUT_SECONDS": "7",
        }
    )

    assert config.dsn == DSN
    assert config.database_name == "analytics"
    assert config.connect_timeout_seconds == 7
    assert "super-secret" not in repr(config)


def test_postgres_config_uses_small_default_timeout() -> None:
    config = read_postgres_config({"DATA_COPILOT_POSTGRES_DSN": DSN})

    assert config.connect_timeout_seconds == 5
    assert config.statement_timeout_ms == 15000


@pytest.mark.parametrize(
    "values",
    [
        {},
        {"DATA_COPILOT_POSTGRES_DSN": ""},
        {"DATA_COPILOT_POSTGRES_DSN": "postgresql://db.example"},
        {
            "DATA_COPILOT_POSTGRES_DSN": DSN,
            "POSTGRES_CONNECT_TIMEOUT_SECONDS": "0",
        },
        {
            "DATA_COPILOT_POSTGRES_DSN": DSN,
            "POSTGRES_CONNECT_TIMEOUT_SECONDS": "61",
        },
        {
            "DATA_COPILOT_POSTGRES_DSN": DSN,
            "POSTGRES_CONNECT_TIMEOUT_SECONDS": "five",
        },
        {
            "DATA_COPILOT_POSTGRES_DSN": DSN,
            "POSTGRES_STATEMENT_TIMEOUT_MS": "0",
        },
        {
            "DATA_COPILOT_POSTGRES_DSN": DSN,
            "POSTGRES_STATEMENT_TIMEOUT_MS": "120001",
        },
        {
            "DATA_COPILOT_POSTGRES_DSN": DSN,
            "POSTGRES_STATEMENT_TIMEOUT_MS": "slow",
        },
    ],
)
def test_missing_or_invalid_postgres_config_fails_closed(
    values: dict[str, str],
) -> None:
    with pytest.raises(DatabaseConfigurationError) as captured:
        read_postgres_config(values)

    assert "super-secret" not in str(captured.value)
    assert "super-secret" not in repr(captured.value)


def test_env_example_contains_postgres_placeholders_without_real_credentials() -> None:
    example = Path(__file__).parents[1].joinpath(".env.example").read_text(
        encoding="utf-8"
    )

    assert (
        "DATA_COPILOT_POSTGRES_DSN="
        "postgresql://username:password@localhost:5432/database_name"
    ) in example
    assert "POSTGRES_CONNECT_TIMEOUT_SECONDS=5" in example
    assert "POSTGRES_STATEMENT_TIMEOUT_MS=15000" in example
    assert "super-secret" not in example
