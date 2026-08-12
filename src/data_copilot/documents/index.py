"""In-memory deterministic BM25-style lexical index for document chunks."""

from collections import Counter
from collections.abc import Sequence
import math

from data_copilot.documents.constants import (
    MAX_DOCUMENT_QUERY_CHARS,
    MAX_TOTAL_CHUNKS,
    MAX_RETRIEVAL_TOP_K,
)
from data_copilot.documents.models import (
    DocumentChunk,
    DocumentRetrievalResult,
    lexical_tokens,
)
from data_copilot.errors import BusinessDocumentLimitError


class BusinessDocumentIndex:
    """Build and search a bounded in-memory local lexical index."""

    def __init__(
        self,
        chunks: Sequence[DocumentChunk],
        *,
        max_chunks: int = MAX_TOTAL_CHUNKS,
        max_top_k: int = MAX_RETRIEVAL_TOP_K,
        max_query_chars: int = MAX_DOCUMENT_QUERY_CHARS,
    ) -> None:
        if isinstance(chunks, (str, bytes)) or not isinstance(chunks, Sequence):
            raise TypeError("chunks must be a sequence.")
        if any(not isinstance(chunk, DocumentChunk) for chunk in chunks):
            raise TypeError("chunks must contain DocumentChunk models.")
        resolved_max_chunks = _positive_limit("max_chunks", max_chunks)
        if len(chunks) > resolved_max_chunks:
            raise BusinessDocumentLimitError(
                "Document index contains too many chunks."
            )
        self._max_top_k = _positive_limit("max_top_k", max_top_k)
        self._max_query_chars = _positive_limit("max_query_chars", max_query_chars)
        self._chunks = tuple(chunks)
        chunk_ids = [chunk.chunk_id for chunk in self._chunks]
        if len(set(chunk_ids)) != len(chunk_ids):
            raise ValueError("Document chunk IDs must be unique.")
        self._term_frequencies = tuple(
            Counter(
                lexical_tokens(
                    " ".join(
                        value
                        for value in (chunk.title, chunk.heading, chunk.text)
                        if value
                    )
                )
            )
            for chunk in self._chunks
        )
        self._lengths = tuple(sum(values.values()) for values in self._term_frequencies)
        self._average_length = (
            sum(self._lengths) / len(self._lengths) if self._lengths else 0.0
        )
        document_frequencies: Counter[str] = Counter()
        for frequencies in self._term_frequencies:
            document_frequencies.update(frequencies.keys())
        self._document_frequencies = document_frequencies

    @property
    def chunk_count(self) -> int:
        return len(self._chunks)

    def search(
        self,
        query: str,
        *,
        top_k: int = 5,
    ) -> tuple[DocumentRetrievalResult, ...]:
        if not isinstance(query, str):
            raise TypeError("Document retrieval query must be a string.")
        if len(query) > self._max_query_chars:
            raise BusinessDocumentLimitError(
                "Document retrieval query exceeds the character limit."
            )
        if isinstance(top_k, bool) or not isinstance(top_k, int) or not (
            1 <= top_k <= self._max_top_k
        ):
            raise BusinessDocumentLimitError(
                "Document retrieval top_k is outside the allowed range."
            )
        if not query.strip():
            return ()
        query_terms = tuple(dict.fromkeys(lexical_tokens(query)))
        if not query_terms or not self._chunks:
            return ()
        scored: list[tuple[float, DocumentChunk]] = []
        for index, chunk in enumerate(self._chunks):
            score = self._score(
                query_terms,
                frequencies=self._term_frequencies[index],
                length=self._lengths[index],
            )
            if score > 0:
                scored.append((score, chunk))
        scored.sort(
            key=lambda item: (
                -item[0],
                item[1].logical_source.casefold(),
                item[1].ordinal,
                item[1].chunk_id,
            )
        )
        return tuple(
            DocumentRetrievalResult(
                chunk_id=chunk.chunk_id,
                document_id=chunk.document_id,
                title=chunk.title,
                heading=chunk.heading,
                logical_source=chunk.logical_source,
                relevance_score=round(score, 12),
                text=chunk.text,
                ordinal=chunk.ordinal,
                provenance=chunk.provenance,
            )
            for score, chunk in scored[:top_k]
        )

    def _score(
        self,
        query_terms: tuple[str, ...],
        *,
        frequencies: Counter[str],
        length: int,
    ) -> float:
        if not frequencies or self._average_length <= 0:
            return 0.0
        score = 0.0
        chunk_count = len(self._chunks)
        k1 = 1.2
        b = 0.75
        for term in query_terms:
            frequency = frequencies.get(term, 0)
            if frequency == 0:
                continue
            document_frequency = self._document_frequencies[term]
            inverse_document_frequency = math.log(
                1 + (chunk_count - document_frequency + 0.5)
                / (document_frequency + 0.5)
            )
            denominator = frequency + k1 * (
                1 - b + b * length / self._average_length
            )
            score += inverse_document_frequency * frequency * (k1 + 1) / denominator
        return score


def _positive_limit(name: str, value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise BusinessDocumentLimitError(f"{name} must be a positive integer.")
    return value
