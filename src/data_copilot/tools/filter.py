"""The filter_dataset Tool."""

from collections.abc import Sequence

from data_copilot.config import DEFAULT_RESULT_ROWS
from data_copilot.datasets.registry import DatasetRegistry
from data_copilot.execution.duckdb_engine import DuckDBEngine
from data_copilot.execution.query_models import FilterCondition, SortSpec
from data_copilot.tools.models import FilterDatasetResult


class FilterDatasetTool:
    """Return bounded source rows matching validated AND filters."""

    name = "filter_dataset"

    def __init__(self, registry: DatasetRegistry) -> None:
        self._registry = registry
        self._engine = DuckDBEngine(registry)

    def __call__(
        self,
        dataset_id: str,
        *,
        columns: Sequence[str] | None = None,
        filters: Sequence[FilterCondition] = (),
        order_by: Sequence[SortSpec] | None = None,
        limit: int = DEFAULT_RESULT_ROWS,
    ) -> FilterDatasetResult:
        self._registry.get(dataset_id)
        result = self._engine.filter(
            dataset_id,
            columns=columns,
            filters=filters,
            order_by=order_by,
            limit=limit,
        )
        return FilterDatasetResult(
            dataset_id=dataset_id,
            columns=result.columns,
            rows=result.rows,
            row_count=result.row_count,
            truncated=result.truncated,
            warnings=result.warnings,
        )
