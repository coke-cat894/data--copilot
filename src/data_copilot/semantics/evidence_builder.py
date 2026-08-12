"""Build compact semantic evidence from trusted catalog resolutions."""

from collections.abc import Sequence

from data_copilot.errors import (
    SemanticEvidenceBuildError,
    SemanticEvidenceLimitError,
    SemanticNotFoundError,
)
from data_copilot.semantics.catalog import SemanticCatalog
from data_copilot.semantics.constants import (
    MAX_SEMANTIC_EVIDENCE_CHARS,
    MAX_SEMANTIC_EVIDENCE_DEFINITIONS,
    MAX_SEMANTIC_FIELDS,
    MAX_SEMANTIC_SYNONYMS,
    MAX_SEMANTIC_TEXT_CHARS,
)
from data_copilot.semantics.evidence_formatter import (
    SEMANTIC_EVIDENCE_PREFIX,
    serialize_semantic_evidence,
)
from data_copilot.semantics.evidence_models import (
    DimensionSemanticEvidence,
    GlossarySemanticEvidence,
    MetricSemanticEvidence,
    SemanticEvidence,
    SemanticEvidenceDefinition,
)
from data_copilot.semantics.resolution import SemanticResolution, SemanticType


class SemanticEvidenceBuilder:
    """Select, structurally bound, and validate only resolved definitions."""

    def __init__(
        self,
        catalog: SemanticCatalog,
        *,
        max_definitions: int = MAX_SEMANTIC_EVIDENCE_DEFINITIONS,
        max_text_chars: int = MAX_SEMANTIC_TEXT_CHARS,
        max_synonyms: int = MAX_SEMANTIC_SYNONYMS,
        max_fields: int = MAX_SEMANTIC_FIELDS,
        max_chars: int = MAX_SEMANTIC_EVIDENCE_CHARS,
    ) -> None:
        if not isinstance(catalog, SemanticCatalog):
            raise TypeError("SemanticEvidenceBuilder requires a SemanticCatalog.")
        self._max_definitions = _positive_limit("max_definitions", max_definitions)
        self._max_text_chars = _positive_limit("max_text_chars", max_text_chars)
        self._max_synonyms = _positive_limit("max_synonyms", max_synonyms)
        self._max_fields = _positive_limit("max_fields", max_fields)
        self._max_chars = _positive_limit("max_chars", max_chars)
        self._catalog = catalog

    def build(
        self,
        resolutions: Sequence[SemanticResolution],
    ) -> SemanticEvidence:
        """Build evidence in resolution order, deduplicating identical definitions."""

        if isinstance(resolutions, (str, bytes)) or not isinstance(
            resolutions, Sequence
        ):
            raise TypeError("resolutions must be a sequence.")

        unique: list[SemanticResolution] = []
        seen: set[tuple[SemanticType, str]] = set()
        for resolution in resolutions:
            if not isinstance(resolution, SemanticResolution):
                raise SemanticEvidenceBuildError(
                    "Semantic evidence requires typed resolution results."
                )
            identity = (resolution.semantic_type, resolution.definition_id)
            if identity not in seen:
                seen.add(identity)
                unique.append(resolution)

        warnings: list[str] = []
        truncated = False
        if len(unique) > self._max_definitions:
            original_count = len(unique)
            unique = unique[: self._max_definitions]
            truncated = True
            warnings.append(
                f"Semantic definitions truncated from {original_count} to "
                f"{self._max_definitions} because "
                f"MAX_SEMANTIC_EVIDENCE_DEFINITIONS={self._max_definitions}."
            )

        definitions: list[SemanticEvidenceDefinition] = []
        for resolution in unique:
            try:
                definition, definition_warnings = self._build_definition(resolution)
            except SemanticNotFoundError:
                raise SemanticEvidenceBuildError(
                    "Semantic resolution references an unknown catalog object."
                ) from None
            definitions.append(definition)
            if definition_warnings:
                truncated = True
                warnings.extend(definition_warnings)

        evidence = SemanticEvidence(
            definitions=tuple(definitions),
            truncated=truncated,
            warnings=tuple(warnings),
        )
        return self._fit_total_size(evidence)

    def _build_definition(
        self,
        resolution: SemanticResolution,
    ) -> tuple[SemanticEvidenceDefinition, tuple[str, ...]]:
        warnings: list[str] = []
        if resolution.semantic_type is SemanticType.METRIC:
            definition = self._catalog.get_metric(resolution.definition_id)
            self._validate_resolution(
                resolution,
                definition_id=definition.metric_id,
                canonical_name=definition.name,
                provenance=definition.provenance,
            )
            return (
                MetricSemanticEvidence(
                    metric_id=definition.metric_id,
                    name=definition.name,
                    display_name=definition.display_name,
                    description=self._bound_text(
                        definition.description,
                        definition.metric_id,
                        "description",
                        warnings,
                    ),
                    business_definition=self._bound_text(
                        definition.business_definition,
                        definition.metric_id,
                        "business definition",
                        warnings,
                    ),
                    synonyms=self._bound_items(
                        definition.synonyms,
                        self._max_synonyms,
                        definition.metric_id,
                        "synonyms",
                        warnings,
                    ),
                    required_fields=self._bound_items(
                        definition.required_fields,
                        self._max_fields,
                        definition.metric_id,
                        "required fields",
                        warnings,
                    ),
                    optional_filters=self._bound_items(
                        definition.optional_filters,
                        self._max_fields,
                        definition.metric_id,
                        "optional filters",
                        warnings,
                    ),
                    provenance=definition.provenance,
                ),
                tuple(warnings),
            )
        if resolution.semantic_type is SemanticType.DIMENSION:
            definition = self._catalog.get_dimension(resolution.definition_id)
            self._validate_resolution(
                resolution,
                definition_id=definition.dimension_id,
                canonical_name=definition.name,
                provenance=definition.provenance,
            )
            return (
                DimensionSemanticEvidence(
                    dimension_id=definition.dimension_id,
                    name=definition.name,
                    display_name=definition.display_name,
                    description=self._bound_text(
                        definition.description,
                        definition.dimension_id,
                        "description",
                        warnings,
                    ),
                    synonyms=self._bound_items(
                        definition.synonyms,
                        self._max_synonyms,
                        definition.dimension_id,
                        "synonyms",
                        warnings,
                    ),
                    source_fields=self._bound_items(
                        definition.source_fields,
                        self._max_fields,
                        definition.dimension_id,
                        "source fields",
                        warnings,
                    ),
                    allowed_values_description=(
                        self._bound_text(
                            definition.allowed_values_description,
                            definition.dimension_id,
                            "allowed values description",
                            warnings,
                        )
                        if definition.allowed_values_description is not None
                        else None
                    ),
                    provenance=definition.provenance,
                ),
                tuple(warnings),
            )
        if resolution.semantic_type is SemanticType.GLOSSARY:
            definition = self._catalog.get_glossary_term(resolution.definition_id)
            self._validate_resolution(
                resolution,
                definition_id=definition.term_id,
                canonical_name=definition.term,
                provenance=definition.provenance,
            )
            return (
                GlossarySemanticEvidence(
                    term_id=definition.term_id,
                    term=definition.term,
                    definition=self._bound_text(
                        definition.definition,
                        definition.term_id,
                        "definition",
                        warnings,
                    ),
                    synonyms=self._bound_items(
                        definition.synonyms,
                        self._max_synonyms,
                        definition.term_id,
                        "synonyms",
                        warnings,
                    ),
                    related_metrics=self._bound_items(
                        definition.related_metrics,
                        self._max_fields,
                        definition.term_id,
                        "related metrics",
                        warnings,
                    ),
                    related_dimensions=self._bound_items(
                        definition.related_dimensions,
                        self._max_fields,
                        definition.term_id,
                        "related dimensions",
                        warnings,
                    ),
                    provenance=definition.provenance,
                ),
                tuple(warnings),
            )
        raise SemanticEvidenceBuildError("Unsupported semantic resolution type.")

    @staticmethod
    def _validate_resolution(
        resolution: SemanticResolution,
        *,
        definition_id: str,
        canonical_name: str,
        provenance: object,
    ) -> None:
        if (
            resolution.definition_id != definition_id
            or resolution.canonical_name != canonical_name
            or resolution.provenance != provenance
        ):
            raise SemanticEvidenceBuildError(
                "Semantic resolution is inconsistent with the catalog."
            )

    def _bound_text(
        self,
        value: str,
        definition_id: str,
        field_name: str,
        warnings: list[str],
    ) -> str:
        if len(value) <= self._max_text_chars:
            return value
        warnings.append(
            f"Semantic {field_name} for '{definition_id}' was truncated because "
            f"MAX_SEMANTIC_TEXT_CHARS={self._max_text_chars}."
        )
        if self._max_text_chars == 1:
            return "…"
        return value[: self._max_text_chars - 1] + "…"

    @staticmethod
    def _bound_items(
        values: tuple[str, ...],
        limit: int,
        definition_id: str,
        field_name: str,
        warnings: list[str],
    ) -> tuple[str, ...]:
        if len(values) <= limit:
            return values
        warnings.append(
            f"Semantic {field_name} for '{definition_id}' were truncated to {limit}."
        )
        return values[:limit]

    def _fit_total_size(self, evidence: SemanticEvidence) -> SemanticEvidence:
        current = evidence
        while self._formatted_length(current) > self._max_chars and current.definitions:
            removed_definition = current.definitions[-1]
            removed_id = _evidence_definition_id(removed_definition)
            warning = (
                "Semantic definitions were reduced to satisfy the total character "
                "limit "
                f"MAX_SEMANTIC_EVIDENCE_CHARS={self._max_chars}."
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
                    "definitions": current.definitions[:-1],
                    "truncated": True,
                    "warnings": warnings,
                }
            )
        if self._formatted_length(current) > self._max_chars:
            raise SemanticEvidenceLimitError(
                "Semantic evidence envelope cannot fit the total character limit."
            )
        return current

    @staticmethod
    def _formatted_length(evidence: SemanticEvidence) -> int:
        return len(SEMANTIC_EVIDENCE_PREFIX + serialize_semantic_evidence(evidence))


def _positive_limit(name: str, value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise SemanticEvidenceLimitError(f"{name} must be a positive integer.")
    return value


def _evidence_definition_id(definition: SemanticEvidenceDefinition) -> str:
    if isinstance(definition, MetricSemanticEvidence):
        return definition.metric_id
    if isinstance(definition, DimensionSemanticEvidence):
        return definition.dimension_id
    return definition.term_id
