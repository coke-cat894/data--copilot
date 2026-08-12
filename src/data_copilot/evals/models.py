"""Typed, deliberately small evaluation contracts."""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from data_copilot.llm import LLMUsage


class EvalCategory(str, Enum):
    FUNCTIONAL = "functional"
    GROUNDING = "grounding"
    NO_ANSWER = "no_answer"
    SAFETY = "safety"


class SemanticCheck(str, Enum):
    JOIN_MULTIPLICATION = "join_multiplication"
    EXPLAIN_PERFORMANCE = "explain_performance"


class EvidenceChannel(str, Enum):
    """The three intentionally separate Phase 3 evidence sources."""

    SEMANTIC = "semantic"
    DOCUMENT = "document"
    DATA = "data"


class EvalCase(BaseModel):
    """One deterministic or human-reviewable Agent evaluation case."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    case_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]*$")
    category: EvalCategory
    question: str = Field(min_length=1)
    dataset: str | None = Field(default=None, min_length=1)
    database: str | None = Field(default=None, min_length=1)
    expected_behavior: str = Field(min_length=1)
    expected_tools: tuple[str, ...] = ()
    allowed_extra_tools: tuple[str, ...] = ()
    forbidden_tools: tuple[str, ...] = ()
    expected_values: tuple[str, ...] = ()
    expected_columns: tuple[str, ...] = ()
    answer_requirements: tuple[str, ...] = ()
    answer_requirement_groups: tuple[tuple[str, ...], ...] = ()
    answer_forbidden_claims: tuple[str, ...] = ()
    semantic_checks: tuple[SemanticCheck, ...] = ()
    expected_evidence_channels: tuple[EvidenceChannel, ...] = ()
    forbidden_evidence_channels: tuple[EvidenceChannel, ...] = ()
    semantic_grounding_requirements: tuple[str, ...] = ()
    document_grounding_requirements: tuple[str, ...] = ()
    data_grounding_requirements: tuple[str, ...] = ()
    safety_requirements: tuple[str, ...] = ()
    safety_requirement_groups: tuple[tuple[str, ...], ...] = ()
    safety_forbidden_claims: tuple[str, ...] = ()
    max_tool_calls: int = Field(default=5, ge=0, le=5)
    requires_live_llm: bool = True
    needs_human_grounding_review: bool = False

    @model_validator(mode="after")
    def validate_tools(self) -> "EvalCase":
        if (self.dataset is None) == (self.database is None):
            raise ValueError("Eval case requires exactly one source.")
        groups = (
            self.expected_tools,
            self.allowed_extra_tools,
            self.forbidden_tools,
        )
        if any(len(group) != len(set(group)) for group in groups):
            raise ValueError("Tool lists cannot contain duplicates.")
        if set(self.expected_tools) & set(self.forbidden_tools):
            raise ValueError("Expected Tools cannot also be forbidden.")
        if len(self.semantic_checks) != len(set(self.semantic_checks)):
            raise ValueError("Semantic checks cannot contain duplicates.")
        if len(self.expected_evidence_channels) != len(
            set(self.expected_evidence_channels)
        ):
            raise ValueError("Expected Evidence channels cannot contain duplicates.")
        if len(self.forbidden_evidence_channels) != len(
            set(self.forbidden_evidence_channels)
        ):
            raise ValueError("Forbidden Evidence channels cannot contain duplicates.")
        if set(self.expected_evidence_channels) & set(
            self.forbidden_evidence_channels
        ):
            raise ValueError("Evidence channels cannot be expected and forbidden.")
        return self


class EvalChecks(BaseModel):
    model_config = ConfigDict(frozen=True)

    tool_selection: bool
    answer_requirements: bool
    forbidden_claims: bool
    efficiency: bool
    semantic_grounding: bool | None = None
    document_grounding: bool | None = None
    data_grounding: bool | None = None


class EvalResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    case_id: str
    category: EvalCategory
    question: str
    passed: bool
    safety_passed: bool | None = None
    answer: str | None
    tool_calls: tuple[str, ...]
    tool_call_count: int
    rounds: int
    latency_ms: float = Field(ge=0)
    expected_tools: tuple[str, ...]
    actual_tools: tuple[str, ...]
    evidence_channels: tuple[EvidenceChannel, ...] = ()
    checks: EvalChecks
    answer_check_applicable: bool
    grounding_check_applicable: bool
    usage: LLMUsage | None = None
    errors: tuple[str, ...] = ()
    metric_failures: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()
    needs_human_grounding_review: bool = False


class EvalSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    cases: int
    passed: int
    failed: int
    task_success_rate: float
    tool_selection_accuracy: float | None
    answer_accuracy: float | None
    grounding_accuracy: float | None
    semantic_grounding_accuracy: float | None = None
    document_grounding_accuracy: float | None = None
    data_grounding_accuracy: float | None = None
    no_answer_accuracy: float | None
    safety_pass_rate: float | None
    efficiency_accuracy: float
    average_tool_calls: float
    average_rounds: float
    average_latency_ms: float
    input_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None
    needs_human_review: int


class EvalRun(BaseModel):
    model_config = ConfigDict(frozen=True)

    provider: str
    model: str
    timestamp: datetime
    git_commit: str | None
    git_dirty: bool | None
    results: tuple[EvalResult, ...]
    summary: EvalSummary
