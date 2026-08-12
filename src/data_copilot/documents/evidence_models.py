"""Typed evidence models for retrieved business-document context."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from data_copilot.documents.models import (
    DocumentHeading,
    DocumentProvenance,
    DocumentTitle,
    LogicalSource,
    NonEmptyText,
)


class DocumentEvidenceChunk(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    chunk_id: str = Field(pattern=r"^chunk_[a-f0-9]{16}$")
    document_id: str = Field(pattern=r"^doc_[a-f0-9]{16}$")
    title: DocumentTitle
    heading: DocumentHeading | None = None
    logical_source: LogicalSource
    relevance_score: float = Field(gt=0, allow_inf_nan=False)
    text: NonEmptyText
    ordinal: int = Field(ge=0)
    provenance: DocumentProvenance

    @model_validator(mode="after")
    def validate_provenance(self) -> "DocumentEvidenceChunk":
        if (
            self.provenance.logical_source != self.logical_source
            or self.provenance.document_id != self.document_id
            or self.provenance.chunk_id != self.chunk_id
            or self.provenance.ordinal != self.ordinal
        ):
            raise ValueError("evidence provenance must match chunk identity")
        return self


class DocumentEvidence(BaseModel):
    """Only retrieved, bounded document chunks for future model context."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1] = 1
    chunks: tuple[DocumentEvidenceChunk, ...]
    truncated: bool
    warnings: tuple[str, ...]
