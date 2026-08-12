"""Explicit mock, live, and live-safety evaluation entry point."""

import argparse
import re
import subprocess
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

from data_copilot.config import (
    load_environment,
    read_llm_config,
    read_postgres_config,
)
from data_copilot.databases import DatabaseRegistry
from data_copilot.errors import DataCopilotError
from data_copilot.evals.loader import load_cases, load_mock_scripts
from data_copilot.evals.models import EvalCase, EvalCategory
from data_copilot.evals.runner import (
    DatabaseEvalRunner,
    EvalRunner,
    format_summary,
    save_eval_run,
)
from data_copilot.llm import FakeLLMClient, LLMResponse, create_llm_client


PROJECT_ROOT = Path(__file__).parents[3]
DEFAULT_CASES = PROJECT_ROOT / "evals/cases/local_foundation.jsonl"
DEFAULT_DATABASE_CASES = PROJECT_ROOT / "evals/cases/database_phase_2.jsonl"
DEFAULT_MOCK_SCRIPTS = PROJECT_ROOT / "evals/fixtures/mock_responses.jsonl"
DEFAULT_RESULTS = PROJECT_ROOT / "evals/results"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="data-copilot-eval")
    parser.add_argument("--mode", choices=("mock", "live", "safety"), required=True)
    parser.add_argument("--target", choices=("dataset", "database"), default="dataset")
    parser.add_argument("--cases", type=Path)
    parser.add_argument("--mock-scripts", type=Path, default=DEFAULT_MOCK_SCRIPTS)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_RESULTS)
    parser.add_argument("--case-id", action="append", default=[])
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        cases_path = args.cases or (
            DEFAULT_DATABASE_CASES if args.target == "database" else DEFAULT_CASES
        )
        cases = _select_cases(load_cases(cases_path), args.case_id)
        git_commit, git_dirty = _git_state(PROJECT_ROOT)
        secrets: tuple[str, ...] = ()
        if args.mode == "mock":
            if args.target == "database":
                raise EvalCliError("Database eval does not use scripted mock mode.")
            scripts = load_mock_scripts(args.mock_scripts)
            _require_scripts(cases, scripts)
            client_factory = lambda case: FakeLLMClient(scripts[case.case_id])
            provider, model = "mock", "fake-llm"
        else:
            load_environment()
            config = read_llm_config()
            if args.mode == "safety":
                cases = tuple(
                    case for case in cases if case.category is EvalCategory.SAFETY
                )
                if not cases:
                    raise EvalCliError("No safety cases were selected.")
            provider, model = config.provider, config.model
            secrets = (config.api_key,)
            print(
                f"Live evaluation: provider={provider} model={model} "
                f"cases={len(cases)}",
                flush=True,
            )
            client_factory = lambda _case: create_llm_client(config)

        if args.target == "database":
            database_config = read_postgres_config()
            registry = DatabaseRegistry()
            database = registry.register(
                database_config,
                display_name="Phase 2 Database Eval",
            )
            secrets = secrets + (database_config.dsn,)
            runner = DatabaseEvalRunner(
                registry=registry,
                database_id=database.database_id,
                client_factory=client_factory,
            )
        else:
            runner = EvalRunner(
                project_root=PROJECT_ROOT,
                client_factory=client_factory,
            )
        run = runner.run(
            cases,
            provider=provider,
            model=model,
            git_commit=git_commit,
            git_dirty=git_dirty,
        )
        output_path = args.output_dir / _result_name(run.timestamp, provider, model)
        save_eval_run(run, output_path, secret_values=secrets)
        print(format_summary(run))
        print(f"Result: {output_path}")
        return 0 if run.summary.failed == 0 else 1
    except DataCopilotError as exc:
        print(f"Eval error: {exc}")
        return 2


class EvalCliError(DataCopilotError):
    pass


def _select_cases(
    cases: tuple[EvalCase, ...], selected_ids: list[str]
) -> tuple[EvalCase, ...]:
    if not selected_ids:
        return cases
    selected = set(selected_ids)
    unknown = selected - {case.case_id for case in cases}
    if unknown:
        raise EvalCliError("Unknown eval case ID.")
    return tuple(case for case in cases if case.case_id in selected)


def _require_scripts(
    cases: tuple[EvalCase, ...],
    scripts: dict[str, tuple[LLMResponse, ...]],
) -> None:
    if any(case.case_id not in scripts for case in cases):
        raise EvalCliError("A selected mock case has no scripted responses.")


def _git_state(root: Path) -> tuple[str | None, bool | None]:
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        dirty = bool(
            subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=root,
                check=True,
                capture_output=True,
                text=True,
            ).stdout
        )
        return commit, dirty
    except (OSError, subprocess.SubprocessError):
        return None, None


def _result_name(timestamp: datetime, provider: str, model: str) -> str:
    def safe(value: str) -> str:
        return re.sub(r"[^a-zA-Z0-9._-]+", "-", value)

    stamp = timestamp.strftime("%Y%m%dT%H%M%SZ")
    return f"{stamp}-{safe(provider)}-{safe(model)}.json"


if __name__ == "__main__":
    raise SystemExit(main())
