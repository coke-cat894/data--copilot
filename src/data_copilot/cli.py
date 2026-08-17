"""Minimal interactive CLI for one explicitly registered local dataset."""

import argparse
import logging
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

from data_copilot.agent import DataCopilotAgent
from data_copilot.config import (
    load_environment,
    read_llm_config,
    read_runtime_config,
)
from data_copilot.datasets import DatasetRegistry
from data_copilot.doctor import DoctorReport, inspect_environment
from data_copilot.errors import DataCopilotError
from data_copilot.llm import LLMClient, create_llm_client


InputFunction = Callable[[str], str]
OutputFunction = Callable[[str], None]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="data-copilot",
        description="Analyze one explicit CSV, Parquet, or JSONL dataset.",
        epilog=(
            "Environment self-check: data-copilot doctor [--help]. "
            "Evaluation is provided separately by data-copilot-eval."
        ),
    )
    parser.add_argument("dataset", help="Explicit local dataset file")
    return parser


def build_doctor_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="data-copilot doctor",
        description=(
            "Validate configured capabilities without contacting an LLM provider."
        ),
    )
    parser.add_argument(
        "--connect-database",
        action="store_true",
        help="Explicitly run the fixed read-only PostgreSQL connectivity check.",
    )
    parser.add_argument(
        "--semantic-source",
        type=Path,
        help="Explicit YAML file or directory to validate and load.",
    )
    parser.add_argument(
        "--document-source",
        type=Path,
        help="Explicit Markdown/text file or directory to validate and index.",
    )
    parser.add_argument(
        "--allowed-root",
        action="append",
        type=Path,
        default=[],
        help="Explicit local data root to validate; repeat for multiple roots.",
    )
    parser.add_argument(
        "--artifact-directory",
        type=Path,
        default=Path("evals/results"),
        help="Eval artifact directory to inspect without creating files.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit the bounded structured doctor report as JSON.",
    )
    return parser


def run_cli(
    argv: Sequence[str] | None = None,
    *,
    llm_client: LLMClient | None = None,
    input_fn: InputFunction = input,
    output_fn: OutputFunction = print,
) -> int:
    arguments = tuple(sys.argv[1:] if argv is None else argv)
    if arguments and arguments[0] == "doctor":
        return run_doctor_cli(arguments[1:], output_fn=output_fn)
    args = build_parser().parse_args(arguments)
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
        runtime = read_runtime_config()
        client = llm_client or create_llm_client(read_llm_config())
        agent = DataCopilotAgent(
            registry,
            dataset.dataset_id,
            client,
            max_tool_rounds=runtime.tool_budget,
            provider_retry_policy=runtime.provider_retry_policy,
        )
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


def run_doctor_cli(
    argv: Sequence[str] | None = None,
    *,
    output_fn: OutputFunction = print,
) -> int:
    args = build_doctor_parser().parse_args(argv)
    report = inspect_environment(
        connect_database=args.connect_database,
        semantic_source=args.semantic_source,
        document_source=args.document_source,
        allowed_roots=tuple(args.allowed_root),
        artifact_directory=args.artifact_directory,
    )
    if args.json:
        output_fn(report.model_dump_json(indent=2))
    else:
        _write_doctor_report(report, output_fn)
    return report.exit_code


def _write_doctor_report(
    report: DoctorReport,
    output_fn: OutputFunction,
) -> None:
    for check in report.checks:
        output_fn(f"{check.status.value.upper():7} {check.name}: {check.summary}")
    output_fn("Doctor result: " + ("FAIL" if report.exit_code else "PASS"))


def main() -> int:
    load_environment()
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s %(name)s %(message)s",
    )
    return run_cli()


if __name__ == "__main__":
    raise SystemExit(main())
