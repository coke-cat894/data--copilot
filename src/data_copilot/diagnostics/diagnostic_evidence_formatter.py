"""Deterministic formatting for the DIAGNOSTIC_EVIDENCE channel."""

import json

from data_copilot.diagnostics.diagnostic_evidence_models import (
    MAX_DIAGNOSTIC_EVIDENCE_CHARS,
    DiagnosticEvidence,
)
from data_copilot.errors import DiagnosticEvidenceLimitError


DIAGNOSTIC_EVIDENCE_PREFIX = "DIAGNOSTIC_EVIDENCE\n"


def serialize_diagnostic_evidence(evidence: DiagnosticEvidence) -> str:
    return json.dumps(
        evidence.model_dump(mode="json", exclude_none=True),
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )


class DiagnosticEvidenceFormatter:
    def __init__(self, *, max_chars: int = MAX_DIAGNOSTIC_EVIDENCE_CHARS) -> None:
        if isinstance(max_chars, bool) or not isinstance(max_chars, int) or max_chars < 1:
            raise DiagnosticEvidenceLimitError(
                "max_chars must be a positive integer."
            )
        self._max_chars = max_chars

    def format(self, evidence: DiagnosticEvidence) -> str:
        if not isinstance(evidence, DiagnosticEvidence):
            raise TypeError("DiagnosticEvidenceFormatter accepts DiagnosticEvidence.")
        formatted = DIAGNOSTIC_EVIDENCE_PREFIX + serialize_diagnostic_evidence(evidence)
        if len(formatted) > self._max_chars:
            raise DiagnosticEvidenceLimitError(
                "Formatted diagnostic evidence exceeds its character limit."
            )
        return formatted
