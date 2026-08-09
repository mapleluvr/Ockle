# Ockle

Ockle is a small software-engineering method pack with an experimental mechanical
outer-loop guard.

## Current Release Shape

Three method Skills are implemented:

- `skills/test-driven-development`
- `skills/systematic-debugging`
- `skills/receiving-code-review`

They are loaded by observed engineering phenomena, not as a fixed workflow. Their
handoff is `patch + executable evidence`; they do not maintain plans, phases,
work units, delivery state, or guard protocol.

The first outer-loop vertical slice is implemented separately in `guard/`:

- host-neutral JavaScript API and CLI;
- `assertion-change@1`, a narrow detector for supported changed test assertions;
- `worktree`, staged `index`, and immutable-ref candidates;
- bounded `check / status / details` envelopes;
- exact-input trusted authorization receipts;
- latest-only local snapshot for context-host re-query.

The guard is not a Skill and does not decide whether the user's request is
complete. See [Outer Loop v1](docs/outer-loop-v1/README.md) for the current
runtime contract and [the original authorization](docs/outer-loop-v1/REQUEST.md).

## Test

Requires Node.js 20 or newer.

```sh
npm install
npm test
```

The three Skills remain usable without installing the optional guard package.

## Design History

- [DESIGN.md](DESIGN.md) is the broad historical design draft; several extension
  sections remain unimplemented candidates.
- [FINDINGS.md](FINDINGS.md) is deprecated research history.
- [Magic Context investigation](docs/magic-context-investigation.md) records the
  host continuity investigation that informed the integration boundary.
- [Inner/outer runtime diagrams](docs/diagrams/README.md) visualize the current
  organization and a medium-complexity example.

Ockle's own project license has not yet been selected. Derived upstream material
and its retained notices are documented in
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
