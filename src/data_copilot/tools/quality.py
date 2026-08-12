"""The check_data_quality Tool."""

from collections.abc import Sequence
from datetime import datetime, timezone

from data_copilot.datasets.registry import DatasetRegistry
from data_copilot.execution.duckdb_engine import DuckDBEngine
from data_copilot.tools.models import DataQualityResult


class CheckDataQualityTool:
    """Return fixed DuckDB-computed quality observations for one dataset."""

    name = "check_data_quality"

    def __init__(self, registry: DatasetRegistry) -> None:
        self._registry = registry
        self._engine = DuckDBEngine(registry)

    def __call__(
        self,
        dataset_id: str,
        *,
        columns: Sequence[str] | None = None,
        reference_time: datetime | None = None,
    ) -> DataQualityResult:
        dataset = self._registry.get(dataset_id)
        effective_reference_time = reference_time or datetime.now(timezone.utc)
        result = self._engine.check_quality(
            dataset_id,
            columns=columns,
            reference_time=effective_reference_time,
        )
        return DataQualityResult(
            dataset_id=dataset.dataset_id,
            display_name=dataset.display_name,
            row_count=result.row_count,
            column_count=result.column_count,
            checked_column_count=result.checked_column_count,
            issues=result.issues,
            warnings=result.warnings,
        )
