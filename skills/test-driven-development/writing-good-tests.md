# Writing Good Tests

Use this reference to design checks, choose test boundaries and doubles,
or reconsider tests affected by current work.

## Establish what the test can tell you

A useful test distinguishes behavior that matters from a plausible wrong
result. Ask what mistake it would reveal and why the expected result is
right. A requirement, a compatibility promise, and a temporary design
hypothesis have different authority; writing an assertion does not erase
that difference.

Derive expectations independently of the code being checked. Literal
values and hand-checked fixtures often make this clear. Independently
justified properties or reference results can cover cases where individual
examples are insufficient. Computing both expected and actual values with
the same production helper can hide the very defect under investigation.

Assert through meaningful consumer-visible behavior, not one test per
function. Straightforward constructors, getters, constants, and forwarding
code are covered through the first consumer-visible result that depends
on them. A focused lower-level check can help when it protects a distinct
rule or makes a relevant failure easier to exercise and diagnose.

Exact values or structure are useful when they are the contract, such as
a wire format or a documented default. Private arrangement or incidental
wording should not acquire a compatibility promise merely because a test
records it. Use related assertions or table cases where they describe one
behavior; split checks when the distinction helps diagnosis or isolation.

Structural checks can verify metadata, schemas, or resolvable references.
They do not establish runtime behavior. To check a script's effects, run
it; to assess instructions for an agent, observe the consuming agent on
relevant work. Existing framework guarantees usually need no duplicate
tests, but your registration, configuration, or integration may.

## Choose a sufficient boundary

A feature-level testing goal does not require every check to run the full
application. Keep the behavior under examination real. The needed boundary
depends on the failure: a component may establish input handling, while
process startup, permission propagation, or consumption of an installed
artifact may require an integration or end-to-end check.

Use doubles for dependencies whose real execution is unnecessary or
impractical for that question. Preserve the data and effects the tested
behavior depends on. A fake that swallows a configuration write cannot
establish behavior that later reads that configuration. Assertions about
arguments, order, or call counts are useful when they express your
component's obligations; merely proving that a mock exists is not.

Use valid, representative fixtures for the interface under test. Include
fields and interactions needed by its consumers, and model omitted or
malformed values deliberately when those are the subject of the check.
Copying every field of an external system is not itself better coverage.

When setup becomes hard to understand, reconsider the boundary and fixture
before adding more scaffolding. A smaller real component, a shared fixture,
or a narrow double may be better than either an elaborate mock or another
full-stack test. Measure costly alternatives rather than assuming a lower
layer will be cheap.

Test-specific controls and cleanup belong in test utilities. A production
component that owns resources may still need a genuine lifecycle API;
judge that responsibility rather than only counting its current callers.

## Maintain a growing suite

Revisit affected tests when requirements change, fixtures become misleading,
coverage overlaps, or feedback becomes costly. Use representative timings
and recurring failures to locate the expensive or confusing parts. Consider
what a test proves now, whether that proof is worth retaining, and when it
needs to run. Work on the relevant collection rather than auditing every
test on every turn.

**Group for use.** Use existing directories, tags, runner filters, or scripts
to give common work a suitable entrypoint. A small everyday set, affected
feature groups, and broader or delivery-specific checks can serve different
questions. Choose groups from the actual dependencies and costs, not just
unit/integration/E2E labels. Changes to shared contracts or uncertain impact
may need broader selection. Keep retained tests discoverable and runnable;
new files should not silently fall outside every selection path.

**Reduce duplicated work.** Combine repeated setup where isolation permits,
use table cases for related inputs, and remove overlapping scenarios whose
useful assertions are covered elsewhere. Move condition combinations to a
smaller real boundary when it can establish them, while retaining the
cross-layer or process cases with distinct value. Preserve useful failure
localization; one giant scenario is not necessarily cheaper to maintain.
For important coverage whose survival is unclear, a targeted negative
control can check that the relevant mistake is still caught. Measure the
result rather than using fewer files or assertions as evidence of savings.

**Make exclusions intentional.** A valuable but expensive test can remain
outside the everyday set and run through a documented affected-change,
release, or explicit command. That is an execution choice, not a claim that
the test has passed, and usually does not need a permanent source-level
skip. An environment-specific test can skip where its prerequisite does
not apply, while remaining runnable in the intended environment.

A broken fixture or flaky test may need temporary isolation or an explicit
skip while it is investigated. Keep the reason, unresolved failure, and
condition for restoring it visible in the existing test or issue record;
retain a way to reproduce it. If that check is required for the current
delivery, its exclusion remains a verification gap. When the requirement
has ended or coverage is genuinely redundant, revise or remove the test
rather than leaving it indefinitely skipped. Cost, age, or recent passes
alone do not decide whether a test is obsolete.

**Check the resulting entrypoints.** Inspect what each changed selection
includes and excludes, and run the checks needed to validate the test edits
and runner changes. Confirm that important remaining assertions still work
and that groups select the intended tests. Put durable selection choices
in existing runner configuration or test guidance, not a new per-test
ledger. One-off probes may leave useful results and conditions without
becoming routine suite members.

[Editing Tests](editing-tests.md) illustrates these choices. Maintain these
arrangements as relevant work exposes a need; they are not extra phases of
every TDD cycle. Preserve unresolved failures and distinguish unexecuted
coverage from passing results.
