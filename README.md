# Data Copilot

Data Copilot is an evidence-first assistant for data analysis, SQL/database
work, and data engineering troubleshooting. Development is intentionally
incremental and keeps deterministic safety and execution in software rather
than prompt instructions.

## Current status

Phase 1.3 — Sample + Filter + Aggregate: **completed**.

The current implementation:

- registers explicitly provided local CSV, Parquet, and JSONL files;
- assigns opaque, process-local dataset IDs;
- inspects public file metadata, row count, and DuckDB schema through a dataset
  ID;
- profiles numeric, categorical, datetime, boolean, and uncommon columns using
  bounded DuckDB aggregates;
- returns reproducible bounded random samples;
- filters bounded rows through structured AND conditions; and
- computes bounded whole-dataset, grouped, and calendar-grain aggregates.

It does not yet include an LLM, Agent loop, Evidence layer, arbitrary SQL,
database connections, cross-dataset operations, or persistence.

## Requirements and setup

Python 3.12 or newer is required.

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -e '.[test]'
```

## Minimal usage

```python
from pathlib import Path

from data_copilot.datasets import DatasetRegistry
from data_copilot.tools import (
    AggregateDatasetTool,
    AggregateFunction,
    DimensionSpec,
    FilterCondition,
    FilterDatasetTool,
    FilterOperator,
    InspectDatasetTool,
    MetricSpec,
    ProfileDatasetTool,
    SampleDatasetTool,
)

data_root = Path("/path/to/explicit/data/root")
registry = DatasetRegistry(allowed_roots=[data_root])
dataset = registry.register(data_root / "orders.csv")

inspection = InspectDatasetTool(registry)(dataset.dataset_id)
print(inspection.model_dump())

profile = ProfileDatasetTool(registry)(
    dataset.dataset_id,
    columns=["amount", "status"],
    top_k=10,
)
print(profile.model_dump())

sample = SampleDatasetTool(registry)(dataset.dataset_id, size=20, seed=42)

filtered = FilterDatasetTool(registry)(
    dataset.dataset_id,
    columns=["order_id", "amount"],
    filters=[FilterCondition("amount", FilterOperator.GT, 100)],
    limit=50,
)

aggregated = AggregateDatasetTool(registry)(
    dataset.dataset_id,
    dimensions=[DimensionSpec("region_name", "region")],
    metrics=[MetricSpec("revenue", AggregateFunction.SUM, "amount")],
)
```

`allowed_roots` is mandatory. Paths are resolved before registration, so a
path or symlink that escapes those roots is rejected. Re-registering the same
resolved file in one registry returns the existing dataset and ID. Registry
state and IDs are in memory only.

The internal `Dataset` model contains `resolved_path`. Call
`dataset.to_public_metadata()` when a path-free representation is needed for a
future external or LLM-facing boundary.

JSONL means newline-delimited JSON records; ordinary JSON is unsupported.

## Tool contracts

`InspectDatasetTool` accepts only `dataset_id` and returns path-free dataset
metadata, row/column counts, and column names/types. It does not return samples
or distribution statistics.

`ProfileDatasetTool` accepts `dataset_id`, optional selected `columns`, and
`top_k`. DuckDB computes exact per-column aggregates:

- numeric: nulls, exact distinct count, bounds, mean, median, p25, and p75;
- categorical: nulls, exact distinct count, and bounded non-null top values;
- datetime: nulls, exact distinct count, and temporal bounds;
- boolean: null, true, false, and exact distinct counts; and
- other/uncommon types: null count and rate only.

Rates use total dataset rows as the denominator. Empty datasets return `0.0`
rates and `None` for undefined numeric or temporal statistics.

## Profile limits

- `MAX_PROFILE_COLUMNS = 50`
- `DEFAULT_TOP_VALUES = 10`
- `MAX_TOP_VALUES = 20`

When `columns=None`, only the first 50 columns are profiled and the result
contains a warning if the dataset is wider. An explicit request over 50
columns, an invalid or duplicate column request, or `top_k > 20` fails closed.

Tool and execution APIs accept dataset IDs, not paths or raw SQL. Requested
column names must exactly match inspected schema and are safely quoted before
internal aggregate SQL is built.

## Structured query tools

`SampleDatasetTool` supports only seeded DuckDB reservoir sampling. The same
dataset, size, and seed produce a reproducible sample where DuckDB permits.

`FilterDatasetTool` supports controlled `eq`, `ne`, `gt`, `gte`, `lt`, `lte`,
`in`, `not_in`, `between`, `is_null`, and `is_not_null` conditions. Multiple
conditions always use `AND`. Sorting is limited to validated source columns and
`asc`/`desc` directions.

`AggregateDatasetTool` supports up to five dimensions and ten metrics. Metrics
are `count`, `count_distinct`, `sum`, `avg`, `median`, `min`, and `max`.
Calendar dimensions support `year`, `quarter`, `month`, `week`, and `day` for
DATE/TIMESTAMP columns. Metric and dimension aliases use a restricted
identifier format and must be globally unique.

Filter values are always sent to DuckDB as bound parameters. Identifiers,
operators, functions, sort directions, and time grains are program-controlled.
No Tool accepts SQL strings or expressions.

Filter and aggregate queries request one extra row internally. `truncated` is
true only when more rows exist beyond the returned limit; no full result count
query is issued.

## Query limits

- `DEFAULT_SAMPLE_ROWS = 20`
- `MAX_SAMPLE_ROWS = 100`
- `DEFAULT_RESULT_ROWS = 50`
- `MAX_RESULT_ROWS = 200`
- `MAX_RESULT_COLUMNS = 50`
- `MAX_FILTERS = 20`
- `MAX_GROUP_BY_DIMENSIONS = 5`
- `MAX_METRICS = 10`

Explicit requests above these limits fail closed with `ResourceLimitError`.
When sample/filter columns are omitted on a wider dataset, the first 50 columns
are returned with a warning.

## Tests

```bash
.venv/bin/python -m pytest -q
```
