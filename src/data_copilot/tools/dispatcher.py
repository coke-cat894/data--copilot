"""Static allowlisted dispatch for untrusted LLM Tool calls."""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from data_copilot.datasets.registry import DatasetRegistry
from data_copilot.errors import ToolArgumentError, UnknownToolError
from data_copilot.execution.query_models import (
    AggregateFunction,
    AggregateSortSpec,
    DimensionSpec,
    FilterCondition,
    FilterOperator,
    MetricSpec,
    SortDirection,
    SortSpec,
    TimeGrain,
)
from data_copilot.llm.models import ToolDefinition
from data_copilot.tools.aggregate import AggregateDatasetTool
from data_copilot.tools.filter import FilterDatasetTool
from data_copilot.tools.inspect import InspectDatasetTool
from data_copilot.tools.models import (
    AggregateDatasetResult,
    DataQualityResult,
    FilterDatasetResult,
    InspectDatasetResult,
    ProfileDatasetResult,
    SampleDatasetResult,
)
from data_copilot.tools.profile import ProfileDatasetTool
from data_copilot.tools.quality import CheckDataQualityTool
from data_copilot.tools.sample import SampleDatasetTool


ToolResult = (
    InspectDatasetResult
    | ProfileDatasetResult
    | SampleDatasetResult
    | FilterDatasetResult
    | AggregateDatasetResult
    | DataQualityResult
)
JsonScalar = str | bool | int | float
JsonFilterValue = JsonScalar | list[JsonScalar] | None


class _Arguments(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class InspectArguments(_Arguments):
    pass


class ProfileArguments(_Arguments):
    columns: list[str] | None = Field(
        default=None, description="Source columns to profile, or null for the bounded default."
    )
    top_k: int = Field(default=10, description="Maximum top values per categorical column.")


class SampleArguments(_Arguments):
    columns: list[str] | None = Field(
        default=None, description="Source columns to sample, or null for the bounded default."
    )
    size: int = Field(default=20, description="Requested bounded sample row count.")
    seed: int = Field(default=42, description="Integer seed for reproducible sampling.")


class FilterConditionArguments(_Arguments):
    column: str = Field(description="Exact source column name.")
    operator: FilterOperator = Field(description="Validated comparison operator.")
    value: JsonFilterValue = Field(
        default=None,
        description="Scalar, scalar list, or null value required by the operator.",
    )


class SortArguments(_Arguments):
    column: str = Field(description="Exact source column name.")
    direction: SortDirection = Field(
        default=SortDirection.ASC, description="Ascending or descending order."
    )


class FilterArguments(_Arguments):
    columns: list[str] | None = Field(
        default=None, description="Output columns, or null for the bounded default."
    )
    filters: list[FilterConditionArguments] = Field(
        default_factory=list, description="Validated conditions combined with AND."
    )
    order_by: list[SortArguments] | None = Field(
        default=None, description="Source-column sorting, or null for no sorting."
    )
    limit: int = Field(default=50, description="Maximum bounded result rows.")


class DimensionArguments(_Arguments):
    name: str = Field(description="Safe unique output name for the dimension.")
    column: str = Field(description="Exact source column name.")
    time_grain: TimeGrain | None = Field(
        default=None, description="Calendar grain for DATE/TIMESTAMP, or null."
    )


class MetricArguments(_Arguments):
    name: str = Field(description="Safe unique output name for the metric.")
    function: AggregateFunction = Field(description="Validated aggregate function.")
    column: str | None = Field(
        default=None, description="Exact source column, or null only for count."
    )


class AggregateSortArguments(_Arguments):
    field: str = Field(description="Dimension or metric output name.")
    direction: SortDirection = Field(
        default=SortDirection.ASC, description="Ascending or descending order."
    )


class AggregateArguments(_Arguments):
    dimensions: list[DimensionArguments] = Field(
        default_factory=list, description="Optional validated grouping dimensions."
    )
    metrics: list[MetricArguments] = Field(
        description="One or more validated aggregate metrics."
    )
    filters: list[FilterConditionArguments] = Field(
        default_factory=list, description="Validated conditions combined with AND."
    )
    order_by: list[AggregateSortArguments] = Field(
        default_factory=list, description="Sorting by aggregate output names."
    )
    limit: int = Field(default=50, description="Maximum bounded aggregate rows.")


class QualityArguments(_Arguments):
    columns: list[str] | None = Field(
        default=None,
        description="Columns for column-level checks, or null for the bounded default.",
    )


_ARGUMENT_MODELS: dict[str, type[_Arguments]] = {
    "inspect_dataset": InspectArguments,
    "profile_dataset": ProfileArguments,
    "sample_dataset": SampleArguments,
    "filter_dataset": FilterArguments,
    "aggregate_dataset": AggregateArguments,
    "check_data_quality": QualityArguments,
}

_DESCRIPTIONS = {
    "inspect_dataset": (
        "Return the current dataset's shape and exact schema. Use for schema "
        "questions, missing-concept confirmation, or recovery after an unknown-"
        "field error. Never use as preflight when the user or conversation "
        "Evidence already provides the required exact field names."
    ),
    "profile_dataset": (
        "Compute bounded descriptive statistics and value distributions for "
        "selected columns. Use only when the question needs a distribution, "
        "statistic, or category understanding; never use to confirm fields or "
        "filter values before aggregation or quality checks."
    ),
    "sample_dataset": (
        "Return bounded seeded representative rows only when record-level examples "
        "are useful. Do not use to discover schema, distributions, aggregates, "
        "missing concepts, or business meaning."
    ),
    "filter_dataset": (
        "Return bounded matching records using validated AND filters and sorting. "
        "Use for row lookup, top records, or record-level investigation, not for "
        "grouped or summary calculations."
    ),
    "aggregate_dataset": (
        "Compute bounded grouped, numeric, comparative, or time-grained analysis. "
        "For an explicit aggregate question with named fields, call this directly "
        "without inspect or profile preflight. Combine all useful metrics, "
        "dimensions, filters, and sorting in one call whenever possible."
    ),
    "check_data_quality": (
        "Directly answer explicit data-quality questions with fixed objective and "
        "conservative heuristic signals. Normally use this as the only Tool; do "
        "not add inspect, profile, or sample calls for optional context."
    ),
}


class ToolDispatcher:
    """Bind exactly six existing Tools to one current dataset ID."""

    def __init__(self, registry: DatasetRegistry, dataset_id: str) -> None:
        registry.get(dataset_id)
        self._dataset_id = dataset_id
        self._inspect = InspectDatasetTool(registry)
        self._profile = ProfileDatasetTool(registry)
        self._sample = SampleDatasetTool(registry)
        self._filter = FilterDatasetTool(registry)
        self._aggregate = AggregateDatasetTool(registry)
        self._quality = CheckDataQualityTool(registry)
        self._schemas = tuple(
            ToolDefinition(
                name=name,
                description=_DESCRIPTIONS[name],
                parameters=_strict_json_schema(model),
            )
            for name, model in _ARGUMENT_MODELS.items()
        )

    @property
    def schemas(self) -> tuple[ToolDefinition, ...]:
        return self._schemas

    @property
    def allowed_tool_names(self) -> frozenset[str]:
        return frozenset(_ARGUMENT_MODELS)

    def dispatch(self, name: str, arguments: str) -> ToolResult:
        model = _ARGUMENT_MODELS.get(name)
        if model is None:
            raise UnknownToolError("Unsupported tool.")
        try:
            parsed = model.model_validate_json(arguments, strict=True)
        except (ValidationError, ValueError, TypeError) as exc:
            raise ToolArgumentError("Tool arguments are invalid.") from exc
        return self._invoke(name, parsed)

    def _invoke(self, name: str, arguments: _Arguments) -> ToolResult:
        if name == "inspect_dataset" and isinstance(
            arguments, InspectArguments
        ):
            return self._inspect(self._dataset_id)
        if name == "profile_dataset" and isinstance(
            arguments, ProfileArguments
        ):
            return self._profile(
                self._dataset_id,
                columns=arguments.columns,
                top_k=arguments.top_k,
            )
        if name == "sample_dataset" and isinstance(arguments, SampleArguments):
            return self._sample(
                self._dataset_id,
                columns=arguments.columns,
                size=arguments.size,
                seed=arguments.seed,
            )
        if name == "filter_dataset" and isinstance(arguments, FilterArguments):
            return self._filter(
                self._dataset_id,
                columns=arguments.columns,
                filters=tuple(_filter_condition(item) for item in arguments.filters),
                order_by=(
                    tuple(
                        SortSpec(item.column, item.direction)
                        for item in arguments.order_by
                    )
                    if arguments.order_by is not None
                    else None
                ),
                limit=arguments.limit,
            )
        if name == "aggregate_dataset" and isinstance(
            arguments, AggregateArguments
        ):
            return self._aggregate(
                self._dataset_id,
                dimensions=tuple(
                    DimensionSpec(item.name, item.column, item.time_grain)
                    for item in arguments.dimensions
                ),
                metrics=tuple(
                    MetricSpec(item.name, item.function, item.column)
                    for item in arguments.metrics
                ),
                filters=tuple(_filter_condition(item) for item in arguments.filters),
                order_by=tuple(
                    AggregateSortSpec(item.field, item.direction)
                    for item in arguments.order_by
                ),
                limit=arguments.limit,
            )
        if name == "check_data_quality" and isinstance(
            arguments, QualityArguments
        ):
            return self._quality(self._dataset_id, columns=arguments.columns)
        raise ToolArgumentError("Tool arguments do not match the requested Tool.")


def _filter_condition(item: FilterConditionArguments) -> FilterCondition:
    return FilterCondition(item.column, item.operator, item.value)


def _strict_json_schema(model: type[_Arguments]) -> dict[str, Any]:
    schema = model.model_json_schema()

    def make_strict(node: Any) -> None:
        if isinstance(node, dict):
            node.pop("default", None)
            if node.get("type") == "object":
                properties = node.get("properties", {})
                if isinstance(properties, dict):
                    node["required"] = list(properties)
                node["additionalProperties"] = False
            for value in node.values():
                make_strict(value)
        elif isinstance(node, list):
            for value in node:
                make_strict(value)

    make_strict(schema)
    return schema
