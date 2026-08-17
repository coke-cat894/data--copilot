"""Bounded, provider-free environment self-checks for configured capabilities."""

import os
import sys
from collections.abc import Callable, Mapping, Sequence
from enum import Enum
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from data_copilot.config import (
    PROVIDER_ENV_VAR,
    read_llm_config,
    read_postgres_config,
    read_runtime_config,
)
from data_copilot.databases import DatabaseRegistry, PostgresConnectionConfig
from data_copilot.databases.constants import (
    POSTGRES_CONNECT_TIMEOUT_ENV_VAR,
    POSTGRES_DSN_ENV_VAR,
    POSTGRES_STATEMENT_TIMEOUT_ENV_VAR,
)
from data_copilot.documents import (
    BusinessDocumentChunker,
    BusinessDocumentIndex,
    BusinessDocumentLoader,
)
from data_copilot.errors import DataCopilotError
from data_copilot.execution import PostgresEngine
from data_copilot.semantics import SemanticCatalogLoader


class HealthStatus(str, Enum):
    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"
    SKIPPED = "skipped"


class HealthCheck(BaseModel):
    """One bounded configuration or connectivity observation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(pattern=r"^[a-z][a-z0-9_]*$", max_length=80)
    status: HealthStatus
    summary: str = Field(min_length=1, max_length=500)


class DoctorReport(BaseModel):
    """Structured doctor result; no secret-bearing configuration is retained."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: str = "1.0"
    checks: tuple[HealthCheck, ...] = Field(max_length=20)

    @property
    def exit_code(self) -> int:
        failed = any(item.status is HealthStatus.FAIL for item in self.checks)
        return 1 if failed else 0


DatabaseConnectivityCheck = Callable[[PostgresConnectionConfig], None]


def inspect_environment(
    *,
    environ: Mapping[str, str] | None = None,
    connect_database: bool = False,
    semantic_source: Path | None = None,
    document_source: Path | None = None,
    allowed_roots: Sequence[Path] = (),
    artifact_directory: Path | None = None,
    database_connectivity_check: DatabaseConnectivityCheck | None = None,
) -> DoctorReport:
    """Inspect configured capabilities without contacting an LLM provider."""

    values = os.environ if environ is None else environ
    checks: list[HealthCheck] = []
    checks.append(_package_check())

    try:
        runtime = read_runtime_config(values)
        checks.append(
            _check(
                "runtime_configuration",
                HealthStatus.PASS,
                "Runtime limits are valid: Tool budget is "
                f"{runtime.tool_budget} and provider retries are bounded to "
                f"{runtime.provider_retry_policy.max_retries}.",
            )
        )
    except DataCopilotError as exc:
        checks.append(_configuration_failure("runtime_configuration", exc))

    provider_configured = bool(values.get(PROVIDER_ENV_VAR, "").strip())
    if provider_configured:
        try:
            provider = read_llm_config(values)
            checks.append(
                _check(
                    "provider_configuration",
                    HealthStatus.PASS,
                    f"Provider configuration is valid for {provider.provider} "
                    f"with model {provider.model}.",
                )
            )
        except DataCopilotError as exc:
            checks.append(_configuration_failure("provider_configuration", exc))
    else:
        checks.append(
            _check(
                "provider_configuration",
                HealthStatus.WARN,
                f"{PROVIDER_ENV_VAR} is not configured; this is valid for "
                "provider-free tests and local deterministic checks.",
            )
        )
    checks.append(
        _check(
            "provider_connectivity",
            HealthStatus.SKIPPED,
            "Provider connectivity is never checked by doctor; no tokens were spent.",
        )
    )

    postgres_names = (
        POSTGRES_DSN_ENV_VAR,
        POSTGRES_CONNECT_TIMEOUT_ENV_VAR,
        POSTGRES_STATEMENT_TIMEOUT_ENV_VAR,
    )
    postgres_requested = any(
        values.get(name, "").strip() for name in postgres_names
    )
    postgres_config: PostgresConnectionConfig | None = None
    if postgres_requested:
        try:
            postgres_config = read_postgres_config(values)
            checks.append(
                _check(
                    "postgres_configuration",
                    HealthStatus.PASS,
                    "PostgreSQL configuration and bounded timeouts are valid.",
                )
            )
        except DataCopilotError as exc:
            checks.append(_configuration_failure("postgres_configuration", exc))
    else:
        checks.append(
            _check(
                "postgres_configuration",
                HealthStatus.SKIPPED,
                "PostgreSQL is not configured; database capability remains disabled.",
            )
        )

    if connect_database and postgres_config is not None:
        try:
            checker = database_connectivity_check or _ping_postgres
            checker(postgres_config)
            checks.append(
                _check(
                    "postgres_connectivity",
                    HealthStatus.PASS,
                    "The explicitly requested read-only PostgreSQL health check passed.",
                )
            )
        except Exception as exc:
            checks.append(_runtime_failure("postgres_connectivity", exc))
    elif connect_database:
        checks.append(
            _check(
                "postgres_connectivity",
                HealthStatus.FAIL,
                "Connectivity was requested but PostgreSQL configuration is unavailable.",
            )
        )
    else:
        checks.append(
            _check(
                "postgres_connectivity",
                HealthStatus.SKIPPED,
                "Database connectivity was not requested; use "
                "--connect-database explicitly.",
            )
        )

    checks.append(_semantic_check(semantic_source))
    checks.append(_document_check(document_source))
    checks.append(_allowed_roots_check(allowed_roots))
    checks.append(_artifact_directory_check(artifact_directory))
    return DoctorReport(checks=tuple(checks))


def _package_check() -> HealthCheck:
    try:
        package_version = version("data-copilot")
    except PackageNotFoundError:
        package_version = "source-tree"
    if sys.version_info < (3, 12):
        return _check(
            "package_runtime",
            HealthStatus.FAIL,
            "Python 3.12 or newer is required.",
        )
    return _check(
        "package_runtime",
        HealthStatus.PASS,
        f"Data Copilot {package_version} is running on a supported Python runtime.",
    )


def _semantic_check(source: Path | None) -> HealthCheck:
    if source is None:
        return _check(
            "semantic_source",
            HealthStatus.SKIPPED,
            "No semantic source was requested.",
        )
    try:
        catalog = SemanticCatalogLoader(source).load()
    except DataCopilotError as exc:
        return _configuration_failure("semantic_source", exc)
    except Exception as exc:
        return _runtime_failure("semantic_source", exc)
    definitions = (
        len(catalog.metrics) + len(catalog.dimensions) + len(catalog.glossary)
    )
    return _check(
        "semantic_source",
        HealthStatus.PASS,
        f"Semantic source loaded {definitions} validated definitions.",
    )


def _document_check(source: Path | None) -> HealthCheck:
    if source is None:
        return _check(
            "document_source",
            HealthStatus.SKIPPED,
            "No business-document source was requested.",
        )
    try:
        documents = BusinessDocumentLoader(source).load()
        chunks = BusinessDocumentChunker().chunk(documents)
        index = BusinessDocumentIndex(chunks)
    except DataCopilotError as exc:
        return _configuration_failure("document_source", exc)
    except Exception as exc:
        return _runtime_failure("document_source", exc)
    return _check(
        "document_source",
        HealthStatus.PASS,
        f"Document source loaded {len(documents)} documents and "
        f"built {index.chunk_count} bounded lexical chunks.",
    )


def _allowed_roots_check(roots: Sequence[Path]) -> HealthCheck:
    if not roots:
        return _check(
            "allowed_roots",
            HealthStatus.SKIPPED,
            "No additional allowed roots were requested; the interactive CLI "
            "binds access to the explicit dataset parent.",
        )
    try:
        resolved = tuple(root.resolve(strict=True) for root in roots)
    except (OSError, RuntimeError):
        return _check(
            "allowed_roots",
            HealthStatus.FAIL,
            "At least one configured allowed root cannot be resolved.",
        )
    if any(not root.is_dir() for root in resolved):
        return _check(
            "allowed_roots",
            HealthStatus.FAIL,
            "Every configured allowed root must be a directory.",
        )
    return _check(
        "allowed_roots",
        HealthStatus.PASS,
        f"Validated {len(resolved)} explicit allowed roots.",
    )


def _artifact_directory_check(directory: Path | None) -> HealthCheck:
    if directory is None:
        return _check(
            "artifact_directory",
            HealthStatus.SKIPPED,
            "No eval artifact directory was requested.",
        )
    if directory.exists() and not directory.is_dir():
        return _check(
            "artifact_directory",
            HealthStatus.FAIL,
            "The configured eval artifact location is not a directory.",
        )
    target = directory if directory.exists() else directory.parent
    if target.exists() and target.is_dir() and os.access(target, os.W_OK):
        status = HealthStatus.PASS if directory.exists() else HealthStatus.WARN
        summary = (
            "The eval artifact directory exists and is writable."
            if directory.exists()
            else (
                "The eval artifact directory does not exist yet; "
                "its parent is writable."
            )
        )
        return _check("artifact_directory", status, summary)
    return _check(
        "artifact_directory",
        HealthStatus.FAIL,
        "The configured eval artifact location is not writable.",
    )


def _ping_postgres(config: PostgresConnectionConfig) -> None:
    registry = DatabaseRegistry()
    database = registry.register(config, display_name="Doctor PostgreSQL Check")
    PostgresEngine(registry).ping(database.database_id)


def _configuration_failure(name: str, error: Exception) -> HealthCheck:
    return _check(name, HealthStatus.FAIL, str(error))


def _runtime_failure(name: str, error: Exception) -> HealthCheck:
    category = type(error).__name__
    return _check(
        name,
        HealthStatus.FAIL,
        f"The check failed safely ({category}); no internal details were exposed.",
    )


def _check(name: str, status: HealthStatus, summary: str) -> HealthCheck:
    return HealthCheck(name=name, status=status, summary=summary)
