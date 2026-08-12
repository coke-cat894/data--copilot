"""Minimal provider adapters and deterministic fake LLM client."""

import os
from collections import deque
from collections.abc import Sequence
from typing import Any, Protocol

from data_copilot.config import (
    DEFAULT_DEEPSEEK_BASE_URL,
    DEFAULT_DEEPSEEK_MODEL,
    DEFAULT_MODEL,
    DEEPSEEK_API_KEY_ENV_VAR,
    DEEPSEEK_BASE_URL_ENV_VAR,
    LLMProviderConfig,
    MODEL_ENV_VAR,
    OPENAI_API_KEY_ENV_VAR,
)
from data_copilot.errors import LLMClientError
from data_copilot.llm.models import (
    LLMMessage,
    LLMResponse,
    LLMRole,
    LLMToolCall,
    LLMUsage,
    ToolDefinition,
)


class LLMClient(Protocol):
    """The only provider behavior required by the Agent loop."""

    def complete(
        self,
        messages: Sequence[LLMMessage],
        tools: Sequence[ToolDefinition],
    ) -> LLMResponse: ...


class OpenAILLMClient:
    """Official Responses API adapter using function tools and local history."""

    def __init__(
        self,
        *,
        model: str | None = None,
        api_key: str | None = None,
        sdk_client: Any | None = None,
    ) -> None:
        self.model = model or os.getenv(MODEL_ENV_VAR) or DEFAULT_MODEL
        if not self.model.strip():
            raise LLMClientError(f"{MODEL_ENV_VAR} cannot be empty.")
        self._provider_outputs: dict[int, tuple[Any, ...]] = {}
        self._pending_response: (
            tuple[int, LLMResponse, tuple[Any, ...]] | None
        ) = None
        if sdk_client is not None:
            self._client = sdk_client
            return

        resolved_api_key = api_key or os.getenv(OPENAI_API_KEY_ENV_VAR)
        if not resolved_api_key:
            raise LLMClientError(
                f"{OPENAI_API_KEY_ENV_VAR} is required for the OpenAI client."
            )
        try:
            from openai import OpenAI

            self._client = OpenAI(api_key=resolved_api_key)
        except Exception as exc:
            raise LLMClientError("The OpenAI client could not be initialized.") from exc

    def complete(
        self,
        messages: Sequence[LLMMessage],
        tools: Sequence[ToolDefinition],
    ) -> LLMResponse:
        try:
            self._bind_pending_response(messages)
            instructions, input_items = self._responses_input(messages)
            request: dict[str, Any] = {
                "model": self.model,
                "instructions": instructions,
                "input": input_items,
            }
            if tools:
                request.update(
                    {
                        "tools": [_responses_tool(tool) for tool in tools],
                        "tool_choice": "auto",
                        "parallel_tool_calls": False,
                    }
                )
            response = self._client.responses.create(
                **request,
            )
            output_items = tuple(response.output)
            tool_calls = tuple(
                LLMToolCall(
                    call_id=item.call_id,
                    name=item.name,
                    arguments=item.arguments,
                )
                for item in output_items
                if item.type == "function_call"
            )
            output_text = response.output_text
            normalized = LLMResponse(
                text=output_text if output_text else None,
                tool_calls=tool_calls,
                usage=_responses_usage(getattr(response, "usage", None)),
            )
            self._pending_response = (
                len(messages),
                normalized,
                output_items,
            )
            return normalized
        except LLMClientError:
            raise
        except Exception as exc:
            raise LLMClientError("The OpenAI request failed safely.") from exc

    def _bind_pending_response(self, messages: Sequence[LLMMessage]) -> None:
        if self._pending_response is None:
            return
        message_index, response, output_items = self._pending_response
        if message_index >= len(messages) or not _matches_response(
            messages[message_index], response
        ):
            raise LLMClientError(
                "The OpenAI conversation history changed unexpectedly."
            )
        self._provider_outputs[message_index] = output_items
        self._pending_response = None

    def _responses_input(
        self, messages: Sequence[LLMMessage]
    ) -> tuple[str | None, list[Any]]:
        instructions = "\n\n".join(
            message.content or ""
            for message in messages
            if message.role is LLMRole.SYSTEM
        ) or None
        input_items: list[Any] = []
        for index, message in enumerate(messages):
            provider_output = self._provider_outputs.get(index)
            if provider_output is not None:
                input_items.extend(provider_output)
                continue
            input_items.extend(_responses_items(message))
        return instructions, input_items


class DeepSeekLLMClient:
    """DeepSeek Chat Completions adapter using complete local history."""

    def __init__(
        self,
        *,
        model: str | None = None,
        api_key: str | None = None,
        base_url: str | None = None,
        sdk_client: Any | None = None,
    ) -> None:
        self.model = (
            model or os.getenv(MODEL_ENV_VAR) or DEFAULT_DEEPSEEK_MODEL
        )
        if not self.model.strip():
            raise LLMClientError(f"{MODEL_ENV_VAR} cannot be empty.")
        if sdk_client is not None:
            self._client = sdk_client
            return

        resolved_api_key = api_key or os.getenv(DEEPSEEK_API_KEY_ENV_VAR)
        if not resolved_api_key:
            raise LLMClientError(
                f"{DEEPSEEK_API_KEY_ENV_VAR} is required for the DeepSeek client."
            )
        resolved_base_url = (
            base_url
            or os.getenv(DEEPSEEK_BASE_URL_ENV_VAR)
            or DEFAULT_DEEPSEEK_BASE_URL
        )
        if not resolved_base_url.strip():
            raise LLMClientError(
                f"{DEEPSEEK_BASE_URL_ENV_VAR} cannot be empty."
            )
        try:
            from openai import OpenAI

            self._client = OpenAI(
                api_key=resolved_api_key,
                base_url=resolved_base_url,
            )
        except Exception as exc:
            raise LLMClientError(
                "The DeepSeek client could not be initialized."
            ) from exc

    def complete(
        self,
        messages: Sequence[LLMMessage],
        tools: Sequence[ToolDefinition],
    ) -> LLMResponse:
        try:
            request: dict[str, Any] = {
                "model": self.model,
                "messages": [_chat_message(message) for message in messages],
                "stream": False,
                "extra_body": {"thinking": {"type": "disabled"}},
            }
            if tools:
                request.update(
                    {
                        "tools": [_chat_tool(tool) for tool in tools],
                        "tool_choice": "auto",
                    }
                )
            response = self._client.chat.completions.create(**request)
            if not response.choices:
                raise LLMClientError("The DeepSeek response contained no choices.")
            message = response.choices[0].message
            raw_tool_calls = tuple(message.tool_calls or ())
            if any(call.type != "function" for call in raw_tool_calls):
                raise LLMClientError(
                    "The DeepSeek response contained an unsupported Tool type."
                )
            tool_calls = tuple(
                LLMToolCall(
                    call_id=call.id,
                    name=call.function.name,
                    arguments=call.function.arguments,
                )
                for call in raw_tool_calls
            )
            content = message.content
            return LLMResponse(
                text=content if content else None,
                tool_calls=tool_calls,
                usage=_chat_usage(getattr(response, "usage", None)),
            )
        except LLMClientError:
            raise
        except Exception as exc:
            raise LLMClientError("The DeepSeek request failed safely.") from exc


class FakeLLMClient:
    """Scripted client for deterministic Agent and CLI tests."""

    def __init__(self, responses: Sequence[LLMResponse]) -> None:
        self._responses = deque(responses)
        self.requests: list[
            tuple[tuple[LLMMessage, ...], tuple[ToolDefinition, ...]]
        ] = []

    def complete(
        self,
        messages: Sequence[LLMMessage],
        tools: Sequence[ToolDefinition],
    ) -> LLMResponse:
        self.requests.append((tuple(messages), tuple(tools)))
        if not self._responses:
            raise LLMClientError("Fake LLM has no scripted response remaining.")
        return self._responses.popleft()


def create_llm_client(config: LLMProviderConfig) -> LLMClient:
    """Select one explicit provider; unsupported values fail closed."""

    if config.provider == "openai":
        return OpenAILLMClient(model=config.model, api_key=config.api_key)
    if config.provider == "deepseek":
        return DeepSeekLLMClient(
            model=config.model,
            api_key=config.api_key,
            base_url=config.base_url,
        )
    raise LLMClientError("Unsupported LLM provider.")


def _responses_tool(tool: ToolDefinition) -> dict[str, object]:
    return {
        "type": "function",
        "name": tool.name,
        "description": tool.description,
        "parameters": tool.parameters,
        "strict": tool.strict,
    }


def _chat_tool(tool: ToolDefinition) -> dict[str, object]:
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.parameters,
            "strict": tool.strict,
        },
    }


def _chat_message(message: LLMMessage) -> dict[str, object]:
    mapped: dict[str, object] = {"role": message.role.value}
    if message.content is not None or message.role is LLMRole.ASSISTANT:
        mapped["content"] = message.content
    if message.tool_calls:
        mapped["tool_calls"] = [
            {
                "id": call.call_id,
                "type": "function",
                "function": {
                    "name": call.name,
                    "arguments": call.arguments,
                },
            }
            for call in message.tool_calls
        ]
    if message.role is LLMRole.TOOL:
        mapped["tool_call_id"] = message.tool_call_id or ""
    return mapped


def _responses_items(message: LLMMessage) -> list[dict[str, object]]:
    if message.role is LLMRole.SYSTEM:
        return []
    if message.role is LLMRole.TOOL:
        return [
            {
                "type": "function_call_output",
                "call_id": message.tool_call_id or "",
                "output": message.content or "",
            }
        ]
    items: list[dict[str, object]] = []
    if message.content is not None:
        items.append(
            {"role": message.role.value, "content": message.content}
        )
    if message.tool_calls:
        items.extend(
            {
                "type": "function_call",
                "call_id": call.call_id,
                "name": call.name,
                "arguments": call.arguments,
            }
            for call in message.tool_calls
        )
    return items


def _matches_response(message: LLMMessage, response: LLMResponse) -> bool:
    if message.role is not LLMRole.ASSISTANT:
        return False
    if message.tool_calls != response.tool_calls:
        return False
    if response.tool_calls:
        return message.content == response.text
    return (message.content or "").strip() == (response.text or "").strip()


def _responses_usage(usage: Any | None) -> LLMUsage | None:
    if usage is None:
        return None
    return LLMUsage(
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        total_tokens=usage.total_tokens,
    )


def _chat_usage(usage: Any | None) -> LLMUsage | None:
    if usage is None:
        return None
    return LLMUsage(
        input_tokens=usage.prompt_tokens,
        output_tokens=usage.completion_tokens,
        total_tokens=usage.total_tokens,
    )
