"""Sequential dataset/database evaluation and safe result persistence."""

from collections.abc import Callable, Sequence
from datetime import UTC, datetime
import json
from pathlib import Path
from time import perf_counter
from uuid import uuid4

from data_copilot.agent import AgentResult, DataCopilotAgent
from data_copilot.database_agent import DatabaseCopilotAgent
from data_copilot.databases import DatabaseRegistry
from data_copilot.datasets import DatasetRegistry
from data_copilot.documents import BusinessDocumentIndex
from data_copilot.diagnostics import TroubleshootingResources
from data_copilot.errors import DataCopilotError
from data_copilot.evals.artifacts import EvalPersistenceError, save_eval_run
from data_copilot.evals.models import (
    EvidenceChannel,
    EvalCase,
    EvalMetricDetail,
    EvalMode,
    EvalReproducibility,
    EvalResult,
    EvalRun,
    EvalTrace,
    EvalTraceEvent,
    MetricStatus,
)
from data_copilot.evals.scoring import (
    classify_automatic_failure,
    explain_case_scores,
    score_behavioral_safety,
    score_case,
    summarize,
)
from data_copilot.evals.trace import (
    ObservableLLMClient,
    bounded_evidence_summary,
    build_safe_trace,
    content_channel,
    sanitize_tool_arguments,
)
from data_copilot.llm import LLMClient, LLMRole
from data_copilot.execution import PostgresEngine
from data_copilot.semantics import SemanticCatalog
from data_copilot.runtime import (
    ProviderRetryPolicy,
    RunOutcome,
    RuntimeStage,
    classify_runtime_failure,
)


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

    def run_case(
        self,
        case: EvalCase,
        *,
        run_id: str | None = None,
        provider: str | None = None,
        model: str | None = None,
        eval_mode: EvalMode = EvalMode.DETERMINISTIC,
        provider_retries: int = 0,
    ) -> EvalResult:
        agent: DataCopilotAgent | None = None
        capture: ObservableLLMClient | None = None

        def run() -> AgentResult:
            nonlocal agent, capture
            if case.dataset is None:
                raise EvalPathError("Dataset eval case requires a dataset source.")
            dataset_path = self._resolve_dataset(case.dataset)
            registry = DatasetRegistry(allowed_roots=[dataset_path.parent])
            dataset = registry.register(dataset_path)
            capture = ObservableLLMClient(self._client_factory(case))
            agent = DataCopilotAgent(
                registry,
                dataset.dataset_id,
                capture,
                provider_retry_policy=ProviderRetryPolicy(
                    max_retries=provider_retries
                ),
            )
            return agent.ask(case.question)

        return _run_case(
            case,
            run,
            lambda: _tool_trace(agent),
            lambda: _evidence_trace(agent),
            lambda: _observable_trace(agent),
            lambda **state: build_safe_trace(
                case_id=case.case_id,
                question=case.question,
                messages=agent.messages if agent is not None else (),
                decisions=capture.decisions if capture is not None else (),
                provider_attempts=capture.attempts if capture is not None else (),
                run_id=run_id,
                provider=provider,
                model=model,
                eval_mode=eval_mode,
                provider_error_category=state.pop(
                    "runtime_error_category",
                    capture.failure_category if capture is not None else None,
                ),
                provider_error_message=state.pop(
                    "runtime_error_message",
                    capture.failure_message if capture is not None else None,
                ),
                **state,
            ),
        )

    def run(
        self,
        cases: Sequence[EvalCase],
        *,
        provider: str,
        model: str,
        git_commit: str | None = None,
        git_dirty: bool | None = None,
        reproducibility: EvalReproducibility | None = None,
    ) -> EvalRun:
        timestamp = datetime.now(UTC)
        run_id = _new_run_id(timestamp)
        configuration = reproducibility or EvalReproducibility()
        results = tuple(
            self.run_case(
                case,
                run_id=run_id,
                provider=provider,
                model=model,
                eval_mode=configuration.eval_mode,
                provider_retries=configuration.provider_max_retries or 0,
            )
            for case in cases
        )
        return EvalRun(
            run_id=run_id,
            provider=provider,
            model=model,
            timestamp=timestamp,
            git_commit=git_commit,
            git_dirty=git_dirty,
            reproducibility=configuration,
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
        semantic_catalog: SemanticCatalog | None = None,
        document_index: BusinessDocumentIndex | None = None,
        troubleshooting_resources_factory: Callable[
            [EvalCase], TroubleshootingResources | None
        ] | None = None,
    ) -> None:
        registry.get(database_id)
        self._registry = registry
        self._database_id = database_id
        self._client_factory = client_factory
        self._engine = engine
        self._semantic_catalog = semantic_catalog
        self._document_index = document_index
        self._troubleshooting_resources_factory = troubleshooting_resources_factory

    def run_case(
        self,
        case: EvalCase,
        *,
        run_id: str | None = None,
        provider: str | None = None,
        model: str | None = None,
        eval_mode: EvalMode = EvalMode.DETERMINISTIC,
        provider_retries: int = 0,
    ) -> EvalResult:
        agent: DatabaseCopilotAgent | None = None
        capture: ObservableLLMClient | None = None

        def run() -> AgentResult:
            nonlocal agent, capture
            if case.database is None:
                raise EvalPathError("Database eval case requires a database source.")
            capture = ObservableLLMClient(self._client_factory(case))
            agent = DatabaseCopilotAgent(
                self._registry,
                self._database_id,
                capture,
                engine=self._engine,
                semantic_catalog=self._semantic_catalog,
                document_index=self._document_index,
                troubleshooting_resources=(
                    self._troubleshooting_resources_factory(case)
                    if self._troubleshooting_resources_factory is not None
                    else None
                ),
                provider_retry_policy=ProviderRetryPolicy(
                    max_retries=provider_retries
                ),
            )
            return agent.ask(case.question)

        return _run_case(
            case,
            run,
            lambda: _tool_trace(agent),
            lambda: _evidence_trace(agent),
            lambda: _observable_trace(agent),
            lambda **state: build_safe_trace(
                case_id=case.case_id,
                question=case.question,
                messages=agent.messages if agent is not None else (),
                decisions=capture.decisions if capture is not None else (),
                provider_attempts=capture.attempts if capture is not None else (),
                run_id=run_id,
                provider=provider,
                model=model,
                eval_mode=eval_mode,
                provider_error_category=state.pop(
                    "runtime_error_category",
                    capture.failure_category if capture is not None else None,
                ),
                provider_error_message=state.pop(
                    "runtime_error_message",
                    capture.failure_message if capture is not None else None,
                ),
                **state,
            ),
        )

    def run(
        self,
        cases: Sequence[EvalCase],
        *,
        provider: str,
        model: str,
        git_commit: str | None = None,
        git_dirty: bool | None = None,
        reproducibility: EvalReproducibility | None = None,
    ) -> EvalRun:
        timestamp = datetime.now(UTC)
        run_id = _new_run_id(timestamp)
        configuration = reproducibility or EvalReproducibility()
        return _make_run(
            tuple(
                self.run_case(
                    case,
                    run_id=run_id,
                    provider=provider,
                    model=model,
                    eval_mode=configuration.eval_mode,
                    provider_retries=configuration.provider_max_retries or 0,
                )
                for case in cases
            ),
            run_id=run_id,
            provider=provider,
            model=model,
            git_commit=git_commit,
            git_dirty=git_dirty,
            timestamp=timestamp,
            reproducibility=configuration,
        )


class EvalPathError(DataCopilotError):
    """Raised when an eval case references an unsafe dataset path."""


def _run_case(
    case: EvalCase,
    run_agent: Callable[[], AgentResult],
    tool_trace: Callable[[], tuple[str, ...]],
    evidence_trace: Callable[[], tuple[EvidenceChannel, ...]],
    observable_trace: Callable[[], tuple[EvalTraceEvent, ...]],
    safe_trace: Callable[..., EvalTrace],
) -> EvalResult:
    started = perf_counter()
    answer: str | None = None
    rounds = 0
    usage = None
    runtime_errors: list[str] = []
    runtime_failure_category: str | None = None
    runtime_failure_message: str | None = None
    agent_result: AgentResult | None = None
    try:
        agent_result = run_agent()
        answer = agent_result.answer
        rounds = agent_result.rounds
        usage = agent_result.usage
    except DataCopilotError as exc:
        stage = (
            RuntimeStage.FINAL_SYNTHESIS
            if type(exc).__name__ == "FinalSynthesisError"
            else RuntimeStage.PROVIDER_DECISION
        )
        failure = classify_runtime_failure(exc, stage=stage)
        runtime_failure_category = failure.category.value
        runtime_failure_message = failure.safe_message
        runtime_errors.append(
            f"{type(exc).__name__}: {failure.category.value}: "
            f"{failure.safe_message}"
        )
    actual_tools = tool_trace()
    evidence_channels = evidence_trace()
    trace = observable_trace()
    checks, metric_failures = score_case(
        case, answer, actual_tools, evidence_channels
    )
    task_errors = list(runtime_errors)
    if not checks.answer_requirements:
        task_errors.append("Failed task check: answer_requirements.")
    if not checks.forbidden_claims:
        task_errors.append("Failed task check: forbidden_claims.")
    for channel in case.expected_evidence_channels:
        field = f"{channel.value}_grounding"
        if getattr(checks, field) is False:
            task_errors.append(f"Failed task check: {field}.")
    for field in (
        "causal_discipline",
        "uncertainty_handling",
        "conflict_handling",
    ):
        if getattr(checks, field) is False:
            task_errors.append(f"Failed task check: {field}.")
    forbidden_tools_used = set(actual_tools) & set(case.forbidden_tools)
    if forbidden_tools_used:
        task_errors.append("Failed task check: forbidden_tool_used.")
    safety_passed = None
    if case.category.value == "safety":
        if not runtime_errors or answer is not None:
            safety_passed = score_behavioral_safety(case, answer, actual_tools)
    passed = not task_errors
    latency_ms = (perf_counter() - started) * 1000
    metric_details = list(
        explain_case_scores(
            case,
            answer,
            actual_tools,
            evidence_channels,
            checks,
            safety_passed=safety_passed,
        )
    )
    metric_details.insert(
        0,
        EvalMetricDetail(
            metric_name="task_success",
            status=MetricStatus.PASS if passed else MetricStatus.FAIL,
            missing_requirements=tuple(task_errors[:50]),
            scorer_note=(
                "Task Success is derived from runtime completion and applicable "
                "answer/grounding requirements, not from efficiency or unrelated metrics."
            ),
        ),
    )
    metric_details.append(
        EvalMetricDetail(
            metric_name="no_answer_uncertainty",
            status=(
                MetricStatus.NOT_APPLICABLE
                if case.category.value != "no_answer"
                else MetricStatus.PASS if passed else MetricStatus.FAIL
            ),
            scorer_note="Applicable only to cases explicitly categorized as no-answer.",
        )
    )
    automatic_classification = classify_automatic_failure(
        passed=passed,
        checks=checks,
        runtime_errors=tuple(runtime_errors),
        safety_passed=safety_passed,
    )
    safety_rejection = any(
        "UnsafeSQLError" in event.evidence_summary
        or "SQLValidationError" in event.evidence_summary
        for event in trace
    )
    unresolved_tool_failure = bool(
        trace and trace[-1].evidence_summary.startswith("tool_error ")
    )
    terminal_no_answer_errors = {
        "SemanticNotFoundError",
        "SemanticAmbiguityError",
        "DiagnosticComparisonUnavailableError",
    }
    last_tool_error = (
        trace[-1].evidence_summary.removeprefix("tool_error type=")
        if unresolved_tool_failure
        else None
    )
    if safety_rejection:
        run_outcome = RunOutcome.SAFETY_REJECTION
    elif (
        case.category.value == "no_answer"
        and not runtime_errors
        and (
            not unresolved_tool_failure
            or last_tool_error in terminal_no_answer_errors
        )
    ):
        run_outcome = RunOutcome.SAFE_NO_ANSWER
    elif runtime_errors or unresolved_tool_failure:
        run_outcome = (
            RunOutcome.PARTIAL
            if evidence_channels
            else RunOutcome.RUNTIME_FAILURE
        )
    else:
        run_outcome = RunOutcome.SUCCESS
    full_trace = safe_trace(
        answer=answer,
        outcome=run_outcome,
        usage=usage,
        latency_ms=latency_ms,
        tool_call_count=len(actual_tools),
        rounds=rounds,
        runtime_error_category=runtime_failure_category,
        runtime_error_message=runtime_failure_message,
    )
    return EvalResult(
        case_id=case.case_id,
        category=case.category,
        question=full_trace.original_question,
        passed=passed,
        safety_passed=safety_passed,
        answer=(
            full_trace.final_answer.response
            if full_trace.final_answer is not None
            else None
        ),
        tool_calls=actual_tools,
        tool_call_count=len(actual_tools),
        rounds=rounds,
        latency_ms=latency_ms,
        expected_tools=case.expected_tools,
        actual_tools=actual_tools,
        evidence_channels=evidence_channels,
        checks=checks,
        answer_check_applicable=bool(
            case.expected_values
            or case.expected_columns
            or case.answer_requirements
            or case.answer_requirement_groups
        ),
        grounding_check_applicable=bool(
            case.answer_forbidden_claims
            or case.expected_evidence_channels
            or case.semantic_grounding_requirements
            or case.semantic_grounding_answer_requirements
            or case.document_grounding_requirements
            or case.data_grounding_requirements
            or case.diagnostic_grounding_requirements
            or case.pipeline_grounding_requirements
        ),
        usage=usage,
        errors=tuple(task_errors),
        metric_failures=metric_failures,
        metric_details=tuple(metric_details),
        notes=(case.expected_behavior,),
        needs_human_grounding_review=case.needs_human_grounding_review,
        trace=trace,
        safe_trace=full_trace,
        automatic_failure_classification=automatic_classification,
    )


def _make_run(
    results: tuple[EvalResult, ...],
    *,
    run_id: str,
    provider: str,
    model: str,
    git_commit: str | None,
    git_dirty: bool | None,
    timestamp: datetime,
    reproducibility: EvalReproducibility,
) -> EvalRun:
    return EvalRun(
        run_id=run_id,
        provider=provider,
        model=model,
        timestamp=timestamp,
        git_commit=git_commit,
        git_dirty=git_dirty,
        reproducibility=reproducibility,
        results=results,
        summary=summarize(results),
    )


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
        f"Semantic Grounding: {_percent(summary.semantic_grounding_accuracy)}",
        f"Document Grounding: {_percent(summary.document_grounding_accuracy)}",
        f"Data Grounding: {_percent(summary.data_grounding_accuracy)}",
        f"Diagnostic Grounding: {_percent(summary.diagnostic_grounding_accuracy)}",
        f"Pipeline Grounding: {_percent(summary.pipeline_grounding_accuracy)}",
        f"Causal Discipline: {_percent(summary.causal_discipline_accuracy)}",
        f"Uncertainty Handling: {_percent(summary.uncertainty_handling_accuracy)}",
        f"Conflict Handling: {_percent(summary.conflict_handling_accuracy)}",
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
    tool_messages = {
        message.tool_call_id: message
        for message in agent.messages
        if message.role is LLMRole.TOOL and message.tool_call_id is not None
    }
    return tuple(
        call.name
        for message in agent.messages
        if message.role is LLMRole.ASSISTANT
        for call in message.tool_calls
        if call.call_id in tool_messages
        and not (tool_messages[call.call_id].content or "").startswith(
            "EVIDENCE_REUSE\n"
        )
        and _tool_message_was_executed(tool_messages[call.call_id].content or "")
    )


def _tool_message_was_executed(content: str) -> bool:
    if not content.startswith("TOOL_ERROR\n"):
        return True
    try:
        payload = json.loads(content.split("\n", 1)[1])
    except (json.JSONDecodeError, IndexError):
        return True
    return not isinstance(payload, dict) or payload.get("tool_executed") is not False


def _evidence_trace(
    agent: DataCopilotAgent | DatabaseCopilotAgent | None,
) -> tuple[EvidenceChannel, ...]:
    if agent is None:
        return ()
    prefixes = {
        "SEMANTIC_EVIDENCE\n": EvidenceChannel.SEMANTIC,
        "DOCUMENT_EVIDENCE\n": EvidenceChannel.DOCUMENT,
        "DATA_EVIDENCE\n": EvidenceChannel.DATA,
        "DIAGNOSTIC_EVIDENCE\n": EvidenceChannel.DIAGNOSTIC,
        "PIPELINE_EVIDENCE\n": EvidenceChannel.PIPELINE,
    }
    observed: list[EvidenceChannel] = []
    for message in agent.messages:
        if message.role is not LLMRole.TOOL or message.content is None:
            continue
        for prefix, channel in prefixes.items():
            if message.content.startswith(prefix) and channel not in observed:
                observed.append(channel)
    return tuple(observed)


def _observable_trace(
    agent: DataCopilotAgent | DatabaseCopilotAgent | None,
) -> tuple[EvalTraceEvent, ...]:
    if agent is None:
        return ()
    messages = agent.messages
    trace: list[EvalTraceEvent] = []
    executed_count = 0
    for index, message in enumerate(messages):
        if len(trace) >= 5:
            break
        if message.role is not LLMRole.ASSISTANT or not message.tool_calls:
            continue
        call = message.tool_calls[0]
        tool_message = next(
            (
                candidate
                for candidate in messages[index + 1 :]
                if candidate.role is LLMRole.TOOL
                and candidate.tool_call_id == call.call_id
            ),
            None,
        )
        content = tool_message.content if tool_message is not None else ""
        if _tool_message_was_executed(content or ""):
            executed_count += 1
        channel = content_channel(content or "")
        round_number = len(trace) + 1
        trace.append(
            EvalTraceEvent(
                round_number=round_number,
                remaining_tool_budget=max(0, 5 - executed_count),
                tool_name=call.name[:128],
                sanitized_arguments=sanitize_tool_arguments(call.arguments),
                evidence_channel=channel,
                evidence_summary=bounded_evidence_summary(content or "")[0],
            )
        )
    return tuple(trace)


def _new_run_id(timestamp: datetime) -> str:
    return f"eval-{timestamp.strftime('%Y%m%dT%H%M%SZ')}-{uuid4().hex[:12]}"


def _percent(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.1%}"
