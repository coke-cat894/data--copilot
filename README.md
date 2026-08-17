# Data Copilot

Data Copilot v1 product positioning:

> An end-to-end governed Data Agent prototype with deterministic safety
> boundaries, business semantics, evidence-grounded reasoning,
> troubleshooting, runtime hardening, and evaluation infrastructure.

It supports local structured data analysis, safe PostgreSQL querying, business
semantics, document context, and data/pipeline troubleshooting. It is not a
fully production-ready platform.

Its core rule is:

> LLM 负责智能，程序负责可靠性。

The LLM reasons about data; the data engine processes data. Permissions,
validation, execution limits, read-only enforcement, state, Evidence, and
secret protection remain deterministic software responsibilities.

## What works today

| Capability | Status | Boundary |
|---|---|---|
| CSV, Parquet, JSONL analysis | Implemented | Explicit local file; bounded DuckDB Tools |
| PostgreSQL querying | Implemented, read-only | One validated statement; timeout and result bounds |
| Semantic Layer | Implemented | Explicit trusted YAML definitions |
| Business-document retrieval | Implemented | Local bounded lexical retrieval; no embeddings |
| Data and pipeline troubleshooting | Implemented foundation | Deterministic snapshots, drift, and explicit local run records |
| Safe traces and evaluation | Implemented | Versioned bounded artifacts; deterministic mock and explicit live modes |
| Environment doctor | Implemented | Configuration checks by default; database network check only by opt-in |
| MySQL, Snowflake, BigQuery | Not implemented | Future adapter work |
| External pipeline adapters | Not implemented | No Airflow/dbt/Spark service integration |
| Vector retrieval | Intentionally absent | Local lexical retrieval only |
| Automatic remediation or writes | Intentionally unsupported | Read-only product boundary |

## Project status

- Phase 1 — Local Data Foundation ✅ COMPLETE
- Phase 2 — SQL / Database Copilot ✅ COMPLETE
- Phase 3 — Semantic Layer + RAG ✅ COMPLETE
- Phase 4 — Data Engineering Troubleshooting ✅ COMPLETE
- Phase 5 — Evaluation + Product Hardening ✅ COMPLETE
- Data Copilot v1 Roadmap ✅ COMPLETE

Detailed phase decisions and historical results live in
[DEVELOPMENT_MANUAL.md](DEVELOPMENT_MANUAL.md).

## Quickstart without a paid provider

Python 3.12 or newer is required.

```bash
git clone <repository-url>
cd data-copilot
python3.12 -m venv .venv
.venv/bin/python -m pip install -e '.[test]'
cp .env.example .env
```

The copied file contains placeholders only. Configure only capabilities you
intend to use; deterministic tests and mock evaluation need neither an API key
nor PostgreSQL.

```bash
.venv/bin/python -m pytest -q
.venv/bin/data-copilot doctor
.venv/bin/data-copilot-eval --mode mock
```

The default doctor never contacts an LLM provider and spends no tokens. Its
statuses distinguish `PASS`, `WARN`, `FAIL`, and `SKIPPED`.

To use the interactive local-dataset Agent, configure a supported provider in
`.env`, then pass one explicit file:

```bash
.venv/bin/data-copilot path/to/data.csv
```

The CLI also accepts Parquet and JSONL. Enter `quit` or `exit` to stop.

## Commands

| Command | Purpose | External access |
|---|---|---|
| `data-copilot DATASET` | Interactive local-dataset Agent | Configured LLM provider |
| `data-copilot doctor` | Environment/configuration self-check | None by default |
| `data-copilot doctor --connect-database` | Explicit fixed PostgreSQL health check | Configured PostgreSQL only |
| `data-copilot-eval --mode mock` | Deterministic dataset eval | None |
| `data-copilot-eval --mode live ...` | Explicit provider/database eval | Yes; paid/remote and separately approved |
| `scripts/postgres/*.py` | Focused development smokes | Explicit local PostgreSQL fixture |

Use `--help` on either entry point for current flags. Live eval commands and
their approval gates are documented in [evals/README.md](evals/README.md).

### Doctor examples

Validate only local configuration and the default eval artifact location:

```bash
.venv/bin/data-copilot doctor
```

Validate explicit local resources without provider or database calls:

```bash
.venv/bin/data-copilot doctor \
  --semantic-source tests/fixtures/semantic \
  --document-source tests/fixtures/business_documents \
  --allowed-root tests/fixtures \
  --artifact-directory evals/results
```

Request machine-readable output or explicitly test PostgreSQL connectivity:

```bash
.venv/bin/data-copilot doctor --json
.venv/bin/data-copilot doctor --connect-database
```

Provider connectivity is always `SKIPPED`: doctor validates provider
configuration but deliberately makes no provider request. Database
configuration and reachability are separate checks.

## Configuration

One validated environment path supplies provider, runtime, and PostgreSQL
settings. Optional capabilities are not required when unused. Local semantic,
document, allowed-root, and artifact locations are explicit CLI arguments or
constructor inputs rather than secret environment state.

| Setting | Required when | Default / bound |
|---|---|---|
| `DATA_COPILOT_PROVIDER` | Starting a provider-backed Agent | `openai` or `deepseek`; no implicit provider |
| `DATA_COPILOT_MODEL` | Provider-backed Agent | Required, bounded model name |
| `OPENAI_API_KEY` | Provider is `openai` | Required; never logged |
| `DEEPSEEK_API_KEY` | Provider is `deepseek` | Required; never logged |
| `DEEPSEEK_BASE_URL` | Optional DeepSeek endpoint override | `https://api.deepseek.com`; HTTP(S), no embedded credentials/query/fragment |
| `DATA_COPILOT_PROVIDER_MAX_RETRIES` | Optional interactive retry override | `1`; allowed `0..2` |
| `DATA_COPILOT_POSTGRES_DSN` | PostgreSQL capability | Required and parsed; never displayed |
| `POSTGRES_CONNECT_TIMEOUT_SECONDS` | PostgreSQL capability | `5`; allowed `1..60` |
| `POSTGRES_STATEMENT_TIMEOUT_MS` | PostgreSQL capability | `15000`; allowed `1..120000` |

Additional fixed or explicit limits:

- The Agent Tool budget is program-owned at five actual Tool executions.
  Invalid or rejected proposals do not execute and do not consume this budget.
- Eval provider retries default to zero and are separately bounded by eval CLI
  configuration; live closure modes remain one-shot.
- Dataset and pipeline loaders require explicit allowed roots and apply file,
  count, size, row, column, and serialization limits.
- Diagnostic limits are typed constructor configuration with hard caps; they
  are not provider-controlled.
- Semantic/document sources are explicit paths. Eval artifacts default to
  `evals/results/`, with safe bounded atomic persistence.

Configuration failures are typed and sanitized. The project does not dump the
process environment or expose keys, DSNs, passwords, raw driver errors, or
provider response objects through user-facing boundaries.

## Architecture

```text
User / CLI
    |
    v
Agent runtime ---- LLMClient protocol ---- OpenAI or DeepSeek adapter
    |
    +-- Semantic Catalog (trusted YAML meaning)
    +-- Document index (bounded local lexical context)
    +-- Dataset Tools (DuckDB over explicit local data)
    +-- Database Tools / engine contract ---- PostgreSQL implementation
    +-- Diagnostics (typed snapshots and deterministic drift)
    +-- Pipeline resources (explicit local typed run records)
    |
    v
Evidence state: SEMANTIC | DOCUMENT | DATA | DIAGNOSTIC | PIPELINE
    |
    v
Grounded answer, safe no-answer, or typed runtime failure

Cross-cutting: capability registry, validation, read-only policy, execution
bounds, retry policy, error taxonomy, safe trace, and evaluation.
```

The Intelligence Layer selects bounded capabilities and explains Evidence.
The Semantic Layer supplies configured business meaning and retrieved policy.
The Execution Layer performs exact inspection, aggregation, SQL, diagnostics,
and loading. Production code never depends on eval internals; eval observes the
same production Agent and Tool paths with controlled fixtures.

### Package boundaries

- `data_copilot.agent` and `database_agent` own the sequential Agent runtime.
- `data_copilot.llm` exposes the provider-neutral `LLMClient` contract and
  normalized response models; provider SDK objects stay inside adapters.
- `data_copilot.datasets`, `execution`, `sql`, and `tools` own registration,
  computation, validation, capability dispatch, and bounded execution.
- `data_copilot.semantics` and `documents` are deterministic local context
  packages; they do not depend on Agent runtime or provider SDKs.
- `data_copilot.diagnostics` represents snapshots, drift, and pipeline run
  facts/comparisons; it does not infer causes or grant capabilities.
- `data_copilot.evals` is test/evaluation infrastructure. Production runtime
  does not import it.
- `data_copilot.cli`, `config`, and `doctor` are composition boundaries.

Supported root-package imports are `AgentResult`, `DataCopilotAgent`, and
`DatabaseCopilotAgent`. Other packages expose focused domain APIs through their
own `__init__` modules. Low-level provider responses, secret-bearing internals,
test helpers, and artifact implementation details are not root public API.

### Provider and database boundaries

Both Agents depend on `LLMClient`, not on DeepSeek-specific behavior. Endpoint
configuration, request formatting, SDK retry disabling, usage extraction, and
Tool-call normalization stay behind the OpenAI/DeepSeek client adapters.

Database direction is:

```text
DatabaseCopilotAgent
  -> typed database Tool dispatcher
  -> registry + SQL validator + execution engine
  -> PostgreSQL/psycopg implementation
```

This is an intended boundary, not a claim of a complete multi-database adapter
framework. The registry models, metadata SQL, plan parsing, diagnostics
collector, and execution engine remain PostgreSQL-specific. A future adapter
must earn its own validation, dialect policy, timeouts, read-only enforcement,
Evidence mapping, tests, and evals.

## Safety and trust

Read-only behavior is enforced in code, not by asking the model to behave.

Trusted or program-owned boundaries include:

- Tool/capability registration and dispatch;
- `SQLValidator`, statement count/dialect policy, and database read-only mode;
- allowed-root resolution, resource registries, timeouts, budgets, and result
  limits;
- explicitly configured Semantic Catalog definitions;
- typed loaders, Evidence builders, sanitizers, error mapping, and trace
  persistence.

Untrusted or inert inputs include user text, document text, pipeline event
text, database values, model-generated SQL before validation, provider Tool
proposals, and Tool results before Evidence validation. Context is not
permission. Retrieved text cannot register a Tool, change a limit, reveal a
secret, or authorize a write.

Key protections:

- exactly one conservative PostgreSQL read statement is validated before
  execution; mutation/DDL and unsafe constructs fail closed;
- database credentials remain behind opaque process-local IDs;
- every data path is bounded by applicable rows, columns, bytes, time, or
  serialization limits;
- compact Evidence—not unbounded raw datasets or logs—enters model context;
- runtime and eval traces exclude hidden reasoning and raw Evidence, and retain
  only safe observable summaries;
- safe no-answer is a valid outcome when semantics, a baseline, alignment, or
  causal Evidence is missing.

Logging records bounded operational summaries such as run/round, Tool name,
status, duration, Evidence channel, and safe failure category. It does not log
Tool arguments, SQL, raw rows, full pipeline logs, paths, keys, DSNs,
passwords, `.env` contents, provider internals, or hidden reasoning.

## Representative workflows

### Business metric query

“每个月销售额是多少？”

```text
resolve configured metric meaning
-> inspect relevant metadata
-> validate and execute safe aggregate SQL
-> DATA_EVIDENCE
-> grounded monthly result
```

### Business policy question

```text
resolve configured term
-> retrieve bounded relevant document chunks
-> SEMANTIC_EVIDENCE + DOCUMENT_EVIDENCE
-> policy answer with logical provenance
```

### Data troubleshooting

```text
compare typed before/after snapshots
-> inspect aligned pipeline run Evidence when available
-> separate observations from hypotheses
-> state missing causal verification and a safe next diagnostic step
```

Matching counts or timestamps are correlation, not automatically root cause.

### Safe no-answer

```text
business metric lacks a definition, or incident lacks a baseline
-> do not substitute guessed semantics/current state
-> report insufficient Evidence
```

## Extending the project

Keep extensions small and program-governed.

### Add a semantic pack

Place versioned metric, dimension, or glossary YAML in an explicitly configured
source. Follow the schemas in `tests/fixtures/semantic/`; use stable IDs,
aliases, references, and clear business definitions. Loading is bounded,
non-recursive, validated, and provenance is program-managed.

### Add a database adapter later

Do not branch on a provider name inside the Agent. Define the database-specific
registry/configuration, dialect validator, metadata/read/plan engine behavior,
read-only controls, limits, typed failures, and Evidence mapping behind the
database Tool boundary. Add security bypass tests and an isolated optional
integration smoke before advertising support.

### Add a Tool

A Tool needs one focused capability, typed bounded arguments, explicit
program-owned registration/permission, deterministic validation, bounded raw
result, a compact Evidence contract, safe error/trace support, and unit,
failure, security, Agent-integration, and eval coverage. A prompt or Skill
cannot grant a Tool.

### Add an eval case

Add a small deterministic fixture and declare required/allowed/forbidden Tools,
expected claims, forbidden claims, required Evidence channels, Tool limit, and
human-review need. Scorers and fixtures remain separate from production cause
logic. See [evals/README.md](evals/README.md).

## Tests, evaluation, and dependency roles

Run the full deterministic gate with:

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m compileall -q src tests scripts
.venv/bin/python -m pip check
git diff --check
```

Automated tests use synthetic files, FakeLLM, fake database connections, and
local fixtures. They do not call paid APIs. `pytest` validates software
behavior; evals separately measure task success, grounding, Tool selection,
safety, causal discipline, uncertainty, efficiency, latency, and known usage.

### Final v1 verification

The final documentation closure follows these completed gates:

- the deterministic suite passed all 922 tests before focused live closure;
- the immutable ten-case DeepSeek final suite was acceptable on grounded human
  review for 10/10 cases, with 100% Answer Accuracy, 100% for every applicable
  Evidence Grounding channel, and 100% Behavioral Safety;
- that suite identified one minor product blocker: an explicit physical-only
  request still exposed and called the Semantic Tool;
- the focused `final_db_join_aggregate` closure run passed after the
  program-owned routing fix with database-only Tool exposure, no Semantic,
  Document, or Troubleshooting Tools, the correct `East = 59,100.00` result,
  100% DATA_EVIDENCE grounding, 100% Tool Selection, and 100% Efficiency.

No product closure blockers remain. Historical automatic results and their
separate human-review records remain preserved rather than rewritten.

Major runtime dependencies are deliberately small:

| Dependency | Role |
|---|---|
| DuckDB | Bounded local analytical execution |
| OpenAI Python SDK | OpenAI-compatible provider transport behind `LLMClient` |
| Pydantic | Strict typed models and validation |
| psycopg | PostgreSQL connectivity, safe identifiers, and read-only execution |
| PyYAML | Safe Semantic Catalog loading |
| python-dotenv | Local environment-file loading without overriding process values |
| sqlglot | Conservative PostgreSQL AST validation |

`pytest` is test-only. Versions are bounded in `pyproject.toml`; project
metadata uses a simple `0.1.0` development version and no invented release
system.

## Production-readiness boundary

Implemented and hardened:

- provider-neutral Agent contract with bounded retry and failure taxonomy;
- explicit capability registries, read-only SQL validation, timeouts, and
  bounded data/Evidence paths;
- safe local semantic/document/pipeline loading;
- deterministic diagnostics, safe observable traces, and reproducible eval
  artifacts;
- provider-free tests, doctor, mock eval, and documented composition points.

Not production-complete:

- PostgreSQL-only database integration;
- local/in-memory registries and Agent state;
- BM25-only RAG, with no embeddings or reranker;
- no external pipeline adapters;
- no automatic time/run alignment;
- no distributed trace backend;
- no RBAC or multi-tenancy;
- no automatic remediation;
- no deployment orchestration;
- bounded scorers still have semantic-language limitations;
- provider behavior remains nondeterministic and provider/network availability
  remains an external dependency.

These are honest scope boundaries, not claims that the current foundation is a
production service. They are non-blocking technical debt after the completed v1
roadmap, not hidden claims of production readiness.

## License

No repository license has been declared yet.
