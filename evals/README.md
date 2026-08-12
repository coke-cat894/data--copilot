# Data Copilot Evaluations

Phase 1.6 separates four concerns:

1. deterministic Tool and safety regression in `pytest`;
2. scripted Mock-Agent evaluation;
3. explicit paid live-LLM evaluation; and
4. documented manual evaluation on unfamiliar real data.

No eval command adds capabilities to the Agent. Every case runs through a fresh
`DatasetRegistry`, the existing `DataCopilotAgent`, the static six-Tool
`ToolDispatcher`, and the existing Evidence layer.

Phase 2 database cases use `DatabaseEvalRunner`, one program-bound registered
database ID, the existing `DatabaseCopilotAgent`, its static five-Tool
dispatcher, and the same Evidence/scoring/result contracts. This runner does
not grant new database capabilities.

Phase 3 cases use the same runner with an explicitly configured local
`SemanticCatalog` and `BusinessDocumentIndex`. Results record the observed
`semantic`, `document`, and `data` Evidence channels and score their grounding
independently. The eval target measures existing Phase 3.4 capabilities; it
does not register a new execution capability.

## Case format

`cases/local_foundation.jsonl` contains 15 functional, grounding, or no-answer
cases and five safety cases. Each JSON line validates as a typed `EvalCase`.
The format intentionally stays small: question, repository-relative dataset,
required/allowed/forbidden Tools, answer substrings, forbidden claims, a Tool
limit, and a human-grounding-review flag.

Natural-language answers are not compared for exact equality. Deterministic
checks cover required facts, forbidden unsupported claims, Tool selection, and
Tool limits. Cases marked `needs_human_grounding_review` still require review;
the automated score is not an LLM judge and must not be presented as complete
semantic correctness.

Task success is independent from Tool selection and efficiency. A correct,
grounded answer remains a task success when the model made an unnecessary
read-only Tool call; that call lowers the separate Tool-selection and efficiency
metrics. Runtime failures, unmet answer requirements, unsupported claims, and
forbidden capability use can still fail the task. Requirement checks accept a
small general set of semantic equivalents, including null/missing/缺失/空值.

## Modes

Mock evaluation is deterministic, free, and CI-safe:

```bash
data-copilot-eval --mode mock
```

Live evaluation loads the normal `.env`, prints only provider, model, and case
count, and then makes paid API calls:

```bash
data-copilot-eval --mode live
```

Run only live safety cases with:

```bash
data-copilot-eval --mode safety
```

Select individual cases by repeating `--case-id CASE_ID`. Ordinary `pytest`
never invokes live mode or an external provider.

The dedicated 12-case Phase 2 database run is explicit and requires the local
read-only fixture configuration in the ignored `.env`:

```bash
data-copilot-eval --mode live --target database
```

Database cases are in `cases/database_phase_2.jsonl`. Scripted mock mode remains
dataset-only; deterministic database Agent behavior uses FakeLLM tests while the
real closure run is deliberately live and one-shot.

The dedicated ten-case Phase 3 run requires the same local read-only fixture
plus the synthetic semantic and document packs:

```bash
data-copilot-eval --mode live --target phase3
```

`--target phase3` is restricted to the configured DeepSeek provider. It must be
run only after explicit approval because it sends the synthetic questions and
bounded evidence to the external provider. The 2026-08-12 baseline was run once
and must not be rerun merely to improve its score.

### Phase 1.6 closure focused rerun

After the closure patch, rerun only the cases related to the observed behavior
failures before considering another full 20-case run:

```bash
data-copilot-eval --mode live \
  --case-id functional_05_monthly_revenue \
  --case-id functional_06_region_average \
  --case-id functional_10_quality \
  --case-id grounding_11_march_decline \
  --case-id no_answer_13_missing_concept \
  --case-id no_answer_14_forecast \
  --case-id grounding_15_semantics \
  --case-id safety_02_mutation
```

This is a paid live command and must be started manually. It covers direct
aggregate selection, the two prior round-limit failures, missing-concept and
forecast no-answer behavior, ambiguous business semantics, and the remaining
safe-but-unnecessary mutation-case Tool call. Do not infer closure from mock
results alone; review grounding and Tool traces in the generated result.

## Results and metrics

Generated JSON files go to `evals/results/` and are ignored except for
`.gitkeep`. Each run records provider, model, UTC timestamp, Git commit/dirty
state, case details, Tool calls, rounds, total latency, optional provider token
usage, deterministic failures, and human-review flags. API keys, resolved
paths, raw datasets, and environment dumps are excluded; persistence also
rejects any configured key found in serialized output.

The summary reports task success, Tool selection, answer checks, grounding
checks, no-answer accuracy, safety pass rate, efficiency, average Tool calls,
average rounds, latency, and tokens when supplied by the provider. No provider
prices are hard-coded, so estimated cost remains unavailable unless a future
approved phase defines an explicit pricing configuration.

### Phase 2.6 one-shot result

The 2026-08-12 DeepSeek `deepseek-v4-flash` run executed all 12 database cases
once without retry: 8 passed and 4 failed. Safety and automated grounding were
100%; no-answer was 0%. Two failures reached the Agent round limit. Human review
found that the JOIN and EXPLAIN answers were grounded despite missing brittle
deterministic phrases, but the stored automatic result is not altered. Phase 2
closure is therefore not recommended from this run.

### Phase 3.5 one-shot result

The 2026-08-12 DeepSeek `deepseek-v4-flash` run executed all ten Phase 3 cases
once without retry: 2 passed and 8 failed. Automatic metrics were 20.0% Task
Success, 10.0% Tool Selection, 60.0% Answer Accuracy, 12.5% Semantic Grounding,
100.0% Document Grounding, 33.3% Data Grounding, 50.0% No-answer, 0.0% Safety,
and 60.0% Efficiency. Human review found safe behavior in the prompt-injection
answer, but the case still lacked required semantic evidence, so the original
automatic result remains unchanged and Phase 3 closure is not recommended.

See `baselines/phase_3_5_deepseek.md` for per-case review and technical debt.

### Phase 3.5 Semantic Routing focused verification

After the deterministic closure patch, the six approved previously failed
high-signal cases ran once without retry. Five passed. Metrics were 83.3% Task
Success, Tool Selection, and Answer Accuracy; 100.0% Semantic Grounding,
Document Grounding, behavioral Safety, and Efficiency; and 75.0% Data
Grounding. The remaining failure resolved both sales and region semantics but
stopped before executing the regional aggregate. The automatic result remains
unchanged, and Phase 3 closure is still not recommended. See
`baselines/phase_3_5_semantic_routing_focused.md`.

## Real data

Real data is manual and never a CI dependency. Follow
`real_data/README.md`; do not commit large, licensed, sensitive, or externally
owned datasets. Record source, size, questions, Tool use, correctness,
grounding, usefulness, and problems in a small Markdown note.
