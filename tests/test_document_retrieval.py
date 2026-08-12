from pathlib import Path

import pytest

from data_copilot.documents import (
    BusinessDocumentChunker,
    BusinessDocumentIndex,
    BusinessDocumentLoader,
    DocumentChunk,
    DocumentProvenance,
)
from data_copilot.errors import BusinessDocumentLimitError


FIXTURE_DIRECTORY = Path(__file__).parent / "fixtures" / "business_documents"


@pytest.fixture
def index() -> BusinessDocumentIndex:
    documents = BusinessDocumentLoader(FIXTURE_DIRECTORY).load()
    chunks = BusinessDocumentChunker().chunk(documents)
    return BusinessDocumentIndex(chunks)


@pytest.mark.parametrize(
    ("query", "expected_source", "expected_heading"),
    [
        ("refund policy revenue", "revenue_policy.md", "Refund Handling"),
        ("cancelled orders fulfillment", "order_status_policy.md", "Cancelled Orders"),
        ("customer region historical reporting", "customer_regions.txt", None),
        ("conveyor rollers inspection", "warehouse_maintenance.txt", None),
    ],
)
def test_relevant_chunk_is_top_ranked(
    index: BusinessDocumentIndex,
    query: str,
    expected_source: str,
    expected_heading: str | None,
) -> None:
    results = index.search(query, top_k=3)

    assert results[0].logical_source == expected_source
    assert results[0].heading == expected_heading
    assert results[0].relevance_score > 0


def test_multi_document_retrieval_ranks_irrelevant_document_lower(
    index: BusinessDocumentIndex,
) -> None:
    results = index.search("completed revenue cancelled orders", top_k=10)
    sources = tuple(result.logical_source for result in results)

    assert sources[0] in {"order_status_policy.md", "revenue_policy.md"}
    assert "warehouse_maintenance.txt" not in sources
    assert {"order_status_policy.md", "revenue_policy.md"}.issubset(sources)


def test_top_k_is_bounded(index: BusinessDocumentIndex) -> None:
    with pytest.raises(BusinessDocumentLimitError, match="top_k"):
        index.search("revenue", top_k=21)
    with pytest.raises(BusinessDocumentLimitError, match="top_k"):
        index.search("revenue", top_k=0)


def test_query_size_is_bounded(index: BusinessDocumentIndex) -> None:
    with pytest.raises(BusinessDocumentLimitError, match="query"):
        index.search("x" * 2001)


@pytest.mark.parametrize("query", ["", "   "])
def test_empty_query_returns_no_results(
    index: BusinessDocumentIndex,
    query: str,
) -> None:
    assert index.search(query) == ()


def test_non_string_query_is_rejected(index: BusinessDocumentIndex) -> None:
    with pytest.raises(TypeError, match="string"):
        index.search(None)  # type: ignore[arg-type]


def test_no_lexical_match_returns_no_results(index: BusinessDocumentIndex) -> None:
    assert index.search("xylophone zeppelin quantum") == ()


def test_stable_tie_breaking_uses_source_then_ordinal() -> None:
    chunks = (
        _chunk("chunk_1111111111111111", "doc_1111111111111111", "z.txt", 0),
        _chunk("chunk_2222222222222222", "doc_2222222222222222", "a.txt", 1),
        _chunk("chunk_3333333333333333", "doc_2222222222222222", "a.txt", 0),
    )
    index = BusinessDocumentIndex(chunks)

    first = index.search("shared token", top_k=3)
    second = index.search("shared token", top_k=3)

    assert first == second
    assert tuple(result.chunk_id for result in first) == (
        "chunk_3333333333333333",
        "chunk_2222222222222222",
        "chunk_1111111111111111",
    )


def test_index_rejects_duplicate_chunk_ids() -> None:
    chunk = _chunk("chunk_1111111111111111", "doc_1111111111111111", "a.txt", 0)

    with pytest.raises(ValueError, match="unique"):
        BusinessDocumentIndex((chunk, chunk))


def test_index_chunk_count_is_bounded() -> None:
    chunks = (
        _chunk("chunk_1111111111111111", "doc_1111111111111111", "a.txt", 0),
        _chunk("chunk_2222222222222222", "doc_2222222222222222", "b.txt", 0),
    )

    with pytest.raises(BusinessDocumentLimitError, match="too many chunks"):
        BusinessDocumentIndex(chunks, max_chunks=1)


def test_empty_index_is_searchable() -> None:
    index = BusinessDocumentIndex(())

    assert index.chunk_count == 0
    assert index.search("revenue") == ()


def _chunk(
    chunk_id: str,
    document_id: str,
    logical_source: str,
    ordinal: int,
) -> DocumentChunk:
    provenance = DocumentProvenance(
        logical_source=logical_source,
        document_id=document_id,
        chunk_id=chunk_id,
        ordinal=ordinal,
    )
    return DocumentChunk(
        chunk_id=chunk_id,
        document_id=document_id,
        title="Shared Policy",
        logical_source=logical_source,
        text="shared token",
        ordinal=ordinal,
        provenance=provenance,
    )
