from pathlib import Path

import pytest

from data_copilot.config import (
    LLMProviderConfig,
    load_environment,
    read_llm_config,
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
        "DATA_COPILOT_PROVIDER=deepseek\n\n"
        "DEEPSEEK_API_KEY=your_deepseek_api_key_here\n"
        "DEEPSEEK_BASE_URL=https://api.deepseek.com\n"
        "DATA_COPILOT_MODEL=deepseek-v4-flash\n\n"
        "# Optional OpenAI configuration\n"
        "OPENAI_API_KEY=your_openai_api_key_here\n"
    )
