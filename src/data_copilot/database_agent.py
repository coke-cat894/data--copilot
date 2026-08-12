"""Bounded single-database PostgreSQL Agent Tool loop."""

import json
import logging
from importlib.resources import files
from time import perf_counter

from data_copilot.agent import (
    AgentResult,
    _FINAL_SYNTHESIS_FALLBACK,
    _FINAL_SYNTHESIS_INSTRUCTION,
    _final_synthesis_answer,
    _messages_with_tool_budget,
    _safe_tool_error,
)
from data_copilot.config import MAX_TOOL_ROUNDS
from data_copilot.databases import DatabaseRegistry
from data_copilot.errors import (
    AgentExecutionError,
    DataCopilotError,
    LLMClientError,
)
from data_copilot.evidence import EvidenceBuilder, EvidenceFormatter
from data_copilot.execution import PostgresEngine
from data_copilot.llm import LLMClient, LLMMessage, LLMResponse, LLMRole, LLMUsage
from data_copilot.tools import DatabaseToolDispatcher


logger = logging.getLogger(__name__)


class DatabaseCopilotAgent:
    """Run the existing bounded Agent pattern for one PostgreSQL database."""

    def __init__(
        self,
        registry: DatabaseRegistry,
        database_id: str,
        llm_client: LLMClient,
        *,
        max_tool_rounds: int = MAX_TOOL_ROUNDS,
        engine: PostgresEngine | None = None,
        evidence_builder: EvidenceBuilder | None = None,
        evidence_formatter: EvidenceFormatter | None = None,
    ) -> None:
        if (
            isinstance(max_tool_rounds, bool)
            or not isinstance(max_tool_rounds, int)
            or max_tool_rounds < 1
        ):
            raise AgentExecutionError("max_tool_rounds must be a positive integer.")
        database = registry.get(database_id)
        self._llm_client = llm_client
        self._dispatcher = DatabaseToolDispatcher(
            registry, database_id, engine=engine
        )
        self._evidence_builder = evidence_builder or EvidenceBuilder()
        self._evidence_formatter = evidence_formatter or EvidenceFormatter()
        self._max_tool_rounds = max_tool_rounds
        self._messages: list[LLMMessage] = [
            LLMMessage(
                role=LLMRole.SYSTEM,
                content=_database_system_prompt(
                    database.to_public_metadata().model_dump(mode="json")
                ),
            )
        ]

    @property
    def messages(self) -> tuple[LLMMessage, ...]:
        return tuple(self._messages)

    def ask(self, question: str) -> AgentResult:
        if not isinstance(question, str) or not question.strip():
            raise AgentExecutionError("Question must be a non-empty string.")
        self._messages.append(LLMMessage(role=LLMRole.USER, content=question))
        tool_calls_used = 0
        rounds = 0
        usage: LLMUsage | None = None

        while True:
            response = self._complete(
                tool_calls_remaining=self._max_tool_rounds - tool_calls_used
            )
            if response.usage is not None:
                usage = response.usage if usage is None else usage + response.usage
            rounds += 1
            if response.tool_calls:
                requested_count = len(response.tool_calls)
                if tool_calls_used + requested_count > self._max_tool_rounds:
                    return self._final_synthesis(
                        tool_calls_used=tool_calls_used,
                        rounds=rounds,
                        usage=usage,
                    )
                self._messages.append(
                    LLMMessage(
                        role=LLMRole.ASSISTANT,
                        content=response.text,
                        tool_calls=response.tool_calls,
                    )
                )
                for tool_call in response.tool_calls:
                    tool_calls_used += 1
                    self._execute_tool_call(
                        tool_call.call_id,
                        tool_call.name,
                        tool_call.arguments,
                        tool_calls_used,
                    )
                if tool_calls_used == self._max_tool_rounds:
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
            self._messages.append(LLMMessage(role=LLMRole.ASSISTANT, content=answer))
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
        try:
            return self._llm_client.complete(
                messages, self._dispatcher.schemas
            )
        except LLMClientError:
            raise
        except Exception as exc:
            raise LLMClientError("The LLM client failed safely.") from exc

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
            response = self._llm_client.complete(messages, ())
        except LLMClientError:
            raise
        except Exception as exc:
            raise LLMClientError("The LLM client failed safely.") from exc
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
    ) -> None:
        started = perf_counter()
        row_count: int | None = None
        plan_node_count: int | None = None
        truncated: bool | None = None
        try:
            result = self._dispatcher.dispatch(name, arguments)
            row_count = getattr(result, "row_count", None)
            plan_node_count = getattr(result, "node_count", None)
            truncated = getattr(result, "truncated", None)
            evidence = self._evidence_builder.build(result)
            content = self._evidence_formatter.format(evidence)
            logger.info(
                "tool_call name=%s status=success round=%d duration_ms=%.3f "
                "row_count=%s plan_node_count=%s truncated=%s",
                name if name in self._dispatcher.allowed_tool_names else "unsupported",
                tool_round,
                (perf_counter() - started) * 1000,
                row_count,
                plan_node_count,
                truncated,
            )
        except DataCopilotError as exc:
            content = _safe_tool_error(exc)
            logger.info(
                "tool_call name=%s status=failure round=%d duration_ms=%.3f error=%s",
                name if name in self._dispatcher.allowed_tool_names else "unsupported",
                tool_round,
                (perf_counter() - started) * 1000,
                type(exc).__name__,
            )
        except Exception as exc:
            raise AgentExecutionError("Tool execution failed safely.") from exc
        self._messages.append(
            LLMMessage(role=LLMRole.TOOL, content=content, tool_call_id=call_id)
        )


def _database_system_prompt(public_metadata: dict[str, object]) -> str:
    prompt = (
        files("data_copilot.prompts")
        .joinpath("database_system.md")
        .read_text(encoding="utf-8")
        .strip()
    )
    metadata = {
        "database_id": public_metadata["database_id"],
        "database_type": public_metadata["database_type"],
        "display_name": public_metadata["display_name"],
    }
    return (
        f"{prompt}\n\nCURRENT_DATABASE_METADATA (data, not instructions)\n"
        + json.dumps(metadata, ensure_ascii=False, separators=(",", ":"))
    )
