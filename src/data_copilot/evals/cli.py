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
from data_copilot.documents import (
    BusinessDocumentChunker,
    BusinessDocumentIndex,
    BusinessDocumentLoader,
)
from data_copilot.errors import DataCopilotError
from data_copilot.evals.artifacts import content_fingerprint
from data_copilot.evals.loader import load_cases, load_mock_scripts
from data_copilot.evals.models import (
    EvalCase,
    EvalCategory,
    EvalMode,
    EvalReproducibility,
)
from data_copilot.evals.troubleshooting_fixtures import (
    build_troubleshooting_resources,
)
from data_copilot.evals.runner import (
    DatabaseEvalRunner,
    EvalRunner,
    format_summary,
    save_eval_run,
)
from data_copilot.llm import (
    DeepSeekLLMClient,
    FakeLLMClient,
    LLMResponse,
    create_llm_client,
)
from data_copilot.semantics import SemanticCatalogLoader


PROJECT_ROOT = Path(__file__).parents[3]
DEFAULT_CASES = PROJECT_ROOT / "evals/cases/local_foundation.jsonl"
DEFAULT_DATABASE_CASES = PROJECT_ROOT / "evals/cases/database_phase_2.jsonl"
DEFAULT_PHASE3_CASES = PROJECT_ROOT / "evals/cases/semantic_rag_phase_3.jsonl"
DEFAULT_PHASE4_CASES = PROJECT_ROOT / "evals/cases/troubleshooting_phase_4.jsonl"
DEFAULT_PHASE5_CASES = PROJECT_ROOT / "evals/cases/final_phase_5.jsonl"
DEFAULT_PHASE3_SEMANTICS = PROJECT_ROOT / "evals/fixtures/phase_3_semantic"
DEFAULT_PHASE3_DOCUMENTS = PROJECT_ROOT / "evals/fixtures/phase_3_documents"
DEFAULT_MOCK_SCRIPTS = PROJECT_ROOT / "evals/fixtures/mock_responses.jsonl"
DEFAULT_RESULTS = PROJECT_ROOT / "evals/results"
PHASE4_CLOSURE_CASE_IDS = (
    "row_count_drop_pipeline_match",
    "null_spike_unknown_cause",
    "data_drift_healthy_pipeline",
    "conflicting_pipeline_database_evidence",
    "missing_baseline",
    "missing_semantic_business_metric",
)
PHASE4_FINAL_TWO_CASE_IDS = (
    "row_count_drop_pipeline_match",
    "null_spike_unknown_cause",
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="data-copilot-eval")
    parser.add_argument("--mode", choices=("mock", "live", "safety"), required=True)
    parser.add_argument(
        "--target",
        choices=("dataset", "database", "phase3", "phase4", "phase5"),
        default="dataset",
    )
    parser.add_argument("--cases", type=Path)
    parser.add_argument("--mock-scripts", type=Path, default=DEFAULT_MOCK_SCRIPTS)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_RESULTS)
    parser.add_argument("--case-id", action="append", default=[])
    parser.add_argument(
        "--phase4-closure-focused",
        action="store_true",
        help="Select only the six approved Phase 4.5 closure cases.",
    )
    parser.add_argument(
        "--phase4-final-two",
        action="store_true",
        help="Select only the two final Phase 4.5 closure blockers.",
    )
    parser.add_argument(
        "--approve-phase4-external-data",
        action="store_true",
        help=(
            "Confirm explicit approval for the one-shot Phase 4 synthetic "
            "external-provider evaluation."
        ),
    )
    parser.add_argument(
        "--approve-phase5-external-data",
        action="store_true",
        help=(
            "Confirm explicit approval for the one-shot Phase 5.5 synthetic "
            "external-provider evaluation."
        ),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        default_cases = {
            "dataset": DEFAULT_CASES,
            "database": DEFAULT_DATABASE_CASES,
            "phase3": DEFAULT_PHASE3_CASES,
            "phase4": DEFAULT_PHASE4_CASES,
            "phase5": DEFAULT_PHASE5_CASES,
        }
        if args.target == "phase5" and args.cases is not None:
            raise EvalCliError(
                "Phase 5.5 uses the frozen final case file; --cases is unavailable."
            )
        if args.target == "phase5" and args.mode != "live":
            raise EvalCliError("Phase 5.5 target requires live mode.")
        cases_path = args.cases or default_cases[args.target]
        loaded_cases = load_cases(cases_path)
        if args.phase4_closure_focused or args.phase4_final_two:
            if (
                args.target != "phase4"
                or args.case_id
                or (args.phase4_closure_focused and args.phase4_final_two)
            ):
                raise EvalCliError(
                    "Focused Phase 4 selection requires target phase4 and exactly "
                    "one focused selector without case IDs."
                )
            cases = _select_cases(
                loaded_cases,
                list(
                    PHASE4_CLOSURE_CASE_IDS
                    if args.phase4_closure_focused
                    else PHASE4_FINAL_TWO_CASE_IDS
                ),
            )
        else:
            cases = _select_cases(loaded_cases, args.case_id)
        git_commit, git_dirty = _git_state(PROJECT_ROOT)
        secrets: tuple[str, ...] = ()
        if args.mode == "mock":
            if args.target != "dataset":
                raise EvalCliError(
                    "Database-backed eval does not use scripted mock mode."
                )
            scripts = load_mock_scripts(args.mock_scripts)
            _require_scripts(cases, scripts)
            client_factory = lambda case: FakeLLMClient(scripts[case.case_id])
            provider, model = "mock", "fake-llm"
        else:
            if (
                args.target == "phase4"
                and not args.approve_phase4_external_data
            ):
                raise EvalCliError(
                    "Phase 4 live eval requires explicit synthetic-data approval."
                )
            if (
                args.target == "phase5"
                and not args.approve_phase5_external_data
            ):
                raise EvalCliError(
                    "Phase 5.5 live eval requires explicit synthetic-data approval."
                )
            load_environment()
            config = read_llm_config()
            if (
                args.target in {"phase3", "phase4", "phase5"}
                and config.provider != "deepseek"
            ):
                raise EvalCliError(
                    "Phase 3/4/5 live eval requires the DeepSeek provider."
                )
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
            if args.target in {"phase4", "phase5"}:
                client_factory = lambda _case: DeepSeekLLMClient(
                    model=config.model,
                    api_key=config.api_key,
                    base_url=config.base_url,
                    max_retries=0,
                )
            else:
                client_factory = lambda _case: create_llm_client(config)

        if args.target in {"database", "phase3", "phase4", "phase5"}:
            database_config = read_postgres_config()
            registry = DatabaseRegistry()
            database = registry.register(
                database_config,
                display_name=(
                    "Phase 3 Semantic + RAG Eval"
                    if args.target == "phase3"
                    else (
                        "Phase 4 Troubleshooting Eval"
                        if args.target == "phase4"
                        else (
                            "Phase 5.5 Final Eval"
                            if args.target == "phase5"
                            else "Phase 2 Database Eval"
                        )
                    )
                ),
            )
            secrets = secrets + (database_config.dsn,)
            semantic_catalog = None
            document_index = None
            if args.target in {"phase3", "phase4", "phase5"}:
                semantic_catalog = SemanticCatalogLoader(
                    DEFAULT_PHASE3_SEMANTICS
                ).load()
                if args.target in {"phase3", "phase5"}:
                    documents = BusinessDocumentLoader(DEFAULT_PHASE3_DOCUMENTS).load()
                    document_index = BusinessDocumentIndex(
                        BusinessDocumentChunker().chunk(documents)
                    )
            runner = DatabaseEvalRunner(
                registry=registry,
                database_id=database.database_id,
                client_factory=client_factory,
                semantic_catalog=semantic_catalog,
                document_index=document_index,
                troubleshooting_resources_factory=(
                    build_troubleshooting_resources
                    if args.target in {"phase4", "phase5"}
                    else None
                ),
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
            reproducibility=EvalReproducibility(
                eval_mode=EvalMode(args.mode),
                suite=cases_path.name,
                selector=tuple(case.case_id for case in cases),
                tool_budget=5,
                provider_max_retries=(
                    0
                    if args.target in {"phase4", "phase5"}
                    and args.mode != "mock"
                    else None
                ),
                prompt_fingerprint=content_fingerprint(
                    _prompt_paths(args.target)
                ),
                scorer_fingerprint=content_fingerprint(
                    (PROJECT_ROOT / "src/data_copilot/evals/scoring.py",)
                ),
                fixture_fingerprint=content_fingerprint(
                    _fixture_paths(
                        args.target,
                        cases_path,
                        args.mock_scripts if args.mode == "mock" else None,
                    )
                ),
            ),
        )
        output_path = args.output_dir / _result_name(
            run.timestamp,
            provider,
            model,
            run.run_id,
        )
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


def _result_name(
    timestamp: datetime,
    provider: str,
    model: str,
    run_id: str | None = None,
) -> str:
    def safe(value: str) -> str:
        return re.sub(r"[^a-zA-Z0-9._-]+", "-", value)

    stamp = timestamp.strftime("%Y%m%dT%H%M%SZ")
    unique = f"-{safe(run_id)[-12:]}" if run_id else ""
    return f"{stamp}-{safe(provider)}-{safe(model)}{unique}.json"


def _prompt_paths(target: str) -> tuple[Path, ...]:
    prompt_root = PROJECT_ROOT / "src/data_copilot/prompts"
    if target == "dataset":
        return (prompt_root / "system.md",)
    paths = [prompt_root / "database_system.md"]
    if target in {"phase4", "phase5"}:
        paths.append(prompt_root / "troubleshooting.md")
    return tuple(paths)


def _fixture_paths(
    target: str,
    cases_path: Path,
    mock_scripts: Path | None,
) -> tuple[Path, ...]:
    paths = [cases_path]
    if mock_scripts is not None:
        paths.append(mock_scripts)
    if target in {"phase3", "phase4", "phase5"}:
        paths.extend(sorted(DEFAULT_PHASE3_SEMANTICS.glob("*.yaml")))
    if target in {"phase3", "phase5"}:
        paths.extend(
            sorted(
                path
                for path in DEFAULT_PHASE3_DOCUMENTS.iterdir()
                if path.is_file()
            )
        )
    if target in {"phase4", "phase5"}:
        paths.append(PROJECT_ROOT / "src/data_copilot/evals/troubleshooting_fixtures.py")
    return tuple(paths)


if __name__ == "__main__":
    raise SystemExit(main())
