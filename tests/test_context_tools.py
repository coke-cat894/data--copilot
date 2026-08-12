import json
from pathlib import Path

import pytest

from data_copilot.documents import (
    BusinessDocumentChunker,
    BusinessDocumentIndex,
    BusinessDocumentLoader,
)
from data_copilot.errors import (
    SemanticAmbiguityError,
    SemanticNotFoundError,
    ToolArgumentError,
)
from data_copilot.semantics import SemanticCatalogLoader
from data_copilot.tools.document_context import DocumentRetrievalTool
from data_copilot.tools.semantic_context import SemanticResolutionTool


SEMANTIC_FIXTURES = Path(__file__).parent / "fixtures" / "semantic"
DOCUMENT_FIXTURES = Path(__file__).parent / "fixtures" / "business_documents"


@pytest.fixture
def semantic_tool() -> SemanticResolutionTool:
    return SemanticResolutionTool(SemanticCatalogLoader(SEMANTIC_FIXTURES).load())


@pytest.fixture
def document_tool() -> DocumentRetrievalTool:
    documents = BusinessDocumentLoader(DOCUMENT_FIXTURES).load()
    chunks = BusinessDocumentChunker().chunk(documents)
    return DocumentRetrievalTool(BusinessDocumentIndex(chunks))


def test_semantic_tool_schema_is_strict_bounded_and_opaque(
    semantic_tool: SemanticResolutionTool,
) -> None:
    schema = semantic_tool.schema
    serialized = json.dumps(schema.model_dump(mode="json")).casefold()
    parameters = json.dumps(schema.parameters).casefold()

    assert schema.name == "resolve_semantic"
    assert schema.strict is True
    assert schema.parameters["additionalProperties"] is False
    assert schema.parameters["required"] == ["terms"]
    assert schema.parameters["properties"]["terms"]["minItems"] == 1
    assert schema.parameters["properties"]["terms"]["maxItems"] == 20
    assert "catalog" not in parameters
    assert "path" not in parameters
    assert "sql" not in parameters
    assert "semantic_evidence" in serialized


def test_semantic_tool_returns_only_requested_semantic_evidence(
    semantic_tool: SemanticResolutionTool,
) -> None:
    evidence = semantic_tool.invoke('{"terms":["fulfilled revenue"]}')

    assert len(evidence.definitions) == 1
    assert evidence.definitions[0].semantic_type == "metric"
    assert evidence.definitions[0].metric_id == "completed_revenue"


def test_semantic_tool_missing_and_ambiguity_fail_explicitly(
    semantic_tool: SemanticResolutionTool,
) -> None:
    with pytest.raises(SemanticNotFoundError):
        semantic_tool.invoke('{"terms":["missing metric"]}')
    with pytest.raises(SemanticAmbiguityError):
        semantic_tool.invoke('{"terms":["customer region"]}')


@pytest.mark.parametrize(
    "arguments",
    [
        "not-json",
        '{"terms":[]}',
        '{"terms":["x"],"catalog":"all"}',
        '{"terms":[1]}',
        '{"terms":["' + "x" * 201 + '"]}',
    ],
)
def test_semantic_tool_rejects_invalid_or_capability_arguments(
    semantic_tool: SemanticResolutionTool,
    arguments: str,
) -> None:
    with pytest.raises(ToolArgumentError):
        semantic_tool.invoke(arguments)


def test_document_tool_schema_is_strict_bounded_and_opaque(
    document_tool: DocumentRetrievalTool,
) -> None:
    schema = document_tool.schema
    serialized = json.dumps(schema.model_dump(mode="json")).casefold()

    assert schema.name == "retrieve_documents"
    assert schema.strict is True
    assert schema.parameters["additionalProperties"] is False
    assert schema.parameters["required"] == ["query", "top_k"]
    assert schema.parameters["properties"]["top_k"]["minimum"] == 1
    assert schema.parameters["properties"]["top_k"]["maximum"] == 20
    assert "filesystem" not in serialized
    assert "absolute" not in serialized
    assert "index internals" not in serialized


def test_document_tool_returns_only_retrieved_evidence(
    document_tool: DocumentRetrievalTool,
) -> None:
    evidence = document_tool.invoke('{"query":"refund revenue","top_k":1}')

    assert len(evidence.chunks) == 1
    assert evidence.chunks[0].logical_source == "revenue_policy.md"
    assert evidence.chunks[0].heading == "Refund Handling"


@pytest.mark.parametrize(
    "arguments",
    [
        "not-json",
        '{"query":"","top_k":1}',
        '{"query":"revenue","top_k":0}',
        '{"query":"revenue","top_k":21}',
        '{"query":"revenue","top_k":1,"path":"/secret"}',
    ],
)
def test_document_tool_rejects_invalid_or_capability_arguments(
    document_tool: DocumentRetrievalTool,
    arguments: str,
) -> None:
    with pytest.raises(ToolArgumentError):
        document_tool.invoke(arguments)
