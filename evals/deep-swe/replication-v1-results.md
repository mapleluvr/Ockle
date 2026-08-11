# DeepSWE Replication V1 Results

## Status and scope

Replication V1 is a result-aware, post-hoc repeated-sampling experiment. It repeats two tasks selected because the single-run pilot produced opposite bare/inner outcomes. It is not a new unbiased benchmark sample, must not be pooled with the twelve-task pilot as if selected prospectively, and does not estimate performance across DeepSWE as a whole.

The frozen matrix ran 50 separately isolated DeepSWE trials with no retries or outcome-based replacement:

- `sql-formatter-bigquery-pipe-formatting`: bare, inner, and full, ten attempts each.
- `tengo-callable-instance-isolation`: bare and inner, ten attempts each.
- Three Pier jobs ran simultaneously at concurrency 3, 3, and 2, for a global maximum of 8.

The DeepSWE verifier reward is the behavior authority. All counts below come from the canonical attested artifact, not model self-reports.

## Authority

| Input or artifact | Value |
|---|---|
| Ockle subject checkpoint | `f8713ca66e3a5197d61111a2ed0fe7e0d323a14b` |
| Runtime tree SHA-256 | `904061d845de145efb17de57a82681dd089fc4de814ca1cd20a64cd59c11f5b3` |
| Replication manifest SHA-256 | `a2efadd163c43a9b8bd68a007ac2d4f73109ba5c004c597578034b7777237508` |
| Guard bundle SHA-256 | `e02fa5139d7d7f7902dfab75798ad35c8d34502d811f97fddddf6fb30c1c27c6` |
| Cells SHA-256 | `9ad3dbffd90c68c24886f59c7768ac7a2190ea8aff4a63d1025ea9a0a5055724` |
| Evidence inventory SHA-256 | `a48fdf0c6c41469f7bbb585d0a89ba394cd857ae1af566f48b336369f13f8d10` |
| Attestation / `COMPLETE` SHA-256 | `42afdb121e5f806f886dd11090769798a8ff04c2f8fb46f24762fe0ef53cc997` |
| Pier | `0.3.0@0daf53d3599e58c4506cf0bcff5e12c77dc282d2`, 127 installed files verified |

The run used `Mapleluv-Main-MSG/deepseek-v4-flash:max` through Anthropic Messages. The attested Pier jobs span 2026-08-11 22:49:11 through 2026-08-12 03:00:47 in host-local time, and all three attested runner stderr logs are empty. An independent verifier recomputed all 1,578 attested files, the complete 50-cell identity set, task-level rewards, paired counts, costs, guard evidence, and security fields.

Before formal execution, an exact-shape boundary preflight passed 50/50 trials at the same concurrency with zero Pi model calls and zero sessions.

## Results

| Condition | Resolved | Rate | Wilson 95% | Exact timeouts | Output tokens | Agent steps |
|---|---:|---:|---:|---:|---:|---:|
| bare | 9/20 | 45% | 25.8% to 65.8% | 1 | 2,500,377 | 2,053 |
| inner | 13/20 | 65% | 43.3% to 81.9% | 0 | 2,639,138 | 2,109 |
| full, SQL subset only | 8/10 | 80% | 49.0% to 94.3% | 0 | 1,105,150 | 1,029 |

Inner exceeded bare by 4 resolutions across the 20 common attempts, an observed difference of +20 percentage points. The frozen repeat pairing was:

| Comparison | Both resolve | Left only | Right only | Neither |
|---|---:|---:|---:|---:|
| bare vs inner, both tasks | 7 | 2 bare | 6 inner | 5 |
| SQL bare vs inner | 6 | 1 bare | 2 inner | 1 |
| Tengo bare vs inner | 1 | 1 bare | 4 inner | 4 |
| SQL inner vs full | 6 | 2 inner | 2 full | 0 |

For the combined bare/inner table, `p=0.2890625` is the mechanically computed exact two-sided McNemar value for the frozen temporal-rank pairing. It is descriptive only: pairs were neither randomized nor seed-matched, so pair independence, exchangeability, and exact-test calibration are unverified.

## Task decomposition

| Task | bare | inner | full |
|---|---:|---:|---:|
| SQL formatter | 7/10 (70%) | 8/10 (80%) | 8/10 (80%) |
| Tengo | 2/10 (20%) | 5/10 (50%) | N/A |

The single-run pilot's SQL contrast was bare success versus inner failure. The repeated SQL result does not reproduce that direction: inner was one resolution higher. The pilot's Tengo contrast was inner success versus bare failure, and the repeated result retains that direction with a 5/10 versus 2/10 split.

Across these two post-hoc selected tasks, the repeated point estimate favors inner: SQL reversed direction and Tengo retained its pilot direction. This does not test whether the pilot's 12-task aggregate is stable, and it does not establish that the three method skills improve DeepSWE generally.

Full and inner each resolved 8/10 SQL attempts; the frozen temporal-rank table has two inner-only and two full-only outcomes. This is zero observed net difference between conditions, not a causal estimate of the guard.

## Cost and reliability

Against bare over the same 20 attempts, inner used:

- 5.5% more output tokens: 2,639,138 versus 2,500,377.
- 2.7% more agent steps: 2,109 versus 2,053.
- Four more resolved attempts: 13 versus 9.

By task, SQL inner used 0.9% more output tokens and 3.3% fewer steps than bare; Tengo inner used 9.7% more output tokens and 8.8% more steps. On the SQL subset, full used 6.2% fewer output tokens and 3.4% more steps than inner while resolving the same number of attempts.

Twelve provider stream-error records occurred and all twelve recovered later in the same session: bare 6, inner 3, full 3. There were no terminal provider errors. One bare Tengo attempt reached the exact 5,400-second agent timeout; its verifier reward remains a valid zero outcome, while its execution is not runtime-valid or complete. The other 49 attempts finished within the agent limit.

All 50 attempts had zero bounded dirty-worktree continuation calls. This is consistent with not observing the earlier dirty-candidate text-only exit mode, but continuation count alone does not test clean-tree premature exits. All 10 full-arm final guard checks were clear, all full deliveries were safe, and unsafe delivery count was zero. Because no assertion-change finding was blocked, this run does not estimate the guard's protective effect.

## Evidence validity

- Benchmark outcomes valid: 50/50.
- Runtime valid: 49/50; the sole exception is the exact timeout.
- Complete resolved deliveries: 30/50.
- Terminal provider errors: 0.
- Credential leaks: 0.
- Unsafe deliveries: 0.
- Pi sessions: exactly 50, one per trial.
- Bounded dirty-worktree continuation calls: 0.
- Result replacement or retry: 0.

## Limits

The two tasks were selected after observing the pilot and are intentionally diagnostic. Ten attempts reduce single-sample noise but do not remove task-selection bias, shared endpoint effects, temporal correlation, or model stochasticity. Repeat indexes pair attempts by post-exit `(started_at, trial_name)` rank; they are temporal blocks, not shared random seeds. The Wilson intervals are nominal binomial intervals and do not adjust for within-task or temporal dependence. Likewise, the mechanically computed McNemar value has no established exact-test calibration without pair independence and exchangeability. The plaintext HTTP Main-MSG transport residual disclosed in the pilot still applies: Pier restricts the destination IP and port, but transport encryption is absent. Public-task contamination cannot be ruled out even though subject network access to benchmark sources was blocked.
