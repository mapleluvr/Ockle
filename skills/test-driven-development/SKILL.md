---
name: test-driven-development
description: Use when adding or changing executable behavior, or repairing a regression; develop examples and focused tests to guide implementation.
---

# Test-Driven Development

Use executable examples to develop behavior and check the implementation.
A test-first cycle is especially useful when the desired behavior is clear
or a bug has a reproducible failure. Follow explicit test-first and
verification requirements from the user or repository.

## Develop the behavior

Organize tests around a feature's observable behavior at a stable consumer
boundary, not around the list of functions changed to implement it.
Use an existing check when it already captures the requirement; add or
extend one when it does not. Derive the expected result from the agreed
behavior, rather than copying what the implementation happens to return.

Run the focused check. A failure helps when it exposes the intended
difference: an accepted input is rejected, a result is wrong, or an effect
is missing. A setup error needs a different investigation. If the check
already passes, determine whether the behavior is already present or the
example misses the proposed change.

Implement the required behavior, using the example to get feedback. Keep
the change coherent with the requirement, not merely with the particular
test inputs. Re-run the affected checks and improve the structure where
that helps. Related examples can share a run; results should still reveal
which behaviors were exercised and what failed.

## Let examples and implementation inform each other

When an interface or behavior is still taking shape, a small prototype,
call experiment, or implementation sketch can reveal useful relationships.
Develop or discard it according to what it contributes and how it can be
verified. Existing-behavior characterization and refactoring checks may
start green; their purpose differs from reproducing a missing behavior.

Tests can also contain mistaken assumptions. Revisit expectations when new
information changes their basis, while preserving current user and
repository contracts unless a change to them has been authorized.
A failing example identifies a difference, not which side must be right.

## Choose verification for the change

Use the repository's supported test entrypoints and select the affected
behaviors. Shared contracts, uncertain impact, or release requirements may
call for broader regression. Investigate failures according to their
source rather than repeating the whole suite without a useful question.
Report the checks actually run and their results and limitations.

For test design, doubles, and ongoing maintenance, see
[Writing Good Tests](writing-good-tests.md). For concrete choices when
revising existing tests, see [Editing Tests](editing-tests.md).
