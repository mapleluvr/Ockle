---
name: receiving-code-review
description: Use when deciding how to act on code review feedback from a person or tool.
---

# Receiving Code Review

Treat a finding as a claim about the change. The reviewer may have found a
real defect without identifying its cause or the right fix.

## Decide what the evidence supports

Check the reported behavior on the revision under review. Often the diff
and a caller settle the question; use a focused example when the outcome
depends on runtime behavior. If you cannot verify the claim, say what is
missing rather than treating it as either confirmed or disproved.

Compare what happens with what callers are entitled to expect. The user's
request, a published interface, or a safety property the feature relies on
can establish that expectation. An existing assertion or a proposed new
one may express it, but may also encode an incidental implementation
detail. Agreement among reviewers is not independent evidence if their
examples all assume the same rule. The user can decide the intended
behavior; a suggested explanation still has to fit the evidence.

Evaluate the remedy separately. Fix a confirmed violation where the
responsibility belongs. For example, if one consumer needs a different
representation, adapt that consumer unless the shared interface is itself
deficient. Check related paths when they share the faulty assumption,
not just because the code looks similar.

## Preserve commitments and act on the result

Declared runtime, platform, and public API support remains in force until
the owner changes it. A newer local test runner is not a reason to raise
the product's minimum version or delete the older-version regression check.
Likewise, no callers found in the repository does not establish that a
public interface is unused. If the suggestion would change a commitment,
explain the trade-off and seek a decision unless the current request
already authorizes it.

Within the requested scope, fix supported findings, explain why others do
not apply, and ask about uncertainty that affects a decision. Hold the
items that depend on that answer; proceed with independent, understood
work. Fixes that are understood separately may share a verification run
when the result still shows which behaviors were checked. Report the change or disagreement with
the evidence that matters. If new evidence overturns your response,
correct it.
