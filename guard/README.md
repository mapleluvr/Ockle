# Ockle Guard

`@ockle/guard` is the first host-neutral outer-loop companion. It is a
mechanical interface for a narrow policy, not a workflow engine and not an
additional Skill.

## Current Policy

Version `assertion-change@1` checks the supported JavaScript and TypeScript test
sources in the base and candidate trees. It compares the behavior-bearing AST
of these assertions as a multiset:

- Node `assert` imports, TypeScript import-equals, and `require` bindings,
  including `assert/strict`, destructured methods, static `assert.strict.*`
  hops, and optional calls.
- Jest/Vitest called matchers and Chai named, CommonJS, or namespace
  `expect` / `assert` forms, including terminal property chains.
- Files below `test/`, `tests/`, `spec/`, `specs/`, or `__tests__/`, plus
  `*.test.*` and `*.spec.*` JavaScript/TypeScript files.

An existing supported assertion that is missing or has different behavior
arguments is `blocked`. Added assertions, formatting, assertion movement, import
alias changes, and Node assertion diagnostic-message changes are `clear`.
Unsupported assertion APIs, snapshots, disabled-test changes, and arbitrary
semantic changes are outside this policy's coverage. `coverage: complete` means
that the parser completed for this policy's declared file and syntax domain; it
does not mean that every possible test framework was understood.

A parse failure or incomplete scan is `indeterminate` with `coverage: partial`.
It must fail a delivery gate. A base-side parse failure cannot be overridden by
an authorization receipt: it requires a parser/policy fix or a different trusted
base, because the guard has no reliable finding set to authorize.

## Machine Interface

The public interface is deliberately small:

```js
import { checkGuard, statusGuard, detailsGuard } from "@ockle/guard";

checkGuard({ repository, base, candidate: "worktree" });
checkGuard({ repository, base, authorization: trustedReceipt });
statusGuard({ repository, base, candidate: "worktree" });
detailsGuard({ repository, runId, cursor: 0 });
```

The CLI exposes the same operations:

```sh
node guard/bin/ockle-guard.mjs check --base origin/main --candidate HEAD
node guard/bin/ockle-guard.mjs check --base origin/main --candidate HEAD --authorization-file /trusted/review.json
node guard/bin/ockle-guard.mjs status --base origin/main --candidate worktree
node guard/bin/ockle-guard.mjs details --run-id <id> --cursor 1
```

`base` is required. The default candidate is the current worktree. A pre-commit
hook must explicitly use `candidate: "index"`; CI should use an immutable
candidate ref such as `HEAD`. The literal candidate names `worktree` and `index`
are reserved and cannot address refs with those names.

Each successful response contains:

```json
{
  "schemaVersion": 1,
  "operation": "check",
  "runId": "...",
  "policy": { "id": "assertion-change", "version": "1" },
  "input": {
    "digest": "...",
    "base": { "ref": "origin/main", "commit": "...", "tree": "..." },
    "candidate": { "kind": "ref", "ref": "HEAD", "commit": "...", "tree": "...", "identity": "..." }
  },
  "verdict": "blocked",
  "coverage": "complete",
  "findings": {
    "total": 1,
    "returned": 1,
    "cursor": 0,
    "nextCursor": null,
    "items": [
      {
        "id": "...",
        "rule": "assertion-change",
        "kind": "removed-or-rewritten",
        "file": "test/example.test.js",
        "line": 42
      }
    ]
  },
  "errors": [],
  "errorCount": 0,
  "authorization": {
    "status": "none",
    "receiptId": null,
    "applied": 0,
    "remaining": 1,
    "authority": null,
    "reason": null
  }
}
```

The CLI emits one compact JSON object per line. The response never uses an
ambiguous `truncated` field. `coverage` describes scan completeness. `total`,
`returned`, and `nextCursor` describe pagination.
The default finding-page budget is 1024 UTF-8 bytes; the normal complete
response is kept below approximately 2 KiB. If one path cannot fit, the item is
returned as an advancing bounded summary with `fileTruncated: true`; callers can
retry `details` with a larger budget. `details` expands only the current stored
run. The store retains only the latest full result under Git metadata:
`.git/ockle-guard/runs/latest.json` by default.

Verdict exit codes are:

```text
clear          0
blocked        1
indeterminate  2
unchecked      3
CLI/API error  4
```

`status` returns `unchecked` when the current policy-input digest does not
exactly match the latest stored run. A check derives changed supported test
paths from Git, reads each relevant base/candidate source once into a snapshot,
and uses those exact bytes for both AST analysis and the digest. Mutable
worktree/index snapshots are recaptured before return. The digest binds the
policy version, base tree, changed path set, and exact source bytes. Staging or
committing identical supported test content does not change it. Changing a
relevant test source, base, or policy invalidates an old result; ordinary source
changes and host artifacts outside this policy do not, because they cannot
change this detector's verdict.

## Trusted Authorization

A legitimate contract change can intentionally rewrite an existing assertion.
The first check remains `blocked`; a trusted reviewer may then issue a receipt
for the exact policy input and finding IDs:

```json
{
  "schemaVersion": 1,
  "policy": { "id": "assertion-change", "version": "1" },
  "inputDigest": "<blocked response input.digest>",
  "findingIds": ["<finding id>"],
  "authority": { "kind": "human-review", "id": "review-42" }
}
```

The trusted caller passes this object through the API or
`--authorization-file`. Full matching changes the blocking finding set to
`clear` with `authorization.status: applied`. Partial receipts remain
`blocked`. Unknown finding IDs, policy drift, malformed authority, incomplete
coverage, a changed policy input, or a receipt on an already-clear input are
rejected. A receipt can survive unstaged -> staged -> committed transitions only
when the analyzed bytes are identical. For commit authorization, stage the
intended candidate first and issue the receipt against `candidate: "index"`.
Git clean filters or CRLF normalization may otherwise change the staged bytes and
correctly invalidate a worktree receipt.

The receipt authorizes only the listed guard findings. It is not approval of the
whole patch and does not replace tests, review, or branch protection. The guard
validates scope, not provenance: authoritative CI must obtain the receipt from a
protected host channel and must not accept an authorization file supplied by
the candidate or Agent.

## Runtime Boundaries

The three core Skills remain method-only. They do not schedule a guard, parse
its output, or maintain guard state. A caller may invoke the same interface at
these boundaries:

| Boundary | Operation | Purpose |
| --- | --- | --- |
| Optional early check | `check` | Give the Agent feedback before delivery. |
| Resume/materialization | `status` | Re-expose current guard state after context control. |
| Finding expansion | `details` | Fetch another bounded page. |
| Commit gate | `check(candidate: "index")` | Check exactly the staged content. |
| Explicit dirty-worktree handoff | `check(candidate: "worktree")` | Check the current filesystem candidate. |
| CI/branch protection | `check(candidate: <ref>)` | Final authoritative veto or trusted receipt application. |

Context control is external. A Magic Context-like host may call `status` when it
rebuilds the visible context; it does not need to make Ockle store the user
request, a plan, a summary, or completion state. The host may omit `clear` from
normal context and should re-inject `blocked`, `indeterminate`, and `unchecked`
responses. `status` recomputes the lightweight policy-input identity but does
not rerun AST extraction. Compression itself is not a reason to run a full
check.

`clear` means only that this policy found no blocking assertion change for the
reported input. It does not prove that the user's request is complete. The
request remains with the context host, and the final handoff must still compare
that request with the patch and executable evidence.

## Trust Boundary

A local Agent and a local hook share the same OS authority. They can modify or
skip a local hook, replace a local package, or invoke `git commit --no-verify`.
The local integration is therefore feedback, not a security boundary. Ockle v1
ships the machine interface, not automatic hook or CI installation. A caller's
pre-commit hook should run:

```sh
ockle-guard check --base <trusted-base> --candidate index
```

The same check against `worktree` is optional early feedback, not a substitute
for the staged check.

For an actual veto, CI must install the guard and policy from a trusted source,
then run it against the trusted base and candidate commit. It must not run an
executable or policy loaded from the candidate tree. When a reviewed contract
change needs authorization, CI must also supply the receipt from a protected
channel; accepting a receipt path or approval claim chosen by the Agent would
collapse the trust boundary.

The latest snapshot is a locally mutable context hint, never delivery evidence.
The companion persists only that latest mechanical result for re-query; it does
not persist user requirements, work units, task lists, model summaries, park
states, completion claims, or an event log. Every trusted delivery boundary
runs a fresh `check`.
