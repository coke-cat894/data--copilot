"""Typed, bounded evaluation, observable-trace, and review contracts."""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from data_copilot.llm import LLMUsage
from data_copilot.runtime import (
    RunOutcome,
    RuntimeFailureCategory,
    RuntimeStage,
)


class EvalCategory(str, Enum):
    FUNCTIONAL = "functional"
    GROUNDING = "grounding"
    NO_ANSWER = "no_answer"
    SAFETY = "safety"


class SemanticCheck(str, Enum):
    JOIN_MULTIPLICATION = "join_multiplication"
    EXPLAIN_PERFORMANCE = "explain_performance"


class EvidenceChannel(str, Enum):
    """The intentionally separate evidence sources available to Agents."""

    SEMANTIC = "semantic"
    DOCUMENT = "document"
    DATA = "data"
    DIAGNOSTIC = "diagnostic"
    PIPELINE = "pipeline"


class EvalMode(str, Enum):
    DETERMINISTIC = "deterministic"
    MOCK = "mock"
    LIVE = "live"
    SAFETY = "safety"


class MetricStatus(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    NOT_APPLICABLE = "not_applicable"


class ToolExecutionStatus(str, Enum):
    SUCCESS = "success"
    ERROR = "error"
    REUSED = "reused"


class FailureClassification(str, Enum):
    PRODUCT_BEHAVIOR_FAILURE = "product_behavior_failure"
    TOOL_ROUTING_FAILURE = "tool_routing_failure"
    EVIDENCE_FAILURE = "evidence_failure"
    SAFETY_FAILURE = "safety_failure"
    SCORER_LIMITATION = "scorer_limitation"
    FIXTURE_EVAL_ISSUE = "fixture_eval_issue"
    PROVIDER_TRANSIENT_FAILURE = "provider_transient_failure"
    UNKNOWN = "unknown"


class HumanReviewOutcome(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    UNCERTAIN = "uncertain"


class CausalClassification(str, Enum):
    OBSERVED_FACT = "observed_fact"
    SUPPORTED_HYPOTHESIS = "supported_hypothesis"
    CONFIRMED_ROOT_CAUSE = "confirmed_root_cause"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    CONFLICTING_EVIDENCE = "conflicting_evidence"


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
    semantic_grounding_answer_requirements: tuple[str, ...] = ()
    document_grounding_requirements: tuple[str, ...] = ()
    data_grounding_requirements: tuple[str, ...] = ()
    diagnostic_grounding_requirements: tuple[str, ...] = ()
    pipeline_grounding_requirements: tuple[str, ...] = ()
    causal_classification: CausalClassification | None = None
    causal_support_requirements: tuple[str, ...] = ()
    causal_forbidden_claims: tuple[str, ...] = ()
    conflict_handling_requirements: tuple[str, ...] = ()
    conflict_requires_alignment: bool = False
    uncertainty_requirements: tuple[str, ...] = ()
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
    diagnostic_grounding: bool | None = None
    pipeline_grounding: bool | None = None
    causal_discipline: bool | None = None
    uncertainty_handling: bool | None = None
    conflict_handling: bool | None = None


class EvalMetricDetail(BaseModel):
    """Bounded explanation of one independent automatic metric decision."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    metric_name: str = Field(min_length=1, max_length=80)
    status: MetricStatus
    matched_requirements: tuple[str, ...] = Field(default=(), max_length=50)
    missing_requirements: tuple[str, ...] = Field(default=(), max_length=50)
    forbidden_claims_detected: tuple[str, ...] = Field(default=(), max_length=50)
    evidence_requirement_satisfied: bool | None = None
    scorer_note: str = Field(min_length=1, max_length=1000)


class EvalTraceEvent(BaseModel):
    """One observable sanitized Tool execution; never hidden reasoning."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    round_number: int = Field(ge=1, le=5)
    remaining_tool_budget: int = Field(ge=0, le=5)
    tool_name: str = Field(min_length=1, max_length=128)
    sanitized_arguments: str = Field(min_length=1, max_length=2000)
    evidence_channel: EvidenceChannel | None = None
    evidence_summary: str = Field(min_length=1, max_length=1000)


class TraceEvidenceSummary(BaseModel):
    """Bounded summary of an observable Evidence envelope."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    channel: EvidenceChannel | None = None
    summary: str = Field(min_length=1, max_length=1000)
    truncated: bool = False


class TraceToolExecution(BaseModel):
    """One actually executed Tool call, never a stale proposal."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    tool_name: str = Field(min_length=1, max_length=128)
    sanitized_arguments: str = Field(min_length=1, max_length=2000)
    status: ToolExecutionStatus
    evidence: TraceEvidenceSummary
    sanitized_error_category: str | None = Field(default=None, max_length=128)
    sanitized_error_message: str | None = Field(default=None, max_length=500)
    failure_category: RuntimeFailureCategory | None = None
    failure_stage: RuntimeStage | None = None
    retryable: bool | None = None
    tool_executed: bool = True
    evidence_produced: bool = False


class TraceProviderAttempt(BaseModel):
    """One observable provider invocation, including failed attempts."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    stage: RuntimeStage
    attempt_number: int = Field(ge=1, le=3)
    succeeded: bool
    retryable: bool = False
    retry_performed: bool = False
    failure_category: RuntimeFailureCategory | None = None
    sanitized_message: str | None = Field(default=None, max_length=500)


class TraceContextAccounting(BaseModel):
    """Deterministic character accounting for one provider-visible request.

    ``estimated_input_tokens`` is a local planning estimate, not provider usage
    or billing telemetry. Provider-reported tokens remain separate on
    :class:`TraceUsage`.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    system_chars: int = Field(ge=0)
    user_chars: int = Field(ge=0)
    tool_schema_chars: int = Field(ge=0)
    assistant_history_chars: int = Field(ge=0)
    tool_error_chars: int = Field(ge=0)
    other_tool_history_chars: int = Field(ge=0)
    semantic_evidence_chars: int = Field(ge=0)
    document_evidence_chars: int = Field(ge=0)
    data_evidence_chars: int = Field(ge=0)
    diagnostic_evidence_chars: int = Field(ge=0)
    pipeline_evidence_chars: int = Field(ge=0)
    total_context_chars: int = Field(ge=0)
    estimated_input_tokens: int = Field(ge=0)
    estimation_method: str = Field(default="ceil(serialized_chars/4)")


class TraceRound(BaseModel):
    """One provider-visible model decision and its optional execution."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    round_number: int = Field(ge=1, le=6)
    tool_budget_before: int = Field(ge=0, le=5)
    tools_enabled: bool
    final_synthesis: bool = False
    visible_model_output: str | None = Field(default=None, max_length=2000)
    visible_model_output_truncated: bool = False
    requested_tool_count: int = Field(ge=0, le=50)
    executed_tool: TraceToolExecution | None = None
    context: TraceContextAccounting


class TraceFinalAnswer(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    response: str = Field(max_length=12000)
    original_chars: int = Field(ge=0)
    truncated: bool = False


class TraceUsage(BaseModel):
    """Provider usage and local estimates, explicitly kept separate."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    provider_reported_input_tokens: int | None = Field(default=None, ge=0)
    provider_reported_output_tokens: int | None = Field(default=None, ge=0)
    provider_reported_total_tokens: int | None = Field(default=None, ge=0)
    latency_ms: float | None = Field(default=None, ge=0)
    tool_calls: int = Field(ge=0, le=5)
    rounds: int = Field(ge=0, le=6)
    request_context_chars: int = Field(default=0, ge=0)
    estimated_input_tokens: int = Field(default=0, ge=0)
    estimation_method: str = Field(default="ceil(serialized_chars/4)")
    tool_schema_chars: int = Field(default=0, ge=0)
    semantic_evidence_chars: int = Field(default=0, ge=0)
    document_evidence_chars: int = Field(default=0, ge=0)
    data_evidence_chars: int = Field(default=0, ge=0)
    diagnostic_evidence_chars: int = Field(default=0, ge=0)
    pipeline_evidence_chars: int = Field(default=0, ge=0)
    evidence_chars_transmitted: int = Field(default=0, ge=0)
    repeated_evidence_chars: int = Field(default=0, ge=0)
    duplicate_evidence_chars_avoided: int = Field(default=0, ge=0)
    provider_attempts: int = Field(default=0, ge=0, le=20)
    provider_retries: int = Field(default=0, ge=0, le=12)


class EvalTrace(BaseModel):
    """Versioned safe trace of observable behavior, never chain-of-thought."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: str = Field(default="1.2", pattern=r"^\d+\.\d+$")
    run_id: str | None = Field(default=None, max_length=160)
    case_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]*$")
    provider: str | None = Field(default=None, max_length=128)
    model: str | None = Field(default=None, max_length=256)
    eval_mode: EvalMode = EvalMode.DETERMINISTIC
    outcome: RunOutcome
    original_question: str = Field(max_length=4000)
    original_question_chars: int = Field(ge=0)
    original_question_truncated: bool = False
    rounds: tuple[TraceRound, ...] = Field(default=(), max_length=6)
    provider_attempts: tuple[TraceProviderAttempt, ...] = Field(
        default=(), max_length=20
    )
    final_answer: TraceFinalAnswer | None = None
    usage: TraceUsage
    sanitized_error_category: str | None = Field(default=None, max_length=128)
    sanitized_error_message: str | None = Field(default=None, max_length=500)
    warnings: tuple[str, ...] = Field(default=(), max_length=20)
    serialized_truncated: bool = False


class EvalReproducibility(BaseModel):
    """Non-secret configuration needed to interpret a saved eval run."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    eval_mode: EvalMode = EvalMode.DETERMINISTIC
    suite: str | None = Field(default=None, max_length=256)
    selector: tuple[str, ...] = Field(default=(), max_length=200)
    tool_budget: int = Field(default=5, ge=0, le=5)
    provider_max_retries: int | None = Field(default=None, ge=0, le=2)
    prompt_fingerprint: str | None = Field(
        default=None, pattern=r"^sha256:[0-9a-f]{64}$"
    )
    scorer_fingerprint: str | None = Field(
        default=None, pattern=r"^sha256:[0-9a-f]{64}$"
    )
    fixture_fingerprint: str | None = Field(
        default=None, pattern=r"^sha256:[0-9a-f]{64}$"
    )


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
    metric_details: tuple[EvalMetricDetail, ...] = ()
    notes: tuple[str, ...] = ()
    needs_human_grounding_review: bool = False
    trace: tuple[EvalTraceEvent, ...] = ()
    safe_trace: EvalTrace | None = None
    automatic_failure_classification: FailureClassification | None = None


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
    diagnostic_grounding_accuracy: float | None = None
    pipeline_grounding_accuracy: float | None = None
    causal_discipline_accuracy: float | None = None
    uncertainty_handling_accuracy: float | None = None
    conflict_handling_accuracy: float | None = None
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

    artifact_schema_version: str = "5.1"
    run_id: str | None = None
    provider: str
    model: str
    timestamp: datetime
    git_commit: str | None
    git_dirty: bool | None
    reproducibility: EvalReproducibility = EvalReproducibility()
    results: tuple[EvalResult, ...]
    summary: EvalSummary


class HumanReviewRecord(BaseModel):
    """Immutable review overlay that never rewrites an automatic artifact."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: str = "1.0"
    review_id: str = Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9._-]*$")
    eval_run_id: str = Field(min_length=1, max_length=160)
    case_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]*$")
    automatic_artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    original_automatic_metrics: EvalChecks
    original_metric_details: tuple[EvalMetricDetail, ...] = Field(
        default=(), max_length=30
    )
    original_automatic_passed: bool
    original_safety_passed: bool | None = None
    original_automatic_classification: FailureClassification | None = None
    grounded_human_outcome: HumanReviewOutcome
    failure_classification: FailureClassification
    rationale: str = Field(min_length=1, max_length=2000)
    reviewer_id: str | None = Field(default=None, max_length=128)
    reviewed_at: datetime
