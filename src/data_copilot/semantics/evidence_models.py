"""Typed, bounded semantic evidence distinct from observed data evidence."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from data_copilot.semantics.models import SemanticProvenance


class _SemanticEvidenceDefinition(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class MetricSemanticEvidence(_SemanticEvidenceDefinition):
    semantic_type: Literal["metric"] = "metric"
    metric_id: str
    name: str
    display_name: str
    description: str
    business_definition: str
    synonyms: tuple[str, ...]
    required_fields: tuple[str, ...]
    optional_filters: tuple[str, ...]
    provenance: SemanticProvenance


class DimensionSemanticEvidence(_SemanticEvidenceDefinition):
    semantic_type: Literal["dimension"] = "dimension"
    dimension_id: str
    name: str
    display_name: str
    description: str
    synonyms: tuple[str, ...]
    source_fields: tuple[str, ...]
    allowed_values_description: str | None = None
    provenance: SemanticProvenance


class GlossarySemanticEvidence(_SemanticEvidenceDefinition):
    semantic_type: Literal["glossary"] = "glossary"
    term_id: str
    term: str
    definition: str
    synonyms: tuple[str, ...]
    related_metrics: tuple[str, ...]
    related_dimensions: tuple[str, ...]
    provenance: SemanticProvenance


SemanticEvidenceDefinition = Annotated[
    MetricSemanticEvidence
    | DimensionSemanticEvidence
    | GlossarySemanticEvidence,
    Field(discriminator="semantic_type"),
]


class SemanticEvidence(BaseModel):
    """Relevant trusted definitions prepared for a future model context."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1] = 1
    definitions: tuple[SemanticEvidenceDefinition, ...]
    truncated: bool
    warnings: tuple[str, ...]
