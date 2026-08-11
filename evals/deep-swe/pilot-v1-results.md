# DeepSWE Pilot v1 Results

## Status

The 29-cell DeepSWE v1.1 pilot completed with the frozen task set and `Mapleluv-Main-MSG/deepseek-v4-flash:max` over Anthropic Messages. DeepSWE's verifier is the behavior authority. This report uses the separate corrected regrade artifact; it does not use the original r5 aggregate's obsolete rule that invalidated a whole session after any historical provider error.

The correction changes only the runtime evidence gate. It does not change any task identity, reward, F2P, P2P, partial score, patch, Git state, guard verdict, or delivery verdict.

Authority:

- Subject checkpoint: `b5d7db4be95c51f44ba5cbc70c7f73cd847ebffd`
- Original cells SHA-256: `3708e0bdd2517b3b65fed8f14d1aa0b541066ac0734877eae2dead251cfbfaec`
- Original 982-file inventory SHA-256: `a9d233470b7a76d034017caa99e369d6c8826023f607eb6c1cbebf0a428040c2`
- Regrade scorer checkpoint: `c4c97b4faa9f835de76b2d1262601389f2228066`
- Scorer files SHA-256: `4a6adfe548bc0368524937e6d21cbf30ca462ddca889c6e318f1f3a4e8c04fa5`
- Pier RECORD set SHA-256: `485104a92419622b2e367ae277e76b40877181743d5af4709e9e47c48dd39312`
- Corrected `regrade.json` SHA-256: `b6abddc53aeed4b3133fdc1b85d49480cbeba1a186f0bce3afa6ca512d0af522`

The corrected artifact is outside the repository at `/home/administrator/ockle-deepswe/formal-pilot-v1-b5d7db4-r5-regrade-v1`. The original r5 directory is unchanged.

## Results

| Arm | Tasks | Resolved | Complete | Runtime evidence | Finished before timeout | Timeouts | Unsafe delivered |
|---|---:|---:|---:|---:|---:|---:|---:|
| bare | 12 | 5 (41.7%) | 5 | 12/12 | 11/12 | 1 | 0 |
| inner | 12 | 3 (25.0%) | 3 | 12/12 | 12/12 | 0 | 0 |
| full | 5 | 1 (20.0%) | 1 | 5/5 | 2/5 | 3 | 0 |
| total | 29 | 9 | 9 | 29/29 | 25/29 | 4 | 0 |

All 29 cells have valid benchmark outcome evidence. The four exact 5,400-second agent timeouts are valid DeepSWE failures, not infrastructure failures or missing scores. Every reward-1 candidate was clean and complete under the delivery gate.

## Paired Outcomes

The primary comparison is `bare` versus `inner` on all 12 tasks:

- Both resolved: 1
- Bare only: 4
- Inner only: 2
- Neither: 5
- Observed paired difference: `3/12 - 5/12 = -16.7 percentage points`

The three method Skills did not improve the one-repeat binary result. The six discordant pairs split 4 to 2 in favor of bare. With only 12 fixed tasks and one stochastic rollout per cell, this is evidence against claiming a benefit, not enough evidence for a stable negative population effect.

The guard increment is `inner` versus `full` on the five frozen JavaScript/TypeScript tasks:

- Both resolved: 0
- Inner only: 1 (`yjs-map-conflict-detection`)
- Full only: 1 (`sql-formatter-bigquery-pipe-formatting`)
- Neither: 3

Both arms resolved 1/5, so the observed behavior difference is zero. Full had three timeouts while the paired inner cells had none. All five final guard verdicts were `clear`, and no unsafe delivery occurred. This pilot therefore demonstrates that the guard did not mechanically veto these candidates, but it did not exercise a true assertion-change block and cannot estimate the guard's protective benefit.

## Task Outcomes

`1` means DeepSWE reward 1, `0` means reward 0, and `T0` means reward 0 after the exact 5,400-second timeout.

| Task | bare | inner | full |
|---|---:|---:|---:|
| `fastapi-implicit-head-options` | T0 | 0 | N/A |
| `go-critic-doc-link-checker` | 1 | 0 | N/A |
| `helm-array-merge-strategies` | 1 | 0 | N/A |
| `kombu-virtual-queue-dead-lettering` | 1 | 0 | N/A |
| `koota-composite-trait-aspects` | 0 | 0 | T0 |
| `pest-character-class-coalescing` | 0 | 0 | N/A |
| `sql-formatter-bigquery-pipe-formatting` | 1 | 0 | 1 |
| `superjson-error-stack-serialization` | 0 | 0 | 0 |
| `tengo-callable-instance-isolation` | 0 | 1 | N/A |
| `testem-bail-on-test-failure` | 0 | 0 | T0 |
| `vulture-persistent-analysis-cache` | 0 | 1 | N/A |
| `yjs-map-conflict-detection` | 1 | 1 | T0 |

## Reliability And Cost

| Arm | Sessions with recovered errors | Error records | Output tokens | Agent steps | Context input including cache | Cache tokens |
|---|---:|---:|---:|---:|---:|---:|
| bare | 5/12 | 6 | 1,673,419 | 1,279 | 242,660,275 | 239,565,184 |
| inner | 8/12 | 19 | 1,807,298 | 1,559 | 315,079,681 | 311,799,552 |
| full | 4/5 | 20 | 869,712 | 731 | 173,947,462 | 172,490,240 |

All 45 provider-stream errors were followed by a fully validated assistant turn in the same Pi session. They remain explicit reliability and cost events. They are not silently discarded and are not terminal runtime failures.

Compared across the same 12 tasks, inner used 8.0% more output tokens and 21.9% more agent steps than bare while resolving two fewer tasks. On the same five JS/TS tasks, full versus inner used 11.2% more output tokens and 5.9% more steps, recorded 20 versus 5 provider errors, and timed out three versus zero times. One repeat cannot separate guard overhead from model and provider variance, but the observed efficiency signal is unfavorable.

No cell used the bounded dirty-worktree continuation. This is consistent with the Anthropic Messages tool loop avoiding the earlier text-only premature turn termination. Pi native compaction remained disabled.

## Interpretation

This pilot does not support a claim that the three method Skills improve DeepSWE performance for this model. The point estimate is lower and the run is more expensive. The full-arm candidates satisfied the delivery-safety checks and the guard did not cause a mechanical behavior veto, but its five-task sample is too small and contains too many timeouts to establish a performance effect.

The result should not be compared directly with DeepSWE's published `15/48` (`31.25%`) for `mini-swe-agent + deepseek-v4-flash:max`. That number is only a difficulty calibration. Pi bare is the relevant control for Ockle, and the paired task outcomes above are the relevant effect evidence.

## Limitations

- This is one rollout per cell on 12 mechanically selected public tasks.
- DeepSWE is public, so runtime network isolation cannot prove that the hosted model never saw task material during training.
- The full guard applies only to five JavaScript/TypeScript tasks.
- Forty-five recovered stream errors and four timeouts show substantial provider/runtime instability, especially on longer full-arm runs.
- The fixed provider endpoint uses plain HTTP. Egress restriction and secret scanning do not provide transport confidentiality.
- The result evaluates these exact Skill texts, guard policy, Pi version, model endpoint, and task sample. It is not a general claim about all models or repositories.

## Reproduction

From scorer checkpoint `c4c97b4faa9f835de76b2d1262601389f2228066`, with the pinned Pier environment and an unused output directory:

```sh
PYTHONPATH=/mnt/d/Projects/Ockle/evals/deep-swe \
/home/administrator/.local/share/uv/tools/datacurve-pier/bin/python -B \
/mnt/d/Projects/Ockle/evals/deep-swe/regrade_formal_r5.py \
  --source-root /home/administrator/ockle-deepswe/formal-pilot-v1-b5d7db4-r5 \
  --output /home/administrator/ockle-deepswe/formal-pilot-v1-b5d7db4-r5-regrade-reproduction
```

The scorer refuses a dirty repository, a pre-existing output directory, any source inventory drift, any Pier RECORD drift, and any unknown exception or evidence inconsistency.
