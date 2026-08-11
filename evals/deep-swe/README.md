# DeepSWE Pilot

This package runs a paired external-validity pilot against DeepSWE v1.1. It is separate from Ockle's synthetic end-to-end diagnostic evaluator: DeepSWE owns the task prompts, repositories, verifier tests, build gate, F2P/P2P scoring, and binary reward.

## Frozen Inputs

`pilot-v1.json` pins:

- DeepSWE commit `435ee89ec2f2e2289f33b0da4f992f0b7b7266b9`.
- Pier commit `0daf53d3599e58c4506cf0bcff5e12c77dc282d2` (`0.3.0`).
- Twelve task IDs selected mechanically from all 113 IDs by language quota and `SHA-256("Ockle DeepSWE v1.1 pilot 1\n" + task_id)` rank.
- Every base commit, source task checksum, hardened prepared checksum, published image tag, and resolved image digest.
- The exact source archive, Node archive, Pi tarball/shrinkwrap, guard bundle, and Pier egress-proxy base image digests.
- `Mapleluv-Main-MSG/deepseek-v4-flash` over `anthropic-messages` at the fixed provider origin `http://38.148.253.23:8317`, with thinking `max`.

The selection algorithm does not use public per-task outcomes. Freeze the manifest before running any Ockle arm. Do not replace failed tasks after seeing results.

## Arms

- `bare`: Pi with no Skills and no Magic Context.
- `inner`: Pi with the three independent Ockle method Skills.
- `full`: `inner` plus the root-owned `assertion-change@1` guard integration. It is run only for the five JavaScript/TypeScript tasks.

All twelve tasks pair `bare` and `inner`. The five JS/TS tasks add `full`, for 29 subjects total. There is no prose arm in the public pilot.

Pi native compaction is disabled in all arms. The model's native context window is used directly. Apart from the three Skill paths and the JS/TS guard integration, the Pi model, prompt, tools, task image, resources, and verifier are identical.

Pi `--print` treats a text-only assistant response as the end of a turn. After the initial turn, every arm applies the same bounded delivery protocol: trusted root Git status checks both the fixed real `/app/.git/index` and an independent `HEAD` index over `/app`; only a dirty result triggers one continuation through Pi's official `--continue` path in the same session. The real index must be a regular non-symlink, non-split, Git-readable index. The adapter never inspects assistant prose, never auto-commits, and never sends more than one continuation. A clean tree or nonzero Pi process result does not trigger it. Root-frozen raw status bytes plus their length and SHA-256 are retained, and the formal extractor recomputes that evidence. An exact 5,400-second benchmark timeout may retain the untouched continuation sidecar and no raw status file because Pi never returned successfully; that state remains a timeout and can never count as complete.

## Authority

DeepSWE's separate verifier container is the only behavior authority. Its candidate patch, build gate, F2P, P2P, partial score, and binary reward are reported without reinterpretation.

The full-arm guard is a separate delivery-safety axis:

1. A root-owned pre-commit hook checks the staged index against the task base and gives bounded advisory feedback. The hook directory is read-only, but a candidate can still bypass local hooks; no score trusts hook execution.
2. After Pi exits, the root-owned engine kills candidate processes, fixes Git to `/app/.git` plus `/app`, rebuilds a root-only index from `HEAD`, removes replace/graft/alternate state, overrides execution-affecting config for each command, and recomputes both `base...HEAD` and the complete worktree. A separate fixed-environment check parses the candidate's actual index and compares it with `HEAD`; overall cleanliness requires both the independent worktree and candidate index to be clean.
3. No candidate-supplied authorization is accepted. DeepSWE feature prompts do not grant authority to rewrite existing assertions.
4. A behavior pass with a final blocked or indeterminate guard is reported as unsafe, not silently folded into the DeepSWE reward.

A clear guard verdict does not imply task completion. A blocked candidate that was not committed is safe-incomplete.

## Isolation

Run Pier and Docker inside WSL2 on an ext4 checkout. A Windows checkout can convert verifier shell scripts to CRLF and is invalid for Linux execution.

The subject runs as non-root user `ockle` and receives only the task instruction and `/app` repository. `/opt/ockle` is root-owned and read-only. The benchmark checkout, public tests, task package, verifier, public outcomes, and task solution are not mounted in the agent container. The hardened prepared task sets current Pier schema fields `agent.user = "ockle"`, `environment.allow_internet = false`, and `verifier.environment.allow_internet = false`.

Pier's filtered proxy permits only `38.148.253.23`. Pier 0.3.0 normally permits only ports 80 and 443; the adapter fail-closed verifies the exact pinned Squid bootstrap bytes and adds only HTTP port 8317 to `Safe_ports`, while CONNECT remains limited to 443. The formal extractor requires every trial's generated `start-squid.sh` to match those trusted bytes. Public sites remain unreachable through the proxy and after unsetting proxy variables because the agent network is Docker-internal.

The `Mapleluv-Main-MSG` credential is loaded from a mode-`0600` WSL env file and is never written into `pilot-v1.json` or Pi configuration. It is distinct from the `Mapleluv` OpenAI-Responses credential. Pi references `$MAPLELUV_API_KEY`. After execution, the adapter scans committed delivery bytes and `/logs/agent`, redacts an exact credential occurrence, and invalidates that subject. Over-budget files and regular files that fail content reads are deleted before the scan fails; any other scanner failure aborts the formal launcher without a summary. The host repeats exact scanning in a `finally` path. Prepared data, credentials, guard bundle, formal output, raw jobs, and model sessions must resolve outside the Ockle repository.

This is a bounded evaluation boundary, not a hostile-code OS sandbox. Provider credentials are present in the Pi process environment, and task code runs inside the task container. The fixed Main-MSG endpoint is plain HTTP: the destination policy constrains egress but does not provide transport confidentiality between Squid and `38.148.253.23:8317`. Keep the provider allowlist and post-run secret scan enabled, and do not reuse the pilot credential for unrelated authority.

## Calibration

Before model subjects:

1. Verify the source and Pier commits.
2. Recompute each Harbor task checksum from the LF-preserving WSL checkout.
3. Resolve every image tag and require the digest in `pilot-v1.json`.
4. Run no-op and oracle calibration for every selected task. A valid task must produce reward `0` for no-op and reward `1` for oracle, with no infrastructure exception.

Calibration has completed for all twelve frozen tasks: all twelve no-op runs returned reward `0`, all twelve official-oracle runs returned reward `1`, and none had an infrastructure exception. A second no-op/oracle pair on a digest-qualified prepared image reference also returned `0`/`1`.

`official-deepseek-v4-flash-max.json` freezes the public difficulty calibration for the same IDs under DeepSWE's official `mini-swe-agent` harness: `15/48` passes (`31.25%`), four tasks at `0/4`, eight mixed, and none at `4/4`. This is not a Pi control arm and cannot measure an Ockle effect.

A no-model Pier boundary probe additionally verified non-root UID, writable `/app`, read-only `/opt/ockle`, absent oracle mounts, an authenticated `curl -f` success at the Main-MSG `/v1/models` route, and blocked public network over both proxy and direct paths. A controlled zero-model continuation probe created the exact staged-index/worktree-at-`HEAD` state and verified one trusted-dirty trigger, Pi `--continue`, one session identity, clean committed delivery, and valid frozen evidence. A full post-run negative probe preserved the same staged-only state and produced independent-worktree `clean`, candidate-index `dirty`, and overall `dirty`, while a corrupt-index probe failed final evidence with Git exit `128`. Separate zero-call full-lifecycle probes verified: clean commit/worktree verdicts and frozen evidence; a deleted tracked test yields commit `clear`, worktree `blocked`, and dirty Git even after candidate config redirects `core.worktree` to a clean decoy; and an oversized log containing the exact credential is purged and makes the subject fail closed.

## Adapter Checks

Run the platform-specific adapter tests in the pinned Pier environment:

```sh
cd /mnt/d/Projects/Ockle/evals/deep-swe
/home/administrator/.local/share/uv/tools/datacurve-pier/bin/python \
  -m unittest -v test_pi_agent.py
```

Run repository structure tests from the Ockle root:

```sh
npm test
```

`pi_agent.py` pins Node `24.18.0` by archive SHA-256 and Pi `0.84.1` by tarball plus bundled shrinkwrap SHA-256. Runtime logs retain Pi's structured session JSONL so token, cache, cost, context, step, and provider-error metrics come from provider usage records rather than model prose. The final assistant stop reason must be `stop` or `toolUse`; `error`, `aborted`, or a missing value invalidates runtime evidence. Provider/model/API mismatch, non-`max` thinking, a second session identity, or compaction also invalidates it. A historical provider-error record followed in the same session by successful assistant turns is retained as a recovered reliability/cost event; it does not invalidate the completed run, and the formal artifact requires `providerErrorCount == recoveredProviderErrorCount`.

A live `inner × superjson-error-stack-serialization` protocol smoke exercised `Mapleluv-Main-MSG/deepseek-v4-flash/max` through the real filtered proxy: one session, 36 tool-use responses, 49 tool calls, zero compactions, clean committed delivery, valid runtime/final/security evidence, and no continuation. DeepSWE still returned reward `0` (`69/80` F2P and `116/116` P2P), which is a model behavior result rather than an infrastructure pass. The smoke is excluded from formal scores.

The completed 29-cell r4 run used the previous OpenAI-Responses adapter and produced `0/29` binary rewards. Its artifacts showed that 17 dirty candidates stopped on text-only transition responses, with unequal arm impact. It is therefore retained only as adapter-protocol calibration and excluded from the Ockle effect estimate.

The 29-cell Anthropic-protocol r5 run is bound to checkpoint `b5d7db4be95c51f44ba5cbc70c7f73cd847ebffd`; its immutable `cells.json` SHA-256 is `3708e0bdd2517b3b65fed8f14d1aa0b541066ac0734877eae2dead251cfbfaec`. DeepSWE observed nine binary rewards and four 5,400-second agent timeouts. Its original post-run parser classified any historical provider error as invalid, even though all 45 such records were followed by successful assistant turns and all 29 sessions ended with non-error assistant state. The original `cells.json` and `summary.json` remain unchanged as calibration artifacts. A corrected, arm-blind regrade uses only the frozen session chronology and external evidence: final provider errors remain invalid, recovered errors are counted, timeouts remain benchmark failures, and no reward, patch, guard, or delivery fact is changed. Publish that regrade only as a separate hash-bound artifact after independent review.

After building the exact guard bundle and materializing the source archive, `run_pilot.py` is a one-shot 29-cell launcher. It has no condition or alternate-manifest CLI, invokes Pier through the RECORD-verified Python distribution, rejects a dirty Ockle tree or pre-existing output, validates every expected task result and generated proxy policy after each arm, scans artifacts for the exact credential, and writes `summary.json` only after all three arms validate.

`regrade_formal_r5.py` is the bounded read-only correction procedure for r5. It hard-binds the original cells, manifest, checkpoint, and canonical 982-file source inventory digests; revalidates every raw session, continuation, proxy, final Git, guard, security, reward, and Pier RECORD input; and writes a new hash-bound artifact without overwriting the source run.

## Limitations

DeepSWE is difficult and executable, but public. Its prompts, tests, task packages, public trajectories, and solutions are available outside the subject boundary, so this pilot is not a hidden benchmark. Subject network isolation prevents runtime lookup but cannot prove that a hosted model never ingested public artifacts. The pilot resolves and verifies image digests, but apt/npm build dependencies inside derived agent layers are not a bitwise offline snapshot. One paired pass is a pilot, not a population estimate. Report task-level pairs and confidence intervals, environment failures separately, and never use the official DeepSeek score as if it were a same-agent Ockle control.
