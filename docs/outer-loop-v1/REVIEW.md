# Outer Loop v1 Review

Status: independent review completed; actionable safety findings closed

Three fresh-context reviewers examined the first complete implementation from
separate perspectives: engineering taste / over-engineering, end-to-end closure,
and adversarial technical correctness. After fixes, an exact v6 package passed
the deterministic suite and a fresh-context behavior recovery run.

The raw reviewer reports remain in the ignored research workspace. This document
records the verified findings and their disposition; reviewer conclusions were
not accepted without reproduction.

## Findings Closed

| Finding | Disposition |
| --- | --- |
| Pre-commit checked worktree rather than staged index | Added `candidate: "index"` and split-staging test. |
| Digest could differ from bytes parsed by the AST | One captured byte snapshot now feeds digest and parser; clean-filter replay test added. |
| Every historical test file was parsed | Only Git-changed policy paths are read and parsed; unchanged broken-file test and 1,000-file benchmark added. |
| Imported bindings were matched by name | Retained Babel scope traversal; local `assert` / `expect` shadowing is ignored. |
| Bare `assert/strict` was missed | Added to the declared Node module set and corpus. |
| Optional assertion calls were missed | Added optional call/member traversal and rewrite/deletion corpus. |
| Chai namespace forms were dead/unrecognized | Added named, CommonJS, default/namespace `expect` and `assert` bindings. |
| Staged deletion plus untracked recreation overwrote the base side | Worktree change records now merge both sides; index/ref behavior remains unchanged. |
| Equivalent string/template, object-key, and static-member forms false-blocked | Added conservative semantic normalization for demonstrated equivalent forms. |
| JSX in plain `.js` tests always became partial | Enabled JSX parser coverage for JavaScript test extensions. |
| Unknown CLI flags were ignored | Unknown, duplicate, and operation-inapplicable options now fail closed. |
| Invocation errors shared exit 2 with `indeterminate` | Guard verdicts remain 0-3; invocation/API errors use exit 4. |
| Oversized first finding could exceed/stall a page | Bounded summary advances the cursor and marks `fileTruncated`. |
| Scan-error `status` lost the matching run ID | Matching latest indeterminate runs now retain `runId` / details linkage. |
| Concurrent recapture failure was claimed but not pinned | Added a deterministic capture-mutate-verify test. |
| Receipt on an already-clear input reported `applied: 0` | It is rejected as `no-findings-to-authorize`; verdict remains clear. |

Final closure confirmation: an independent fresh-context reviewer re-ran the
suite and verified every listed finding closed. Result: `48/48`, closure `PASS`.

## Over-Engineering Assessment

The independent taste verdict was: lean at the safety core, mildly
over-specified at the context-facing edge. The concern is real; v1 is 1,229
runtime lines and installs a 7.6 MiB Babel dependency tree for one policy.

### Complexity retained

`check` is non-negotiable. The broad behavior comparison produced 7/18 unsafe
bare deliveries, 5/18 with a prose rule, and 0/18 with the guard.

`candidate: index` is retained because a worktree pre-commit check has a proven
split-staging hole. Immutable ref checks remain the trusted CI path.

Exact-input authorization is retained because legitimate contract changes must
have a closed path. Three wide-change runs were blocked first and delivered only
after exact-digest host receipts in fresh contexts.

Babel traversal is retained because the smaller name-based implementation
produced a concrete false positive under lexical shadowing. Replacing it with a
custom scope resolver would hide, not remove, that complexity.

`status / details / latest-only store` are retained by deliberate product
choice. They are the approved re-query surface for a Magic Context-like host:
`status` distinguishes matching from `unchecked`, while `details` keeps blocked
context bounded. The store is one replaceable result, not an event history and
not delivery evidence. This subsystem has not yet been connected to a proven
Magic Context provider hook, so it remains experimental rather than mandatory.

The 2 KiB default response target and pagination are also retained. They directly
answer the approved context-control requirement that the model must not infer
whether output was cut: `coverage` reports scan completeness; counts and cursor
report display completeness. The implementation exposes a larger bounded budget
when a host needs more detail.

### Complexity rejected

v1 does not contain an outer-loop Skill, router, task state, request projection,
append-only workflow events, compression implementation, automatic task split,
completion oracle, installed repository hook, or candidate-controlled approval.

Result storage was reduced to one atomic `latest.json`; check input was reduced
to changed policy paths; CLI output was reduced to compact JSON; and the final
trusted veto remains external CI rather than a local security claim.

### Documentation duplication

`docs/outer-loop-v1/README.md` is the project authority. `guard/README.md`
repeats part of the contract because it is the only README shipped in the
standalone package tarball. This duplication is accepted for v1, but package
publication should generate or mechanically check the shared protocol section
to avoid drift.

## Closed Paths

The following paths now have executable coverage:

1. no finding -> clear -> index commit -> immutable-ref CI;
2. finding -> blocked -> repair -> changed digest -> fresh check;
3. parse/read/Git failure -> indeterminate + partial -> fail closed;
4. many findings -> bounded first page -> `details` cursor progress;
5. compression/resume -> host `status` -> matching result or unchecked;
6. legal rewrite -> blocked -> trusted exact-index receipt -> normal commit ->
   same-content ref check;
7. stale, partial, unknown, malformed, already-clear, or wrong-policy receipt ->
   rejected;
8. local hook bypass -> explicitly outside the security boundary -> trusted CI
   still recomputes from protected inputs.

No completion claim is derived from `clear`; the context host still owns the
user request and the handoff compares it with patch plus executable evidence.

## Residual Risks

- The actual installed Magic Context plugin has not been shown to expose a
  generic provider-registration hook. Ockle implements the re-query boundary,
  not that plugin adapter.
- A base-side parse failure is fail-closed and cannot be authorized without a
  reliable finding set; it requires a parser/policy fix or different trusted
  base.
- Exact bytes mean CRLF/clean-filter normalization can invalidate a worktree
  receipt at staging. Commit authorization should be issued against the index.
- `worktree` and `index` are reserved candidate names and shadow refs with those
  names.
- Snapshots, skipped/disabled tests, shared helper weakening, schemas, and
  arbitrary assertion libraries remain outside `assertion-change@1`.
- A local Agent can bypass a local hook. Only protected CI can be the final veto.
- The behavior sample is one model and one language ecosystem; the package
  remains an experimental vertical slice.
