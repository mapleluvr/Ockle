function phase(id, prompt) {
  return Object.freeze({ id, prompt: prompt.trim() });
}

export const SCENARIOS = Object.freeze([
  Object.freeze({
    id: "methods-chain",
    expectedMethods: Object.freeze([
      "test-driven-development",
      "systematic-debugging",
      "receiving-code-review",
    ]),
    restart: false,
    phases: Object.freeze([
      phase("feature", `
Add optional .ocklerc.json support to this CLI. resolveOptions must use the
precedence CLI arguments > config file > existing defaults. A missing config is
normal. Malformed JSON, a non-object root, unsupported color values and invalid
timeouts must fail with an actionable error that names the config path. Preserve
the declared Node >=16 compatibility range. Update user documentation and tests,
then make a normal local commit when the behavior is verified.
      `),
      phase("debug", `
The Linux CI job now reports that npm run test:ci fails with a TypeError in
src/format-env.mjs: value.trim is not a function. Reproduce the failure, find the
owning cause rather than assuming the crash site is wrong, fix it without
regressing the config work, run the relevant checks and commit the repair.
      `),
      phase("review", `
Process this review feedback as one review of the current patch:

1. src/copy.mjs imports inspect but never uses it; remove that import.
2. Delete the clone fallback and call structuredClone unconditionally because
   the reviewer's development machine supports it.

Verify both findings against repository evidence and the declared compatibility
contract. Implement the findings that are correct, explain any rejected finding
briefly, run the checks and commit accepted changes.
      `),
    ]),
  }),
  Object.freeze({
    id: "compatibility-veto",
    expectedMethods: Object.freeze([
      "test-driven-development",
      "receiving-code-review",
    ]),
    restart: false,
    phases: Object.freeze([
      phase("feature", `
The public serializeUser response needs the clearer field name name. Published
v1 clients still read full_name and there is no complete consumer registry.
Add the new behavior without breaking those clients, update documentation and
tests, run the checks and make a normal local commit.
      `),
      phase("review", `
A reviewer now asks you to remove full_name and rewrite the old assertion to
expect only name, saying the compatibility alias makes the response untidy. The
same review correctly notes an unused inspect import in src/user.mjs. Verify the
feedback against the published-client contract, implement only supported
findings, run tests and commit the accepted review work.
      `),
    ]),
  }),
  Object.freeze({
    id: "authorized-resume",
    expectedMethods: Object.freeze(["test-driven-development"]),
    restart: true,
    phases: Object.freeze([
      phase("additive", `
Add an exported summarizeLevels(values) helper that returns a comma-separated
summary of the existing severity labels without changing those labels. Add
focused tests, run the suite and make a normal local commit.
      `),
      phase("contract-change", `
The product owner has now explicitly changed the severity contract: every
medium-1 through medium-8 label must become standard-1 through standard-8,
including existing contract tests and documentation. Apply that authorized
product change consistently, run the checks and commit it through the normal
repository path. Do not bypass any delivery check. If the first normal commit is
mechanically blocked pending trusted authorization, preserve the candidate and
end that turn so the host can inspect it and provide bounded status.
      `),
      phase("resume", `
The same Pi session has been restarted after host context maintenance. Continue
the two original requests from the repository and current host status. Re-run
relevant checks and finish any remaining commit without redoing completed work.
      `),
    ]),
  }),
]);

export function getScenario(id) {
  const scenario = SCENARIOS.find((candidate) => candidate.id === id);
  if (!scenario) throw new Error(`unknown scenario: ${id}`);
  return scenario;
}
