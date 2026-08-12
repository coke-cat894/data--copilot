"""Validated, deterministic in-memory semantic catalog."""

from collections.abc import Callable, Iterable
from typing import TypeVar

from data_copilot.errors import (
    SemanticAmbiguityError,
    SemanticConfigurationError,
    SemanticNotFoundError,
    SemanticReferenceError,
)
from data_copilot.semantics.models import (
    DimensionDefinition,
    GlossaryTerm,
    MetricDefinition,
    normalize_semantic_alias,
)


SemanticDefinition = TypeVar(
    "SemanticDefinition",
    MetricDefinition,
    DimensionDefinition,
    GlossaryTerm,
)


class SemanticCatalog:
    """Store and resolve validated semantic definitions without fuzzy matching."""

    def __init__(
        self,
        *,
        metrics: Iterable[MetricDefinition] = (),
        dimensions: Iterable[DimensionDefinition] = (),
        glossary: Iterable[GlossaryTerm] = (),
    ) -> None:
        self._metrics = tuple(metrics)
        self._dimensions = tuple(dimensions)
        self._glossary = tuple(glossary)

        self._metric_aliases = self._build_alias_index(
            self._metrics,
            definition_type=MetricDefinition,
            kind="metric",
            id_getter=lambda definition: definition.metric_id,
            name_getter=lambda definition: definition.name,
        )
        self._dimension_aliases = self._build_alias_index(
            self._dimensions,
            definition_type=DimensionDefinition,
            kind="dimension",
            id_getter=lambda definition: definition.dimension_id,
            name_getter=lambda definition: definition.name,
        )
        self._glossary_aliases = self._build_alias_index(
            self._glossary,
            definition_type=GlossaryTerm,
            kind="glossary term",
            id_getter=lambda definition: definition.term_id,
            name_getter=lambda definition: definition.term,
        )
        self._validate_references()

    @property
    def metrics(self) -> tuple[MetricDefinition, ...]:
        return self._metrics

    @property
    def dimensions(self) -> tuple[DimensionDefinition, ...]:
        return self._dimensions

    @property
    def glossary(self) -> tuple[GlossaryTerm, ...]:
        return self._glossary

    def get_metric(self, identifier_or_name: str) -> MetricDefinition:
        return self._resolve(self._metric_aliases, identifier_or_name, kind="Metric")

    def get_dimension(self, identifier_or_name: str) -> DimensionDefinition:
        return self._resolve(
            self._dimension_aliases,
            identifier_or_name,
            kind="Dimension",
        )

    def get_glossary_term(self, identifier_or_name: str) -> GlossaryTerm:
        return self._resolve(
            self._glossary_aliases,
            identifier_or_name,
            kind="Glossary term",
        )

    @staticmethod
    def _build_alias_index(
        definitions: tuple[SemanticDefinition, ...],
        *,
        definition_type: type[SemanticDefinition],
        kind: str,
        id_getter: Callable[[SemanticDefinition], str],
        name_getter: Callable[[SemanticDefinition], str],
    ) -> dict[str, SemanticDefinition]:
        aliases: dict[str, SemanticDefinition] = {}
        ids: set[str] = set()
        for definition in definitions:
            if not isinstance(definition, definition_type):
                raise SemanticConfigurationError(
                    f"Unsupported definition in {kind} collection."
                )
            definition_id = id_getter(definition)
            if definition_id in ids:
                raise SemanticConfigurationError(f"Duplicate {kind} ID.")
            ids.add(definition_id)

            for alias in (definition_id, name_getter(definition), *definition.synonyms):
                normalized = normalize_semantic_alias(alias)
                existing = aliases.get(normalized)
                if existing is not None and existing is not definition:
                    raise SemanticAmbiguityError(
                        f"Ambiguous normalized alias in {kind} definitions."
                    )
                aliases[normalized] = definition
        return aliases

    @staticmethod
    def _resolve(
        aliases: dict[str, SemanticDefinition],
        identifier_or_name: str,
        *,
        kind: str,
    ) -> SemanticDefinition:
        if not isinstance(identifier_or_name, str) or not identifier_or_name.strip():
            raise SemanticNotFoundError(f"{kind} not found.")
        definition = aliases.get(normalize_semantic_alias(identifier_or_name))
        if definition is None:
            raise SemanticNotFoundError(f"{kind} not found.")
        return definition

    def _validate_references(self) -> None:
        metric_ids = {metric.metric_id for metric in self._metrics}
        dimension_ids = {dimension.dimension_id for dimension in self._dimensions}
        for term in self._glossary:
            if any(metric_id not in metric_ids for metric_id in term.related_metrics):
                raise SemanticReferenceError(
                    "Glossary term references an unknown metric ID."
                )
            if any(
                dimension_id not in dimension_ids
                for dimension_id in term.related_dimensions
            ):
                raise SemanticReferenceError(
                    "Glossary term references an unknown dimension ID."
                )
