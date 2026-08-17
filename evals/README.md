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

Phase 4.5 adds a focused 12-case troubleshooting target. Each case receives an
isolated program-owned set of synthetic `DatasetSnapshot` and `PipelineRun`
resources, while pure database and Phase 3 regression cases continue to use the
existing read-only PostgreSQL and semantic paths. The target evaluates existing
Phase 4.4 capability; it adds no Agent permission or remediation path.

Phase 5.1 hardens this same eval path with a typed, bounded, versioned safe
trace and independently explainable scorer details. The trace records only
observable behavior: provider-visible assistant text, returned Tool proposals,
the actually executed Tool, sanitized arguments, bounded Evidence summaries,
safe error categories, final answer, and known usage. It never captures hidden
chain-of-thought, scratchpads, provider reasoning content, or unexposed
reasoning tokens.

## Case format

`cases/local_foundation.jsonl` contains 15 functional, grounding, or no-answer
cases and five safety cases. Each JSON line validates as a typed `EvalCase`.
The format intentionally stays small: question, repository-relative dataset,
required/allowed/forbidden Tools, answer substrings, forbidden claims, a Tool
limit, and a human-grounding-review flag.

Troubleshooting cases additionally declare expected diagnostic/pipeline
Evidence channels, a qualitative causal classification, causal
support/forbidden claims, and uncertainty or conflict requirements. These are
eval expectations, not production root-cause rules or calibrated confidence
scores.

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
small general set of semantic equivalents, including null/missing/缺失/空值,
and numerically equal percentage formatting such as `17%` and `17.0%`.

Tool-selection scoring accepts a safe allowed route when it produces every
required Evidence channel; it does not require one brittle Tool sequence.
Semantic grounding keeps internal catalog identity traceable through
SEMANTIC_EVIDENCE while separately checking configured user-facing definition
claims, so an answer need not print an internal ID. Causal scoring ignores
explicitly negated definitive phrases. Unaligned conflict scoring additionally
requires alignment uncertainty and rejects unsupported source privileging.

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

The Phase 4.5 one-shot target is:

```bash
data-copilot-eval --mode live --target phase4 \
  --approve-phase4-external-data
```

It contains exactly 12 cases in `cases/troubleshooting_phase_4.jsonl` and is
restricted to the configured DeepSeek provider. It must not be run before the
user explicitly approves sending only the documented synthetic questions,
definitions, and bounded Evidence. Each case runs once, without retry, prompt
tuning, code changes, or scorer changes between cases.

The original 12-case Phase 4.5 baseline must not be rerun. After the closure
patch and a fresh explicit approval, use the frozen focused selector:

```bash
data-copilot-eval --mode live --target phase4 \
  --phase4-closure-focused \
  --approve-phase4-external-data
```

This selects only `row_count_drop_pipeline_match`,
`null_spike_unknown_cause`, `data_drift_healthy_pipeline`,
`conflicting_pipeline_database_evidence`, `missing_baseline`, and
`missing_semantic_business_metric`. Provider retries remain disabled. The
command is documented for the separately approved run; deterministic tests do
not invoke it.

After the six-case focused verification, only two true product blockers remained.
The final selector is therefore frozen to those two cases and must also receive
fresh explicit approval before execution:

```bash
data-copilot-eval --mode live --target phase4 \
  --phase4-final-two \
  --approve-phase4-external-data
```

It selects only `row_count_drop_pipeline_match` and
`null_spike_unknown_cause`. It cannot be combined with the six-case selector or
individual case IDs. The full 12-case and six-case runs must not be repeated.

### Phase 5.5 final closure target — approval pending

Phase 5.5 uses a layered 16-check closure set. Four exact safety/reliability
checks remain deterministic because a provider would add no useful assurance:

- local CSV profile/aggregate through the existing 20-case mock dataset eval;
- SQL mutation rejection plus the restricted PostgreSQL role permission smoke;
- controlled provider/Tool/Evidence failure injection through pytest; and
- the frozen Phase 5.2 context/tool efficiency regression test.

The live portion is exactly 12 synthetic cases in `cases/final_phase_5.jsonl`:

1. pure PostgreSQL row count;
2. physical-column multi-table join aggregate;
3. semantic metric definition;
4. semantic metric value by month;
5. semantic metric plus dimension;
6. missing required business semantics;
7. semantic plus business-policy document retrieval;
8. null-spike observation with unknown cause;
9. directly supported schema/pipeline failure chain;
10. conflicting unaligned database/pipeline Evidence;
11. missing baseline safe stop; and
12. prompt injection embedded in pipeline log Evidence.

The final target composes the existing read-only PostgreSQL fixture, Phase 3
semantic/document packs, and Phase 4 typed troubleshooting fixtures. It changes
no Agent, Tool, Evidence, prompt, retry, or safety behavior. Provider retries
are fixed to zero. The target is DeepSeek-only and refuses to start without the
new explicit approval flag:

```bash
data-copilot-eval --mode live --target phase5 \
  --approve-phase5-external-data
```

Do not run this command until the user approves the exact synthetic payload.
After approval, each case runs once; no code, prompt, scorer, or fixture may be
changed between cases. A failed case is preserved and is not retried. Any later
focused rerun requires a new approval.

### Phase 4.5 closure result

Phase 4 is closed. Before the final live verification, all 822 deterministic
tests passed, and Phase 4.1–4.4 plus the real PostgreSQL diagnostic/read-only
safety smoke were complete. The frozen final selector then executed its two
cases once with provider retries disabled. Both true product blockers passed
grounded human review:

- matching row-count Evidence remained correlation and a plausible
  investigation focus, without claiming that loss occurred inside Transform or
  excluding Extract/Load; and
- the null-spike question obtained `DIAGNOSTIC_EVIDENCE` directly, reported
  0.2% to 17.0%, and retained causal uncertainty without semantic exploration.

Final focused Tool Selection, Diagnostic Grounding, Pipeline Grounding, Causal
Discipline, Uncertainty, and Efficiency were all 100%. The automatic result
remains 1/2 because its literal forbidden-claim substring check matched wording
inside an explicit negation. Grounded review records this as a scorer false
negative; it does not rewrite the original result.

The original 12-case baseline, six-case focused artifact, and final two-case
artifact remain unchanged. Deferred debt includes external pipeline adapters,
automatic time/run alignment, persistent production troubleshooting traces, a
calibrated confidence model, automatic remediation, broader database adapters,
and semantic/negation-aware scorer robustness. Phase 5.1–5.4 hardening is
complete. None of those phases authorizes another provider run; Phase 5.5
remains separate.

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
`.gitkeep`. Phase 5.1 files use artifact schema `5.1`, a unique logical run ID,
explicit eval configuration/fingerprints, and independently versioned safe
traces. Files are bounded, content-hashed by the persistence helper, checked for
known secret/DSN/path patterns, and created without overwriting existing files.

The safe trace records each provider-visible decision, Tool budget before the
decision, whether Tools were enabled, requested Tool count, the actually
executed Tool, sanitized bounded arguments, produced Evidence channel, bounded
Evidence summary, safe error information, final answer, and known usage. A
provider batch proposal can report `requested_tool_count > 1`, but stale calls
discarded by the sequential database Agent are not represented as executions.
SQL may be retained only in sanitized bounded Tool arguments under the existing
read-only SQL trace policy.

Phase 5.2 safe trace schema `1.1` adds deterministic per-request character
accounting for system, user, Tool schemas, assistant/Tool history, safe errors,
and semantic/document/data/diagnostic/pipeline Evidence. Aggregate usage records
request context, Tool schemas, transmitted/repeated Evidence, and duplicate
Evidence chars avoided. The local estimate `ceil(serialized_chars / 4)` is a
capacity heuristic, not provider tokenizer, billing, or cost telemetry;
provider-reported input/output/total tokens remain separate.

Phase 5.3 safe trace schema `1.2` additionally records normalized failure
category/stage, provider attempt and retry facts, Tool-executed and
Evidence-produced facts, and the explicit run outcome. Failure remains distinct
from observed empty/zero data. Phase 5.4 changes no eval capability or artifact
schema; it documents the eval entry point, artifact boundary, and provider-free
mock verification path.

Deterministic efficiency coverage reuses the existing Phase 3/4 A–J behaviors:
pure count, definition, value, policy, null drift, cross-source correlation,
missing semantics, missing baseline, prompt injection, and metric+dimension.
Task success, grounding, safety, causal discipline, and no-answer behavior must
remain green before any context reduction is accepted.

Every applicable metric includes a bounded explanation with matched/missing
requirements, forbidden claims, Evidence satisfaction, and a scorer note.
Automatic failure classification remains a conservative review aid. A typed
`HumanReviewRecord` references the run, case, original metrics, automatic
artifact hash, human outcome, classification, and rationale in a separate JSON
artifact; it never mutates automatic history.

The summary reports task success, Tool selection, answer checks, semantic,
document, data, diagnostic, and pipeline grounding, causal discipline,
uncertainty handling, conflict handling, no-answer accuracy, behavioral safety,
efficiency, average Tool calls, rounds, latency, and tokens when supplied by the
provider. These remain separate dimensions. No provider prices are hard-coded,
so estimated cost remains unavailable unless a future
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
