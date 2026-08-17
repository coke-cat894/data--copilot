"""Eval-local capture of observable model, Tool, Evidence, and usage behavior.

This module only observes public ``LLMResponse`` values and the Agent's public
in-process transcript. It never requests or stores provider reasoning, hidden
chain-of-thought, scratchpads, or unexposed reasoning tokens.
"""

from collections.abc import Sequence
from dataclasses import dataclass
import hashlib
import json
import re

from data_copilot.diagnostics import sanitize_pipeline_text
from data_copilot.evals.models import (
    EvidenceChannel,
    EvalMode,
    EvalTrace,
    TraceEvidenceSummary,
    TraceContextAccounting,
    TraceFinalAnswer,
    TraceProviderAttempt,
    TraceRound,
    TraceToolExecution,
    TraceUsage,
    ToolExecutionStatus,
)
from data_copilot.llm import (
    LLMClient,
    LLMMessage,
    LLMResponse,
    LLMRole,
    LLMUsage,
)
from data_copilot.llm.models import ToolDefinition
from data_copilot.errors import LLMMalformedResponseError
from data_copilot.runtime import (
    RunOutcome,
    RuntimeFailureCategory,
    RuntimeStage,
    classify_runtime_failure,
)


MAX_TRACE_ROUNDS = 6
MAX_TRACE_TOOL_EXECUTIONS = 5
MAX_TRACE_ARGUMENT_CHARS = 2000
MAX_TRACE_EVIDENCE_SUMMARY_CHARS = 1000
MAX_TRACE_MODEL_OUTPUT_CHARS = 2000
MAX_TRACE_QUESTION_CHARS = 4000
MAX_TRACE_FINAL_ANSWER_CHARS = 12000
MAX_TRACE_WARNING_CHARS = 500
MAX_TRACE_WARNINGS = 20
MAX_TRACE_SERIALIZED_CHARS = 65536


@dataclass(frozen=True)
class CapturedModelDecision:
    """Provider-visible response plus program-owned request controls."""

    tool_budget_before: int
    tools_enabled: bool
    context: TraceContextAccounting
    evidence_fingerprints: tuple[tuple[str, str, int], ...]
    response: LLMResponse


@dataclass(frozen=True)
class CapturedProviderAttempt:
    request_fingerprint: str
    stage: RuntimeStage
    attempt_number: int
    succeeded: bool
    failure_category: RuntimeFailureCategory | None = None
    retryable: bool = False
    safe_message: str | None = None


class ObservableLLMClient:
    """Transparent eval-only client wrapper that captures observable responses."""

    def __init__(self, client: LLMClient) -> None:
        self._client = client
        self.decisions: list[CapturedModelDecision] = []
        self.attempts: list[CapturedProviderAttempt] = []
        self.failure_category: str | None = None
        self.failure_message: str | None = None

    def complete(
        self,
        messages: Sequence[LLMMessage],
        tools: Sequence[ToolDefinition],
    ) -> LLMResponse:
        fingerprint = _request_fingerprint(messages, tools)
        attempt_number = 1
        if self.attempts and self.attempts[-1].request_fingerprint == fingerprint:
            attempt_number = min(3, self.attempts[-1].attempt_number + 1)
        stage = (
            RuntimeStage.FINAL_SYNTHESIS
            if _tool_budget(messages) == 0 and not tools
            else RuntimeStage.PROVIDER_DECISION
        )
        try:
            response = self._client.complete(messages, tools)
            if response.text is None and not response.tool_calls:
                raise LLMMalformedResponseError(
                    "The model provider returned no usable decision."
                )
        except Exception as exc:
            failure = classify_runtime_failure(exc, stage=stage)
            self.failure_category = failure.category.value
            self.failure_message = failure.safe_message
            self.attempts.append(
                CapturedProviderAttempt(
                    request_fingerprint=fingerprint,
                    stage=stage,
                    attempt_number=attempt_number,
                    succeeded=False,
                    failure_category=failure.category,
                    retryable=failure.retryable,
                    safe_message=failure.safe_message,
                )
            )
            raise
        self.attempts.append(
            CapturedProviderAttempt(
                request_fingerprint=fingerprint,
                stage=stage,
                attempt_number=attempt_number,
                succeeded=True,
            )
        )
        self.decisions.append(
            CapturedModelDecision(
                tool_budget_before=_tool_budget(messages),
                tools_enabled=bool(tools),
                context=_context_accounting(messages, tools),
                evidence_fingerprints=_evidence_fingerprints(messages),
                response=response,
            )
        )
        return response


def serialize_eval_trace(trace: EvalTrace) -> str:
    """Serialize a trace with stable field and collection ordering."""

    if not isinstance(trace, EvalTrace):
        raise TypeError("serialize_eval_trace requires an EvalTrace.")
    return json.dumps(
        trace.model_dump(mode="json"),
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def build_safe_trace(
    *,
    case_id: str,
    question: str,
    answer: str | None,
    outcome: RunOutcome,
    messages: tuple[LLMMessage, ...],
    decisions: Sequence[CapturedModelDecision],
    provider_attempts: Sequence[CapturedProviderAttempt] = (),
    usage: LLMUsage | None,
    latency_ms: float,
    tool_call_count: int,
    rounds: int,
    run_id: str | None = None,
    provider: str | None = None,
    model: str | None = None,
    eval_mode: EvalMode = EvalMode.DETERMINISTIC,
    provider_error_category: str | None = None,
    provider_error_message: str | None = None,
) -> EvalTrace:
    """Build a deterministic bounded trace from observable runtime state."""

    warnings: list[str] = []
    safe_question = _safe_bounded_text(
        question,
        MAX_TRACE_QUESTION_CHARS,
        "Original question",
        warnings,
    )
    safe_answer = None
    if answer is not None:
        bounded_answer = _safe_bounded_text(
            answer,
            MAX_TRACE_FINAL_ANSWER_CHARS,
            "Final answer",
            warnings,
        )
        safe_answer = TraceFinalAnswer(
            response=bounded_answer,
            original_chars=len(answer),
            truncated=len(bounded_answer) < len(answer),
        )

    tool_messages = {
        message.tool_call_id: message
        for message in messages
        if message.role is LLMRole.TOOL and message.tool_call_id is not None
    }
    assistant_calls = {
        call.call_id: call
        for message in messages
        if message.role is LLMRole.ASSISTANT
        for call in message.tool_calls
    }
    trace_rounds: list[TraceRound] = []
    traced_executions = 0
    for index, decision in enumerate(decisions[:MAX_TRACE_ROUNDS], start=1):
        response = decision.response
        visible_output = None
        output_truncated = False
        if response.text:
            visible_output = _safe_bounded_text(
                response.text,
                MAX_TRACE_MODEL_OUTPUT_CHARS,
                f"Round {index} visible model output",
                warnings,
            )
            output_truncated = len(visible_output) < len(response.text)

        execution = None
        executed_calls = [
            assistant_calls[call.call_id]
            for call in response.tool_calls
            if call.call_id in assistant_calls
            and call.call_id in tool_messages
        ]
        if executed_calls and traced_executions < MAX_TRACE_TOOL_EXECUTIONS:
            execution = _tool_execution(
                executed_calls[0],
                tool_messages[executed_calls[0].call_id],
            )
            traced_executions += 1
        if len(executed_calls) > 1:
            raise ValueError(
                "Sequential trace observed multiple executions for one decision."
            )

        trace_rounds.append(
            TraceRound(
                round_number=index,
                tool_budget_before=decision.tool_budget_before,
                tools_enabled=decision.tools_enabled,
                final_synthesis=(
                    not decision.tools_enabled
                    and decision.tool_budget_before == 0
                ),
                visible_model_output=visible_output,
                visible_model_output_truncated=output_truncated,
                requested_tool_count=min(len(response.tool_calls), 50),
                executed_tool=execution,
                context=decision.context,
            )
        )
    if len(decisions) > MAX_TRACE_ROUNDS:
        _warning(warnings, f"Trace rounds were truncated to {MAX_TRACE_ROUNDS}.")

    contexts = tuple(decision.context for decision in decisions[:MAX_TRACE_ROUNDS])
    evidence_totals = {
        channel: sum(getattr(context, channel) for context in contexts)
        for channel in (
            "semantic_evidence_chars",
            "document_evidence_chars",
            "data_evidence_chars",
            "diagnostic_evidence_chars",
            "pipeline_evidence_chars",
        )
    }
    evidence_transmitted = sum(evidence_totals.values())
    unique_evidence_chars = _unique_evidence_chars(decisions[:MAX_TRACE_ROUNDS])
    traced_provider_attempts = _trace_provider_attempts(provider_attempts)
    trace = EvalTrace(
        run_id=run_id,
        case_id=case_id,
        provider=_safe_optional_identity(provider, 128),
        model=_safe_optional_identity(model, 256),
        eval_mode=eval_mode,
        outcome=outcome,
        original_question=safe_question,
        original_question_chars=len(question),
        original_question_truncated=len(safe_question) < len(question),
        rounds=tuple(trace_rounds),
        provider_attempts=traced_provider_attempts,
        final_answer=safe_answer,
        usage=TraceUsage(
            provider_reported_input_tokens=(
                usage.input_tokens if usage is not None else None
            ),
            provider_reported_output_tokens=(
                usage.output_tokens if usage is not None else None
            ),
            provider_reported_total_tokens=(
                usage.total_tokens if usage is not None else None
            ),
            latency_ms=latency_ms,
            tool_calls=min(tool_call_count, MAX_TRACE_TOOL_EXECUTIONS),
            rounds=min(rounds, MAX_TRACE_ROUNDS),
            request_context_chars=sum(item.total_context_chars for item in contexts),
            estimated_input_tokens=sum(item.estimated_input_tokens for item in contexts),
            tool_schema_chars=sum(item.tool_schema_chars for item in contexts),
            **evidence_totals,
            evidence_chars_transmitted=evidence_transmitted,
            repeated_evidence_chars=max(0, evidence_transmitted - unique_evidence_chars),
            duplicate_evidence_chars_avoided=_duplicate_evidence_chars_avoided(messages),
            provider_attempts=len(traced_provider_attempts),
            provider_retries=sum(
                item.attempt_number > 1 for item in traced_provider_attempts
            ),
        ),
        sanitized_error_category=(
            sanitize_trace_text(provider_error_category)[:128]
            if provider_error_category
            else None
        ),
        sanitized_error_message=(
            sanitize_trace_text(provider_error_message)[:500]
            if provider_error_message
            else None
        ),
        warnings=tuple(warnings[:MAX_TRACE_WARNINGS]),
    )
    if len(serialize_eval_trace(trace)) <= MAX_TRACE_SERIALIZED_CHARS:
        return trace

    reduced_rounds = tuple(
        item.model_copy(
            update={
                "visible_model_output": None,
                "visible_model_output_truncated": (
                    item.visible_model_output is not None
                    or item.visible_model_output_truncated
                ),
            }
        )
        for item in trace.rounds
    )
    reduced_warnings = list(trace.warnings)
    _warning(
        reduced_warnings,
        "Visible model outputs were removed to satisfy the serialized trace limit.",
    )
    reduced = trace.model_copy(
        update={
            "rounds": reduced_rounds,
            "warnings": tuple(reduced_warnings[:MAX_TRACE_WARNINGS]),
            "serialized_truncated": True,
        }
    )
    if len(serialize_eval_trace(reduced)) > MAX_TRACE_SERIALIZED_CHARS:
        raise ValueError("Safe trace cannot fit the serialized trace limit.")
    return reduced


def sanitize_tool_arguments(arguments: str) -> str:
    """Return stable bounded JSON without secrets, paths, or driver internals."""

    try:
        value = json.loads(arguments)
    except (json.JSONDecodeError, TypeError):
        return '{"status":"invalid_arguments"}'

    def sanitize(item: object, *, key: str | None = None) -> object:
        if key is not None and _SENSITIVE_ARGUMENT_KEYS.search(key):
            return "[REDACTED]"
        if isinstance(item, dict):
            return {
                str(child_key): sanitize(child, key=str(child_key))
                for child_key, child in sorted(
                    item.items(), key=lambda pair: str(pair[0])
                )
            }
        if isinstance(item, list):
            selected = [sanitize(child) for child in item[:50]]
            if len(item) > 50:
                selected[-1] = "[TRUNCATED]"
            return selected
        if isinstance(item, str):
            sanitized = sanitize_trace_text(item)
            if len(sanitized) > 1000:
                marker = "...[TRUNCATED]"
                return sanitized[: 1000 - len(marker)] + marker
            return sanitized
        return item

    serialized = json.dumps(
        sanitize(value),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    if len(serialized) <= MAX_TRACE_ARGUMENT_CHARS:
        return serialized
    preview = serialized[: MAX_TRACE_ARGUMENT_CHARS - 100]
    bounded = json.dumps(
        {"preview": preview, "status": "truncated"},
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    while len(bounded) > MAX_TRACE_ARGUMENT_CHARS and preview:
        preview = preview[:-50]
        bounded = json.dumps(
            {"preview": preview, "status": "truncated"},
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    return bounded


def bounded_evidence_summary(content: str) -> tuple[str, bool]:
    """Summarize an Evidence envelope without retaining its raw payload."""

    channel = content_channel(content)
    if channel is None:
        if content.startswith("TOOL_ERROR\n"):
            error_type, _ = _safe_tool_error_parts(content)
            return f"tool_error type={error_type}", False
        return "no_evidence", False
    payload_text = content.split("\n", 1)[1] if "\n" in content else ""
    try:
        payload = json.loads(payload_text)
    except json.JSONDecodeError:
        return f"channel={channel.value} malformed=true", False
    parts = [f"channel={channel.value}"]
    for key in (
        "kind",
        "status",
        "truncated",
        "source_truncated",
        "evidence_truncated",
    ):
        if key in payload and isinstance(payload[key], (str, bool, int, float)):
            value = sanitize_trace_text(str(payload[key]))[:128]
            parts.append(f"{key}={value}")
    metadata = payload.get("metadata")
    if isinstance(metadata, dict):
        for key in (
            "source_row_count",
            "evidence_record_count",
            "source_column_count",
            "evidence_column_count",
        ):
            if isinstance(metadata.get(key), int):
                parts.append(f"{key}={metadata[key]}")
    if isinstance(payload.get("run"), dict):
        run = payload["run"]
        for key in ("pipeline_id", "run_id", "status"):
            if isinstance(run.get(key), str):
                parts.append(f"{key}={sanitize_trace_text(run[key])[:128]}")
    for key in (
        "findings",
        "events",
        "steps",
        "definitions",
        "chunks",
        "records",
        "columns",
    ):
        if isinstance(payload.get(key), list):
            parts.append(f"{key}={len(payload[key])}")
    comparison = payload.get("comparison")
    if isinstance(comparison, dict) and isinstance(comparison.get("findings"), list):
        parts.append(f"comparison_findings={len(comparison['findings'])}")
    if channel is EvidenceChannel.SEMANTIC:
        for definition in _dict_items(payload.get("definitions"), limit=5):
            identity = next(
                (
                    definition.get(key)
                    for key in ("metric_id", "dimension_id", "term_id")
                    if isinstance(definition.get(key), str)
                ),
                None,
            )
            name = next(
                (
                    definition.get(key)
                    for key in ("name", "term", "display_name")
                    if isinstance(definition.get(key), str)
                ),
                None,
            )
            fields = definition.get("required_fields") or definition.get("source_fields")
            if identity is not None:
                parts.append(f"definition={_summary_value(identity)}")
            if name is not None:
                parts.append(f"name={_summary_value(name)}")
            if isinstance(fields, list):
                parts.append(
                    "fields="
                    + ",".join(_summary_value(item) for item in fields[:10] if isinstance(item, str))
                )
    elif channel is EvidenceChannel.DOCUMENT:
        for chunk in _dict_items(payload.get("chunks"), limit=5):
            for key in ("chunk_id", "title", "heading"):
                if isinstance(chunk.get(key), str):
                    parts.append(f"{key}={_summary_value(chunk[key])}")
    elif channel is EvidenceChannel.DATA:
        operation = payload.get("operation")
        if isinstance(operation, str):
            parts.append(f"operation={_summary_value(operation)}")
        columns = payload.get("columns")
        if isinstance(columns, list):
            parts.append(
                "column_names="
                + ",".join(
                    _summary_value(item) for item in columns[:10] if isinstance(item, str)
                )
            )
    elif channel is EvidenceChannel.DIAGNOSTIC:
        selected = payload.get("snapshot") or payload.get("comparison")
        if isinstance(selected, dict):
            for key in (
                "dataset_id",
                "snapshot_id",
                "before_snapshot_id",
                "after_snapshot_id",
                "row_count",
            ):
                if isinstance(selected.get(key), (str, int)):
                    parts.append(f"{key}={_summary_value(selected[key])}")
            for finding in _dict_items(selected.get("findings"), limit=10):
                finding_type = finding.get("drift_type")
                column_name = finding.get("column_name")
                if isinstance(finding_type, str):
                    value = _summary_value(finding_type)
                    if isinstance(column_name, str):
                        value += f":{_summary_value(column_name)}"
                    parts.append(f"finding={value}")
    elif channel is EvidenceChannel.PIPELINE:
        for step in _dict_items(payload.get("steps"), limit=10):
            step_id = step.get("step_id")
            status = step.get("status")
            if isinstance(step_id, str):
                value = _summary_value(step_id)
                if isinstance(status, str):
                    value += f":{_summary_value(status)}"
                parts.append(f"step={value}")
        for finding in _dict_items(payload.get("findings"), limit=10):
            finding_type = finding.get("finding_type")
            if isinstance(finding_type, str):
                parts.append(f"finding={_summary_value(finding_type)}")
    summary = " ".join(parts)
    truncated = any(
        bool(payload.get(key))
        for key in ("truncated", "source_truncated", "evidence_truncated")
    )
    if len(summary) > MAX_TRACE_EVIDENCE_SUMMARY_CHARS:
        summary = summary[: MAX_TRACE_EVIDENCE_SUMMARY_CHARS - 14] + "...[TRUNCATED]"
        truncated = True
    return summary, truncated


def _dict_items(value: object, *, limit: int) -> tuple[dict[str, object], ...]:
    if not isinstance(value, list):
        return ()
    return tuple(item for item in value[:limit] if isinstance(item, dict))


def _summary_value(value: object) -> str:
    return sanitize_trace_text(str(value)).replace(" ", "_")[:128]


def content_channel(content: str) -> EvidenceChannel | None:
    prefixes = (
        ("SEMANTIC_EVIDENCE\n", EvidenceChannel.SEMANTIC),
        ("DOCUMENT_EVIDENCE\n", EvidenceChannel.DOCUMENT),
        ("DATA_EVIDENCE\n", EvidenceChannel.DATA),
        ("DIAGNOSTIC_EVIDENCE\n", EvidenceChannel.DIAGNOSTIC),
        ("PIPELINE_EVIDENCE\n", EvidenceChannel.PIPELINE),
    )
    return next(
        (channel for prefix, channel in prefixes if content.startswith(prefix)),
        None,
    )


def sanitize_trace_text(value: str) -> str:
    sanitized = sanitize_pipeline_text(value)
    return _ABSOLUTE_PATH.sub("[REDACTED_PATH]", sanitized)


def _tool_execution(call: object, tool_message: LLMMessage) -> TraceToolExecution:
    call_id = getattr(call, "call_id")
    if tool_message.tool_call_id != call_id:
        raise ValueError("Tool execution does not match the observable Tool request.")
    content = tool_message.content or ""
    channel = content_channel(content)
    summary, truncated = bounded_evidence_summary(content)
    error_category = None
    error_message = None
    status = ToolExecutionStatus.SUCCESS
    failure_category = None
    failure_stage = None
    retryable = None
    tool_executed = True
    evidence_produced = channel is not None
    if content.startswith("TOOL_ERROR\n"):
        status = ToolExecutionStatus.ERROR
        error_category, error_message = _safe_tool_error_parts(content)
        (
            failure_category,
            failure_stage,
            retryable,
            tool_executed,
            evidence_produced,
        ) = _safe_tool_failure_parts(content)
    elif content.startswith("EVIDENCE_REUSE\n"):
        status = ToolExecutionStatus.REUSED
        summary = "run-local evidence reused; duplicate execution avoided"
    return TraceToolExecution(
        tool_name=str(getattr(call, "name"))[:128],
        sanitized_arguments=sanitize_tool_arguments(str(getattr(call, "arguments"))),
        status=status,
        evidence=TraceEvidenceSummary(
            channel=channel,
            summary=summary,
            truncated=truncated,
        ),
        sanitized_error_category=error_category,
        sanitized_error_message=error_message,
        failure_category=failure_category,
        failure_stage=failure_stage,
        retryable=retryable,
        tool_executed=tool_executed,
        evidence_produced=evidence_produced,
    )


def _trace_provider_attempts(
    attempts: Sequence[CapturedProviderAttempt],
) -> tuple[TraceProviderAttempt, ...]:
    selected = attempts[:20]
    result: list[TraceProviderAttempt] = []
    for index, attempt in enumerate(selected):
        retry_performed = (
            not attempt.succeeded
            and index + 1 < len(selected)
            and selected[index + 1].request_fingerprint == attempt.request_fingerprint
        )
        result.append(
            TraceProviderAttempt(
                stage=attempt.stage,
                attempt_number=attempt.attempt_number,
                succeeded=attempt.succeeded,
                retryable=attempt.retryable,
                retry_performed=retry_performed,
                failure_category=attempt.failure_category,
                sanitized_message=(
                    sanitize_trace_text(attempt.safe_message)[:500]
                    if attempt.safe_message
                    else None
                ),
            )
        )
    return tuple(result)


def _request_fingerprint(
    messages: Sequence[LLMMessage],
    tools: Sequence[ToolDefinition],
) -> str:
    payload = {
        "messages": [message.model_dump(mode="json") for message in messages],
        "tools": [tool.model_dump(mode="json") for tool in tools],
    }
    return hashlib.sha256(_compact_json(payload).encode("utf-8")).hexdigest()


def _safe_tool_failure_parts(
    content: str,
) -> tuple[
    RuntimeFailureCategory | None,
    RuntimeStage | None,
    bool | None,
    bool,
    bool,
]:
    try:
        payload = json.loads(content.split("\n", 1)[1])
    except (json.JSONDecodeError, IndexError):
        return None, None, None, True, False
    if not isinstance(payload, dict):
        return None, None, None, True, False
    try:
        category = RuntimeFailureCategory(payload.get("failure_category"))
    except (TypeError, ValueError):
        category = None
    try:
        stage = RuntimeStage(payload.get("failure_stage"))
    except (TypeError, ValueError):
        stage = None
    retryable = payload.get("retryable")
    return (
        category,
        stage,
        retryable if isinstance(retryable, bool) else None,
        payload.get("tool_executed") is not False,
        payload.get("evidence_produced") is True,
    )


def _context_accounting(
    messages: Sequence[LLMMessage],
    tools: Sequence[ToolDefinition],
) -> TraceContextAccounting:
    """Account for serialized request context without claiming tokenizer parity."""

    counts = {
        "system_chars": 0,
        "user_chars": 0,
        "tool_schema_chars": len(_compact_json([tool.model_dump(mode="json") for tool in tools])),
        "assistant_history_chars": 0,
        "tool_error_chars": 0,
        "other_tool_history_chars": 0,
        "semantic_evidence_chars": 0,
        "document_evidence_chars": 0,
        "data_evidence_chars": 0,
        "diagnostic_evidence_chars": 0,
        "pipeline_evidence_chars": 0,
    }
    channel_fields = {
        EvidenceChannel.SEMANTIC: "semantic_evidence_chars",
        EvidenceChannel.DOCUMENT: "document_evidence_chars",
        EvidenceChannel.DATA: "data_evidence_chars",
        EvidenceChannel.DIAGNOSTIC: "diagnostic_evidence_chars",
        EvidenceChannel.PIPELINE: "pipeline_evidence_chars",
    }
    for message in messages:
        chars = len(_compact_json(message.model_dump(mode="json")))
        if message.role is LLMRole.SYSTEM:
            counts["system_chars"] += chars
        elif message.role is LLMRole.USER:
            counts["user_chars"] += chars
        elif message.role is LLMRole.ASSISTANT:
            counts["assistant_history_chars"] += chars
        elif message.role is LLMRole.TOOL:
            content = message.content or ""
            channel = content_channel(content)
            if channel is not None:
                counts[channel_fields[channel]] += chars
            elif content.startswith("TOOL_ERROR\n"):
                counts["tool_error_chars"] += chars
            else:
                counts["other_tool_history_chars"] += chars
    total = sum(counts.values())
    return TraceContextAccounting(
        **counts,
        total_context_chars=total,
        estimated_input_tokens=(total + 3) // 4,
    )


def _compact_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _evidence_fingerprints(
    messages: Sequence[LLMMessage],
) -> tuple[tuple[str, str, int], ...]:
    items: list[tuple[str, str, int]] = []
    for message in messages:
        if message.role is not LLMRole.TOOL or message.content is None:
            continue
        channel = content_channel(message.content)
        if channel is None:
            continue
        serialized_chars = len(_compact_json(message.model_dump(mode="json")))
        digest = hashlib.sha256(message.content.encode("utf-8")).hexdigest()
        items.append((channel.value, digest, serialized_chars))
    return tuple(items)


def _unique_evidence_chars(decisions: Sequence[CapturedModelDecision]) -> int:
    seen: set[tuple[str, str]] = set()
    total = 0
    for decision in decisions:
        for channel, digest, chars in decision.evidence_fingerprints:
            key = (channel, digest)
            if key not in seen:
                seen.add(key)
                total += chars
    return total


def _duplicate_evidence_chars_avoided(messages: Sequence[LLMMessage]) -> int:
    total = 0
    for message in messages:
        if message.role is not LLMRole.TOOL or not message.content:
            continue
        if not message.content.startswith("EVIDENCE_REUSE\n"):
            continue
        try:
            payload = json.loads(message.content.split("\n", 1)[1])
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict) and isinstance(payload.get("avoided_chars"), int):
            total += max(0, payload["avoided_chars"])
    return total


def _safe_tool_error_parts(content: str) -> tuple[str, str | None]:
    detail = content.split("\n", 1)[1] if "\n" in content else "unknown"
    try:
        payload = json.loads(detail)
    except json.JSONDecodeError:
        payload = None
    if isinstance(payload, dict):
        category = payload.get("error_type")
        message = payload.get("message")
        safe_category = (
            re.sub(r"[^A-Za-z0-9_.-]", "", category)[:128]
            if isinstance(category, str)
            else "unknown"
        ) or "unknown"
        safe_message = (
            sanitize_trace_text(message)[:500]
            if isinstance(message, str) and message
            else None
        )
        return safe_category, safe_message
    category, separator, message = detail.partition(":")
    safe_category = re.sub(r"[^A-Za-z0-9_.-]", "", category)[:128] or "unknown"
    safe_message = sanitize_trace_text(message.strip())[:500] if separator else None
    return safe_category, safe_message


def _tool_budget(messages: Sequence[LLMMessage]) -> int:
    for message in messages:
        if message.role is not LLMRole.SYSTEM or message.content is None:
            continue
        match = _TOOL_BUDGET.search(message.content)
        if match is not None:
            return min(int(match.group(1)), MAX_TRACE_TOOL_EXECUTIONS)
    return 0


def _safe_bounded_text(
    value: str,
    limit: int,
    label: str,
    warnings: list[str],
) -> str:
    sanitized = sanitize_trace_text(value)
    if sanitized != value:
        _warning(warnings, f"{label} contained sensitive or path-like text and was redacted.")
    if len(sanitized) <= limit:
        return sanitized
    _warning(warnings, f"{label} was truncated to {limit} characters.")
    marker = "...[TRUNCATED]"
    return sanitized[: limit - len(marker)] + marker


def _safe_optional_identity(value: str | None, limit: int) -> str | None:
    if value is None:
        return None
    return sanitize_trace_text(value)[:limit]


def _warning(warnings: list[str], value: str) -> None:
    safe = sanitize_trace_text(value)[:MAX_TRACE_WARNING_CHARS]
    if safe not in warnings and len(warnings) < MAX_TRACE_WARNINGS:
        warnings.append(safe)


_TOOL_BUDGET = re.compile(r"Tool calls remaining:\s*(\d+)")
_SENSITIVE_ARGUMENT_KEYS = re.compile(
    r"(?i)(?:password|passwd|pwd|api.?key|token|secret|dsn|credential|"
    r"connection.?string|driver)"
)
_ABSOLUTE_PATH = re.compile(
    r"(?:(?<![A-Za-z0-9])(?:/Users|/home|/var|/private|/tmp)/[^\s\"'`,;}\]]+|"
    r"(?<![A-Za-z0-9])[A-Za-z]:\\[^\s\"'`,;}\]]+)"
)
