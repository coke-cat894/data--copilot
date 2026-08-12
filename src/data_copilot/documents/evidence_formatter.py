"""Deterministic compact JSON formatting for document evidence."""

import json

from data_copilot.documents.constants import MAX_DOCUMENT_EVIDENCE_CHARS
from data_copilot.documents.evidence_models import DocumentEvidence
from data_copilot.errors import DocumentEvidenceLimitError


DOCUMENT_EVIDENCE_PREFIX = "DOCUMENT_EVIDENCE\n"


def serialize_document_evidence(evidence: DocumentEvidence) -> str:
    return json.dumps(
        evidence.model_dump(mode="json", exclude_none=True),
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )


class DocumentEvidenceFormatter:
    """Format retrieved context as a distinct bounded content envelope."""

    def __init__(self, *, max_chars: int = MAX_DOCUMENT_EVIDENCE_CHARS) -> None:
        if isinstance(max_chars, bool) or not isinstance(max_chars, int) or max_chars < 1:
            raise DocumentEvidenceLimitError(
                "max_chars must be a positive integer."
            )
        self._max_chars = max_chars

    def format(self, evidence: DocumentEvidence) -> str:
        if not isinstance(evidence, DocumentEvidence):
            raise TypeError("DocumentEvidenceFormatter accepts DocumentEvidence.")
        formatted = DOCUMENT_EVIDENCE_PREFIX + serialize_document_evidence(evidence)
        if len(formatted) > self._max_chars:
            raise DocumentEvidenceLimitError(
                "Formatted document evidence exceeds its character limit."
            )
        return formatted
