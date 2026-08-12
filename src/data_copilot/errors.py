"""Domain errors exposed by Data Copilot's deterministic boundaries."""


class DataCopilotError(Exception):
    """Base class for expected Data Copilot domain failures."""


class DatasetRegistrationError(DataCopilotError):
    """Raised when a dataset cannot be registered safely."""


class DatasetFileNotFoundError(DatasetRegistrationError):
    """Raised when a dataset file is missing or is not a regular file."""


class DatasetPathNotAllowedError(DatasetRegistrationError):
    """Raised when a dataset resolves outside the configured roots."""


class UnsupportedFormatError(DatasetRegistrationError):
    """Raised when a dataset does not have an explicitly supported format."""


class DatasetNotFoundError(DataCopilotError):
    """Raised when a dataset ID is not present in the current registry."""


class DatasetExecutionError(DataCopilotError):
    """Raised when the execution engine cannot process a registered dataset."""


class ColumnNotFoundError(DataCopilotError):
    """Raised when a requested column is absent from the registered dataset."""


class ResourceLimitError(DataCopilotError):
    """Raised when an explicit request exceeds a deterministic limit."""


class InvalidProfileRequestError(DataCopilotError):
    """Raised when profile arguments are invalid or ambiguous."""


class QueryBuildError(DataCopilotError):
    """Base class for invalid structured query requests."""


class InvalidProjectionError(QueryBuildError):
    """Raised when a requested output projection is invalid."""


class InvalidSampleRequestError(QueryBuildError):
    """Raised when random sample arguments are invalid."""


class InvalidFilterError(QueryBuildError):
    """Raised when a structured filter has invalid semantics."""


class InvalidSortError(QueryBuildError):
    """Raised when a source or aggregate sort specification is invalid."""


class InvalidMetricError(QueryBuildError):
    """Raised when an aggregate metric is invalid or incompatible."""


class InvalidDimensionError(QueryBuildError):
    """Raised when an aggregate dimension is invalid or incompatible."""


class InvalidQualityRequestError(DataCopilotError):
    """Raised when data-quality arguments are invalid or ambiguous."""


class EvidenceBuildError(DataCopilotError):
    """Raised when a typed Tool Result cannot be converted to evidence."""


class EvidenceLimitError(EvidenceBuildError):
    """Raised when valid structured evidence cannot fit the context limit."""


class LLMClientError(DataCopilotError):
    """Raised when the configured LLM client cannot produce a safe response."""


class ConfigurationError(DataCopilotError):
    """Raised when explicit application configuration is missing or invalid."""


class DatabaseConfigurationError(ConfigurationError):
    """Raised when database configuration is missing or invalid."""


class DatabaseNotFoundError(DataCopilotError):
    """Raised when a database ID is not present in the current registry."""


class DatabaseConnectionError(DataCopilotError):
    """Raised when a registered database cannot be reached safely."""


class DatabaseMetadataError(DataCopilotError):
    """Raised when PostgreSQL metadata cannot be retrieved safely."""


class SchemaNotFoundError(DatabaseMetadataError):
    """Raised when a requested PostgreSQL schema does not exist."""


class TableNotFoundError(DatabaseMetadataError):
    """Raised when a requested schema-qualified table does not exist."""


class SQLValidationError(DataCopilotError):
    """Base class for rejected untrusted SQL."""


class SQLParseError(SQLValidationError):
    """Raised when SQL is empty, malformed, or cannot be parsed safely."""


class UnsafeSQLError(SQLValidationError):
    """Raised when parsed SQL violates the read-only policy."""


class MultipleStatementsError(SQLValidationError):
    """Raised when SQL contains anything other than one statement."""


class SQLExecutionError(DataCopilotError):
    """Raised when validated read-only SQL cannot execute safely."""


class QueryTimeoutError(SQLExecutionError):
    """Raised when PostgreSQL cancels a query at the program-owned timeout."""


class QueryResultTooWideError(SQLExecutionError):
    """Raised before fetching when a query returns too many columns."""


class SQLObjectNotFoundError(SQLExecutionError):
    """Raised when a query references an unknown table or column."""


class SQLAmbiguousColumnError(SQLExecutionError):
    """Raised when PostgreSQL cannot resolve an unqualified column."""


class SQLTypeMismatchError(SQLExecutionError):
    """Raised when PostgreSQL rejects incompatible SQL data types."""


class SQLGroupingError(SQLExecutionError):
    """Raised when PostgreSQL rejects invalid aggregate/grouping semantics."""


class ExplainQueryError(SQLExecutionError):
    """Raised when a safe program-owned EXPLAIN cannot produce a valid plan."""


class UnsupportedDatabaseError(DataCopilotError):
    """Raised when a database type is outside the explicit allowlist."""


class ToolDispatchError(DataCopilotError):
    """Base class for rejected LLM-requested Tool calls."""


class UnknownToolError(ToolDispatchError):
    """Raised when an LLM requests a Tool outside the static allowlist."""


class ToolArgumentError(ToolDispatchError):
    """Raised when untrusted Tool arguments fail structural validation."""


class AgentExecutionError(DataCopilotError):
    """Raised when an Agent run cannot safely reach a final answer."""


class AgentRoundLimitError(AgentExecutionError):
    """Raised when an Agent requests more than the allowed Tool calls."""


class SemanticConfigurationError(ConfigurationError):
    """Raised when trusted semantic configuration is malformed or inconsistent."""


class SemanticNotFoundError(DataCopilotError):
    """Raised when a semantic definition cannot be resolved."""


class SemanticAmbiguityError(SemanticConfigurationError):
    """Raised when one normalized semantic alias resolves to multiple definitions."""


class SemanticReferenceError(SemanticConfigurationError):
    """Raised when a semantic definition references an unknown definition ID."""
