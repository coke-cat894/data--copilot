"""The aggregate_dataset Tool."""

from collections.abc import Sequence

from data_copilot.config import DEFAULT_RESULT_ROWS
from data_copilot.datasets.registry import DatasetRegistry
from data_copilot.execution.duckdb_engine import DuckDBEngine
from data_copilot.execution.query_models import (
    AggregateSortSpec,
    DimensionSpec,
    FilterCondition,
    MetricSpec,
)
from data_copilot.tools.models import AggregateDatasetResult


class AggregateDatasetTool:
    """Return bounded aggregates from validated dimensions and metrics."""

    name = "aggregate_dataset"

    def __init__(self, registry: DatasetRegistry) -> None:
        self._registry = registry
        self._engine = DuckDBEngine(registry)

    def __call__(
        self,
        dataset_id: str,
        *,
        dimensions: Sequence[DimensionSpec] = (),
        metrics: Sequence[MetricSpec],
        filters: Sequence[FilterCondition] = (),
        order_by: Sequence[AggregateSortSpec] = (),
        limit: int = DEFAULT_RESULT_ROWS,
    ) -> AggregateDatasetResult:
        self._registry.get(dataset_id)
        result = self._engine.aggregate(
            dataset_id,
            dimensions=dimensions,
            metrics=metrics,
            filters=filters,
            order_by=order_by,
            limit=limit,
        )
        return AggregateDatasetResult(
            dataset_id=dataset_id,
            columns=result.columns,
            rows=result.rows,
            row_count=result.row_count,
            truncated=result.truncated,
        )
