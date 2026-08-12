from types import SimpleNamespace

import pytest

from data_copilot.errors import LLMClientError
from data_copilot.llm import (
    DeepSeekLLMClient,
    FakeLLMClient,
    LLMMessage,
    LLMResponse,
    LLMRole,
    LLMToolCall,
    LLMUsage,
    OpenAILLMClient,
    ToolDefinition,
)


class FakeResponses:
    def __init__(
        self,
        responses: list[object] | None = None,
        error: Exception | None = None,
    ) -> None:
        self.responses = list(responses or [])
        self.error = error
        self.requests: list[dict[str, object]] = []

    def create(self, **kwargs: object) -> object:
        self.requests.append(kwargs)
        if self.error is not None:
            raise self.error
        return self.responses.pop(0)


def _sdk(responses: FakeResponses) -> SimpleNamespace:
    return SimpleNamespace(responses=responses)


class FakeChatCompletions:
    def __init__(
        self,
        responses: list[object] | None = None,
        error: Exception | None = None,
    ) -> None:
        self.responses = list(responses or [])
        self.error = error
        self.requests: list[dict[str, object]] = []

    def create(self, **kwargs: object) -> object:
        self.requests.append(kwargs)
        if self.error is not None:
            raise self.error
        return self.responses.pop(0)


def _chat_sdk(completions: FakeChatCompletions) -> SimpleNamespace:
    return SimpleNamespace(
        chat=SimpleNamespace(completions=completions)
    )


def _chat_response(
    *, content: str | None = None, tool_calls: list[object] | None = None
) -> SimpleNamespace:
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content=content,
                    tool_calls=tool_calls,
                )
            )
        ]
    )


def _chat_tool_call(
    call_id: str, name: str, arguments: str
) -> SimpleNamespace:
    return SimpleNamespace(
        id=call_id,
        type="function",
        function=SimpleNamespace(name=name, arguments=arguments),
    )


def _tool_definition() -> ToolDefinition:
    return ToolDefinition(
        name="inspect_dataset",
        description="Inspect shape and schema.",
        parameters={
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        },
    )


def test_openai_responses_client_maps_tools_calls_outputs_and_continuation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reasoning_item = SimpleNamespace(type="reasoning", id="reasoning_1")
    function_item = SimpleNamespace(
        type="function_call",
        call_id="call_1",
        name="inspect_dataset",
        arguments="{}",
    )
    final_message_item = SimpleNamespace(type="message", id="message_1")
    next_call_item = SimpleNamespace(
        type="function_call",
        call_id="call_2",
        name="check_data_quality",
        arguments='{"columns":null}',
    )
    responses = FakeResponses(
        [
            SimpleNamespace(
                output=[reasoning_item, function_item], output_text=""
            ),
            SimpleNamespace(
                output=[final_message_item], output_text="Eight columns."
            ),
            SimpleNamespace(output=[next_call_item], output_text=""),
        ]
    )
    monkeypatch.setenv("DATA_COPILOT_MODEL", "configured-model")
    client = OpenAILLMClient(sdk_client=_sdk(responses))
    initial_messages = (
        LLMMessage(role=LLMRole.SYSTEM, content="rules"),
        LLMMessage(role=LLMRole.USER, content="question"),
    )

    first_result = client.complete(initial_messages, (_tool_definition(),))

    assert first_result == LLMResponse(
        tool_calls=(
            LLMToolCall(
                call_id="call_1",
                name="inspect_dataset",
                arguments="{}",
            ),
        )
    )
    first_request = responses.requests[0]
    assert first_request["model"] == "configured-model"
    assert first_request["instructions"] == "rules"
    assert first_request["input"] == [
        {"role": "user", "content": "question"}
    ]
    assert first_request["parallel_tool_calls"] is False
    assert first_request["tool_choice"] == "auto"
    assert first_request["tools"] == [
        {
            "type": "function",
            "name": "inspect_dataset",
            "description": "Inspect shape and schema.",
            "parameters": _tool_definition().parameters,
            "strict": True,
        }
    ]
    assert "previous_response_id" not in first_request
    assert all(tool["type"] == "function" for tool in first_request["tools"])

    tool_messages = initial_messages + (
        LLMMessage(
            role=LLMRole.ASSISTANT,
            tool_calls=first_result.tool_calls,
        ),
        LLMMessage(
            role=LLMRole.TOOL,
            content="DATA_EVIDENCE\n{}",
            tool_call_id="call_1",
        ),
    )

    second_result = client.complete(tool_messages, (_tool_definition(),))

    assert second_result == LLMResponse(text="Eight columns.")
    second_input = responses.requests[1]["input"]
    assert second_input[:3] == [
        {"role": "user", "content": "question"},
        reasoning_item,
        function_item,
    ]
    assert second_input[-1] == {
        "type": "function_call_output",
        "call_id": "call_1",
        "output": "DATA_EVIDENCE\n{}",
    }

    follow_up_messages = tool_messages + (
        LLMMessage(role=LLMRole.ASSISTANT, content=second_result.text),
        LLMMessage(role=LLMRole.USER, content="quality?"),
    )

    third_result = client.complete(follow_up_messages, (_tool_definition(),))

    assert third_result.tool_calls[0].call_id == "call_2"
    third_input = responses.requests[2]["input"]
    assert final_message_item in third_input
    assert third_input[-1] == {"role": "user", "content": "quality?"}


def test_openai_client_requires_environment_key_without_injected_sdk(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    with pytest.raises(LLMClientError, match="OPENAI_API_KEY"):
        OpenAILLMClient()


def test_openai_provider_exception_is_wrapped_without_details() -> None:
    responses = FakeResponses(error=RuntimeError("secret-provider-detail"))
    client = OpenAILLMClient(model="test-model", sdk_client=_sdk(responses))

    with pytest.raises(LLMClientError, match="failed safely") as captured:
        client.complete(
            (LLMMessage(role=LLMRole.USER, content="question"),),
            (_tool_definition(),),
        )

    assert "secret-provider-detail" not in str(captured.value)


def test_openai_client_rejects_divergent_continuation_history() -> None:
    function_item = SimpleNamespace(
        type="function_call",
        call_id="call_1",
        name="inspect_dataset",
        arguments="{}",
    )
    responses = FakeResponses(
        [SimpleNamespace(output=[function_item], output_text="")]
    )
    client = OpenAILLMClient(model="test-model", sdk_client=_sdk(responses))
    initial = (LLMMessage(role=LLMRole.USER, content="question"),)

    client.complete(initial, (_tool_definition(),))

    with pytest.raises(LLMClientError, match="history changed"):
        client.complete(
            initial + (LLMMessage(role=LLMRole.ASSISTANT, content="wrong"),),
            (_tool_definition(),),
        )


def test_deepseek_client_maps_plain_final_answer_and_strict_tool_schema() -> None:
    completions = FakeChatCompletions(
        [_chat_response(content="Eight columns.")]
    )
    client = DeepSeekLLMClient(
        model="deepseek-v4-flash",
        sdk_client=_chat_sdk(completions),
    )

    result = client.complete(
        (
            LLMMessage(role=LLMRole.SYSTEM, content="rules"),
            LLMMessage(role=LLMRole.USER, content="question"),
        ),
        (_tool_definition(),),
    )

    assert result == LLMResponse(text="Eight columns.")
    request = completions.requests[0]
    assert request == {
        "model": "deepseek-v4-flash",
        "messages": [
            {"role": "system", "content": "rules"},
            {"role": "user", "content": "question"},
        ],
        "tools": [
            {
                "type": "function",
                "function": {
                    "name": "inspect_dataset",
                    "description": "Inspect shape and schema.",
                    "parameters": _tool_definition().parameters,
                    "strict": True,
                },
            }
        ],
        "tool_choice": "auto",
        "stream": False,
        "extra_body": {"thinking": {"type": "disabled"}},
    }


def test_deepseek_client_preserves_sequential_tool_calls_and_evidence() -> None:
    first_call = _chat_tool_call(
        "call_1", "inspect_dataset", '{"requested":true}'
    )
    second_call = _chat_tool_call(
        "call_2", "profile_dataset", '{"columns":["amount"]}'
    )
    completions = FakeChatCompletions(
        [
            _chat_response(tool_calls=[first_call]),
            _chat_response(tool_calls=[second_call]),
            _chat_response(content="The amount profile is grounded."),
        ]
    )
    client = DeepSeekLLMClient(
        model="deepseek-v4-flash",
        sdk_client=_chat_sdk(completions),
    )
    messages = (
        LLMMessage(role=LLMRole.SYSTEM, content="rules"),
        LLMMessage(role=LLMRole.USER, content="analyze"),
    )

    first = client.complete(messages, (_tool_definition(),))

    assert first.tool_calls == (
        LLMToolCall(
            call_id="call_1",
            name="inspect_dataset",
            arguments='{"requested":true}',
        ),
    )
    messages += (
        LLMMessage(role=LLMRole.ASSISTANT, tool_calls=first.tool_calls),
        LLMMessage(
            role=LLMRole.TOOL,
            tool_call_id="call_1",
            content='DATA_EVIDENCE\n{"operation":"inspect_dataset"}',
        ),
    )

    second = client.complete(messages, (_tool_definition(),))

    assert second.tool_calls[0].call_id == "call_2"
    assert second.tool_calls[0].arguments == '{"columns":["amount"]}'
    second_request_messages = completions.requests[1]["messages"]
    assert second_request_messages[-2]["tool_calls"][0]["id"] == "call_1"
    assert second_request_messages[-1] == {
        "role": "tool",
        "content": 'DATA_EVIDENCE\n{"operation":"inspect_dataset"}',
        "tool_call_id": "call_1",
    }
    messages += (
        LLMMessage(role=LLMRole.ASSISTANT, tool_calls=second.tool_calls),
        LLMMessage(
            role=LLMRole.TOOL,
            tool_call_id="call_2",
            content='DATA_EVIDENCE\n{"operation":"profile_dataset"}',
        ),
    )

    final = client.complete(messages, (_tool_definition(),))

    assert final == LLMResponse(text="The amount profile is grounded.")
    final_messages = completions.requests[2]["messages"]
    assert final_messages[-2]["tool_calls"][0]["id"] == "call_2"
    assert final_messages[-1]["tool_call_id"] == "call_2"


def test_deepseek_client_requires_key_and_wraps_provider_details(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    with pytest.raises(LLMClientError, match="DEEPSEEK_API_KEY"):
        DeepSeekLLMClient()

    completions = FakeChatCompletions(
        error=RuntimeError("secret-provider-detail")
    )
    client = DeepSeekLLMClient(
        model="deepseek-v4-flash",
        sdk_client=_chat_sdk(completions),
    )
    with pytest.raises(LLMClientError, match="failed safely") as captured:
        client.complete(
            (LLMMessage(role=LLMRole.USER, content="question"),),
            (_tool_definition(),),
        )
    assert "secret-provider-detail" not in str(captured.value)


def test_provider_usage_is_normalized_without_changing_protocol() -> None:
    openai_responses = FakeResponses(
        [
            SimpleNamespace(
                output=[],
                output_text="OpenAI answer",
                usage=SimpleNamespace(
                    input_tokens=11,
                    output_tokens=7,
                    total_tokens=18,
                ),
            )
        ]
    )
    deepseek_completions = FakeChatCompletions(
        [
            SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(
                            content="DeepSeek answer", tool_calls=None
                        )
                    )
                ],
                usage=SimpleNamespace(
                    prompt_tokens=13,
                    completion_tokens=9,
                    total_tokens=22,
                ),
            )
        ]
    )

    openai_result = OpenAILLMClient(
        model="test-model", sdk_client=_sdk(openai_responses)
    ).complete(
        (LLMMessage(role=LLMRole.USER, content="question"),),
        (_tool_definition(),),
    )
    deepseek_result = DeepSeekLLMClient(
        model="deepseek-v4-flash",
        sdk_client=_chat_sdk(deepseek_completions),
    ).complete(
        (LLMMessage(role=LLMRole.USER, content="question"),),
        (_tool_definition(),),
    )

    assert openai_result.usage == LLMUsage(
        input_tokens=11, output_tokens=7, total_tokens=18
    )
    assert deepseek_result.usage == LLMUsage(
        input_tokens=13, output_tokens=9, total_tokens=22
    )


def test_fake_client_records_snapshots_and_fails_when_exhausted() -> None:
    response = LLMResponse(text="answer")
    client = FakeLLMClient([response])
    messages = (LLMMessage(role=LLMRole.USER, content="question"),)

    assert client.complete(messages, (_tool_definition(),)) == response
    assert client.requests[0][0] == messages
    with pytest.raises(LLMClientError, match="no scripted"):
        client.complete(messages, (_tool_definition(),))


def test_provider_clients_omit_tool_configuration_when_tools_are_disabled() -> None:
    openai_responses = FakeResponses(
        [SimpleNamespace(output=[], output_text="Final synthesis")]
    )
    deepseek_completions = FakeChatCompletions(
        [_chat_response(content="Final synthesis")]
    )
    messages = (LLMMessage(role=LLMRole.USER, content="finalize"),)

    OpenAILLMClient(
        model="test-model", sdk_client=_sdk(openai_responses)
    ).complete(messages, ())
    DeepSeekLLMClient(
        model="deepseek-v4-flash",
        sdk_client=_chat_sdk(deepseek_completions),
    ).complete(messages, ())

    assert "tools" not in openai_responses.requests[0]
    assert "tool_choice" not in openai_responses.requests[0]
    assert "parallel_tool_calls" not in openai_responses.requests[0]
    assert "tools" not in deepseek_completions.requests[0]
    assert "tool_choice" not in deepseek_completions.requests[0]
