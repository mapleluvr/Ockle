# Condition-Based Waiting

When a test needs work to finish, wait for evidence of completion from
that operation. An acknowledged write may establish acceptance but not
visibility to a reader. If visibility is the behavior under test, observe
the reader rather than sleeping for an estimated write duration.

Use a completion promise or event if it represents the condition you need.
For a transient event, subscribe before starting the action and match the
operation so an old or unrelated completion cannot satisfy the wait. When
only state is observable, read fresh state on each poll. Bound the wait
and report the expected condition and last relevant observation on timeout.
Choose the interval for the cost of the check and the expected change;
there is no universal polling frequency.

If time itself is the contract, eventual success is not enough. For a
debounce, for example, check that the effect has not fired before the
interval and does fire when due. A controlled clock helps when it drives
the behavior being tested; use a real clock when the real scheduling
boundary matters.

[The event-waiting example](condition-based-waiting-example.ts) illustrates
polling an event history by type, count, or predicate. Its intervals and
timeouts are choices for that fixture, not defaults for other systems.
