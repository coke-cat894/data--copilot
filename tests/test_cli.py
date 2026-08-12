from collections.abc import Iterator
from pathlib import Path

from data_copilot.cli import run_cli
from data_copilot.llm import FakeLLMClient, LLMResponse


def _input(values: list[str]) -> tuple[Iterator[str], object]:
    iterator = iter(values)
    return iterator, lambda _prompt: next(iterator)


def test_cli_registers_dataset_answers_one_question_and_exits(
    sample_files: dict[str, Path],
) -> None:
    client = FakeLLMClient([LLMResponse(text="There are three rows.")])
    outputs: list[str] = []
    _, input_fn = _input(["How many rows?", "exit"])

    exit_code = run_cli(
        [str(sample_files["csv"])],
        llm_client=client,
        input_fn=input_fn,
        output_fn=outputs.append,
    )

    assert exit_code == 0
    assert outputs[0].startswith("Dataset registered: sample.csv [csv] (ds_")
    assert outputs[1] == "Data Copilot > There are three rows."
    assert outputs[2] == "Goodbye."
    assert str(sample_files["csv"].resolve()) not in "\n".join(outputs)


def test_cli_quit_does_not_call_llm(sample_files: dict[str, Path]) -> None:
    client = FakeLLMClient([])
    outputs: list[str] = []
    _, input_fn = _input(["quit"])

    exit_code = run_cli(
        [str(sample_files["parquet"])],
        llm_client=client,
        input_fn=input_fn,
        output_fn=outputs.append,
    )

    assert exit_code == 0
    assert client.requests == []
    assert outputs[-1] == "Goodbye."


def test_cli_handles_eof(sample_files: dict[str, Path]) -> None:
    outputs: list[str] = []

    def end_of_input(_prompt: str) -> str:
        raise EOFError

    exit_code = run_cli(
        [str(sample_files["jsonl"])],
        llm_client=FakeLLMClient([]),
        input_fn=end_of_input,
        output_fn=outputs.append,
    )

    assert exit_code == 0
    assert outputs[-1] == "Goodbye."


def test_cli_handles_missing_dataset_without_path_leak(tmp_path: Path) -> None:
    missing = tmp_path / "private-name.csv"
    outputs: list[str] = []

    exit_code = run_cli(
        [str(missing)],
        llm_client=FakeLLMClient([]),
        output_fn=outputs.append,
    )

    assert exit_code == 2
    assert outputs == ["Error: Dataset file does not exist or cannot be resolved."]
    assert str(missing) not in outputs[0]


def test_cli_handles_unsupported_format_safely(tmp_path: Path) -> None:
    unsupported = tmp_path / "dataset.json"
    unsupported.write_text("[]", encoding="utf-8")
    outputs: list[str] = []

    exit_code = run_cli(
        [str(unsupported)],
        llm_client=FakeLLMClient([]),
        output_fn=outputs.append,
    )

    assert exit_code == 2
    assert outputs == [
        "Error: Unsupported dataset format; expected CSV, Parquet, or JSONL."
    ]
    assert str(unsupported) not in outputs[0]
