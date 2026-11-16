# Editing Tests

These cases adapt observed work in a project with CLI, SQLite, browser,
and installed-artifact tests. They show the conditions behind different
choices, not a sequence to apply to every change. Suggested generalizations
are distinguished from the observed outcomes.

## A behavior changes, but nearby protection remains

A product change allowed input to continue after a model error. Tests that
required the session to reject all later input now conflicted with the
requested behavior. Their expectations needed revision. Protection against
automatically replaying the old request still served a different purpose.

Elsewhere, an HTTP failure was initially attributed to an obsolete usage
limit. Reading the test showed that the assertion protected permissions,
so that explanation was withdrawn. The current task did not make every
nearby refusal obsolete.

The useful edit follows the changed requirement through the test. It does
not preserve an old restriction because it has an assertion, or remove a
valid restriction merely because it fails during related work.

## Several scenarios protect the same restoration behavior

A maintenance suite had 17 top-level CLI scenarios. Consolidation left
10 CLI scenarios and three service-level scenarios. Shared setup was
combined, and an independent corrupted-database scenario was removed
because a corrupted-database plus exited-writer scenario retained its
original-byte preservation assertion.

Process death, interrupted publication, and credential delivery still
needed their distinct real boundaries. A records-only fingerprint check
moved to a real service fixture. A temporary negative control removed its
pending-records guard and made that check fail, confirming that this
particular protection had survived the move.

Moving four scenarios down a layer reduced their measured time from about
354 to 316 seconds, not an order of magnitude. The experiment supported
some savings, not the belief that service tests were automatically cheap.

This case supports consolidation where protection is understood. It does
not require replaying every historic bug before any deletion, or moving
all process tests into services. The negative control answered a specific
question about the proposed edit.

## The test cannot reach the behavior it is supposed to check

Two listener tests tried to bind a fixed local port before checking its
replacement. The host rejected the bind with EACCES. At that point, the
failure said nothing about whether the replacement behavior was correct.
The fixture needed a way to establish its intended condition on that host;
weakening the product assertion would not answer the question.

Other broad runs ended with native Node subprocess exits in different
files and no individual business assertion. Local checks were useful for
investigation, but did not turn the failed broad runs into passes. After
further repetition, the investigation stopped blindly rerunning the full
suite and separated the unknown crash from source-level findings.

Distinguish a broken fixture, an environmental failure, and a product
defect. Each can matter, but each calls for different evidence and edits.

## The default command no longer fits everyday work

In the same project, broad verification runs took tens of minutes. The
revised everyday entrypoint selected a core collection, with explicit
feature groups for affected work and separate entries for broader or
delivery-specific verification. The measured core run covered 17 files and
60 tests in about 43.5 seconds; the consolidated maintenance collection
still took about 13.2 minutes for 13 tests.

This was a change in verification scope, not identical coverage made much
faster. Expensive retained checks remained available when their evidence
was needed. The unaudited remainder stayed available for broad regression,
without being declared permanently valuable merely because it was retained.

The case suggests maintaining runnable selections rather than marking every
non-default test with a permanent skip. When a change affects restoration,
its relevant maintenance tests join the selected checks. When shared
contracts make the impact difficult to bound, a broader run can be needed.
The entrypoints express these relationships so each task does not have to
reconstruct the entire selection from memory. This does not require every
repository to adopt the same group names or counts.

## A useful experiment need not become permanent suite membership

The consolidation work used both a temporary negative control and a
same-host timing comparison. These established whether an assertion could
catch its target mistake and how much a particular change cost at that
time. They were different from tests exercising restoration on future
product revisions.

A subsequent maintenance choice can preserve the measured results and
conditions without scheduling those experiments on every change. Retain
an executable probe when reproducing the question remains valuable; put it
in routine regression when there is a continuing behavior to protect.
This is a suggested retention judgment, not a claim that all the original
experimental files were deleted.
