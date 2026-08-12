"""Typed compact-evidence envelope and provenance metadata."""

from enum import Enum

from pydantic import BaseModel, ConfigDict, JsonValue


class EvidenceOperation(str, Enum):
    INSPECT_DATASET = "inspect_dataset"
    PROFILE_DATASET = "profile_dataset"
    SAMPLE_DATASET = "sample_dataset"
    FILTER_DATASET = "filter_dataset"
    AGGREGATE_DATASET = "aggregate_dataset"
    CHECK_DATA_QUALITY = "check_data_quality"


class EvidenceMetadata(BaseModel):
    """Minimal source/evidence size provenance."""

    model_config = ConfigDict(frozen=True)

    source_row_count: int
    evidence_record_count: int
    source_column_count: int
    evidence_column_count: int


class Evidence(BaseModel):
    """Uniform envelope with Tool-specific normalized factual records."""

    model_config = ConfigDict(frozen=True)

    evidence_id: str
    dataset_id: str
    operation: EvidenceOperation
    summary: dict[str, JsonValue]
    columns: tuple[str, ...]
    records: tuple[JsonValue, ...]
    source_truncated: bool
    evidence_truncated: bool
    warnings: tuple[str, ...]
    metadata: EvidenceMetadata
