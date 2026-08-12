"""Build bounded document evidence from local typed retrieval results."""

from collections.abc import Sequence

from data_copilot.documents.constants import (
    MAX_DOCUMENT_EVIDENCE_CHARS,
    MAX_DOCUMENT_EVIDENCE_CHUNKS,
    MAX_DOCUMENT_EVIDENCE_CHUNK_CHARS,
    MAX_DOCUMENT_EVIDENCE_METADATA_CHARS,
)
from data_copilot.documents.evidence_formatter import (
    DOCUMENT_EVIDENCE_PREFIX,
    serialize_document_evidence,
)
from data_copilot.documents.evidence_models import (
    DocumentEvidence,
    DocumentEvidenceChunk,
)
from data_copilot.documents.models import DocumentRetrievalResult
from data_copilot.errors import (
    DocumentEvidenceBuildError,
    DocumentEvidenceLimitError,
)


class DocumentEvidenceBuilder:
    """Bound only retrieved chunks, preserving ranking and safe provenance."""

    def __init__(
        self,
        *,
        max_chunks: int = MAX_DOCUMENT_EVIDENCE_CHUNKS,
        max_chunk_chars: int = MAX_DOCUMENT_EVIDENCE_CHUNK_CHARS,
        max_metadata_chars: int = MAX_DOCUMENT_EVIDENCE_METADATA_CHARS,
        max_chars: int = MAX_DOCUMENT_EVIDENCE_CHARS,
    ) -> None:
        self._max_chunks = _positive_limit("max_chunks", max_chunks)
        self._max_chunk_chars = _positive_limit(
            "max_chunk_chars",
            max_chunk_chars,
        )
        self._max_metadata_chars = _positive_limit(
            "max_metadata_chars",
            max_metadata_chars,
        )
        self._max_chars = _positive_limit("max_chars", max_chars)

    def build(
        self,
        results: Sequence[DocumentRetrievalResult],
    ) -> DocumentEvidence:
        if isinstance(results, (str, bytes)) or not isinstance(results, Sequence):
            raise TypeError("results must be a sequence.")
        if any(not isinstance(result, DocumentRetrievalResult) for result in results):
            raise DocumentEvidenceBuildError(
                "Document evidence requires typed retrieval results."
            )
        warnings: list[str] = []
        selected = tuple(results)
        truncated = False
        if len(selected) > self._max_chunks:
            original_count = len(selected)
            selected = selected[: self._max_chunks]
            truncated = True
            warnings.append(
                f"Document evidence chunks truncated from {original_count} to "
                f"{self._max_chunks}."
            )
        chunks: list[DocumentEvidenceChunk] = []
        for result in selected:
            text = result.text
            if len(text) > self._max_chunk_chars:
                truncated = True
                warnings.append(
                    f"Document chunk '{result.chunk_id}' text was truncated to "
                    f"MAX_DOCUMENT_EVIDENCE_CHUNK_CHARS={self._max_chunk_chars}."
                )
                text = (
                    "…"
                    if self._max_chunk_chars == 1
                    else text[: self._max_chunk_chars - 1] + "…"
                )
            chunks.append(
                DocumentEvidenceChunk(
                    chunk_id=result.chunk_id,
                    document_id=result.document_id,
                    title=self._bound_metadata(
                        result.title,
                        result.chunk_id,
                        "title",
                        warnings,
                    ),
                    heading=(
                        self._bound_metadata(
                            result.heading,
                            result.chunk_id,
                            "heading",
                            warnings,
                        )
                        if result.heading is not None
                        else None
                    ),
                    logical_source=result.logical_source,
                    relevance_score=result.relevance_score,
                    text=text,
                    ordinal=result.ordinal,
                    provenance=result.provenance,
                )
            )
            if chunks[-1].title != result.title or chunks[-1].heading != result.heading:
                truncated = True
        evidence = DocumentEvidence(
            chunks=tuple(chunks),
            truncated=truncated,
            warnings=tuple(warnings),
        )
        return self._fit_total_size(evidence)

    def _bound_metadata(
        self,
        value: str,
        chunk_id: str,
        field_name: str,
        warnings: list[str],
    ) -> str:
        if len(value) <= self._max_metadata_chars:
            return value
        warnings.append(
            f"Document chunk '{chunk_id}' {field_name} was truncated to "
            f"MAX_DOCUMENT_EVIDENCE_METADATA_CHARS={self._max_metadata_chars}."
        )
        if self._max_metadata_chars == 1:
            return "…"
        return value[: self._max_metadata_chars - 1] + "…"

    def _fit_total_size(self, evidence: DocumentEvidence) -> DocumentEvidence:
        current = evidence
        while self._formatted_length(current) > self._max_chars and current.chunks:
            removed_id = current.chunks[-1].chunk_id
            warning = (
                "Document chunks were reduced to satisfy the total character limit "
                f"MAX_DOCUMENT_EVIDENCE_CHARS={self._max_chars}."
            )
            warnings = tuple(
                existing
                for existing in current.warnings
                if f"'{removed_id}'" not in existing
            )
            if warning not in warnings:
                warnings = warnings + (warning,)
            current = current.model_copy(
                update={
                    "chunks": current.chunks[:-1],
                    "truncated": True,
                    "warnings": warnings,
                }
            )
        if self._formatted_length(current) > self._max_chars:
            raise DocumentEvidenceLimitError(
                "Document evidence envelope cannot fit the character limit."
            )
        return current

    @staticmethod
    def _formatted_length(evidence: DocumentEvidence) -> int:
        return len(DOCUMENT_EVIDENCE_PREFIX + serialize_document_evidence(evidence))


def _positive_limit(name: str, value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise DocumentEvidenceLimitError(f"{name} must be a positive integer.")
    return value
