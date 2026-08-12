"""Sequential dataset/database evaluation and safe result persistence."""

from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter

from data_copilot.agent import AgentResult, DataCopilotAgent
from data_copilot.database_agent import DatabaseCopilotAgent
from data_copilot.databases import DatabaseRegistry
from data_copilot.datasets import DatasetRegistry
from data_copilot.errors import DataCopilotError
from data_copilot.evals.models import EvalCase, EvalResult, EvalRun
from data_copilot.evals.scoring import score_case, summarize
from data_copilot.llm import LLMClient, LLMRole
from data_copilot.execution import PostgresEngine


LLMClientFactory = Callable[[EvalCase], LLMClient]


class EvalRunner:
    """Run cases one at a time through the real Agent architecture."""

    def __init__(
        self,
        *,
        project_root: Path,
        client_factory: LLMClientFactory,
    ) -> None:
        self._project_root = project_root.resolve()
        self._client_factory = client_factory

    def run_case(self, case: EvalCase) -> EvalResult:
        agent: DataCopilotAgent | None = None

        def run() -> AgentResult:
            nonlocal agent
            if case.dataset is None:
                raise EvalPathError("Dataset eval case requires a dataset source.")
            dataset_path = self._resolve_dataset(case.dataset)
            registry = DatasetRegistry(allowed_roots=[dataset_path.parent])
            dataset = registry.register(dataset_path)
            agent = DataCopilotAgent(
                registry,
                dataset.dataset_id,
                self._client_factory(case),
            )
            return agent.ask(case.question)

        return _run_case(case, run, lambda: _tool_trace(agent))

    def run(
        self,
        cases: Sequence[EvalCase],
        *,
        provider: str,
        model: str,
        git_commit: str | None = None,
        git_dirty: bool | None = None,
    ) -> EvalRun:
        results = tuple(self.run_case(case) for case in cases)
        return EvalRun(
            provider=provider,
            model=model,
            timestamp=datetime.now(UTC),
            git_commit=git_commit,
            git_dirty=git_dirty,
            results=results,
            summary=summarize(results),
        )

    def _resolve_dataset(self, dataset: str) -> Path:
        candidate = (self._project_root / dataset).resolve()
        if not candidate.is_relative_to(self._project_root):
            raise EvalPathError("Eval dataset must remain inside the project root.")
        if not candidate.is_file():
            raise EvalPathError("Eval dataset is missing or is not a file.")
        return candidate


class DatabaseEvalRunner:
    """Run database cases through one program-bound registered database."""

    def __init__(
        self,
        *,
        registry: DatabaseRegistry,
        database_id: str,
        client_factory: LLMClientFactory,
        engine: PostgresEngine | None = None,
    ) -> None:
        registry.get(database_id)
        self._registry = registry
        self._database_id = database_id
        self._client_factory = client_factory
        self._engine = engine

    def run_case(self, case: EvalCase) -> EvalResult:
        agent: DatabaseCopilotAgent | None = None

        def run() -> AgentResult:
            nonlocal agent
            if case.database is None:
                raise EvalPathError("Database eval case requires a database source.")
            agent = DatabaseCopilotAgent(
                self._registry,
                self._database_id,
                self._client_factory(case),
                engine=self._engine,
            )
            return agent.ask(case.question)

        return _run_case(case, run, lambda: _tool_trace(agent))

    def run(
        self,
        cases: Sequence[EvalCase],
        *,
        provider: str,
        model: str,
        git_commit: str | None = None,
        git_dirty: bool | None = None,
    ) -> EvalRun:
        return _make_run(
            tuple(self.run_case(case) for case in cases),
            provider=provider,
            model=model,
            git_commit=git_commit,
            git_dirty=git_dirty,
        )


class EvalPathError(DataCopilotError):
    """Raised when an eval case references an unsafe dataset path."""


def _run_case(
    case: EvalCase,
    run_agent: Callable[[], AgentResult],
    tool_trace: Callable[[], tuple[str, ...]],
) -> EvalResult:
    started = perf_counter()
    answer: str | None = None
    rounds = 0
    usage = None
    runtime_errors: list[str] = []
    try:
        outcome = run_agent()
        answer = outcome.answer
        rounds = outcome.rounds
        usage = outcome.usage
    except DataCopilotError as exc:
        runtime_errors.append(f"{type(exc).__name__}: {exc}")
    actual_tools = tool_trace()
    checks, metric_failures = score_case(case, answer, actual_tools)
    task_errors = list(runtime_errors)
    if not checks.answer_requirements:
        task_errors.append("Failed task check: answer_requirements.")
    if not checks.forbidden_claims:
        task_errors.append("Failed task check: forbidden_claims.")
    forbidden_tools_used = set(actual_tools) & set(case.forbidden_tools)
    if forbidden_tools_used:
        task_errors.append("Failed task check: forbidden_tool_used.")
    safety_passed = None
    if case.category.value == "safety":
        safety_passed = (
            not runtime_errors
            and checks.answer_requirements
            and checks.forbidden_claims
            and not forbidden_tools_used
        )
    return EvalResult(
        case_id=case.case_id,
        category=case.category,
        question=case.question,
        passed=not task_errors,
        safety_passed=safety_passed,
        answer=answer,
        tool_calls=actual_tools,
        tool_call_count=len(actual_tools),
        rounds=rounds,
        latency_ms=(perf_counter() - started) * 1000,
        expected_tools=case.expected_tools,
        actual_tools=actual_tools,
        checks=checks,
        answer_check_applicable=bool(
            case.expected_values
            or case.expected_columns
            or case.answer_requirements
            or case.answer_requirement_groups
        ),
        grounding_check_applicable=bool(case.answer_forbidden_claims),
        usage=usage,
        errors=tuple(task_errors),
        metric_failures=metric_failures,
        notes=(case.expected_behavior,),
        needs_human_grounding_review=case.needs_human_grounding_review,
    )


def _make_run(
    results: tuple[EvalResult, ...],
    *,
    provider: str,
    model: str,
    git_commit: str | None,
    git_dirty: bool | None,
) -> EvalRun:
    return EvalRun(
        provider=provider,
        model=model,
        timestamp=datetime.now(UTC),
        git_commit=git_commit,
        git_dirty=git_dirty,
        results=results,
        summary=summarize(results),
    )


def save_eval_run(
    run: EvalRun,
    output_path: Path,
    *,
    secret_values: Sequence[str] = (),
) -> None:
    """Persist one result atomically after checking configured secrets."""

    serialized = run.model_dump_json(indent=2)
    for secret in secret_values:
        if secret and secret in serialized:
            raise EvalPersistenceError("Eval result contains a configured secret.")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_suffix(output_path.suffix + ".tmp")
    try:
        temporary.write_text(serialized + "\n", encoding="utf-8")
        temporary.replace(output_path)
    except OSError as exc:
        raise EvalPersistenceError("Eval result could not be written safely.") from exc


class EvalPersistenceError(DataCopilotError):
    """Raised when a structured eval result cannot be persisted safely."""


def format_summary(run: EvalRun) -> str:
    summary = run.summary
    lines = [
        f"Cases: {summary.cases}",
        f"Passed: {summary.passed}",
        f"Failed: {summary.failed}",
        f"Task Success: {_percent(summary.task_success_rate)}",
        f"Tool Selection: {_percent(summary.tool_selection_accuracy)}",
        f"Answer Accuracy: {_percent(summary.answer_accuracy)}",
        f"Grounding: {_percent(summary.grounding_accuracy)}",
        f"No-answer: {_percent(summary.no_answer_accuracy)}",
        f"Safety: {_percent(summary.safety_pass_rate)}",
        f"Efficiency: {_percent(summary.efficiency_accuracy)}",
        f"Average Tool Calls: {summary.average_tool_calls:.2f}",
        f"Average Rounds: {summary.average_rounds:.2f}",
        f"Average Latency: {summary.average_latency_ms:.2f} ms",
        f"Tokens: {summary.total_tokens if summary.total_tokens is not None else 'n/a'}",
        f"Needs Human Review: {summary.needs_human_review}",
    ]
    failed = [result for result in run.results if not result.passed]
    if failed:
        lines.append("Failures:")
        lines.extend(
            f"- {result.case_id}: {'; '.join(result.errors)}"
            for result in failed
        )
    metric_misses = [result for result in run.results if result.metric_failures]
    if metric_misses:
        lines.append("Metric misses:")
        lines.extend(
            f"- {result.case_id}: {'; '.join(result.metric_failures)}"
            for result in metric_misses
        )
    return "\n".join(lines)


def _tool_trace(
    agent: DataCopilotAgent | DatabaseCopilotAgent | None,
) -> tuple[str, ...]:
    if agent is None:
        return ()
    return tuple(
        call.name
        for message in agent.messages
        if message.role is LLMRole.ASSISTANT
        for call in message.tool_calls
    )


def _percent(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.1%}"
