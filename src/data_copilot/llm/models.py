"""Provider-neutral conversation and Tool-call models."""

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class LLMRole(str, Enum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class LLMToolCall(BaseModel):
    """One untrusted structured function request returned by an LLM."""

    model_config = ConfigDict(frozen=True)

    call_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    arguments: str


class LLMMessage(BaseModel):
    """One in-process conversation item."""

    model_config = ConfigDict(frozen=True)

    role: LLMRole
    content: str | None = None
    tool_calls: tuple[LLMToolCall, ...] = ()
    tool_call_id: str | None = None

    @model_validator(mode="after")
    def validate_role_fields(self) -> "LLMMessage":
        if self.role is LLMRole.TOOL:
            if self.tool_call_id is None or self.content is None:
                raise ValueError("Tool messages require tool_call_id and content.")
            if self.tool_calls:
                raise ValueError("Tool messages cannot request Tools.")
        elif self.tool_call_id is not None:
            raise ValueError("Only Tool messages may set tool_call_id.")
        if self.tool_calls and self.role is not LLMRole.ASSISTANT:
            raise ValueError("Only assistant messages may request Tools.")
        if (
            self.content is None
            and self.role is not LLMRole.ASSISTANT
            and not self.tool_calls
        ):
            raise ValueError("Non-assistant messages require content.")
        return self


class ToolDefinition(BaseModel):
    """One static function definition exposed to an LLM provider."""

    model_config = ConfigDict(frozen=True)

    name: str
    description: str
    parameters: dict[str, Any]
    strict: bool = True


class LLMResponse(BaseModel):
    """Normalized assistant text and function requests from one provider call."""

    model_config = ConfigDict(frozen=True)

    text: str | None = None
    tool_calls: tuple[LLMToolCall, ...] = ()
    usage: "LLMUsage | None" = None


class LLMUsage(BaseModel):
    """Provider-neutral token usage for one or more model requests."""

    model_config = ConfigDict(frozen=True)

    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    total_tokens: int = Field(ge=0)

    def __add__(self, other: "LLMUsage") -> "LLMUsage":
        return LLMUsage(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            total_tokens=self.total_tokens + other.total_tokens,
        )
