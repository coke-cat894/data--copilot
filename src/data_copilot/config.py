"""Small, deterministic configuration constants and LLM bootstrap."""

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

from data_copilot.errors import ConfigurationError

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


def _required(values: Mapping[str, str], name: str) -> str:
    value = values.get(name)
    if value is None or not value.strip():
        raise ConfigurationError(f"{name} is not configured.")
    return value.strip()
