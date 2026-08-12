"""Optional Agent-facing adapter for deterministic local document retrieval."""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from data_copilot.documents import (
    BusinessDocumentIndex,
    DocumentEvidence,
    DocumentEvidenceBuilder,
)
from data_copilot.documents.constants import (
    MAX_DOCUMENT_QUERY_CHARS,
    MAX_RETRIEVAL_TOP_K,
)
from data_copilot.errors import ToolArgumentError
from data_copilot.llm.models import ToolDefinition


class _RetrieveDocumentsArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    query: str = Field(
        min_length=1,
        max_length=MAX_DOCUMENT_QUERY_CHARS,
        description="Plain lexical query for relevant trusted business-document context.",
    )
    top_k: int = Field(
        ge=1,
        le=MAX_RETRIEVAL_TOP_K,
        description="Maximum number of relevant chunks to retrieve.",
    )


class DocumentRetrievalTool:
    """Retrieve local top chunks and build bounded document evidence."""

    name = "retrieve_documents"

    def __init__(
        self,
        index: BusinessDocumentIndex,
        *,
        evidence_builder: DocumentEvidenceBuilder | None = None,
    ) -> None:
        if not isinstance(index, BusinessDocumentIndex):
            raise TypeError("DocumentRetrievalTool requires a BusinessDocumentIndex.")
        self._index = index
        self._evidence_builder = evidence_builder or DocumentEvidenceBuilder()
        if not isinstance(self._evidence_builder, DocumentEvidenceBuilder):
            raise TypeError("evidence_builder must be a DocumentEvidenceBuilder.")
        self._schema = ToolDefinition(
            name=self.name,
            description=(
                "Retrieve bounded relevant chunks from the configured trusted local "
                "business-document index. Returns DOCUMENT_EVIDENCE for policy, "
                "rationale, history, and explanatory context. It does not return "
                "official structured metric definitions or observed database values."
            ),
            parameters=_strict_json_schema(_RetrieveDocumentsArguments),
        )

    @property
    def schema(self) -> ToolDefinition:
        return self._schema

    def invoke(self, arguments: str) -> DocumentEvidence:
        try:
            parsed = _RetrieveDocumentsArguments.model_validate_json(
                arguments,
                strict=True,
            )
        except (ValidationError, ValueError, TypeError):
            raise ToolArgumentError("Tool arguments are invalid.") from None
        results = self._index.search(parsed.query, top_k=parsed.top_k)
        return self._evidence_builder.build(results)


def _strict_json_schema(model: type[BaseModel]) -> dict[str, Any]:
    schema = model.model_json_schema()

    def make_strict(node: Any) -> None:
        if isinstance(node, dict):
            node.pop("default", None)
            if node.get("type") == "object":
                properties = node.get("properties", {})
                if isinstance(properties, dict):
                    node["required"] = list(properties)
                node["additionalProperties"] = False
            for value in node.values():
                make_strict(value)
        elif isinstance(node, list):
            for value in node:
                make_strict(value)

    make_strict(schema)
    return schema
