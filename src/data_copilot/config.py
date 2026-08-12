"""Small, deterministic configuration constants and LLM bootstrap."""

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

from data_copilot.databases.constants import (
    DEFAULT_POSTGRES_CONNECT_TIMEOUT_SECONDS,
    DEFAULT_POSTGRES_STATEMENT_TIMEOUT_MS,
    MAX_POSTGRES_CONNECT_TIMEOUT_SECONDS,
    MAX_POSTGRES_STATEMENT_TIMEOUT_MS,
    POSTGRES_CONNECT_TIMEOUT_ENV_VAR,
    POSTGRES_DSN_ENV_VAR,
    POSTGRES_STATEMENT_TIMEOUT_ENV_VAR,
)
from data_copilot.databases.models import PostgresConnectionConfig
from data_copilot.errors import ConfigurationError, DatabaseConfigurationError

try:
    from psycopg.conninfo import conninfo_to_dict
    from psycopg.errors import ProgrammingError
except ImportError:  # pragma: no cover - installation integrity guard
    conninfo_to_dict = None
    ProgrammingError = Exception

MAX_PROFILE_COLUMNS = 50
DEFAULT_TOP_VALUES = 10
MAX_TOP_VALUES = 20

DEFAULT_SAMPLE_ROWS = 20
MAX_SAMPLE_ROWS = 100

DEFAULT_RESULT_ROWS = 50
MAX_RESULT_ROWS = 200
MAX_RESULT_COLUMNS = 50

MAX_GROUP_BY_DIMENSIONS = 5
MAX_METRICS = 10
MAX_FILTERS = 20

MAX_QUALITY_COLUMNS = 50

MAX_EVIDENCE_ROWS = 100
MAX_EVIDENCE_COLUMNS = 30
MAX_CELL_CHARS = 1000
MAX_EVIDENCE_CHARS = 30000

MAX_TOOL_ROUNDS = 5
DEFAULT_MODEL = "gpt-5.6-terra"
DEFAULT_DEEPSEEK_MODEL = "deepseek-v4-flash"
DEFAULT_DEEPSEEK_BASE_URL = "https://api.deepseek.com"
PROVIDER_ENV_VAR = "DATA_COPILOT_PROVIDER"
MODEL_ENV_VAR = "DATA_COPILOT_MODEL"
OPENAI_API_KEY_ENV_VAR = "OPENAI_API_KEY"
DEEPSEEK_API_KEY_ENV_VAR = "DEEPSEEK_API_KEY"
DEEPSEEK_BASE_URL_ENV_VAR = "DEEPSEEK_BASE_URL"


@dataclass(frozen=True)
class LLMProviderConfig:
    """Validated configuration for exactly one supported provider."""

    provider: str
    model: str
    api_key: str = field(repr=False)
    base_url: str | None = None


def load_environment(dotenv_path: str | Path | None = None) -> bool:
    """Load one .env file without overriding the existing process environment."""

    if dotenv_path is None:
        return load_dotenv(override=False)
    return load_dotenv(dotenv_path=dotenv_path, override=False)


def read_llm_config(
    environ: Mapping[str, str] | None = None,
) -> LLMProviderConfig:
    """Read and validate the selected provider without implicit fallback."""

    values = os.environ if environ is None else environ
    provider = _required(values, PROVIDER_ENV_VAR).lower()
    if provider not in {"openai", "deepseek"}:
        raise ConfigurationError(
            f"{PROVIDER_ENV_VAR} must be one of: openai, deepseek."
        )
    model = _required(values, MODEL_ENV_VAR)
    if any(character.isspace() for character in model):
        raise ConfigurationError(f"{MODEL_ENV_VAR} is invalid.")

    if provider == "openai":
        return LLMProviderConfig(
            provider=provider,
            model=model,
            api_key=_required(values, OPENAI_API_KEY_ENV_VAR),
        )

    base_url = values.get(
        DEEPSEEK_BASE_URL_ENV_VAR, DEFAULT_DEEPSEEK_BASE_URL
    ).strip()
    if not base_url:
        raise ConfigurationError(
            f"{DEEPSEEK_BASE_URL_ENV_VAR} cannot be empty."
        )
    return LLMProviderConfig(
        provider=provider,
        model=model,
        api_key=_required(values, DEEPSEEK_API_KEY_ENV_VAR),
        base_url=base_url,
    )


def read_postgres_config(
    environ: Mapping[str, str] | None = None,
) -> PostgresConnectionConfig:
    """Read one PostgreSQL connection without exposing credentials in errors."""

    values = os.environ if environ is None else environ
    dsn = _required_database_value(values, POSTGRES_DSN_ENV_VAR)
    timeout_value = values.get(
        POSTGRES_CONNECT_TIMEOUT_ENV_VAR,
        str(DEFAULT_POSTGRES_CONNECT_TIMEOUT_SECONDS),
    ).strip()
    try:
        connect_timeout_seconds = int(timeout_value)
    except ValueError:
        raise DatabaseConfigurationError(
            f"{POSTGRES_CONNECT_TIMEOUT_ENV_VAR} must be an integer."
        ) from None
    if not 1 <= connect_timeout_seconds <= MAX_POSTGRES_CONNECT_TIMEOUT_SECONDS:
        raise DatabaseConfigurationError(
            f"{POSTGRES_CONNECT_TIMEOUT_ENV_VAR} must be between 1 and "
            f"{MAX_POSTGRES_CONNECT_TIMEOUT_SECONDS}."
        )
    statement_timeout_ms = _bounded_int(
        values,
        POSTGRES_STATEMENT_TIMEOUT_ENV_VAR,
        default=DEFAULT_POSTGRES_STATEMENT_TIMEOUT_MS,
        maximum=MAX_POSTGRES_STATEMENT_TIMEOUT_MS,
    )

    if conninfo_to_dict is None:
        raise DatabaseConfigurationError(
            "The PostgreSQL driver is not installed."
        )
    try:
        connection_parameters = conninfo_to_dict(dsn)
    except (ProgrammingError, TypeError, ValueError):
        raise DatabaseConfigurationError(
            f"{POSTGRES_DSN_ENV_VAR} is invalid."
        ) from None
    database_name = connection_parameters.get("dbname", "").strip()
    if not database_name:
        raise DatabaseConfigurationError(
            f"{POSTGRES_DSN_ENV_VAR} must include a database name."
        )

    return PostgresConnectionConfig(
        dsn=dsn,
        database_name=database_name,
        connect_timeout_seconds=connect_timeout_seconds,
        statement_timeout_ms=statement_timeout_ms,
    )


def _required(values: Mapping[str, str], name: str) -> str:
    value = values.get(name)
    if value is None or not value.strip():
        raise ConfigurationError(f"{name} is not configured.")
    return value.strip()


def _required_database_value(values: Mapping[str, str], name: str) -> str:
    value = values.get(name)
    if value is None or not value.strip():
        raise DatabaseConfigurationError(f"{name} is not configured.")
    return value.strip()


def _bounded_int(
    values: Mapping[str, str],
    name: str,
    *,
    default: int,
    maximum: int,
) -> int:
    raw_value = values.get(name, str(default)).strip()
    try:
        value = int(raw_value)
    except ValueError:
        raise DatabaseConfigurationError(f"{name} must be an integer.") from None
    if not 1 <= value <= maximum:
        raise DatabaseConfigurationError(
            f"{name} must be between 1 and {maximum}."
        )
    return value
