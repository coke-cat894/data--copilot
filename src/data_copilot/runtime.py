"""Small program-owned runtime failure, retry, and outcome contracts."""

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from data_copilot.errors import (
    AgentExecutionError,
    ConfigurationError,
    DataCopilotError,
    DatabaseConnectionError,
    DiagnosticEvidenceBuildError,
    DiagnosticResourceError,
    DiagnosticTimeoutError,
    DocumentEvidenceBuildError,
    EvidenceBuildError,
    FinalSynthesisError,
    LLMClientError,
    LLMFatalError,
    LLMMalformedResponseError,
    LLMTransientError,
    PipelineEvidenceBuildError,
    PipelineError,
    QueryTimeoutError,
    SQLExecutionError,
    SQLValidationError,
    SemanticEvidenceBuildError,
    ToolArgumentError,
    ToolDispatchError,
)


DEFAULT_PROVIDER_MAX_RETRIES = 1
MAX_PROVIDER_RETRIES = 2


class RuntimeFailureCategory(str, Enum):
    PROVIDER_TRANSIENT = "provider_transient"
    PROVIDER_FATAL = "provider_fatal"
    PROVIDER_MALFORMED_RESPONSE = "provider_malformed_response"
    TOOL_VALIDATION = "tool_validation"
    TOOL_EXECUTION = "tool_execution"
    DATABASE_CONNECTION = "database_connection"
    DATABASE_TIMEOUT = "database_timeout"
    SQL_VALIDATION = "sql_validation"
    EVIDENCE_BUILD = "evidence_build"
    RESOURCE_UNAVAILABLE = "resource_unavailable"
    FINAL_SYNTHESIS = "final_synthesis"
    BUDGET_EXHAUSTED = "budget_exhausted"
    CONFIGURATION = "configuration"
    UNKNOWN_RUNTIME = "unknown_runtime"


class RuntimeStage(str, Enum):
    PROVIDER_DECISION = "provider_decision"
    TOOL_VALIDATION = "tool_validation"
    TOOL_EXECUTION = "tool_execution"
    EVIDENCE_BUILD = "evidence_build"
    FINAL_SYNTHESIS = "final_synthesis"
    CONFIGURATION = "configuration"


class RunOutcome(str, Enum):
    SUCCESS = "success"
    SAFE_NO_ANSWER = "safe_no_answer"
    PARTIAL = "partial"
    RUNTIME_FAILURE = "runtime_failure"
    SAFETY_REJECTION = "safety_rejection"


class ProviderRetryPolicy(BaseModel):
    """Explicit bounded retries for provider decisions only."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    max_retries: int = Field(
        default=DEFAULT_PROVIDER_MAX_RETRIES,
        ge=0,
        le=MAX_PROVIDER_RETRIES,
    )


class RuntimeFailure(BaseModel):
    """Sanitized observable failure; never contains driver/provider internals."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    category: RuntimeFailureCategory
    stage: RuntimeStage
    retryable: bool
    safe_message: str = Field(min_length=1, max_length=500)
    tool_executed: bool = False
    evidence_produced: bool = False


def classify_runtime_failure(
    error: Exception,
    *,
    stage: RuntimeStage,
    tool_executed: bool = False,
) -> RuntimeFailure:
    """Map an internal exception to a small safe deterministic taxonomy."""

    category = RuntimeFailureCategory.UNKNOWN_RUNTIME
    retryable = False
    message = "The operation failed safely before a result was produced."
    if isinstance(error, LLMTransientError):
        category = RuntimeFailureCategory.PROVIDER_TRANSIENT
        retryable = True
        message = "The model provider is temporarily unavailable."
    elif isinstance(error, LLMMalformedResponseError):
        category = RuntimeFailureCategory.PROVIDER_MALFORMED_RESPONSE
        message = "The model provider returned an invalid response."
    elif isinstance(error, (LLMFatalError, LLMClientError)):
        category = RuntimeFailureCategory.PROVIDER_FATAL
        message = "The model provider could not complete the request."
    elif isinstance(error, FinalSynthesisError):
        category = RuntimeFailureCategory.FINAL_SYNTHESIS
        stage = RuntimeStage.FINAL_SYNTHESIS
        message = (
            "Final synthesis failed after the available Evidence was collected."
        )
    elif isinstance(error, AgentExecutionError) and isinstance(
        error.__cause__, LLMClientError
    ):
        return classify_runtime_failure(
            error.__cause__,
            stage=stage,
            tool_executed=tool_executed,
        )
    elif isinstance(error, ToolDispatchError):
        category = RuntimeFailureCategory.TOOL_VALIDATION
        message = "The requested Tool call was rejected by program validation."
    elif isinstance(error, SQLValidationError):
        category = RuntimeFailureCategory.SQL_VALIDATION
        message = "The proposed SQL was rejected by the read-only safety policy."
    elif isinstance(error, (QueryTimeoutError, DiagnosticTimeoutError)):
        category = RuntimeFailureCategory.DATABASE_TIMEOUT
        message = "The database operation exceeded its configured execution limit."
    elif isinstance(error, DatabaseConnectionError):
        category = RuntimeFailureCategory.DATABASE_CONNECTION
        message = "The configured database resource is currently unavailable."
    elif isinstance(
        error,
        (
            EvidenceBuildError,
            SemanticEvidenceBuildError,
            DocumentEvidenceBuildError,
            DiagnosticEvidenceBuildError,
            PipelineEvidenceBuildError,
        ),
    ):
        category = RuntimeFailureCategory.EVIDENCE_BUILD
        stage = RuntimeStage.EVIDENCE_BUILD
        message = "The Tool result could not be converted into bounded Evidence."
    elif isinstance(error, (DiagnosticResourceError, PipelineError)):
        category = RuntimeFailureCategory.RESOURCE_UNAVAILABLE
        message = "The configured diagnostic resource is unavailable."
    elif isinstance(error, ConfigurationError):
        category = RuntimeFailureCategory.CONFIGURATION
        stage = RuntimeStage.CONFIGURATION
        message = "The required runtime configuration is unavailable or invalid."
    elif isinstance(error, (SQLExecutionError, DataCopilotError)):
        category = RuntimeFailureCategory.TOOL_EXECUTION
        message = "The Tool failed safely before producing Evidence."
    return RuntimeFailure(
        category=category,
        stage=stage,
        retryable=retryable,
        safe_message=message,
        tool_executed=tool_executed,
        evidence_produced=False,
    )


def is_nonexecuting_tool_failure(error: Exception) -> bool:
    """Return true when validation rejected a Tool before its operation ran."""

    return isinstance(error, (ToolArgumentError, ToolDispatchError, SQLValidationError))
