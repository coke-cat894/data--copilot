# Data Copilot

Data Copilot is an evidence-first assistant for data analysis, SQL/database
work, and data engineering troubleshooting. Development is intentionally
incremental and keeps deterministic safety and execution in software rather
than prompt instructions.

## Current status

Phase 3.1 — Semantic Catalog Foundation: **implemented as a standalone deterministic boundary**.

Phase 1 — Local Data Foundation and the Phase 2.1–2.3 database boundaries remain
unchanged and Phase 2 is frozen. Phase 3.1 adds trusted local semantic metadata;
it does not connect semantics to either Agent, perform semantic retrieval, or
start RAG.

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
  check; and
- lists non-system relations and inspects declared columns, primary keys,
  foreign keys, basic indexes, and inbound/outbound relationships; and
- validates exactly one untrusted SQL statement against a conservative
  read-only PostgreSQL AST policy; and
- lets a single-database Agent discover declared schema metadata, generate
  PostgreSQL, execute bounded read queries, inspect estimated query plans, and
  answer from Compact Evidence; and
- loads explicitly configured, trusted local YAML into typed metric, dimension,
  and glossary definitions with deterministic aliases, validated references,
  and path-safe logical provenance.

It does not include EXPLAIN ANALYZE, automatic SQL repair or optimization,
database writes, cross-database queries, persistent memory, RAG, MCP, connection
pooling, Agent semantic integration, fuzzy semantic matching, or metric-to-SQL
compilation.

## Semantic Catalog Foundation

`SemanticCatalogLoader` accepts one explicit YAML file or one explicit
directory. Directory loading is deterministic and non-recursive. Each trusted
file declares `version: 1`, one `type` (`metrics`, `dimensions`, or `glossary`),
and a `definitions` list. The loader does not discover database values or call
an LLM.

Metric definitions record business meaning and canonical
`schema.table.column` inputs, not SQL. Dimensions record business meaning and
source fields. Glossary terms may reference metric and dimension IDs. All three
retain a program-created provenance pair containing only the source file name
and definition ID.

Catalog lookup supports stable IDs, canonical names, and explicitly configured
synonyms using trim plus case-insensitive normalization. Duplicate IDs,
canonical-name or synonym ambiguity, invalid cross-references, malformed files,
unsupported fields (including SQL), and unsafe source forms fail closed. The
catalog is currently a program-facing foundation only; no catalog content is
added to system prompts.

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
POSTGRES_STATEMENT_TIMEOUT_MS=15000
```

The connect timeout defaults to 5 seconds and must be between 1 and 60 seconds.
The statement timeout defaults to 15 seconds and must be between 1 and 120,000
milliseconds. The DSN must include a database name. Parsed credentials remain
in an internal frozen configuration model whose representation omits the DSN.

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

## PostgreSQL metadata discovery

`PostgresEngine` exposes three Phase 2.2 metadata capabilities. Each accepts an
opaque `database_id`; table identity always consists of `schema_name` and
`table_name`:

```python
tables = engine.list_tables(database.database_id, schema="sales")
inspection = engine.inspect_table(
    database.database_id,
    schema_name="sales",
    table_name="orders",
)
relationships = engine.get_relationships(
    database.database_id,
    schema_name="sales",
    table_name="orders",
)
```

`list_tables` reports schema, relation name, and relation type while excluding
`pg_catalog`, `information_schema`, TOAST, and temporary schemas. An optional
schema filter is passed as a bound parameter.

`inspect_table` reports ordered columns with PostgreSQL display types and
nullability, the ordered primary-key columns, declared outbound foreign keys,
and valid basic indexes. Composite keys retain their declared column order.
`get_relationships` reports only declared foreign keys and labels each as
`outbound` or `inbound` relative to the requested table; it performs no key or
business-relationship inference.

Every operation establishes read-only mode before executing fixed,
program-owned `pg_catalog` SQL. Schema and table values are bound parameters;
internal SQL, connection details, and credentials are absent from result
models and public errors. No method accepts SQL from a caller.

Metadata output limits are:

- `MAX_DATABASE_TABLES = 200`
- `MAX_TABLE_COLUMNS = 200`
- `MAX_RELATIONSHIPS = 200`
- `MAX_INDEXES = 100`

Queries request one extra record where applicable. Results set `truncated=true`
and include an explicit warning when a limit is reached. Automated tests use
mocked psycopg connections rather than a live PostgreSQL server.

## Read-only SQL validation

Phase 2.3 adds a standalone validation boundary based on sqlglot's PostgreSQL
dialect:

```python
from data_copilot.sql import SQLValidator

validated = SQLValidator().validate(
    "WITH recent AS (SELECT * FROM orders) SELECT * FROM recent"
)
```

`ValidatedSQL` contains only the original SQL, normalized PostgreSQL SQL,
`statement_type="select"`, and `is_explain`. It does not contain a database ID,
credentials, an execution result, or an execution capability.

The validator requires exactly one parsed statement and allows only `SELECT`,
read-only set operations such as `UNION`, `WITH ... SELECT`, and plain
`EXPLAIN SELECT`. It traverses the complete query AST and rejects mutation or
administration nodes even when nested inside CTEs or subqueries. It also rejects
`SELECT INTO`, all row-locking clauses, `EXPLAIN ANALYZE`, and every
parenthesized EXPLAIN option in this first version.

A small explicit function denylist blocks external-file, large-object, dblink,
sequence mutation, advisory-lock, backend-control, WAL/control, logical-message,
and sleep capabilities. Examples include `pg_read_file`, `pg_read_binary_file`,
`pg_ls_dir`, `lo_import`, `lo_export`, `dblink*`, `nextval`, `setval`,
`pg_advisory_lock*`, `pg_terminate_backend`, and `pg_sleep`.

This allowlist/denylist is intentionally conservative but cannot establish that
every installed PostgreSQL function is side-effect free. AST validation, future
Phase 2.4 read-only sessions, database-level read-only credentials, execution
timeouts, and result limits are defense-in-depth layers. Phase 2.3 performs no
database connection, SQL rewriting, LIMIT injection, or execution.

## PostgreSQL database Agent

`DatabaseCopilotAgent` binds one registered `database_id` in program state and
exposes exactly five LLM tools: `list_tables`, `inspect_table`,
`get_relationships`, `execute_read_query`, and `explain_query`. Tool schemas
never expose a DSN, credentials, or a selectable database ID.

`execute_read_query` always performs this deterministic pipeline:

```text
untrusted SQL → SQLValidator → reject EXPLAIN → resolve database_id
→ connect → read-only mode → program-owned statement timeout
→ execute normalized SQL with a server-side cursor → enforce 50-column limit
→ fetch at most 201 rows → return at most 200 rows
→ Compact Evidence → LLM
```

Validation failure occurs before registry resolution or connection. Each query
connection independently establishes read-only mode and a transaction-local
statement timeout. Queries wider than 50 columns fail before row fetching;
queries over 200 returned rows set `source_truncated=true` with an explicit
warning. SQL is not rewritten to inject LIMIT, so statement timeout remains an
independent protection against expensive computation.

Database metadata and query results reuse the existing `EvidenceBuilder` and
`EvidenceFormatter`. Database Evidence carries an opaque `database_id` instead
of `dataset_id` and preserves the existing row, column, cell, and total-size
limits. Query SQL, credentials, connection configuration, driver diagnostics,
and raw exceptions are absent from Evidence. Prompt-like cell content remains
quoted data inside `DATA_EVIDENCE`.

Automated Agent and execution tests use `FakeLLMClient` and mocked psycopg
connections. No paid model or live PostgreSQL call is part of the test suite.

`explain_query` accepts the underlying read-only query, never caller-authored
EXPLAIN syntax. It validates first, rejects mutation and user-supplied EXPLAIN,
then constructs program-owned `EXPLAIN (FORMAT JSON)` on a fresh read-only
connection with the configured statement timeout. It never uses ANALYZE, so the
underlying query does not execute.

The raw PostgreSQL JSON plan is reduced to stable facts such as node type,
relation, alias, join type, estimated cost/rows/width, filter, index name, and
child structure. Plans are bounded to 100 nodes and depth 20 with explicit
truncation warnings before conversion to `DATA_EVIDENCE`. The Agent may explain
SQL syntax without a Tool, use plan Evidence for performance hypotheses, and
combine declared metadata with bounded queries for SQL/JOIN debugging. A
suggested fix remains unverified until it is actually executed successfully.

## Phase 2 real PostgreSQL validation

The manual Phase 2.6 fixture scripts live under `scripts/postgres/`. They create
only a dedicated `data_copilot_test` database, `commerce` and `support` schemas,
and a restricted `data_copilot_ro` application role. The deterministic fixture
contains 12 users, 8 products, 1,200 orders, 2,400 order items, and 2 notes. The
role has LOGIN, CONNECT, schema USAGE, and table SELECT only; its default
transaction mode is read-only. Credentials belong only in the ignored `.env`.

The real smoke verifies ping, metadata, declared relationships, SELECT,
aggregation, 200-row result truncation, program-owned EXPLAIN, validator
rejection, and independent database permission denial for INSERT, UPDATE,
DELETE, CREATE, DROP, and ALTER. Normal pytest remains independent of a live
database and external LLM.

The focused database eval set contains 12 cases in
`evals/cases/database_phase_2.jsonl`. Run it explicitly with:

```bash
data-copilot-eval --mode live --target database
```

The one-shot 2026-08-12 DeepSeek run achieved 8/12 automated task success,
100% tool selection, 66.7% answer checks, 100% grounding checks, 0% no-answer,
100% safety, and 83.3% efficiency. Two failures were round-limit failures; two
additional deterministic answer checks were false negatives on semantically
grounded JOIN/EXPLAIN answers. Because the missing-concept case produced no
answer, Phase 2 closure is not yet recommended. Failed cases were not rerun.

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
