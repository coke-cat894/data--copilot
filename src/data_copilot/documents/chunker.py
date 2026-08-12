"""Simple deterministic heading- and paragraph-aware document chunking."""

from collections.abc import Sequence
import hashlib
import re

from data_copilot.documents.constants import (
    MAX_CHUNK_CHARS,
    MAX_CHUNKS_PER_DOCUMENT,
    MAX_DOCUMENT_HEADING_CHARS,
    MAX_TOTAL_CHUNKS,
)
from data_copilot.documents.models import (
    BusinessDocument,
    DocumentChunk,
    DocumentProvenance,
)
from data_copilot.errors import BusinessDocumentLimitError


_HEADING_PATTERN = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
_PARAGRAPH_SPLIT = re.compile(r"\n\s*\n+")


class BusinessDocumentChunker:
    """Create bounded chunks without semantic inference or external services."""

    def __init__(
        self,
        *,
        max_chunk_chars: int = MAX_CHUNK_CHARS,
        max_chunks_per_document: int = MAX_CHUNKS_PER_DOCUMENT,
        max_total_chunks: int = MAX_TOTAL_CHUNKS,
    ) -> None:
        self._max_chunk_chars = _positive_limit("max_chunk_chars", max_chunk_chars)
        self._max_chunks_per_document = _positive_limit(
            "max_chunks_per_document",
            max_chunks_per_document,
        )
        self._max_total_chunks = _positive_limit(
            "max_total_chunks",
            max_total_chunks,
        )

    def chunk(
        self,
        documents: Sequence[BusinessDocument],
    ) -> tuple[DocumentChunk, ...]:
        if isinstance(documents, (str, bytes)) or not isinstance(documents, Sequence):
            raise TypeError("documents must be a sequence.")
        chunks: list[DocumentChunk] = []
        for document in documents:
            if not isinstance(document, BusinessDocument):
                raise TypeError("documents must contain BusinessDocument models.")
            document_chunks = self._chunk_document(document)
            if len(document_chunks) > self._max_chunks_per_document:
                raise BusinessDocumentLimitError(
                    "Business document produces too many chunks."
                )
            if len(chunks) + len(document_chunks) > self._max_total_chunks:
                raise BusinessDocumentLimitError(
                    "Business-document collection produces too many chunks."
                )
            chunks.extend(document_chunks)
        return tuple(chunks)

    def _chunk_document(self, document: BusinessDocument) -> tuple[DocumentChunk, ...]:
        sections = _markdown_sections(document.content)
        if not sections:
            sections = ((None, document.content),)
        pieces: list[tuple[str | None, str]] = []
        for heading, text in sections:
            if heading is not None and len(heading) > MAX_DOCUMENT_HEADING_CHARS:
                raise BusinessDocumentLimitError(
                    "Business-document heading exceeds the character limit."
                )
            for piece in _bounded_pieces(text, self._max_chunk_chars):
                if piece:
                    pieces.append((heading, piece))
                    if len(pieces) > self._max_chunks_per_document:
                        raise BusinessDocumentLimitError(
                            "Business document produces too many chunks."
                        )
        chunks: list[DocumentChunk] = []
        for ordinal, (heading, text) in enumerate(pieces):
            chunk_id = "chunk_" + hashlib.sha256(
                f"{document.document_id}\n{ordinal}\n{heading or ''}\n{text}".encode(
                    "utf-8"
                )
            ).hexdigest()[:16]
            provenance = DocumentProvenance(
                logical_source=document.logical_source,
                document_id=document.document_id,
                chunk_id=chunk_id,
                ordinal=ordinal,
            )
            chunks.append(
                DocumentChunk(
                    chunk_id=chunk_id,
                    document_id=document.document_id,
                    title=document.title,
                    logical_source=document.logical_source,
                    heading=heading,
                    text=text,
                    ordinal=ordinal,
                    provenance=provenance,
                )
            )
        return tuple(chunks)


def _markdown_sections(content: str) -> tuple[tuple[str | None, str], ...]:
    sections: list[tuple[str | None, str]] = []
    heading: str | None = None
    body: list[str] = []
    found_heading = False
    for line in content.splitlines():
        match = _HEADING_PATTERN.fullmatch(line.strip())
        if match is not None:
            found_heading = True
            text = "\n".join(body).strip()
            if text:
                sections.append((heading, text))
            heading = match.group(2).strip()
            body = []
        else:
            body.append(line)
    text = "\n".join(body).strip()
    if text:
        sections.append((heading, text))
    return tuple(sections) if found_heading else ()


def _bounded_pieces(text: str, max_chars: int) -> tuple[str, ...]:
    paragraphs = tuple(
        " ".join(paragraph.split())
        for paragraph in _PARAGRAPH_SPLIT.split(text.strip())
        if paragraph.strip()
    )
    pieces: list[str] = []
    current = ""
    for paragraph in paragraphs:
        for segment in _split_long_text(paragraph, max_chars):
            candidate = segment if not current else f"{current}\n\n{segment}"
            if len(candidate) <= max_chars:
                current = candidate
            else:
                if current:
                    pieces.append(current)
                current = segment
    if current:
        pieces.append(current)
    return tuple(pieces)


def _split_long_text(text: str, max_chars: int) -> tuple[str, ...]:
    remaining = text
    pieces: list[str] = []
    while len(remaining) > max_chars:
        split_at = remaining.rfind(" ", 0, max_chars + 1)
        if split_at < 1:
            split_at = max_chars
        pieces.append(remaining[:split_at].strip())
        remaining = remaining[split_at:].strip()
    if remaining:
        pieces.append(remaining)
    return tuple(pieces)


def _positive_limit(name: str, value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise BusinessDocumentLimitError(f"{name} must be a positive integer.")
    return value
