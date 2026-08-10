import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import path from "node:path";
import { PI_VERSION } from "./config.mjs";

export function resolveRuntimePaths({ env = process.env } = {}) {
  const piCli = env.OCKLE_PI_CLI
    ?? (env.APPDATA ? path.join(env.APPDATA, "npm", "node_modules", "@earendil-works", "pi-coding-agent", "dist", "cli.js") : null);
  if (!piCli || !existsSync(piCli)) throw new Error(`Pi CLI not found: ${piCli ?? "no configured path"}`);
  const piPackage = JSON.parse(readFileSync(path.resolve(path.dirname(piCli), "..", "package.json"), "utf8"));
  if (piPackage.version !== PI_VERSION) {
    throw new Error(`Pi version ${piPackage.version} does not match required ${PI_VERSION}`);
  }
  return { piCli: path.resolve(piCli), piVersion: piPackage.version };
}

function removeAmbientExecutionControls(env) {
  const exact = new Set([
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_INDEX_FILE",
    "GIT_OBJECT_DIRECTORY",
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    "GIT_EXTERNAL_DIFF",
    "GIT_DIFF_OPTS",
    "GIT_PAGER",
    "PAGER",
    "LESS",
    "NODE_OPTIONS",
    "NODE_PATH",
    "RIPGREP_CONFIG_PATH",
    "GREP_OPTIONS",
    "MAGIC_CONTEXT_TEST_DATA_DIR",
    "MAGIC_CONTEXT_LOG_PATH",
    "OCKLE_MAGIC_CONTEXT_EXTENSION",
    "OCKLE_MAGIC_CONTEXT_CONFIG",
  ]);
  for (const name of Object.keys(env)) {
    const upper = name.toUpperCase();
    if (exact.has(upper) || upper.startsWith("GIT_CONFIG_") || upper.startsWith("NPM_CONFIG_")) delete env[name];
  }
}

export function createRunEnvironment({
  runRoot,
  repository = null,
  allowedReadRoots = [],
  parentEnv = process.env,
}) {
  const env = { ...parentEnv };
  removeAmbientExecutionControls(env);
  env.GIT_CONFIG_GLOBAL = path.join(runRoot, "control", "gitconfig");
  env.GIT_CONFIG_NOSYSTEM = "1";
  env.NPM_CONFIG_USERCONFIG = path.join(runRoot, "control", "npmrc");
  env.NPM_CONFIG_GLOBALCONFIG = path.join(runRoot, "control", "npmrc");
  env.RIPGREP_CONFIG_PATH = path.join(runRoot, "control", "ripgreprc");
  env.OCKLE_E2E_AUDIT_PATH = path.join(runRoot, "audit.jsonl");
  env.OCKLE_E2E_TEST_AUDIT_PATH = path.join(runRoot, "test-audit.jsonl");
  if (repository) env.OCKLE_E2E_REPOSITORY = repository;
  env.OCKLE_E2E_ALLOWED_READ_ROOTS = JSON.stringify(allowedReadRoots);
  env.PI_OFFLINE = "1";
  env.NO_COLOR = "1";
  env.FORCE_COLOR = "0";
  return env;
}

export function prepareRunDirectories(runRoot) {
  const directories = [
    runRoot,
    path.join(runRoot, "sessions"),
    path.join(runRoot, "trusted"),
    path.join(runRoot, "control"),
  ];
  for (const directory of directories) mkdirSync(directory, { recursive: true });
  for (const name of ["gitconfig", "npmrc", "ripgreprc"]) {
    writeFileSync(path.join(runRoot, "control", name), "", "utf8");
  }
  return {
    sessions: path.join(runRoot, "sessions"),
    audit: path.join(runRoot, "audit.jsonl"),
  };
}
