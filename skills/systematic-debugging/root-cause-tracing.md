# Root Cause Tracing

Use backward tracing when a failure is visible at a consumer but you do not
yet know how the value, event, or state reached it. Start with the failing
operation and its actual input. Follow the relevant caller, producer, or
stored record until you can explain the difference from a working case.
For asynchronous work, the producer may not appear on the failing stack;
correlate the operation with its originating request or state transition.

For example, a test initialized a repository in the source tree rather
than in its temporary directory. Tracing the target directory back through
workspace creation showed that the fixture's path had been read *before*
setup assigned it. Inspecting the path after setup would miss the defect.
Make the path available at the right time, or fail clearly on premature
access. Verify in an isolated directory that initialization now affects the
intended location and leaves the original location alone.

That trace explains this incident; it does not decide what every caller
must validate. If the public operation also promises to reject an invalid
target, check that promise on its own terms. If the next link in a trace
is unknown, a temporary observation on either side of the handoff can be
more useful than logging the entire stack and environment.

For an unexpected file left by tests, [find-polluter.sh](find-polluter.sh)
tries matching test files individually. Use it in a disposable copy with
an initially absent target and a test command that honors the file filter.
It checks whether the target appeared, not whether the tests passed. If
the failure requires a particular order, preserve that order when reducing
the reproducer instead.
