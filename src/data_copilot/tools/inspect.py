"""The inspect_dataset Tool."""

from data_copilot.datasets.registry import DatasetRegistry
from data_copilot.execution.duckdb_engine import DuckDBEngine
from data_copilot.tools.models import ColumnSchema, InspectDatasetResult


class InspectDatasetTool:
    """Return public schema, size, and shape for one registered dataset ID."""

    name = "inspect_dataset"

    def __init__(self, registry: DatasetRegistry) -> None:
        self._registry = registry
        self._engine = DuckDBEngine(registry)

    def __call__(self, dataset_id: str) -> InspectDatasetResult:
        dataset = self._registry.get(dataset_id)
        inspection = self._engine.inspect(dataset_id)
        return InspectDatasetResult(
            dataset_id=dataset.dataset_id,
            display_name=dataset.display_name,
            format=dataset.format,
            file_size_bytes=dataset.file_size_bytes,
            row_count=inspection.row_count,
            column_count=inspection.column_count,
            columns=tuple(
                ColumnSchema(name=column.name, type=column.duckdb_type)
                for column in inspection.columns
            ),
        )
