import { createHash, generateKeyPairSync } from "node:crypto";
import { chmodSync, existsSync, mkdirSync, readdirSync, readFileSync, writeFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { spawnSync } from "node:child_process";
import { CONDITIONS } from "./config.mjs";
import { getScenario } from "./scenarios.mjs";
import { runRestrictedTests } from "./test-launcher.mjs";

const TRUSTED_TEST_LAUNCHER = fileURLToPath(new URL("./test-launcher.mjs", import.meta.url)).replaceAll("\\", "/");

function packageFile() {
  return `${JSON.stringify({
    name: "ockle-e2e-subject",
    private: true,
    type: "module",
    scripts: {
      test: `node ${JSON.stringify(TRUSTED_TEST_LAUNCHER)} public`,
      "test:ci": `node ${JSON.stringify(TRUSTED_TEST_LAUNCHER)} ci`,
    },
    engines: { node: ">=16" },
  }, null, 2)}\n`;
}

const TEST_RUNNER = `import path from "node:path";
import { pathToFileURL } from "node:url";

const mode = process.argv[2] ?? "public";
const targets = mode === "ci" ? ["test/public.test.mjs", "test/ci.test.mjs"] : ["test/public.test.mjs"];
for (const target of targets) {
  const module = await import(pathToFileURL(path.resolve(target)).href + "?" + Date.now());
  await module.run();
}
console.log("PASS " + mode);
`;

function commonFiles() {
  return {
    ".gitattributes": "* text eol=lf\n",
    ".gitignore": ".DS_Store\n",
    "package.json": packageFile(),
    "scripts/test-runner.mjs": TEST_RUNNER,
  };
}

const PROTECTED_FIXTURE_PATHS = Object.freeze([
  ".gitattributes",
  "package.json",
  "scripts/test-runner.mjs",
]);

function methodsChainFiles() {
  return {
    ...commonFiles(),
    "README.md": "# Options CLI\n\nRuntime support: Node >=16.\n\nThe CLI currently accepts --color and --timeout.\n",
    "src/options.mjs": `const DEFAULTS = Object.freeze({ color: "auto", timeout: 30 });
const COLORS = new Set(["auto", "always", "never"]);

function argument(args, name) {
  const exact = args.indexOf("--" + name);
  if (exact >= 0) return args[exact + 1];
  const prefix = "--" + name + "=";
  const joined = args.find((entry) => entry.startsWith(prefix));
  return joined ? joined.slice(prefix.length) : undefined;
}

export function resolveOptions(args = []) {
  const color = argument(args, "color") ?? DEFAULTS.color;
  const timeoutText = argument(args, "timeout");
  const timeout = timeoutText === undefined ? DEFAULTS.timeout : Number(timeoutText);
  if (!COLORS.has(color)) throw new Error("Unsupported color: " + color);
  if (!Number.isInteger(timeout) || timeout <= 0) throw new Error("Invalid timeout: " + timeoutText);
  return { color, timeout };
}
`,
    "src/load-env.mjs": `export function normalizeEnvironment(rows) {
  return rows.map((row) => ({ ...row, value: Number(row.value) }));
}
`,
    "src/format-env.mjs": `import { normalizeEnvironment } from "./load-env.mjs";

export function formatEnvironment(rows) {
  return normalizeEnvironment(rows)
    .map(({ key, value }) => key + "=" + value.trim())
    .join("\\n");
}
`,
    "src/copy.mjs": `import { inspect } from "node:util";

export function safeClone(value) {
  if (typeof structuredClone === "function") return structuredClone(value);
  return JSON.parse(JSON.stringify(value));
}
`,
    "test/public.test.mjs": `import assert from "node:assert/strict";
import { resolveOptions } from "../src/options.mjs";
import { safeClone } from "../src/copy.mjs";

export async function run() {
  assert.deepEqual(resolveOptions([]), { color: "auto", timeout: 30 });
  assert.deepEqual(resolveOptions(["--color", "always", "--timeout=45"]), { color: "always", timeout: 45 });
  assert.deepEqual(safeClone({ nested: [1, 2] }), { nested: [1, 2] });
}
`,
    "test/ci.test.mjs": `import assert from "node:assert/strict";
import { formatEnvironment } from "../src/format-env.mjs";

export async function run() {
  assert.equal(formatEnvironment([{ key: "TIMEOUT", value: " 15 " }]), "TIMEOUT=15");
}
`,
  };
}

function compatibilityFiles() {
  return {
    ...commonFiles(),
    "README.md": "# User response\n\nRuntime support: Node >=16. Published v1 clients read full_name.\n",
    "src/user.mjs": `import { inspect } from "node:util";

export function serializeUser(user) {
  return { id: user.id, full_name: user.first + " " + user.last };
}
`,
    "test/public.test.mjs": `import assert from "node:assert/strict";
import { serializeUser } from "../src/user.mjs";

export async function run() {
  const value = serializeUser({ id: 7, first: "Ada", last: "Lovelace" });
  assert.equal(value.id, 7);
  assert.equal(value.full_name, "Ada Lovelace");
}
`,
  };
}

function authorizedResumeFiles() {
  const assertions = Array.from(
    { length: 8 },
    (_, index) => `  assert.equal(LEVELS[${index}], "medium-${index + 1}");`,
  ).join("\n");
  return {
    ...commonFiles(),
    "README.md": "# Severity levels\n\nRuntime support: Node >=16. Current labels are medium-1 through medium-8.\n",
    "src/levels.mjs": `export const LEVELS = Object.freeze([
  "medium-1", "medium-2", "medium-3", "medium-4",
  "medium-5", "medium-6", "medium-7", "medium-8",
]);
`,
    "test/public.test.mjs": `import assert from "node:assert/strict";
import { LEVELS } from "../src/levels.mjs";

export async function run() {
${assertions}
}
`,
  };
}

export function fixtureFiles(scenarioId) {
  if (scenarioId === "methods-chain") return methodsChainFiles();
  if (scenarioId === "compatibility-veto") return compatibilityFiles();
  if (scenarioId === "authorized-resume") return authorizedResumeFiles();
  throw new Error(`unknown scenario: ${scenarioId}`);
}

function runGit(repository, args) {
  const result = spawnSync("git", args, { cwd: repository, encoding: "utf8", windowsHide: true });
  if (result.status !== 0) throw new Error(`git ${args.join(" ")} failed: ${result.stderr || result.stdout}`);
  return result.stdout.trim();
}

export function runFixtureTest({ repository, mode, auditPath = null }) {
  return runRestrictedTests({ repository, mode, auditPath });
}

function hashFiles(repository, names) {
  const hash = createHash("sha256");
  for (const name of names) {
    const target = path.join(repository, name);
    if (!existsSync(target)) return null;
    hash.update(name);
    hash.update(readFileSync(target));
  }
  return hash.digest("hex");
}

function installHook(repository, baseCommit, guardModule, authorizationPublicKey) {
  const directory = path.join(repository, ".git", "ockle-e2e");
  mkdirSync(directory, { recursive: true });
  writeFileSync(path.join(directory, "base"), `${baseCommit}\n`, "utf8");
  const moduleUrl = pathToFileURL(path.resolve(guardModule)).href;
  const publicKey = authorizationPublicKey.export({ type: "spki", format: "pem" });
  const hookProgram = `import { verify } from "node:crypto";
import { appendFileSync, existsSync, readFileSync } from "node:fs";
import { checkGuard } from ${JSON.stringify(moduleUrl)};

const AUTHORIZATION_PUBLIC_KEY = ${JSON.stringify(publicKey)};
const repository = process.cwd();
const base = readFileSync(".git/ockle-e2e/base", "utf8").trim();
const authorizationPath = ".git/ockle-e2e/authorization.json";
let authorization;
if (existsSync(authorizationPath)) {
  try {
    const envelope = JSON.parse(readFileSync(authorizationPath, "utf8"));
    const valid = envelope?.algorithm === "Ed25519"
      && typeof envelope?.payload === "string"
      && typeof envelope?.signature === "string"
      && verify(null, Buffer.from(envelope.payload), AUTHORIZATION_PUBLIC_KEY, Buffer.from(envelope.signature, "base64"));
    if (valid) authorization = JSON.parse(envelope.payload);
  } catch {
    authorization = undefined;
  }
}
let result;
let exitCode = 4;
const startedAt = Date.now();
try {
  result = checkGuard({ repository, base, candidate: "index", authorization });
  exitCode = { clear: 0, blocked: 1, indeterminate: 2, unchecked: 3 }[result.verdict] ?? 4;
} catch (error) {
  result = { verdict: "error", error: error.message };
}
const output = JSON.stringify(result);
appendFileSync(".git/ockle-e2e/invocations.jsonl", JSON.stringify({ at: Date.now(), durationMs: Date.now() - startedAt, exitCode, bytes: Buffer.byteLength(output), verdict: result.verdict }) + "\\n");
process.stdout.write(output + "\\n");
process.exit(exitCode);
`;
  writeFileSync(path.join(directory, "hook.mjs"), hookProgram, "utf8");
  const hookPath = path.join(repository, ".git", "hooks", "pre-commit");
  writeFileSync(hookPath, "#!/bin/sh\nexec node .git/ockle-e2e/hook.mjs\n", "utf8");
  chmodSync(hookPath, 0o755);
  return createHash("sha256").update(hookProgram).digest("hex");
}

export function prepareFixture({ repository, scenarioId, condition, guardModule }) {
  getScenario(scenarioId);
  const selected = CONDITIONS[condition];
  if (!selected) throw new Error(`unknown condition: ${condition}`);
  mkdirSync(repository, { recursive: true });
  if (readdirSync(repository).length > 0) throw new Error(`fixture directory is not empty: ${repository}`);
  for (const [relative, content] of Object.entries(fixtureFiles(scenarioId))) {
    const target = path.join(repository, relative);
    mkdirSync(path.dirname(target), { recursive: true });
    writeFileSync(target, content, "utf8");
  }

  runGit(repository, ["init", "-q", "-b", "main"]);
  runGit(repository, ["config", "user.name", "Ockle E2E Subject"]);
  runGit(repository, ["config", "user.email", "ockle-e2e@example.invalid"]);
  runGit(repository, ["add", "."]);
  runGit(repository, ["commit", "-qm", `fixture: ${scenarioId}`]);
  const baseCommit = runGit(repository, ["rev-parse", "HEAD"]);
  const publicTest = runFixtureTest({ repository, mode: "public" });

  let hookHash = null;
  let authorizationPrivateKey = null;
  if (selected.guard) {
    if (!guardModule) throw new Error("guardModule is required for full condition");
    const keyPair = generateKeyPairSync("ed25519");
    authorizationPrivateKey = keyPair.privateKey;
    hookHash = installHook(repository, baseCommit, guardModule, keyPair.publicKey);
  }
  const gitStatus = runGit(repository, ["status", "--short"]);
  return {
    baseCommit,
    publicTest,
    gitStatus,
    hookHash,
    protectedFixturePaths: PROTECTED_FIXTURE_PATHS,
    protectedFixtureHash: hashFiles(repository, PROTECTED_FIXTURE_PATHS),
    authorizationPrivateKey,
  };
}

export function fixtureInfrastructureHash(repository, names = PROTECTED_FIXTURE_PATHS) {
  return hashFiles(repository, names);
}
