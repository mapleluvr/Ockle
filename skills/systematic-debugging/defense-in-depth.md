# Defense in Depth

Start with the effect that must not occur and the component responsible
for preventing it. Place protection where the decision can be made with
the necessary information and where it still governs the effect. Preserve
existing security and compatibility commitments while evaluating a change.

Consider an import started from an interactive form or a scheduled job.
The form can reject invalid input early for the user's benefit. The service
that accepts imports from both sources must still enforce its own input
contract. Copying the same predicate into every function between the form
and the service adds no protection against the scheduled input. A distinct
entry, trust boundary, or change in the state used for the decision can
justify another check; explain what failure that check would prevent.

For access decisions, identify the resource, the operation and the point
at which authorization is promised. Serving a snapshot already obtained
and reading fresh protected data are different operations. If revocation
must take effect before delivery, preserve that guarantee. If the contract
only specifies authorization at acquisition, a second check on delivery
would change observable behavior; decide that policy explicitly rather
than introducing it as a side effect of fixing a bug.

Verify the protection through the paths that rely on it, including that
valid work still succeeds. A test double that omits the real check may
need correction as a fixture; by itself it says nothing about a production
entry. Logs help explain what happened, but do not prevent the effect.
