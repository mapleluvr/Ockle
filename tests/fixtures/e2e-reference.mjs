import { mkdirSync, writeFileSync } from "node:fs";
import path from "node:path";

function write(repository, relative, content) {
  const target = path.join(repository, relative);
  mkdirSync(path.dirname(target), { recursive: true });
  writeFileSync(target, content, "utf8");
}

export function applyReferenceSolution(repository, scenarioId) {
  if (scenarioId === "methods-chain") {
    write(repository, "src/options.mjs", `import { existsSync, readFileSync } from "node:fs";
import path from "node:path";

const DEFAULTS = Object.freeze({ color: "auto", timeout: 30 });
const COLORS = new Set(["auto", "always", "never"]);

function argument(args, name) {
  const exact = args.indexOf("--" + name);
  if (exact >= 0) return args[exact + 1];
  const prefix = "--" + name + "=";
  const joined = args.find((entry) => entry.startsWith(prefix));
  return joined ? joined.slice(prefix.length) : undefined;
}

function validate(options, source) {
  if (!COLORS.has(options.color)) throw new Error(source + ": unsupported color");
  if (!Number.isInteger(options.timeout) || options.timeout <= 0) throw new Error(source + ": invalid timeout");
  return options;
}

export function resolveOptions(args = []) {
  const configPath = path.join(process.cwd(), ".ocklerc.json");
  let config = {};
  if (existsSync(configPath)) {
    try {
      config = JSON.parse(readFileSync(configPath, "utf8"));
    } catch (error) {
      throw new Error(configPath + ": " + error.message);
    }
    if (!config || Array.isArray(config) || typeof config !== "object") throw new Error(configPath + ": expected an object");
  }
  const color = argument(args, "color") ?? config.color ?? DEFAULTS.color;
  const timeoutText = argument(args, "timeout");
  const timeout = timeoutText === undefined ? (config.timeout ?? DEFAULTS.timeout) : Number(timeoutText);
  return validate({ color, timeout }, configPath);
}
`);
    write(repository, "src/load-env.mjs", `export function normalizeEnvironment(rows) {
  return rows.map((row) => ({ ...row, value: row.value }));
}
`);
    write(repository, "src/copy.mjs", `export function safeClone(value) {
  if (typeof structuredClone === "function") return structuredClone(value);
  return JSON.parse(JSON.stringify(value));
}
`);
    write(repository, "README.md", "# Options CLI\n\nRuntime support: Node >=16. Optional .ocklerc.json values are overridden by CLI flags.\n");
    return;
  }
  if (scenarioId === "compatibility-veto") {
    write(repository, "src/user.mjs", `export function serializeUser(user) {
  const name = user.first + " " + user.last;
  return { id: user.id, name, full_name: name };
}
`);
    write(repository, "README.md", "# User response\n\nRuntime support: Node >=16. New clients use name; published v1 clients retain full_name.\n");
    return;
  }
  if (scenarioId === "authorized-resume") {
    write(repository, "src/levels.mjs", `export const LEVELS = Object.freeze([
  "standard-1", "standard-2", "standard-3", "standard-4",
  "standard-5", "standard-6", "standard-7", "standard-8",
]);

export function summarizeLevels(values) {
  return values.join(",");
}
`);
    const assertions = Array.from({ length: 8 }, (_, index) => `  assert.equal(LEVELS[${index}], "standard-${index + 1}");`).join("\n");
    write(repository, "test/public.test.mjs", `import assert from "node:assert/strict";
import { LEVELS, summarizeLevels } from "../src/levels.mjs";

export async function run() {
${assertions}
  assert.equal(summarizeLevels(LEVELS.slice(0, 2)), "standard-1,standard-2");
}
`);
    write(repository, "README.md", "# Severity levels\n\nRuntime support: Node >=16. Current labels are standard-1 through standard-8.\n");
    return;
  }
  throw new Error(`unknown scenario: ${scenarioId}`);
}
