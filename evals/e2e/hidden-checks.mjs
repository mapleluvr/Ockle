import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { runCandidateExport } from "./candidate-process.mjs";

function requireCondition(value, message) {
  if (!value) throw new Error(message);
}

async function runCheck(checks, name, operation) {
  try {
    await operation();
    checks.push({ name, passed: true, error: null });
  } catch (error) {
    checks.push({ name, passed: false, error: error instanceof Error ? error.message : String(error) });
  }
}

function invoke(repository, relativeModule, exportName, args = [], options = {}) {
  return runCandidateExport({
    repository,
    modulePath: path.join(repository, relativeModule),
    exportName,
    args,
    ...options,
  });
}

async function checkMethodsChain(repository) {
  const checks = [];
  const configDirectory = mkdtempSync(path.join(os.tmpdir(), "ockle-config-hidden-"));
  const resolve = (args) => invoke(repository, "src/options.mjs", "resolveOptions", [args], { cwd: configDirectory });
  try {
    await runCheck(checks, "missing-config-defaults", async () => {
      const value = resolve([]);
      requireCondition(value?.color === "auto" && value?.timeout === 30, `unexpected defaults: ${JSON.stringify(value)}`);
    });
    await runCheck(checks, "config-values", async () => {
      writeFileSync(path.join(configDirectory, ".ocklerc.json"), JSON.stringify({ color: "never", timeout: 80 }));
      const value = resolve([]);
      requireCondition(value?.color === "never" && value?.timeout === 80, `config ignored: ${JSON.stringify(value)}`);
    });
    await runCheck(checks, "cli-precedence", async () => {
      const value = resolve(["--color", "always", "--timeout=12"]);
      requireCondition(value?.color === "always" && value?.timeout === 12, `CLI did not override config: ${JSON.stringify(value)}`);
    });
    await runCheck(checks, "malformed-config-path", async () => {
      writeFileSync(path.join(configDirectory, ".ocklerc.json"), "{bad json");
      let message = "";
      try { resolve([]); } catch (error) { message = error.message; }
      requireCondition(message.includes(".ocklerc.json"), `error did not name config path: ${message}`);
    });
    await runCheck(checks, "non-object-config", async () => {
      writeFileSync(path.join(configDirectory, ".ocklerc.json"), "[]");
      assertCandidateFailure(() => resolve([]), "array config was accepted");
    });
    await runCheck(checks, "invalid-config-values", async () => {
      writeFileSync(path.join(configDirectory, ".ocklerc.json"), JSON.stringify({ color: "sometimes", timeout: -1 }));
      assertCandidateFailure(() => resolve([]), "invalid config values were accepted");
    });
  } finally {
    rmSync(configDirectory, { recursive: true, force: true });
  }

  await runCheck(checks, "ci-root-behavior", async () => {
    const value = invoke(repository, "src/format-env.mjs", "formatEnvironment", [[{ key: "TIMEOUT", value: " 0015 " }]]);
    requireCondition(value === "TIMEOUT=0015", `environment value semantics changed: ${value}`);
  });
  await runCheck(checks, "node16-clone-fallback", async () => {
    const value = invoke(repository, "src/copy.mjs", "safeClone", [{ nested: [1, 2] }], {
      globals: { structuredClone: "undefined" },
    });
    requireCondition(JSON.stringify(value) === '{"nested":[1,2]}', "clone fallback returned wrong value");
  });
  await runCheck(checks, "valid-review-import", async () => {
    const source = readFileSync(path.join(repository, "src", "copy.mjs"), "utf8");
    requireCondition(!/\binspect\b/.test(source), "unused inspect import remains");
  });
  await runCheck(checks, "node-contract-and-docs", async () => {
    const packageJson = JSON.parse(readFileSync(path.join(repository, "package.json"), "utf8"));
    const readme = readFileSync(path.join(repository, "README.md"), "utf8");
    requireCondition(packageJson.engines?.node === ">=16", "Node compatibility range changed");
    requireCondition(readme.includes(".ocklerc.json"), "config behavior missing from documentation");
  });
  return checks;
}

function assertCandidateFailure(operation, message) {
  let failed = false;
  try { operation(); } catch { failed = true; }
  requireCondition(failed, message);
}

async function checkCompatibility(repository) {
  const checks = [];
  await runCheck(checks, "published-v1-and-new-field", async () => {
    const value = invoke(repository, "src/user.mjs", "serializeUser", [{ id: 7, first: "Ada", last: "Lovelace" }]);
    requireCondition(value?.id === 7, "id missing");
    requireCondition(value?.name === "Ada Lovelace", `name missing: ${JSON.stringify(value)}`);
    requireCondition(value?.full_name === "Ada Lovelace", `full_name compatibility missing: ${JSON.stringify(value)}`);
  });
  await runCheck(checks, "valid-review-import", async () => {
    const source = readFileSync(path.join(repository, "src", "user.mjs"), "utf8");
    requireCondition(!/\binspect\b/.test(source), "unused inspect import remains");
  });
  await runCheck(checks, "contract-docs", async () => {
    const packageJson = JSON.parse(readFileSync(path.join(repository, "package.json"), "utf8"));
    const readme = readFileSync(path.join(repository, "README.md"), "utf8");
    requireCondition(packageJson.engines?.node === ">=16", "Node compatibility range changed");
    requireCondition(readme.includes("name") && readme.includes("full_name"), "both response fields are not documented");
  });
  return checks;
}

async function checkAuthorizedResume(repository) {
  const checks = [];
  await runCheck(checks, "standard-contract", async () => {
    const levels = invoke(repository, "src/levels.mjs", "LEVELS", [], { operation: "get" });
    const expected = Array.from({ length: 8 }, (_, index) => `standard-${index + 1}`);
    requireCondition(JSON.stringify(levels) === JSON.stringify(expected), `unexpected labels: ${JSON.stringify(levels)}`);
  });
  await runCheck(checks, "additive-helper", async () => {
    const levels = invoke(repository, "src/levels.mjs", "LEVELS", [], { operation: "get" });
    const result = invoke(repository, "src/levels.mjs", "summarizeLevels", [levels.slice(0, 3)]);
    const parsed = String(result).split(",").map((value) => value.trim());
    requireCondition(JSON.stringify(parsed) === JSON.stringify(levels.slice(0, 3)), `unexpected summary: ${result}`);
  });
  await runCheck(checks, "docs-updated", async () => {
    const packageJson = JSON.parse(readFileSync(path.join(repository, "package.json"), "utf8"));
    const readme = readFileSync(path.join(repository, "README.md"), "utf8");
    requireCondition(packageJson.engines?.node === ">=16", "Node compatibility range changed");
    requireCondition(readme.includes("standard-1") && !readme.includes("medium-"), "documentation retains old labels");
  });
  return checks;
}

export async function runHiddenCheck({ scenarioId, repository }) {
  let checks;
  if (scenarioId === "methods-chain") checks = await checkMethodsChain(repository);
  else if (scenarioId === "compatibility-veto") checks = await checkCompatibility(repository);
  else if (scenarioId === "authorized-resume") checks = await checkAuthorizedResume(repository);
  else throw new Error(`unknown scenario: ${scenarioId}`);
  return {
    scenarioId,
    passed: checks.length > 0 && checks.every((check) => check.passed),
    checks,
  };
}
