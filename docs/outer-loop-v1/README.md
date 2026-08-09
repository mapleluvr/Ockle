# Ockle Outer Loop v1

Status: implemented experimental vertical slice

Original authorization: [REQUEST.md](REQUEST.md)

This document is the current authority for the outer-loop v1 implementation.
Earlier candidate documents remain research history and do not override this
runtime contract.

## Boundary

The user request does not move from an inner loop into an outer loop. The context
host retains the request throughout the session.

```text
context host: request, conversation, compression, work continuity
inner Skills: TDD, systematic debugging, receiving review
Ockle guard: current candidate -> mechanical policy verdict
handoff: original request + patch + executable evidence
```

Ockle does not persist the request, a plan, task decomposition, completion state,
or a model summary. `clear` means only that the active guard policy found no
blocking condition for its reported input.

## Implemented Policy

`assertion-change@1` detects removal or behavior-argument rewriting of supported
JavaScript and TypeScript assertions on changed test paths. Its declared binding
domain currently includes Node `assert` (including `assert/strict` and optional
calls), Jest/Vitest `expect`, and Chai named/CommonJS/namespace `expect` and
`assert` forms. It deliberately does not claim to understand all test weakening.
A parse/read/scan failure is `indeterminate + partial`; a base-side parse failure
requires a parser/policy fix or a different trusted base and cannot be authorized
without a reliable finding set.

The implementation lives in `guard/` and exposes one engine through:

```text
check(base, candidate, optional trusted authorization)
status(base, candidate)
details(runId, cursor)
```

`check` is independently usable by an Agent, a local hook, a context host, or
trusted CI. The core Skills do not schedule it or parse its protocol.

## Candidate Kinds

| Boundary | Candidate | Meaning |
| --- | --- | --- |
| Optional early feedback | `worktree` | Current filesystem content |
| Pre-commit | `index` | Exactly the staged content |
| Explicit dirty-worktree handoff | `worktree` | Files being handed off without a commit |
| Pre-push / CI / branch protection | immutable ref | Candidate commit/tree |
| Context rematerialization | same candidate used by latest run | Lightweight `status` identity check |

A pre-commit hook that checks `worktree` is incorrect: split staging can make the
index differ from the filesystem. Ockle therefore provides `candidate: "index"`.
The literal candidate names `worktree` and `index` are reserved and cannot also
name refs through this interface.

Local hooks are feedback, not a security boundary. An Agent with the same OS
identity can bypass or replace them. Final veto requires trusted CI to install
Ockle from a trusted source and run it against a trusted base and immutable
candidate ref.

Ockle v1 supplies the machine interface and integration contract; it does not
silently install hooks or repository-specific CI.

## Input Identity

A check resolves the base and immutable candidate refs once, obtains Git's
changed path set with rename detection disabled, and keeps only paths inside the
policy's declared test-source domain. It reads each relevant base/candidate
source into a snapshot.

The same exact source bytes are used for:

1. the policy-input digest;
2. AST extraction;
3. trusted authorization matching.

Worktree and index snapshots are recaptured before the verdict is returned. A
concurrent relevant mutation produces `indeterminate`, never stale `clear`.
Staging and committing identical supported test content preserve the digest;
changing relevant source bytes, the base tree, or the policy invalidates it.
Production files and context-host artifacts are intentionally outside this
policy input because they cannot change `assertion-change@1`'s verdict.

## Context-Control Cooperation

A Magic Context-like host owns compression and recovery. It may call `status`
when context is materialized:

```text
matching blocked / indeterminate -> re-inject the bounded envelope
matching clear                   -> usually inject nothing
stale or missing                 -> inject unchecked
```

`status` recalculates the policy-input identity but does not rerun AST
extraction. The latest full result is stored under Git metadata solely to support
that lookup and `details` pagination. It is locally mutable, latest-only, and
never acceptable as CI evidence. Every delivery boundary performs a fresh
`check`.

`details` exposes another bounded page from that latest run. `coverage` reports
scan completeness; `total`, `returned`, and `nextCursor` report pagination.
There is no ambiguous `truncated` flag. Oversized paths are represented by an
advancing bounded summary with `fileTruncated: true`.

## Trusted Authorization

A legitimate contract change can intentionally rewrite an assertion. It first
returns `blocked`. A trusted host may then provide a receipt bound to:

- policy ID and version;
- exact policy-input digest;
- explicit finding IDs;
- bounded authority identity.

Partial, stale, malformed, unknown-finding, already-clear, or
incomplete-coverage receipts fail closed. The guard validates receipt scope, not
provenance. Trusted CI must obtain the receipt from a protected channel; an
Agent-authored file is not authority. For a commit authorization, stage the
intended candidate and issue the receipt against `candidate: "index"`: exact-byte
identity means Git clean filters or CRLF normalization may invalidate an earlier
worktree receipt. The receipt authorizes only those findings, not the entire
patch or completion of the user request.

## State That Does Not Exist

Ockle v1 has no:

- outer-loop Skill or router;
- request/scope/phase/target object;
- append-only workflow event log;
- task progress or completion projection;
- model-created approval path;
- full transcript or context-compression subsystem.

Its only persisted object is the latest mechanical guard result for bounded
re-query.

## Verification

Deterministic checks:

```sh
npm test
```

Behavior evaluation uses isolated real repositories and
`Mapleluv/deepseek-v4-flash:max`. The grader reads final Git state, diff, tests,
hidden behavior checks, and a guard installed outside the candidate workspace.
Model self-reports do not enter scoring. See [EVALUATION.md](EVALUATION.md).
Independent taste, over-engineering, and closure findings are consolidated in
[REVIEW.md](REVIEW.md).

## Superseded Candidate Statements

The following earlier statements remain useful research constraints but are not
the current implementation contract:

- `docs/outer-loop-baseline.md`: pre-investigation candidate, explicitly not
  implementation authorization;
- `docs/magic-context-investigation.md`: “stateless” means no durable workflow or
  delivery state. v1 later received explicit authorization for one latest-only,
  non-authoritative mechanical snapshot so a context host can call `status`;
- `DESIGN.md`: broad candidate design containing unimplemented SDD,
  unattended-delivery, events, and recovery projection.
