"""The profile_dataset Tool."""

from collections.abc import Sequence

from data_copilot.config import DEFAULT_TOP_VALUES
from data_copilot.datasets.registry import DatasetRegistry
from data_copilot.execution.duckdb_engine import DuckDBEngine
from data_copilot.tools.models import ProfileDatasetResult


class ProfileDatasetTool:
    """Return bounded DuckDB aggregates for selected registered columns."""

    name = "profile_dataset"

    def __init__(self, registry: DatasetRegistry) -> None:
        self._registry = registry
        self._engine = DuckDBEngine(registry)

    def __call__(
        self,
        dataset_id: str,
        *,
        columns: Sequence[str] | None = None,
        top_k: int = DEFAULT_TOP_VALUES,
    ) -> ProfileDatasetResult:
        dataset = self._registry.get(dataset_id)
        profile = self._engine.profile(
            dataset_id, columns=columns, top_k=top_k
        )
        return ProfileDatasetResult(
            dataset_id=dataset.dataset_id,
            display_name=dataset.display_name,
            format=dataset.format,
            row_count=profile.row_count,
            column_count=profile.column_count,
            profiled_column_count=len(profile.columns),
            columns=profile.columns,
            warnings=profile.warnings,
        )
