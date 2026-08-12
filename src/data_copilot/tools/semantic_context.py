"""Optional Agent-facing adapter for deterministic semantic resolution."""

from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError

from data_copilot.errors import SemanticNotFoundError, ToolArgumentError
from data_copilot.llm.models import ToolDefinition
from data_copilot.semantics import (
    SemanticCatalog,
    SemanticEvidence,
    SemanticEvidenceBuilder,
    SemanticMentionExtractor,
    SemanticResolver,
)
from data_copilot.semantics.constants import MAX_SEMANTIC_QUERY_TERMS


SemanticQueryTerm = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=200),
]


class _ResolveSemanticArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    terms: tuple[SemanticQueryTerm, ...] = Field(
        min_length=1,
        max_length=MAX_SEMANTIC_QUERY_TERMS,
        description=(
            "Already-extracted candidate metric, dimension, or glossary terms. "
            "Use exact IDs, canonical names, or explicit synonyms only."
        ),
    )


class SemanticResolutionTool:
    """Resolve bounded candidate terms and build only relevant semantic evidence."""

    name = "resolve_semantic"

    def __init__(
        self,
        catalog: SemanticCatalog,
        *,
        resolver: SemanticResolver | None = None,
        evidence_builder: SemanticEvidenceBuilder | None = None,
    ) -> None:
        if not isinstance(catalog, SemanticCatalog):
            raise TypeError("SemanticResolutionTool requires a SemanticCatalog.")
        self._resolver = resolver or SemanticResolver(catalog)
        if not isinstance(self._resolver, SemanticResolver):
            raise TypeError("resolver must be a SemanticResolver.")
        self._evidence_builder = evidence_builder or SemanticEvidenceBuilder(catalog)
        if not isinstance(self._evidence_builder, SemanticEvidenceBuilder):
            raise TypeError("evidence_builder must be a SemanticEvidenceBuilder.")
        self._mention_extractor = SemanticMentionExtractor(catalog)
        self._schema = ToolDefinition(
            name=self.name,
            description=(
                "Resolve bounded candidate business terms against the configured "
                "structured Semantic Catalog. Returns authoritative "
                "SEMANTIC_EVIDENCE for exact IDs, canonical names, or explicit "
                "synonyms. Use for metric definitions, business dimensions, and "
                "glossary meaning; missing or ambiguous terms fail explicitly."
            ),
            parameters=_strict_json_schema(_ResolveSemanticArguments),
        )

    @property
    def schema(self) -> ToolDefinition:
        return self._schema

    def invoke(
        self,
        arguments: str,
        *,
        current_user_message: str | None = None,
    ) -> SemanticEvidence:
        try:
            parsed = _ResolveSemanticArguments.model_validate_json(
                arguments,
                strict=True,
            )
        except (ValidationError, ValueError, TypeError):
            raise ToolArgumentError("Tool arguments are invalid.") from None
        exact_mentions = (
            self._mention_extractor.extract(current_user_message)
            if current_user_message is not None
            else ()
        )
        merged_terms = _merge_terms(exact_mentions, parsed.terms)
        if not exact_mentions:
            resolutions = self._resolver.resolve_many(merged_terms)
        else:
            resolved = list(self._resolver.resolve_many(exact_mentions))
            exact_normalized = {
                term.strip().casefold() for term in exact_mentions
            }
            for term in merged_terms:
                if term.strip().casefold() in exact_normalized:
                    continue
                try:
                    resolved.append(self._resolver.resolve(term))
                except SemanticNotFoundError:
                    continue
            resolutions = tuple(resolved)
        return self._evidence_builder.build(resolutions)


def _merge_terms(
    exact_mentions: tuple[str, ...],
    llm_terms: tuple[str, ...],
) -> tuple[str, ...]:
    merged: list[str] = []
    seen: set[str] = set()
    for term in (*exact_mentions, *llm_terms):
        normalized = term.strip().casefold()
        if normalized not in seen:
            seen.add(normalized)
            merged.append(term)
        if len(merged) == MAX_SEMANTIC_QUERY_TERMS:
            break
    return tuple(merged)


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
