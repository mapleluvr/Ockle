---
name: systematic-debugging
description: Use when investigating a bug, a failing check, or unexpected runtime, build, or performance behavior.
---

# Systematic Debugging

Start from the failure you have: what happened, under which conditions,
and what was expected instead. Keep the original error or measurement.
Check that the expectation still applies and that the observation reached
the behavior in question. A listener test that fails to bind its port has
not yet exercised listener replacement.

## Choose an observation that distinguishes causes

If a failing example and the relevant code already explain the failure,
make the correction and verify it. Otherwise, use the uncertainty to
choose the next step. Compare a working and failing input on the same
revision, follow a suspect value to its producer, or observe the boundary
where two explanations predict different results. Use existing evidence
before adding a probe. If a parser rejects the same input only in CI,
compare the parser version and options used in each run before changing
its logic. Record only the state needed for the distinction; a credential's
presence can be checked without exposing its value.

A reversible change can be a useful experiment. Know what result would
support or weaken the explanation, and keep unrelated changes out of that
comparison. If the result is surprising, check that the fixture, clock, or
measurement captured what you thought it did. A failed prediction narrows
the investigation; it need not send you back to the beginning. Reconsider
the design when evidence points to misplaced responsibility or incompatible
requirements, not because a certain number of attempts failed.

## Repair and verify the affected behavior

Correct the component responsible for the violated requirement. The trigger,
the place that reports the error, and the place that should change can be
different. When setup is wrong, repair setup and exercise the original
behavior; when the expected result is wrong, establish its basis before
changing the assertion. Preserve checks for commitments that still apply.

Re-run the original case under comparable conditions where possible, then
check affected consumers and any required delivery checks. Reuse an existing
regression test or add one at a stable consumer boundary when it protects
a continuing behavior. Use `test-driven-development` for designing or
revising those tests. Keep enough evidence to explain the result; remove
temporary probes unless there is a continuing diagnostic need worth
supporting. For intermittent failures, report the conditions and extent
of the rerun; one passing attempt does not show the cause is gone.

An authorized rollback or other containment can be appropriate before the
cause is known. Verify what it restored. If diagnosis remains open, say
what the evidence rules out and what observation would help next. Do not
report containment or an unrelated green run as a verified repair.

## Techniques for particular questions

- [Root cause tracing](root-cause-tracing.md): where did the unexpected value or state come from?
- [Defense in depth](defense-in-depth.md): which operation needs protection, and where can it be enforced?
- [Condition-based waiting](condition-based-waiting.md): what signal shows that this operation is ready?
