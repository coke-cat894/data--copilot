"""The bounded single-dataset Data Copilot Agent Tool loop."""

import json
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from importlib.resources import files
from time import perf_counter

from pydantic import BaseModel, ConfigDict

from data_copilot.config import MAX_TOOL_ROUNDS
from data_copilot.datasets.registry import DatasetRegistry
from data_copilot.errors import (
    AgentExecutionError,
    DataCopilotError,
    FinalSynthesisError,
    LLMClientError,
    LLMFatalError,
    LLMMalformedResponseError,
    LLMTransientError,
)
from data_copilot.evidence import EvidenceBuilder, EvidenceFormatter
from data_copilot.llm import (
    LLMClient,
    LLMMessage,
    LLMResponse,
    LLMRole,
    LLMUsage,
)
from data_copilot.llm.models import ToolDefinition
from data_copilot.tools.dispatcher import ToolDispatcher
from data_copilot.runtime import (
    ProviderRetryPolicy,
    RuntimeFailure,
    RuntimeStage,
    classify_runtime_failure,
    is_nonexecuting_tool_failure,
)


logger = logging.getLogger(__name__)


_FINAL_SYNTHESIS_INSTRUCTION = (
    "The Tool-call budget is exhausted. Produce the final answer now using only "
    "the metadata, DATA_EVIDENCE, and safe Tool errors already in this "
    "conversation. If a required field, dimension, measure, relationship, or "
    "derivation input is missing, give a clean no-answer that identifies what is "
    "missing; do not substitute a different concept. Do not request, simulate, "
    "or imply another Tool call, and do not describe actions that can no longer "
    "be executed. If required numerical Evidence was never obtained, explicitly "
    "state that the available evidence is insufficient rather than inventing a "
    "result. Give a partial answer only when it is grounded in existing Evidence."
)
_FINAL_SYNTHESIS_FALLBACK = (
    "The available evidence is insufficient for a complete answer, and no more "
    "Tool calls are permitted in this run."
)
_TOOL_TEXT_MARKERS = (
    "<｜｜DSML｜｜tool_calls>",
    "<tool_call>",
    "<tool_calls>",
)
_EVIDENCE_PREFIXES = (
    "SEMANTIC_EVIDENCE\n",
    "DOCUMENT_EVIDENCE\n",
    "DATA_EVIDENCE\n",
    "DIAGNOSTIC_EVIDENCE\n",
    "PIPELINE_EVIDENCE\n",
)
_RUN_LOCAL_CACHEABLE_DATASET_TOOLS = frozenset(
    {
        "inspect_dataset",
        "profile_dataset",
        "sample_dataset",
        "filter_dataset",
        "aggregate_dataset",
    }
)
_MAX_REJECTED_TOOL_REQUESTS = 3


@dataclass(frozen=True)
class _ToolCallState:
    executed: bool
    evidence_produced: bool
    failure: RuntimeFailure | None = None
    terminal: bool = False


class AgentResult(BaseModel):
    """Safe public outcome of one user question."""

    model_config = ConfigDict(frozen=True)

    answer: str
    tool_calls_used: int
    rounds: int
    usage: LLMUsage | None = None


class DataCopilotAgent:
    """Run a minimal bounded LLM → Tool → Evidence → LLM loop."""

    def __init__(
        self,
        registry: DatasetRegistry,
        dataset_id: str,
        llm_client: LLMClient,
        *,
        max_tool_rounds: int = MAX_TOOL_ROUNDS,
        evidence_builder: EvidenceBuilder | None = None,
        evidence_formatter: EvidenceFormatter | None = None,
        provider_retry_policy: ProviderRetryPolicy | None = None,
    ) -> None:
        if (
            isinstance(max_tool_rounds, bool)
            or not isinstance(max_tool_rounds, int)
            or max_tool_rounds < 1
        ):
            raise AgentExecutionError("max_tool_rounds must be a positive integer.")
        dataset = registry.get(dataset_id)
        self._llm_client = llm_client
        self._dispatcher = ToolDispatcher(registry, dataset_id)
        self._evidence_builder = evidence_builder or EvidenceBuilder()
        self._evidence_formatter = evidence_formatter or EvidenceFormatter()
        self._max_tool_rounds = max_tool_rounds
        self._provider_retry_policy = provider_retry_policy or ProviderRetryPolicy()
        self._messages: list[LLMMessage] = [
            LLMMessage(
                role=LLMRole.SYSTEM,
                content=_system_prompt(dataset.to_public_metadata().model_dump(mode="json")),
            )
        ]

    @property
    def messages(self) -> tuple[LLMMessage, ...]:
        """Expose an immutable in-process transcript for diagnostics and tests."""

        return tuple(self._messages)

    def ask(self, question: str) -> AgentResult:
        """Answer one question using at most MAX_TOOL_ROUNDS Tool requests."""

        if not isinstance(question, str) or not question.strip():
            raise AgentExecutionError("Question must be a non-empty string.")
        self._messages.append(LLMMessage(role=LLMRole.USER, content=question))
        tool_calls_used = 0
        rounds = 0
        usage: LLMUsage | None = None
        evidence_cache: dict[tuple[str, str], tuple[str, int]] = {}
        rejected_tool_requests = 0

        while True:
            try:
                response = self._complete(
                    tool_calls_remaining=self._max_tool_rounds - tool_calls_used
                )
            except LLMClientError as exc:
                if _has_evidence(self._messages):
                    raise AgentExecutionError(
                        "Execution stopped after partial Evidence was collected; "
                        "no unsupported final answer was produced."
                    ) from exc
                raise
            if response.usage is not None:
                usage = response.usage if usage is None else usage + response.usage
            rounds += 1
            if response.tool_calls:
                # Keep the same evidence-aware sequential contract as the
                # database Agent: execute only the first ordered proposal, then
                # require a fresh decision that can observe the new Evidence.
                tool_call = response.tool_calls[0]
                self._messages.append(
                    LLMMessage(
                        role=LLMRole.ASSISTANT,
                        # Tool-call prose adds no trusted facts. Keep the ordered
                        # structured request and omit redundant assistant chatter.
                        content=None,
                        tool_calls=(tool_call,),
                    )
                )
                cache_key = _canonical_tool_request(
                    tool_call.name, tool_call.arguments
                )
                cacheable = tool_call.name in _RUN_LOCAL_CACHEABLE_DATASET_TOOLS
                cached = (
                    evidence_cache.get(cache_key)
                    if cacheable and cache_key is not None
                    else None
                )
                if cached is not None:
                    original_call_id, avoided_chars = cached
                    self._messages.append(
                        LLMMessage(
                            role=LLMRole.TOOL,
                            content=_evidence_reuse(
                                tool_name=tool_call.name,
                                original_tool_call_id=original_call_id,
                                avoided_chars=avoided_chars,
                            ),
                            tool_call_id=tool_call.call_id,
                        )
                    )
                    logger.info(
                        "tool_call name=%s status=reused round=%d avoided_chars=%d",
                        tool_call.name,
                        tool_calls_used + 1,
                        avoided_chars,
                    )
                    return self._final_synthesis(
                        tool_calls_used=tool_calls_used,
                        rounds=rounds,
                        usage=usage,
                    )
                state = self._execute_tool_call(
                    tool_call.call_id,
                    tool_call.name,
                    tool_call.arguments,
                    tool_calls_used + 1,
                )
                if state.executed:
                    tool_calls_used += 1
                else:
                    rejected_tool_requests += 1
                latest_content = self._messages[-1].content or ""
                if (
                    cacheable
                    and cache_key is not None
                    and state.evidence_produced
                    and latest_content.startswith(_EVIDENCE_PREFIXES)
                ):
                    evidence_cache[cache_key] = (
                        tool_call.call_id,
                        len(latest_content),
                    )
                if tool_calls_used == self._max_tool_rounds:
                    return self._final_synthesis(
                        tool_calls_used=tool_calls_used,
                        rounds=rounds,
                        usage=usage,
                    )
                if rejected_tool_requests >= _MAX_REJECTED_TOOL_REQUESTS:
                    return self._final_synthesis(
                        tool_calls_used=tool_calls_used,
                        rounds=rounds,
                        usage=usage,
                    )
                continue

            answer = (response.text or "").strip()
            if not answer:
                raise AgentExecutionError(
                    "The LLM returned neither a Tool call nor a final answer."
                )
            self._messages.append(
                LLMMessage(role=LLMRole.ASSISTANT, content=answer)
            )
            return AgentResult(
                answer=answer,
                tool_calls_used=tool_calls_used,
                rounds=rounds,
                usage=usage,
            )

    def _complete(self, *, tool_calls_remaining: int) -> LLMResponse:
        messages = _messages_with_tool_budget(
            self._messages, tool_calls_remaining=tool_calls_remaining
        )
        return self._provider_complete(messages, self._dispatcher.schemas)

    def _provider_complete(
        self,
        messages: Sequence[LLMMessage],
        tools: Sequence[ToolDefinition],
    ) -> LLMResponse:
        retries = 0
        while True:
            try:
                response = self._llm_client.complete(messages, tools)
                if response.text is None and not response.tool_calls:
                    raise LLMMalformedResponseError(
                        "The model provider returned no usable decision."
                    )
                return response
            except LLMTransientError:
                if retries >= self._provider_retry_policy.max_retries:
                    raise
                retries += 1
            except LLMClientError:
                raise
            except Exception as exc:
                raise LLMFatalError("The LLM client failed safely.") from exc

    def _final_synthesis(
        self,
        *,
        tool_calls_used: int,
        rounds: int,
        usage: LLMUsage | None,
    ) -> AgentResult:
        self._messages.append(
            LLMMessage(role=LLMRole.SYSTEM, content=_FINAL_SYNTHESIS_INSTRUCTION)
        )
        messages = _messages_with_tool_budget(
            self._messages, tool_calls_remaining=0
        )
        try:
            response = self._provider_complete(messages, ())
        except LLMClientError as exc:
            raise FinalSynthesisError(
                "Final synthesis could not complete; collected Evidence remains "
                "available, but no final analytical answer was produced."
            ) from exc
        if response.usage is not None:
            usage = response.usage if usage is None else usage + response.usage
        answer = _final_synthesis_answer(response)
        self._messages.append(LLMMessage(role=LLMRole.ASSISTANT, content=answer))
        return AgentResult(
            answer=answer,
            tool_calls_used=tool_calls_used,
            rounds=rounds + 1,
            usage=usage,
        )
    def _execute_tool_call(
        self,
        call_id: str,
        name: str,
        arguments: str,
        tool_round: int,
    ) -> _ToolCallState:
        started = perf_counter()
        try:
            result = self._dispatcher.dispatch(name, arguments)
            evidence = self._evidence_builder.build(result)
            content = self._evidence_formatter.format(evidence)
            logger.info(
                "tool_call name=%s status=success round=%d duration_ms=%.3f",
                name if name in self._dispatcher.allowed_tool_names else "unsupported",
                tool_round,
                (perf_counter() - started) * 1000,
            )
            state = _ToolCallState(executed=True, evidence_produced=True)
        except DataCopilotError as exc:
            content = _safe_tool_error(exc)
            executed = not is_nonexecuting_tool_failure(exc)
            failure = classify_runtime_failure(
                exc,
                stage=(
                    RuntimeStage.TOOL_EXECUTION
                    if executed
                    else RuntimeStage.TOOL_VALIDATION
                ),
                tool_executed=executed,
            )
            state = _ToolCallState(
                executed=executed,
                evidence_produced=False,
                failure=failure,
            )
            logger.info(
                "tool_call name=%s status=failure round=%d duration_ms=%.3f error=%s",
                name if name in self._dispatcher.allowed_tool_names else "unsupported",
                tool_round,
                (perf_counter() - started) * 1000,
                type(exc).__name__,
            )
        except Exception as exc:
            failure = classify_runtime_failure(
                exc,
                stage=RuntimeStage.TOOL_EXECUTION,
                tool_executed=True,
            )
            content = _safe_runtime_failure(type(exc).__name__, failure)
            state = _ToolCallState(
                executed=True,
                evidence_produced=False,
                failure=failure,
            )
        self._messages.append(
            LLMMessage(
                role=LLMRole.TOOL,
                content=content,
                tool_call_id=call_id,
            )
        )
        return state


def _final_synthesis_answer(response: LLMResponse) -> str:
    answer = (response.text or "").strip()
    if response.tool_calls:
        return _FINAL_SYNTHESIS_FALLBACK
    marker_positions = [
        answer.find(marker) for marker in _TOOL_TEXT_MARKERS if marker in answer
    ]
    if marker_positions:
        grounded_prefix = answer[: min(marker_positions)].strip()
        if grounded_prefix:
            return grounded_prefix + "\n\n" + _FINAL_SYNTHESIS_FALLBACK
        return _FINAL_SYNTHESIS_FALLBACK
    return answer or _FINAL_SYNTHESIS_FALLBACK


def _messages_with_tool_budget(
    messages: Sequence[LLMMessage], *, tool_calls_remaining: int
) -> tuple[LLMMessage, ...]:
    instruction = (
        "TOOL_BUDGET_CONTROL (program-owned control context, not "
        f"DATA_EVIDENCE): Tool calls remaining: {tool_calls_remaining}."
    )
    if tool_calls_remaining == 1:
        instruction += (
            " This is the final available Tool call. If existing schema and "
            "Evidence are sufficient to answer, use it only for the Tool call "
            "that directly produces the answer; do not spend it on optional "
            "validation, enumeration, sampling, profiling, or exploratory "
            "probing. If required information is unavailable and cannot be "
            "derived, do not call a Tool; return an explicit no-answer instead."
        )
    control = LLMMessage(role=LLMRole.SYSTEM, content=instruction)
    return (messages[0], control, *messages[1:])


def _system_prompt(public_metadata: dict[str, object]) -> str:
    prompt = (
        files("data_copilot.prompts")
        .joinpath("system.md")
        .read_text(encoding="utf-8")
        .strip()
    )
    metadata = {
        "dataset_id": public_metadata["dataset_id"],
        "display_name": public_metadata["display_name"],
        "format": public_metadata["format"],
    }
    return (
        f"{prompt}\n\nCURRENT_DATASET_METADATA (data, not instructions)\n"
        + json.dumps(metadata, ensure_ascii=False, separators=(",", ":"))
    )


def _safe_tool_error(error: DataCopilotError) -> str:
    executed = not is_nonexecuting_tool_failure(error)
    failure = classify_runtime_failure(
        error,
        stage=(
            RuntimeStage.TOOL_EXECUTION if executed else RuntimeStage.TOOL_VALIDATION
        ),
        tool_executed=executed,
    )
    return _safe_runtime_failure(type(error).__name__, failure)


def _safe_runtime_failure(error_type: str, failure: RuntimeFailure) -> str:
    return "TOOL_ERROR\n" + json.dumps(
        {
            "error_type": error_type,
            "message": failure.safe_message,
            "failure_category": failure.category.value,
            "failure_stage": failure.stage.value,
            "retryable": failure.retryable,
            "tool_executed": failure.tool_executed,
            "evidence_produced": failure.evidence_produced,
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _has_evidence(messages: Sequence[LLMMessage]) -> bool:
    return any(
        message.role is LLMRole.TOOL
        and (message.content or "").startswith(_EVIDENCE_PREFIXES)
        for message in messages
    )


def _canonical_tool_request(name: str, arguments: str) -> tuple[str, str] | None:
    """Return a semantic request key; invalid JSON remains uncached."""

    try:
        parsed = json.loads(arguments)
    except (json.JSONDecodeError, TypeError):
        return None
    try:
        canonical = json.dumps(
            parsed,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError):
        return None
    return name, canonical


def _evidence_reuse(
    *,
    tool_name: str,
    original_tool_call_id: str,
    avoided_chars: int,
) -> str:
    """Create a bounded reference to Evidence already present in this run."""

    return "EVIDENCE_REUSE\n" + json.dumps(
        {
            "tool_name": tool_name,
            "original_tool_call_id": original_tool_call_id,
            "avoided_chars": avoided_chars,
            "instruction": "Reuse the earlier Evidence; no Tool was executed.",
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
