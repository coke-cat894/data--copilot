"""Minimal interactive CLI for one explicitly registered local dataset."""

import argparse
import logging
from collections.abc import Callable, Sequence
from pathlib import Path

from data_copilot.agent import DataCopilotAgent
from data_copilot.config import load_environment, read_llm_config
from data_copilot.datasets import DatasetRegistry
from data_copilot.errors import DataCopilotError
from data_copilot.llm import LLMClient, create_llm_client


InputFunction = Callable[[str], str]
OutputFunction = Callable[[str], None]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="data-copilot",
        description="Analyze one explicit CSV, Parquet, or JSONL dataset.",
    )
    parser.add_argument("dataset", help="Explicit local dataset file")
    return parser


def run_cli(
    argv: Sequence[str] | None = None,
    *,
    llm_client: LLMClient | None = None,
    input_fn: InputFunction = input,
    output_fn: OutputFunction = print,
) -> int:
    args = build_parser().parse_args(argv)
    requested_path = Path(args.dataset).expanduser()
    allowed_root = requested_path.parent.resolve(strict=False)
    try:
        registry = DatasetRegistry(allowed_roots=[allowed_root])
        dataset = registry.register(requested_path)
        public = dataset.to_public_metadata()
        output_fn(
            "Dataset registered: "
            f"{public.display_name} [{public.format.value}] ({public.dataset_id})"
        )
        client = llm_client or create_llm_client(read_llm_config())
        agent = DataCopilotAgent(registry, dataset.dataset_id, client)
    except DataCopilotError as exc:
        output_fn(f"Error: {exc}")
        return 2

    while True:
        try:
            question = input_fn("You > ")
        except (EOFError, KeyboardInterrupt):
            output_fn("Goodbye.")
            return 0
        if question.strip().lower() in {"exit", "quit"}:
            output_fn("Goodbye.")
            return 0
        if not question.strip():
            continue
        try:
            result = agent.ask(question)
        except DataCopilotError as exc:
            output_fn(f"Data Copilot error: {exc}")
            continue
        output_fn(f"Data Copilot > {result.answer}")


def main() -> int:
    load_environment()
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s %(name)s %(message)s",
    )
    return run_cli()


if __name__ == "__main__":
    raise SystemExit(main())
