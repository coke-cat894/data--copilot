"""Deterministic resolution of already-extracted semantic candidate terms."""

from collections.abc import Sequence
from enum import Enum

from pydantic import BaseModel, ConfigDict

from data_copilot.errors import (
    SemanticAmbiguityError,
    SemanticNotFoundError,
    SemanticResolutionLimitError,
)
from data_copilot.semantics.catalog import SemanticCatalog
from data_copilot.semantics.constants import MAX_SEMANTIC_QUERY_TERMS
from data_copilot.semantics.models import (
    SemanticProvenance,
    normalize_semantic_alias,
)


class SemanticType(str, Enum):
    """Semantic definition categories supported by the catalog."""

    METRIC = "metric"
    DIMENSION = "dimension"
    GLOSSARY = "glossary"


class SemanticMatchType(str, Enum):
    """The exact deterministic alias class that matched a query term."""

    EXACT_ID = "exact_id"
    CANONICAL_NAME = "canonical_name"
    EXPLICIT_SYNONYM = "explicit_synonym"


class SemanticResolution(BaseModel):
    """Minimal resolution metadata without copying a complete definition."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    query_term: str
    semantic_type: SemanticType
    definition_id: str
    canonical_name: str
    match_type: SemanticMatchType
    provenance: SemanticProvenance


class SemanticResolver:
    """Resolve IDs, canonical names, and explicit synonyms across one catalog."""

    def __init__(
        self,
        catalog: SemanticCatalog,
        *,
        max_terms: int = MAX_SEMANTIC_QUERY_TERMS,
    ) -> None:
        if not isinstance(catalog, SemanticCatalog):
            raise TypeError("SemanticResolver requires a SemanticCatalog.")
        if isinstance(max_terms, bool) or not isinstance(max_terms, int) or max_terms < 1:
            raise SemanticResolutionLimitError(
                "max_terms must be a positive integer."
            )
        self._catalog = catalog
        self._max_terms = max_terms

    def resolve(self, query_term: str) -> SemanticResolution:
        """Resolve one candidate term, failing closed on missing or ambiguous matches."""

        if not isinstance(query_term, str) or not query_term.strip():
            raise SemanticNotFoundError("Semantic term not found.")
        normalized = normalize_semantic_alias(query_term)
        candidates: list[SemanticResolution] = []

        for metric in self._catalog.metrics:
            match_type = _match_type(
                normalized,
                definition_id=metric.metric_id,
                canonical_name=metric.name,
                synonyms=metric.synonyms,
            )
            if match_type is not None:
                candidates.append(
                    SemanticResolution(
                        query_term=query_term.strip(),
                        semantic_type=SemanticType.METRIC,
                        definition_id=metric.metric_id,
                        canonical_name=metric.name,
                        match_type=match_type,
                        provenance=metric.provenance,
                    )
                )

        for dimension in self._catalog.dimensions:
            match_type = _match_type(
                normalized,
                definition_id=dimension.dimension_id,
                canonical_name=dimension.name,
                synonyms=dimension.synonyms,
            )
            if match_type is not None:
                candidates.append(
                    SemanticResolution(
                        query_term=query_term.strip(),
                        semantic_type=SemanticType.DIMENSION,
                        definition_id=dimension.dimension_id,
                        canonical_name=dimension.name,
                        match_type=match_type,
                        provenance=dimension.provenance,
                    )
                )

        for term in self._catalog.glossary:
            match_type = _match_type(
                normalized,
                definition_id=term.term_id,
                canonical_name=term.term,
                synonyms=term.synonyms,
            )
            if match_type is not None:
                candidates.append(
                    SemanticResolution(
                        query_term=query_term.strip(),
                        semantic_type=SemanticType.GLOSSARY,
                        definition_id=term.term_id,
                        canonical_name=term.term,
                        match_type=match_type,
                        provenance=term.provenance,
                    )
                )

        if not candidates:
            raise SemanticNotFoundError("Semantic term not found.")
        if len(candidates) > 1:
            raise SemanticAmbiguityError(
                "Semantic term is ambiguous across definition types."
            )
        return candidates[0]

    def resolve_many(
        self,
        query_terms: Sequence[str],
    ) -> tuple[SemanticResolution, ...]:
        """Resolve a bounded collection in caller-provided order."""

        if isinstance(query_terms, (str, bytes)) or not isinstance(
            query_terms, Sequence
        ):
            raise TypeError("query_terms must be a sequence of strings.")
        if len(query_terms) > self._max_terms:
            raise SemanticResolutionLimitError(
                "Semantic query contains too many candidate terms."
            )
        return tuple(self.resolve(query_term) for query_term in query_terms)


def _match_type(
    normalized_query: str,
    *,
    definition_id: str,
    canonical_name: str,
    synonyms: tuple[str, ...],
) -> SemanticMatchType | None:
    if normalized_query == normalize_semantic_alias(definition_id):
        return SemanticMatchType.EXACT_ID
    if normalized_query == normalize_semantic_alias(canonical_name):
        return SemanticMatchType.CANONICAL_NAME
    if any(
        normalized_query == normalize_semantic_alias(synonym)
        for synonym in synonyms
    ):
        return SemanticMatchType.EXPLICIT_SYNONYM
    return None
