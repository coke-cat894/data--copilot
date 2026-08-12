"""Public, path-free Tool result models."""

from pydantic import BaseModel, ConfigDict

from data_copilot.datasets.models import DatasetFormat
from data_copilot.execution.models import ColumnProfile
from data_copilot.execution.quality_models import DataQualityIssue


class ColumnSchema(BaseModel):
    """One public column name and DuckDB type."""

    model_config = ConfigDict(frozen=True)

    name: str
    type: str


class InspectDatasetResult(BaseModel):
    """Public schema, size, and shape returned by inspect_dataset."""

    model_config = ConfigDict(frozen=True)

    dataset_id: str
    display_name: str
    format: DatasetFormat
    file_size_bytes: int
    row_count: int
    column_count: int
    columns: tuple[ColumnSchema, ...]


class ProfileDatasetResult(BaseModel):
    """Public aggregate statistics returned by profile_dataset."""

    model_config = ConfigDict(frozen=True)

    dataset_id: str
    display_name: str
    format: DatasetFormat
    row_count: int
    column_count: int
    profiled_column_count: int
    columns: tuple[ColumnProfile, ...]
    warnings: tuple[str, ...] = ()


class TabularResultBase(BaseModel):
    """Shared path-free structure for bounded factual rows."""

    model_config = ConfigDict(frozen=True)

    dataset_id: str
    columns: tuple[str, ...]
    rows: tuple[dict[str, object], ...]
    row_count: int


class SampleDatasetResult(TabularResultBase):
    """Bounded reproducible random sample rows."""

    requested_size: int
    seed: int
    warnings: tuple[str, ...] = ()


class FilterDatasetResult(TabularResultBase):
    """Bounded rows matching structured AND filters."""

    truncated: bool
    warnings: tuple[str, ...] = ()


class AggregateDatasetResult(TabularResultBase):
    """Bounded grouped or whole-dataset aggregate rows."""

    truncated: bool


class DataQualityResult(BaseModel):
    """Public deterministic and heuristic data-quality observations."""

    model_config = ConfigDict(frozen=True)

    dataset_id: str
    display_name: str
    row_count: int
    column_count: int
    checked_column_count: int
    issues: tuple[DataQualityIssue, ...]
    warnings: tuple[str, ...] = ()
