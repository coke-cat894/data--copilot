"""Deterministic compact formatting for the PIPELINE_EVIDENCE channel."""

import json

from data_copilot.diagnostics.pipeline_constants import MAX_PIPELINE_EVIDENCE_CHARS
from data_copilot.diagnostics.pipeline_evidence_models import PipelineEvidence
from data_copilot.errors import PipelineEvidenceLimitError


PIPELINE_EVIDENCE_PREFIX = "PIPELINE_EVIDENCE\n"


def serialize_pipeline_evidence(evidence: PipelineEvidence) -> str:
    return json.dumps(
        evidence.model_dump(mode="json", exclude_none=True),
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )


class PipelineEvidenceFormatter:
    """Format sanitized pipeline facts as a distinct bounded envelope."""

    def __init__(self, *, max_chars: int = MAX_PIPELINE_EVIDENCE_CHARS) -> None:
        if isinstance(max_chars, bool) or not isinstance(max_chars, int) or max_chars < 1:
            raise PipelineEvidenceLimitError(
                "max_chars must be a positive integer."
            )
        self._max_chars = max_chars

    def format(self, evidence: PipelineEvidence) -> str:
        if not isinstance(evidence, PipelineEvidence):
            raise TypeError("PipelineEvidenceFormatter accepts PipelineEvidence.")
        formatted = PIPELINE_EVIDENCE_PREFIX + serialize_pipeline_evidence(evidence)
        if len(formatted) > self._max_chars:
            raise PipelineEvidenceLimitError(
                "Formatted pipeline evidence exceeds its character limit."
            )
        return formatted
