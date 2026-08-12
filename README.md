# Data Copilot

Data Copilot is an evidence-first assistant for data analysis, SQL/database
work, and data engineering troubleshooting. Development is intentionally
incremental and keeps deterministic safety and execution in software rather
than prompt instructions.

## Current status

Phase 2.1 — PostgreSQL Connection + Registry: **implemented**.

Phase 1 — Local Data Foundation remains unchanged. Phase 2.1 adds only the
program-side PostgreSQL configuration, opaque registry, and read-only health
check boundary; it does not expose database capabilities to the Agent.

The current implementation:

- registers explicitly provided local CSV, Parquet, and JSONL files;
- assigns opaque, process-local dataset IDs;
- inspects public file metadata, row count, and DuckDB schema through a dataset
  ID;
- profiles numeric, categorical, datetime, boolean, and uncommon columns using
  bounded DuckDB aggregates;
- returns reproducible bounded random samples;
- filters bounded rows through structured AND conditions;
- computes bounded whole-dataset, grouped, and calendar-grain aggregates;
- checks fixed objective and heuristic data-quality signals;
- converts all six Tool result types into bounded, path-free compact Evidence;
- lets one LLM select only those six Tools through a static allowlist; and
- returns grounded answers through a bounded in-process Agent loop and CLI.
- registers one or more PostgreSQL connection configurations behind opaque,
  process-local database IDs; and
- verifies registered PostgreSQL connectivity with a fixed read-only health
  check.

It does not include an explicit planner, arbitrary SQL, schema discovery,
database query Tools, cross-dataset operations, persistent memory, RAG, MCP,
or data mutation.

## Requirements and setup

Python 3.12 or newer is required.

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -e '.[test]'
```

The interactive Agent supports OpenAI through the Responses API and DeepSeek
through its OpenAI-compatible Chat Completions API. Both adapters use the
official OpenAI Python SDK behind the provider-neutral `LLMClient` boundary.

## LLM configuration

Copy the tracked placeholder file, then edit the local ignored `.env`:

```bash
cp .env.example .env
```

The CLI loads `.env` once at startup with `override=False`, so an existing
system environment variable always wins. `DATA_COPILOT_PROVIDER` and
`DATA_COPILOT_MODEL` are required; unknown providers and missing selected-key
configuration fail closed without falling back to another provider.

For DeepSeek:

```text
DATA_COPILOT_PROVIDER=deepseek
DEEPSEEK_API_KEY=your-real-local-key
DEEPSEEK_BASE_URL=https://api.deepseek.com
DATA_COPILOT_MODEL=deepseek-v4-flash
```

For OpenAI:

```text
DATA_COPILOT_PROVIDER=openai
OPENAI_API_KEY=your-real-local-key
DATA_COPILOT_MODEL=gpt-5.6-terra
```

Real keys belong only in the ignored local `.env` or external environment.
They are never placed in prompts, Evidence, logs, Tool arguments, examples, or
tests.

## PostgreSQL connection configuration

Phase 2.1 uses psycopg 3 and reads PostgreSQL credentials only from the existing
environment-loading boundary. Configure the ignored local `.env` or external
environment:

```text
DATA_COPILOT_POSTGRES_DSN=postgresql://username:password@localhost:5432/database_name
POSTGRES_CONNECT_TIMEOUT_SECONDS=5
```

The timeout defaults to 5 seconds and must be between 1 and 60 seconds. The DSN
must include a database name. Parsed credentials remain in an internal frozen
configuration model whose representation omits the DSN.

The minimal program-side flow is:

```python
from data_copilot.config import load_environment, read_postgres_config
from data_copilot.databases import DatabaseRegistry
from data_copilot.execution import PostgresEngine

load_environment()
registry = DatabaseRegistry()
database = registry.register(read_postgres_config(), display_name="Analytics")
result = PostgresEngine(registry).ping(database.database_id)
```

`database.to_public_metadata()` exposes only `database_id`, `database_type`,
and `display_name`. It omits the DSN, password, host, port, internal database
name, and connection options. `PostgresEngine` accepts only `database_id` and
has no generic SQL execution method.

`ping()` connects synchronously with the configured timeout, sets the psycopg
connection to read-only before querying, then executes the program-owned fixed
`SELECT 1`. A connection or read-only setup failure returns a sanitized domain
error and never falls back to read/write. Normal automated tests mock psycopg
and do not require a live PostgreSQL server.

## Minimal usage

```python
from pathlib import Path

from data_copilot.datasets import DatasetRegistry
from data_copilot.evidence import EvidenceBuilder, EvidenceFormatter
from data_copilot.tools import (
    AggregateDatasetTool,
    AggregateFunction,
    CheckDataQualityTool,
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

quality = CheckDataQualityTool(registry)(dataset.dataset_id)
evidence = EvidenceBuilder().build(quality)
formatted_evidence = EvidenceFormatter().format(evidence)
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

## Data-quality contract

`CheckDataQualityTool` accepts a `dataset_id`, optional source `columns`, and an
optional timezone-aware `reference_time`. Its fixed checks are:

- objective: null values, exact full-row duplicates beyond the first row,
  all-null columns, and constant columns; and
- heuristic: negative numeric values and DATE/TIMESTAMP values later than the
  UTC reference time.

Null, negative, and future-value rates use total dataset rows as the
denominator. A column is constant only when it has more than one non-null value
and exactly one distinct non-null value. Consequently, empty, all-null, and
single-non-null-value columns are not reported as constant. Duplicate checking
always uses the complete row, even when a subset of columns is selected for
column checks.

If `reference_time` is omitted, the Tool captures the current UTC time once.
Tests and reproducible callers should inject a fixed timezone-aware value.
`TIME` values are deliberately excluded because they have no date with which
to establish "future" status. Heuristic findings are signals, not proof that
the data is invalid.

`MAX_QUALITY_COLUMNS = 50`. With no explicit selection, only the first 50
columns are checked and a warning reports wider input. Explicit overflow,
unknown or duplicate columns, empty selections, and naive reference times fail
closed. Full-row duplicate checking is dataset-level and remains active.

## Compact Evidence contract

`EvidenceBuilder` accepts only the typed results of `inspect_dataset`,
`profile_dataset`, `sample_dataset`, `filter_dataset`, `aggregate_dataset`, and
`check_data_quality`. It performs no file reads, registry lookups, or data
queries. Each returned `Evidence` has an opaque process-local `evidence_id`,
`dataset_id`, operation, compact summary, columns/records, source and Evidence
truncation flags, warnings, and count metadata.

The source Tool result is the sole evidence boundary. Resolved paths and
internal SQL are not copied into Evidence. Tabular rows are represented as
values aligned to a single bounded `columns` list, avoiding repeated source
column names. Prompt-like text, SQL-looking strings, and JSON-looking strings
remain ordinary quoted data.

`EvidenceFormatter` emits deterministic compact JSON prefixed with
`DATA_EVIDENCE\n`. It never slices serialized JSON. Values are normalized as
follows: strings remain strings, integers/floats/booleans/null remain native
JSON values, decimals become strings, dates/times become ISO strings, and
non-finite floats become null with a warning.

Evidence applies limits independently of upstream Tool limits:

- `MAX_EVIDENCE_ROWS = 100`
- `MAX_EVIDENCE_COLUMNS = 30`
- `MAX_CELL_CHARS = 1000`
- `MAX_EVIDENCE_CHARS = 30000` (including the formatter prefix)

Rows, columns, and cells are reduced structurally with explicit warnings. The
total-size limit removes complete trailing records until valid JSON fits. If
the metadata envelope alone cannot fit, building or formatting fails closed
with `EvidenceLimitError`.

## Tests

```bash
.venv/bin/python -m pytest -q
```

## Agent Tool loop

Launch the minimal interactive CLI with one explicit local dataset:

```bash
data-copilot /path/to/orders.csv
```

The CLI registers only that file, prints public path-free metadata, and accepts
questions until `exit`, `quit`, Ctrl+C, or Ctrl+D. A typical manual smoke test
can ask:

```text
这个数据集有哪些字段？
哪个地区的平均订单金额最高？
每个月的销售额是多少？
找出金额最高的 5 个 completed 订单。
这个数据集有什么明显的数据质量问题？
为什么三月份收入下降？
```

The Agent's initial model context contains only the system rules plus the
current dataset's opaque ID, display name, and format. Schema, profiles, rows,
aggregates, and quality facts enter the conversation only after an allowlisted
Tool produces a typed result and that result passes through `EvidenceBuilder`
and `EvidenceFormatter`.

The six available functions are `inspect_dataset`, `profile_dataset`,
`sample_dataset`, `filter_dataset`, `aggregate_dataset`, and
`check_data_quality`. Their schemas intentionally omit dataset IDs, paths, SQL,
and arbitrary expressions. The current dataset ID is bound inside
`ToolDispatcher`; LLM arguments are untrusted and undergo Pydantic parsing plus
all existing Tool and DuckDB validations.

Each requested Tool call consumes one of `MAX_TOOL_ROUNDS = 5`, including
rejected calls. OpenAI Responses parallel Tool calls are disabled; all returned
Tool calls from either provider execute serially in the existing Agent loop.
Tool errors are reduced to domain-safe messages so the model can recover,
without receiving stack traces, paths, internal SQL, or provider details.
Reaching the limit is an explicit failure, never success.

The system prompt requires dataset-specific claims to be grounded in current
Evidence, treats dataset text as data rather than instructions, and requires an
insufficient-evidence answer instead of invented business causes. These prompt
rules guide model behavior; capability enforcement, argument validation,
resource limits, and the stopping condition remain deterministic Python code.

Automated tests use `FakeLLMClient` or mocked provider SDK responses and never
call a paid API. After configuring `.env`, run `data-copilot <dataset-path>` for
an explicit real-provider smoke test.

## Evaluation

Phase 1.6 adds a small typed pipeline:

```text
EvalCase → DataCopilotAgent → Tool/Evidence transcript
         → deterministic scoring + human-review flags → EvalResult
```

Run the free deterministic 20-case Mock Eval:

```bash
data-copilot-eval --mode mock
```

Live modes are explicit and may consume provider credits. Before calls begin,
the CLI displays provider, model, and case count without showing the API key:

```bash
data-copilot-eval --mode live
data-copilot-eval --mode safety
```

Generated JSON results are written under ignored `evals/results/`. They record
Tool calls, rounds, total latency, optional provider token usage, Git state,
deterministic failures, and human-review flags, but not configured keys,
resolved paths, raw datasets, or internal SQL.

The suite contains 15 functional/grounding/no-answer cases and five safety
cases. Exact natural-language matching is deliberately avoided; deterministic
checks use required facts, multilingual alternatives, forbidden claims, Tool
selection, and Tool limits. Human review remains required where these checks
cannot establish complete grounding.

For an unfamiliar real dataset, keep the data local and follow the five-question
protocol in `evals/real_data/README.md`. The current UCI Iris review and the
DeepSeek baseline are recorded under `evals/real_data/` and `evals/baselines/`.
See `evals/README.md` for the complete case and metric contract.
