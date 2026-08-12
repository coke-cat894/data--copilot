from pathlib import Path

import pytest

from data_copilot.documents import (
    BusinessDocument,
    BusinessDocumentChunker,
    BusinessDocumentLoader,
)
from data_copilot.errors import BusinessDocumentLimitError


FIXTURE_DIRECTORY = Path(__file__).parent / "fixtures" / "business_documents"


def _document(content: str, *, document_id: str = "doc_0123456789abcdef") -> BusinessDocument:
    return BusinessDocument(
        document_id=document_id,
        title="Synthetic Policy",
        logical_source="policy.md",
        content=content,
    )


def test_markdown_heading_sections_retain_heading_and_provenance() -> None:
    document = BusinessDocumentLoader(
        FIXTURE_DIRECTORY / "revenue_policy.md"
    ).load()[0]

    chunks = BusinessDocumentChunker().chunk([document])

    assert tuple(chunk.heading for chunk in chunks) == (
        "Revenue Eligibility",
        "Refund Handling",
    )
    assert tuple(chunk.ordinal for chunk in chunks) == (0, 1)
    assert all(chunk.title == "Revenue Policy" for chunk in chunks)
    assert all(chunk.provenance.logical_source == "revenue_policy.md" for chunk in chunks)


def test_plain_text_paragraphs_are_combined_within_bound() -> None:
    document = _document("First paragraph.\n\nSecond paragraph.")

    chunks = BusinessDocumentChunker(max_chunk_chars=100).chunk([document])

    assert len(chunks) == 1
    assert chunks[0].heading is None
    assert chunks[0].text == "First paragraph.\n\nSecond paragraph."


def test_long_section_splits_at_word_boundaries() -> None:
    document = _document("# Policy\n\n" + "word " * 50)

    chunks = BusinessDocumentChunker(max_chunk_chars=40).chunk([document])

    assert len(chunks) > 1
    assert all(len(chunk.text) <= 40 for chunk in chunks)
    assert all(chunk.heading == "Policy" for chunk in chunks)


def test_unbroken_long_text_is_split_safely() -> None:
    chunks = BusinessDocumentChunker(max_chunk_chars=10).chunk(
        [_document("x" * 25)]
    )

    assert tuple(len(chunk.text) for chunk in chunks) == (10, 10, 5)


def test_chunk_ids_are_deterministic() -> None:
    document = _document("# Policy\n\nOne.\n\nTwo.")
    chunker = BusinessDocumentChunker(max_chunk_chars=10)

    first = chunker.chunk([document])
    second = chunker.chunk([document])

    assert first == second
    assert all(chunk.chunk_id.startswith("chunk_") for chunk in first)


def test_per_document_chunk_limit_fails_closed() -> None:
    document = _document("one\n\ntwo\n\nthree")

    with pytest.raises(BusinessDocumentLimitError, match="too many chunks"):
        BusinessDocumentChunker(
            max_chunk_chars=5,
            max_chunks_per_document=2,
        ).chunk([document])


def test_total_chunk_limit_fails_closed() -> None:
    documents = (
        _document("first", document_id="doc_0123456789abcdef"),
        _document("second", document_id="doc_fedcba9876543210"),
    )

    with pytest.raises(BusinessDocumentLimitError, match="collection"):
        BusinessDocumentChunker(max_total_chunks=1).chunk(documents)


def test_empty_document_collection_returns_no_chunks() -> None:
    assert BusinessDocumentChunker().chunk([]) == ()


def test_oversized_markdown_heading_fails_closed() -> None:
    document = _document("## " + "H" * 501 + "\n\nPolicy text.")

    with pytest.raises(BusinessDocumentLimitError, match="heading"):
        BusinessDocumentChunker().chunk([document])
