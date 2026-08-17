# Phase 4.5 Final Two-Case Live Verification

## Run scope

- Provider/model: DeepSeek / `deepseek-v4-flash`
- Selector: frozen Phase 4.5 final two-case selector
- Cases executed once: 2
- Provider retries: 0
- Automatic result artifact: `20260813T114852Z-deepseek-deepseek-v4-flash.json`
- Automatic artifact SHA-256: `8c68dd898a899cb401497e5d7c08efa26ce8599806d8e418b4d0557f333e585e`
- No case was retried and no code, Prompt, or scorer change occurred between cases.

## Automatic result

- Overall: FAIL (1 passed, 1 failed)
- Task Success: 50.0%
- Answer Accuracy: 100.0%
- Tool Selection: 100.0%
- Grounding: 50.0%
- Diagnostic Grounding: 100.0%
- Pipeline Grounding: 100.0%
- Causal Discipline: 100.0%
- No-answer / Uncertainty: 100.0%
- Efficiency: 100.0%
- Behavioral Safety: not automatically scored for these two non-safety cases

## Grounded human review

The original automatic result remains unchanged. Human review found both
user-facing outcomes acceptable under the frozen closure criteria.

| Case | Automatic | Human grounded outcome | Classification |
| --- | --- | --- | --- |
| `row_count_drop_pipeline_match` | Fail | Pass | Scorer false negative. The answer reports 1,200 to 780, distinguishes matching cross-run values from the same-run Transform boundary observation, labels Transform only as a plausible/priority investigation focus, explicitly refuses to say the loss occurred inside Transform, and explicitly refuses to exclude Extract or Load. The deterministic substring scorer matched the forbidden Chinese phrase inside that explicit negation. Its separate causal-discipline check passed. |
| `null_spike_unknown_cause` | Pass | Pass | True product pass. The Agent called only `compare_table_snapshots`, reported 0.2% to 17.0%, introduced no semantic or unrelated Evidence, did not invent a mechanism, retained uncertainty, and proposed bounded next diagnostic observations. |

## Actual execution metrics

| Case | Tool sequence | Tool calls | Rounds | Latency | Input tokens | Output tokens | Total tokens |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `row_count_drop_pipeline_match` | `compare_table_snapshots` -> `compare_pipeline_runs` | 2 | 3 | 17,954.70 ms | 15,735 | 1,651 | 17,386 |
| `null_spike_unknown_cause` | `compare_table_snapshots` | 1 | 2 | 9,080.82 ms | 8,888 | 836 | 9,724 |
| Total |  | 3 | 5 | 27,035.53 ms | 24,623 | 2,487 | 27,110 |

Average latency was 13,517.76 ms per case.

## Closure recommendation

Recommend closing Phase 4. The two previously identified product blockers pass
grounded human review in this frozen one-shot verification. The remaining
automatic failure is a recorded scorer limitation caused by negation-insensitive
substring matching, not a product-behavior failure. Do not rewrite the original
automatic result to reflect this review, and do not start Phase 5 as part of this
verification.
