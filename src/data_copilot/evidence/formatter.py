"""Deterministic compact JSON formatting for future model context."""

import json

from data_copilot.config import MAX_EVIDENCE_CHARS
from data_copilot.errors import EvidenceLimitError
from data_copilot.evidence.models import Evidence


EVIDENCE_PREFIX = "DATA_EVIDENCE\n"


def serialize_evidence(evidence: Evidence) -> str:
    """Serialize one normalized Evidence model without whitespace overhead."""

    return json.dumps(
        evidence.model_dump(mode="json"),
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )


class EvidenceFormatter:
    """Format evidence as a clearly delimited, bounded data envelope."""

    def __init__(self, *, max_chars: int = MAX_EVIDENCE_CHARS) -> None:
        if isinstance(max_chars, bool) or not isinstance(max_chars, int) or max_chars < 1:
            raise EvidenceLimitError("max_chars must be a positive integer.")
        self._max_chars = max_chars

    def format(self, evidence: Evidence) -> str:
        if not isinstance(evidence, Evidence):
            raise TypeError("EvidenceFormatter accepts an Evidence model.")
        formatted = EVIDENCE_PREFIX + serialize_evidence(evidence)
        if len(formatted) > self._max_chars:
            raise EvidenceLimitError(
                f"Formatted evidence exceeds MAX_EVIDENCE_CHARS={self._max_chars}."
            )
        return formatted
