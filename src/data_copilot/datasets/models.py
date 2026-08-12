"""Typed models for registered datasets."""

from enum import Enum
from pathlib import Path

from pydantic import BaseModel, ConfigDict


class DatasetFormat(str, Enum):
    """Local dataset formats supported in Phase 1.1."""

    CSV = "csv"
    PARQUET = "parquet"
    JSONL = "jsonl"


class PublicDatasetMetadata(BaseModel):
    """Metadata safe to expose without leaking a local filesystem path."""

    model_config = ConfigDict(frozen=True)

    dataset_id: str
    display_name: str
    format: DatasetFormat
    file_size_bytes: int


class Dataset(PublicDatasetMetadata):
    """Internal dataset metadata retained only by deterministic code."""

    resolved_path: Path

    def to_public_metadata(self) -> PublicDatasetMetadata:
        """Return metadata that deliberately omits the resolved local path."""

        return PublicDatasetMetadata(
            dataset_id=self.dataset_id,
            display_name=self.display_name,
            format=self.format,
            file_size_bytes=self.file_size_bytes,
        )
