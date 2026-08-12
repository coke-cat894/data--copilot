from pathlib import Path

from data_copilot.agent import DataCopilotAgent
from data_copilot.config import (
    MAX_EVIDENCE_CHARS,
    MAX_EVIDENCE_COLUMNS,
    MAX_EVIDENCE_ROWS,
    MAX_TOOL_ROUNDS,
)
from data_copilot.datasets import DatasetRegistry
from data_copilot.llm import (
    FakeLLMClient,
    LLMResponse,
    LLMToolCall,
)
from data_copilot.tools.dispatcher import ToolDispatcher


PROJECT_ROOT = Path(__file__).parents[1]
SIX_TOOLS = {
    "inspect_dataset",
    "profile_dataset",
    "sample_dataset",
    "filter_dataset",
    "aggregate_dataset",
    "check_data_quality",
}


def _registry() -> tuple[DatasetRegistry, str, Path]:
    path = PROJECT_ROOT / "tests/fixtures/orders_demo.csv"
    registry = DatasetRegistry(allowed_roots=[path.parent])
    dataset = registry.register(path)
    return registry, dataset.dataset_id, path.resolve()


def test_phase_1_capability_boundary_remains_exactly_six_pathless_tools() -> None:
    registry, dataset_id, _ = _registry()
    dispatcher = ToolDispatcher(registry, dataset_id)

    assert dispatcher.allowed_tool_names == SIX_TOOLS
    assert {schema.name for schema in dispatcher.schemas} == SIX_TOOLS
    serialized = " ".join(
        schema.model_dump_json() for schema in dispatcher.schemas
    ).casefold()
    for forbidden in (
        '"path"',
        '"sql"',
        "execute_python",
        "shell",
        "mutation",
        "write_dataset",
    ):
        assert forbidden not in serialized


def test_initial_and_inspection_context_exclude_raw_rows_paths_and_sql() -> None:
    registry, dataset_id, resolved_path = _registry()
    client = FakeLLMClient(
        [
            LLMResponse(
                tool_calls=(
                    LLMToolCall(
                        call_id="call_1",
                        name="inspect_dataset",
                        arguments="{}",
                    ),
                )
            ),
            LLMResponse(text="48 rows and 6 columns."),
        ]
    )
    agent = DataCopilotAgent(registry, dataset_id, client)

    agent.ask("How many rows?")

    transcript = "\n".join(
        message.content or ""
        for request, _tools in client.requests
        for message in request
    )
    assert str(resolved_path) not in transcript
    assert "ORD-001" not in transcript
    assert "SELECT " not in transcript.upper()
    assert "DATA_EVIDENCE" in transcript


def test_phase_1_limits_are_still_bounded() -> None:
    assert MAX_TOOL_ROUNDS == 5
    assert MAX_EVIDENCE_ROWS == 100
    assert MAX_EVIDENCE_COLUMNS == 30
    assert MAX_EVIDENCE_CHARS == 30000


def test_env_and_result_secret_safety_rules_are_present() -> None:
    gitignore = (PROJECT_ROOT / ".gitignore").read_text(encoding="utf-8")
    example = (PROJECT_ROOT / ".env.example").read_text(encoding="utf-8")

    assert ".env\n" in gitignore
    assert ".env.*" in gitignore
    assert "!.env.example" in gitignore
    assert "your_deepseek_api_key_here" in example
    assert "your_openai_api_key_here" in example
    assert "sk-" not in example
