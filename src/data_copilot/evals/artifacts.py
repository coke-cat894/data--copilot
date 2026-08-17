"""Small filesystem artifact integrity and safety helpers for Phase 5.1."""

from collections.abc import Sequence
from datetime import UTC, datetime
from hashlib import sha256
import json
import os
from pathlib import Path
import re

from pydantic import BaseModel, ConfigDict, Field

from data_copilot.errors import DataCopilotError
from data_copilot.evals.models import (
    EvalRun,
    FailureClassification,
    HumanReviewOutcome,
    HumanReviewRecord,
)


MAX_EVAL_ARTIFACT_BYTES = 2_000_000
MAX_SAFETY_SCAN_CHARS = MAX_EVAL_ARTIFACT_BYTES


class ArtifactIntegrity(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    filename: str = Field(min_length=1, max_length=255)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(ge=1, le=MAX_EVAL_ARTIFACT_BYTES)


class EvalPersistenceError(DataCopilotError):
    """Raised when an eval/review artifact cannot be persisted safely."""


def save_eval_run(
    run: EvalRun,
    output_path: Path,
    *,
    secret_values: Sequence[str] = (),
) -> ArtifactIntegrity:
    return _save_json_artifact(
        run.model_dump(mode="json"),
        output_path,
        secret_values=secret_values,
    )


def save_human_review(
    review: HumanReviewRecord,
    output_path: Path,
    *,
    secret_values: Sequence[str] = (),
) -> ArtifactIntegrity:
    """Persist a separate immutable review overlay, never an automatic result."""

    return _save_json_artifact(
        review.model_dump(mode="json"),
        output_path,
        secret_values=secret_values,
    )


def build_human_review(
    run: EvalRun,
    *,
    case_id: str,
    automatic_artifact_sha256: str,
    grounded_human_outcome: HumanReviewOutcome,
    failure_classification: FailureClassification,
    rationale: str,
    reviewer_id: str | None = None,
    reviewed_at: datetime | None = None,
    review_id: str | None = None,
) -> HumanReviewRecord:
    """Create a review overlay from, but without mutating, automatic results."""

    if run.run_id is None:
        raise EvalPersistenceError("Human review requires an eval run ID.")
    result = next((item for item in run.results if item.case_id == case_id), None)
    if result is None:
        raise EvalPersistenceError("Human review references an unknown eval case.")
    timestamp = reviewed_at or datetime.now(UTC)
    logical_review_id = review_id or (
        f"review-{case_id}-{timestamp.strftime('%Y%m%dT%H%M%SZ')}"
    )
    return HumanReviewRecord(
        review_id=logical_review_id,
        eval_run_id=run.run_id,
        case_id=case_id,
        automatic_artifact_sha256=automatic_artifact_sha256,
        original_automatic_metrics=result.checks,
        original_metric_details=result.metric_details,
        original_automatic_passed=result.passed,
        original_safety_passed=result.safety_passed,
        original_automatic_classification=(
            result.automatic_failure_classification
        ),
        grounded_human_outcome=grounded_human_outcome,
        failure_classification=failure_classification,
        rationale=rationale,
        reviewer_id=reviewer_id,
        reviewed_at=timestamp,
    )


def artifact_sha256(path: Path) -> str:
    """Hash one existing bounded regular artifact without modifying it."""

    if path.is_symlink() or not path.is_file():
        raise EvalPersistenceError("Artifact hash requires a regular non-symlink file.")
    try:
        size = path.stat().st_size
        if size > MAX_EVAL_ARTIFACT_BYTES:
            raise EvalPersistenceError("Artifact exceeds the configured size limit.")
        return sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise EvalPersistenceError("Artifact could not be read safely.") from exc


def content_fingerprint(paths: Sequence[Path]) -> str | None:
    """Return a stable aggregate hash for known files, or unknown when absent."""

    if not paths:
        return None
    digest = sha256()
    for path in sorted(paths, key=lambda item: item.as_posix()):
        if path.is_symlink() or not path.is_file():
            raise EvalPersistenceError("Fingerprint input must be a regular file.")
        try:
            payload = path.read_bytes()
        except OSError as exc:
            raise EvalPersistenceError("Fingerprint input could not be read.") from exc
        logical_path = "/".join(path.parts[-4:])
        digest.update(logical_path.encode("utf-8"))
        digest.update(b"\0")
        digest.update(payload)
        digest.update(b"\0")
    return f"sha256:{digest.hexdigest()}"


def scan_artifact_text(
    serialized: str,
    *,
    secret_values: Sequence[str] = (),
) -> None:
    """Fail closed on bounded, known high-risk secret/path patterns.

    This deterministic scan is intentionally conservative and does not claim
    comprehensive secret detection.
    """

    if len(serialized) > MAX_SAFETY_SCAN_CHARS:
        raise EvalPersistenceError("Artifact exceeds the bounded safety scan limit.")
    for secret in secret_values:
        if secret and secret in serialized:
            raise EvalPersistenceError("Eval artifact contains a configured secret.")
    for label, pattern in _HIGH_RISK_PATTERNS:
        if pattern.search(serialized):
            raise EvalPersistenceError(
                f"Eval artifact failed the deterministic {label} safety scan."
            )


def _save_json_artifact(
    value: object,
    output_path: Path,
    *,
    secret_values: Sequence[str],
) -> ArtifactIntegrity:
    _validate_output_path(output_path)
    serialized = json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        indent=2,
        sort_keys=True,
    ) + "\n"
    payload = serialized.encode("utf-8")
    if len(payload) > MAX_EVAL_ARTIFACT_BYTES:
        raise EvalPersistenceError("Eval artifact exceeds the configured size limit.")
    scan_artifact_text(serialized, secret_values=secret_values)
    if output_path.exists() or output_path.is_symlink():
        raise EvalPersistenceError("Eval artifact already exists and is immutable.")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_name(f".{output_path.name}.tmp")
    if temporary.exists() or temporary.is_symlink():
        raise EvalPersistenceError("Eval artifact temporary path is unavailable.")
    try:
        with temporary.open("x", encoding="utf-8") as handle:
            handle.write(serialized)
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temporary, output_path)
        temporary.unlink()
    except FileExistsError as exc:
        if temporary.exists() and not temporary.is_symlink():
            temporary.unlink()
        raise EvalPersistenceError("Eval artifact already exists and is immutable.") from exc
    except OSError as exc:
        if temporary.exists() and not temporary.is_symlink():
            temporary.unlink()
        raise EvalPersistenceError("Eval artifact could not be written safely.") from exc
    return ArtifactIntegrity(
        filename=output_path.name,
        sha256=sha256(payload).hexdigest(),
        size_bytes=len(payload),
    )


def _validate_output_path(output_path: Path) -> None:
    if not isinstance(output_path, Path):
        raise EvalPersistenceError("Artifact output path must be a Path.")
    if output_path.name.startswith(".") or not _SAFE_FILENAME.fullmatch(
        output_path.name
    ):
        raise EvalPersistenceError("Artifact filename is unsafe.")
    if output_path.suffix != ".json":
        raise EvalPersistenceError("Eval artifacts must use a .json filename.")


_SAFE_FILENAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,254}")
_HIGH_RISK_PATTERNS = (
    ("bearer-token", re.compile(r"(?i)\bbearer\s+(?!\[REDACTED\])[A-Za-z0-9._~+/=-]{8,}")),
    ("api-key", re.compile(r"\b(?:sk-[A-Za-z0-9_-]{12,}|(?:AKIA|ASIA)[A-Z0-9]{16})\b")),
    (
        "credential",
        re.compile(
            r"(?i)\b(?:password|passwd|pwd|api[_ -]?key|access[_ -]?token|"
            r"refresh[_ -]?token|client[_ -]?secret)\b[\"']?\s*[:=]\s*"
            r"[\"']?(?!\[REDACTED\])[^\s,;}\"]{4,}"
        ),
    ),
    (
        "dsn",
        re.compile(
            r"(?i)\b(?:postgres(?:ql)?|mysql|mariadb|mongodb(?:\+srv)?|redis)://"
        ),
    ),
    (
        "connection-string",
        re.compile(r"(?i)\b(?:server|data\s+source|user\s+id|uid)\s*=.+?;"),
    ),
    (
        "env-value",
        re.compile(r"(?m)^\s*[A-Z][A-Z0-9_]{2,}\s*=\s*(?!\[REDACTED\])\S+"),
    ),
    (
        "absolute-path",
        re.compile(
            r"(?:(?<![A-Za-z0-9])(?:/Users|/home|/private|/var|/tmp)/[^\s\"']+|"
            r"(?<![A-Za-z0-9])[A-Za-z]:\\[^\s\"']+)"
        ),
    ),
)
