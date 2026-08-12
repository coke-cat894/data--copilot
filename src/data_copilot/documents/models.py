"""Typed, path-safe models for trusted local business documents."""

from pathlib import PurePath
import re
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


_DOCUMENT_ID_PATTERN = r"^doc_[a-f0-9]{16}$"
_CHUNK_ID_PATTERN = r"^chunk_[a-f0-9]{16}$"
NonEmptyText = Annotated[str, Field(min_length=1)]
LogicalSource = Annotated[str, Field(min_length=1, max_length=255)]
DocumentTitle = Annotated[str, Field(min_length=1, max_length=500)]
DocumentHeading = Annotated[str, Field(min_length=1, max_length=500)]


class _DocumentModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)


class DocumentProvenance(_DocumentModel):
    """Safe logical document and chunk identity for future citation."""

    logical_source: LogicalSource
    document_id: Annotated[str, Field(pattern=_DOCUMENT_ID_PATTERN)]
    chunk_id: Annotated[str, Field(pattern=_CHUNK_ID_PATTERN)]
    ordinal: Annotated[int, Field(ge=0)]

    @field_validator("logical_source")
    @classmethod
    def validate_logical_source(cls, value: str) -> str:
        if (
            PurePath(value).name != value
            or "/" in value
            or "\\" in value
            or "\x00" in value
        ):
            raise ValueError("logical_source must be a safe logical file identifier")
        return value


class BusinessDocument(_DocumentModel):
    """Program-managed content loaded from one trusted Markdown or text file."""

    document_id: Annotated[str, Field(pattern=_DOCUMENT_ID_PATTERN)]
    title: DocumentTitle
    logical_source: LogicalSource
    content: NonEmptyText

    @field_validator("logical_source")
    @classmethod
    def validate_logical_source(cls, value: str) -> str:
        return DocumentProvenance.validate_logical_source(value)


class DocumentChunk(_DocumentModel):
    """One deterministic bounded section/paragraph chunk."""

    chunk_id: Annotated[str, Field(pattern=_CHUNK_ID_PATTERN)]
    document_id: Annotated[str, Field(pattern=_DOCUMENT_ID_PATTERN)]
    title: DocumentTitle
    logical_source: LogicalSource
    heading: DocumentHeading | None = None
    text: NonEmptyText
    ordinal: Annotated[int, Field(ge=0)]
    provenance: DocumentProvenance

    @field_validator("logical_source")
    @classmethod
    def validate_logical_source(cls, value: str) -> str:
        return DocumentProvenance.validate_logical_source(value)

    @model_validator(mode="after")
    def validate_provenance(self) -> "DocumentChunk":
        if (
            self.provenance.logical_source != self.logical_source
            or self.provenance.document_id != self.document_id
            or self.provenance.chunk_id != self.chunk_id
            or self.provenance.ordinal != self.ordinal
        ):
            raise ValueError("chunk provenance must match chunk identity")
        return self


class DocumentRetrievalResult(_DocumentModel):
    """A scored document chunk returned by deterministic lexical retrieval."""

    chunk_id: Annotated[str, Field(pattern=_CHUNK_ID_PATTERN)]
    document_id: Annotated[str, Field(pattern=_DOCUMENT_ID_PATTERN)]
    title: DocumentTitle
    heading: DocumentHeading | None = None
    logical_source: LogicalSource
    relevance_score: Annotated[float, Field(gt=0, allow_inf_nan=False)]
    text: NonEmptyText
    ordinal: Annotated[int, Field(ge=0)]
    provenance: DocumentProvenance

    @field_validator("logical_source")
    @classmethod
    def validate_logical_source(cls, value: str) -> str:
        return DocumentProvenance.validate_logical_source(value)

    @model_validator(mode="after")
    def validate_provenance(self) -> "DocumentRetrievalResult":
        if (
            self.provenance.logical_source != self.logical_source
            or self.provenance.document_id != self.document_id
            or self.provenance.chunk_id != self.chunk_id
            or self.provenance.ordinal != self.ordinal
        ):
            raise ValueError("retrieval provenance must match chunk identity")
        return self


_TOKEN_PATTERN = re.compile(r"[^\W_]+", re.UNICODE)


def lexical_tokens(value: str) -> tuple[str, ...]:
    """Return conservative Unicode word tokens for deterministic local retrieval."""

    return tuple(token.casefold() for token in _TOKEN_PATTERN.findall(value))
