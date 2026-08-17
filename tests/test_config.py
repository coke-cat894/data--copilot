from pathlib import Path

import pytest

from data_copilot.config import (
    LLMProviderConfig,
    RuntimeConfig,
    load_environment,
    read_llm_config,
    read_runtime_config,
)
from data_copilot.errors import ConfigurationError, LLMClientError
from data_copilot.llm import (
    DeepSeekLLMClient,
    OpenAILLMClient,
    create_llm_client,
)


def test_dotenv_configuration_loads_without_real_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dotenv_path = tmp_path / ".env"
    dotenv_path.write_text(
        "DATA_COPILOT_PROVIDER=deepseek\n"
        "DEEPSEEK_API_KEY=test-dotenv-key\n"
        "DATA_COPILOT_MODEL=deepseek-v4-flash\n",
        encoding="utf-8",
    )
    for name in (
        "DATA_COPILOT_PROVIDER",
        "DEEPSEEK_API_KEY",
        "DATA_COPILOT_MODEL",
    ):
        monkeypatch.delenv(name, raising=False)

    assert load_environment(dotenv_path) is True

    config = read_llm_config()
    assert config.provider == "deepseek"
    assert config.model == "deepseek-v4-flash"
    assert config.api_key == "test-dotenv-key"
    assert config.base_url == "https://api.deepseek.com"


def test_existing_environment_overrides_dotenv(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dotenv_path = tmp_path / ".env"
    dotenv_path.write_text(
        "DATA_COPILOT_PROVIDER=deepseek\n"
        "DEEPSEEK_API_KEY=dotenv-key\n"
        "DATA_COPILOT_MODEL=dotenv-model\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("DATA_COPILOT_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    monkeypatch.setenv("DATA_COPILOT_MODEL", "external-model")

    assert load_environment(dotenv_path) is True

    config = read_llm_config()
    assert config.provider == "openai"
    assert config.model == "external-model"
    assert config.api_key == "test-openai-key"


@pytest.mark.parametrize(
    ("values", "missing_name"),
    [
        ({}, "DATA_COPILOT_PROVIDER"),
        (
            {
                "DATA_COPILOT_PROVIDER": "deepseek",
                "DATA_COPILOT_MODEL": "deepseek-v4-flash",
            },
            "DEEPSEEK_API_KEY",
        ),
        (
            {
                "DATA_COPILOT_PROVIDER": "openai",
                "DATA_COPILOT_MODEL": "test-model",
            },
            "OPENAI_API_KEY",
        ),
        (
            {
                "DATA_COPILOT_PROVIDER": "openai",
                "OPENAI_API_KEY": "test-key",
            },
            "DATA_COPILOT_MODEL",
        ),
    ],
)
def test_missing_provider_configuration_fails_closed(
    values: dict[str, str], missing_name: str
) -> None:
    with pytest.raises(ConfigurationError, match=missing_name):
        read_llm_config(values)


def test_invalid_model_and_unknown_provider_fail_closed() -> None:
    with pytest.raises(ConfigurationError, match="DATA_COPILOT_MODEL"):
        read_llm_config(
            {
                "DATA_COPILOT_PROVIDER": "openai",
                "DATA_COPILOT_MODEL": "invalid model",
                "OPENAI_API_KEY": "test-key",
            }
        )
    with pytest.raises(ConfigurationError, match="must be one of"):
        read_llm_config(
            {
                "DATA_COPILOT_PROVIDER": "other",
                "DATA_COPILOT_MODEL": "test-model",
            }
        )


@pytest.mark.parametrize(
    "base_url",
    (
        "not-a-url",
        "ftp://api.example.test",
        "https://user:password@api.example.test",
        "https://api.example.test?token=value",
        "https://api.example.test#fragment",
        "https://api example.test",
        "https://:443",
        "https://api.example.test:99999",
        "https://[invalid",
    ),
)
def test_invalid_provider_base_url_fails_closed(base_url: str) -> None:
    with pytest.raises(ConfigurationError, match="DEEPSEEK_BASE_URL"):
        read_llm_config(
            {
                "DATA_COPILOT_PROVIDER": "deepseek",
                "DATA_COPILOT_MODEL": "deepseek-v4-flash",
                "DEEPSEEK_API_KEY": "test-key",
                "DEEPSEEK_BASE_URL": base_url,
            }
        )


@pytest.mark.parametrize("value", ("-1", "3", "many", "1.5"))
def test_runtime_retry_configuration_fails_closed(value: str) -> None:
    with pytest.raises(ConfigurationError, match="PROVIDER_MAX_RETRIES"):
        read_runtime_config({"DATA_COPILOT_PROVIDER_MAX_RETRIES": value})


def test_runtime_configuration_has_fixed_tool_budget_and_bounded_retries() -> None:
    default = read_runtime_config({})
    disabled = read_runtime_config({"DATA_COPILOT_PROVIDER_MAX_RETRIES": "0"})

    assert isinstance(default, RuntimeConfig)
    assert default.tool_budget == 5
    assert default.provider_retry_policy.max_retries == 1
    assert disabled.provider_retry_policy.max_retries == 0


def test_provider_selection_creates_only_explicit_adapter() -> None:
    openai_client = create_llm_client(
        LLMProviderConfig("openai", "test-model", "test-openai-key")
    )
    deepseek_client = create_llm_client(
        LLMProviderConfig(
            "deepseek",
            "deepseek-v4-flash",
            "test-deepseek-key",
            "https://api.deepseek.com",
        )
    )

    assert isinstance(openai_client, OpenAILLMClient)
    assert isinstance(deepseek_client, DeepSeekLLMClient)

    with pytest.raises(LLMClientError, match="Unsupported"):
        create_llm_client(
            LLMProviderConfig("other", "test-model", "test-key")
        )


def test_provider_configuration_repr_does_not_expose_key() -> None:
    config = LLMProviderConfig("openai", "test-model", "sensitive-test-key")

    assert "sensitive-test-key" not in repr(config)


def test_env_example_contains_only_documented_placeholders() -> None:
    example = Path(__file__).parents[1].joinpath(".env.example").read_text(
        encoding="utf-8"
    )

    assert example == (
        "# Configure only the capabilities you intend to use.\n"
        "DATA_COPILOT_PROVIDER_MAX_RETRIES=1\n\n"
        "# Optional provider-backed Agent (DeepSeek example)\n"
        "# DATA_COPILOT_PROVIDER=deepseek\n"
        "# DATA_COPILOT_MODEL=deepseek-v4-flash\n"
        "# DEEPSEEK_API_KEY=your-key-here\n"
        "# DEEPSEEK_BASE_URL=https://api.deepseek.com\n\n"
        "# Used only when DATA_COPILOT_PROVIDER=openai\n"
        "# OPENAI_API_KEY=your-key-here\n\n"
        "# Optional PostgreSQL capability; replace the placeholder locally.\n"
        "# DATA_COPILOT_POSTGRES_DSN=your-postgresql-dsn-here\n"
        "# POSTGRES_CONNECT_TIMEOUT_SECONDS=5\n"
        "# POSTGRES_STATEMENT_TIMEOUT_MS=15000\n"
    )
