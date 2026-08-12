"""The sample_dataset Tool."""

from collections.abc import Sequence

from data_copilot.config import DEFAULT_SAMPLE_ROWS
from data_copilot.datasets.registry import DatasetRegistry
from data_copilot.execution.duckdb_engine import DuckDBEngine
from data_copilot.tools.models import SampleDatasetResult


class SampleDatasetTool:
    """Return a bounded DuckDB reservoir sample for a registered dataset."""

    name = "sample_dataset"

    def __init__(self, registry: DatasetRegistry) -> None:
        self._registry = registry
        self._engine = DuckDBEngine(registry)

    def __call__(
        self,
        dataset_id: str,
        *,
        columns: Sequence[str] | None = None,
        size: int = DEFAULT_SAMPLE_ROWS,
        seed: int = 42,
    ) -> SampleDatasetResult:
        self._registry.get(dataset_id)
        result = self._engine.sample(
            dataset_id, columns=columns, size=size, seed=seed
        )
        return SampleDatasetResult(
            dataset_id=dataset_id,
            columns=result.columns,
            rows=result.rows,
            row_count=result.row_count,
            requested_size=size,
            seed=seed,
            warnings=result.warnings,
        )
