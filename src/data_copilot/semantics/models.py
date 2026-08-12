"""Opaque, non-executable models for trusted business semantics."""

from pathlib import PurePath
import re
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator


_FIELD_REFERENCE_PATTERN = re.compile(
    r"^[A-Za-z_][A-Za-z0-9_$]*\."
    r"[A-Za-z_][A-Za-z0-9_$]*\."
    r"[A-Za-z_][A-Za-z0-9_$]*$"
)
_SEMANTIC_ID_PATTERN = r"^[a-z][a-z0-9_]*$"

NonEmptyText = Annotated[str, Field(min_length=1)]
SemanticId = Annotated[str, Field(pattern=_SEMANTIC_ID_PATTERN)]
FieldReferences = Annotated[tuple[str, ...], Field(min_length=1)]


def normalize_semantic_alias(value: str) -> str:
    """Normalize only whitespace at the edges and Unicode case."""

    return value.strip().casefold()


def _validate_unique_nonempty_strings(
    values: tuple[str, ...],
    *,
    field_name: str,
) -> tuple[str, ...]:
    seen: set[str] = set()
    normalized_values: list[str] = []
    for value in values:
        stripped = value.strip()
        if not stripped:
            raise ValueError(f"{field_name} entries cannot be empty")
        normalized = normalize_semantic_alias(stripped)
        if normalized in seen:
            raise ValueError(f"{field_name} entries must be unique")
        seen.add(normalized)
        normalized_values.append(stripped)
    return tuple(normalized_values)


def _validate_field_references(values: tuple[str, ...]) -> tuple[str, ...]:
    validated = _validate_unique_nonempty_strings(
        values,
        field_name="field reference",
    )
    if any(_FIELD_REFERENCE_PATTERN.fullmatch(value) is None for value in validated):
        raise ValueError("field references must use schema.table.column syntax")
    return validated


class _SemanticModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)


class SemanticProvenance(_SemanticModel):
    """Logical source identity safe to expose without a filesystem path."""

    source: NonEmptyText
    definition_id: SemanticId

    @field_validator("source")
    @classmethod
    def validate_safe_source(cls, value: str) -> str:
        if (
            PurePath(value).name != value
            or "/" in value
            or "\\" in value
            or "\x00" in value
        ):
            raise ValueError("source must be a safe logical file identifier")
        return value


class MetricDefinition(_SemanticModel):
    """Business meaning and required data inputs for a non-executable metric."""

    metric_id: SemanticId
    name: NonEmptyText
    display_name: NonEmptyText
    description: NonEmptyText
    synonyms: tuple[str, ...] = ()
    business_definition: NonEmptyText
    required_fields: FieldReferences
    optional_filters: tuple[str, ...] = ()
    owner: NonEmptyText | None = None
    tags: tuple[str, ...] = ()
    provenance: SemanticProvenance

    @field_validator("synonyms")
    @classmethod
    def validate_synonyms(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _validate_unique_nonempty_strings(values, field_name="synonym")

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _validate_unique_nonempty_strings(values, field_name="tag")

    @field_validator("required_fields", "optional_filters")
    @classmethod
    def validate_field_references(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _validate_field_references(values)


class DimensionDefinition(_SemanticModel):
    """Business dimension mapped to declared source-field references."""

    dimension_id: SemanticId
    name: NonEmptyText
    display_name: NonEmptyText
    description: NonEmptyText
    synonyms: tuple[str, ...] = ()
    source_fields: FieldReferences
    allowed_values_description: NonEmptyText | None = None
    tags: tuple[str, ...] = ()
    provenance: SemanticProvenance

    @field_validator("synonyms")
    @classmethod
    def validate_synonyms(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _validate_unique_nonempty_strings(values, field_name="synonym")

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _validate_unique_nonempty_strings(values, field_name="tag")

    @field_validator("source_fields")
    @classmethod
    def validate_source_fields(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _validate_field_references(values)


class GlossaryTerm(_SemanticModel):
    """A business concept with optional references to catalog definitions."""

    term_id: SemanticId
    term: NonEmptyText
    definition: NonEmptyText
    synonyms: tuple[str, ...] = ()
    related_metrics: tuple[SemanticId, ...] = ()
    related_dimensions: tuple[SemanticId, ...] = ()
    provenance: SemanticProvenance

    @field_validator("synonyms")
    @classmethod
    def validate_synonyms(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _validate_unique_nonempty_strings(values, field_name="synonym")

    @field_validator("related_metrics", "related_dimensions")
    @classmethod
    def validate_related_ids(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _validate_unique_nonempty_strings(values, field_name="related ID")
