"""Deterministic formatting for the separate semantic evidence channel."""

import json

from data_copilot.errors import SemanticEvidenceLimitError
from data_copilot.semantics.constants import MAX_SEMANTIC_EVIDENCE_CHARS
from data_copilot.semantics.evidence_models import SemanticEvidence


SEMANTIC_EVIDENCE_PREFIX = "SEMANTIC_EVIDENCE\n"


def serialize_semantic_evidence(evidence: SemanticEvidence) -> str:
    """Serialize semantic evidence as deterministic compact JSON."""

    return json.dumps(
        evidence.model_dump(mode="json", exclude_none=True),
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )


class SemanticEvidenceFormatter:
    """Format a bounded semantic envelope without treating content as instructions."""

    def __init__(self, *, max_chars: int = MAX_SEMANTIC_EVIDENCE_CHARS) -> None:
        if isinstance(max_chars, bool) or not isinstance(max_chars, int) or max_chars < 1:
            raise SemanticEvidenceLimitError(
                "max_chars must be a positive integer."
            )
        self._max_chars = max_chars

    def format(self, evidence: SemanticEvidence) -> str:
        if not isinstance(evidence, SemanticEvidence):
            raise TypeError(
                "SemanticEvidenceFormatter accepts a SemanticEvidence model."
            )
        formatted = SEMANTIC_EVIDENCE_PREFIX + serialize_semantic_evidence(evidence)
        if len(formatted) > self._max_chars:
            raise SemanticEvidenceLimitError(
                "Formatted semantic evidence exceeds its total character limit."
            )
        return formatted
