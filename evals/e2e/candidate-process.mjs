import { realpathSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { spawnSync } from "node:child_process";

const WORKER = fileURLToPath(new URL("./candidate-worker.mjs", import.meta.url));

function canonical(value) {
  return realpathSync.native(path.resolve(value));
}

function within(candidate, root) {
  const relative = path.relative(root, candidate);
  return relative === "" || (!relative.startsWith("..") && !path.isAbsolute(relative));
}

function permissionArgument(name, value) {
  return `--${name}=${value}`;
}

function sanitizedEnvironment(cwd) {
  const env = {
    NO_COLOR: "1",
    TEMP: cwd,
    TMP: cwd,
    TZ: "UTC",
  };
  for (const name of ["SystemRoot", "WINDIR"]) {
    if (typeof process.env[name] === "string") env[name] = process.env[name];
  }
  return env;
}

export function runCandidateExport({
  repository,
  modulePath,
  exportName,
  args = [],
  cwd = repository,
  operation = "call",
  globals = {},
  timeoutMs = 30000,
}) {
  const root = canonical(repository);
  const sourceRoot = canonical(path.join(root, "src"));
  const target = canonical(modulePath);
  const workingDirectory = canonical(cwd);
  if (!within(target, sourceRoot)) throw new Error(`candidate module is outside src: ${target}`);
  if (!new Set(["call", "get"]).has(operation)) throw new Error(`unsupported candidate operation: ${operation}`);
  if (typeof exportName !== "string" || exportName.length === 0) throw new Error("candidate exportName is required");

  const readRoots = new Set([sourceRoot]);
  if (!within(workingDirectory, root)) readRoots.add(workingDirectory);
  const result = spawnSync(process.execPath, [
    "--permission",
    ...[...readRoots].map((value) => permissionArgument("allow-fs-read", value)),
    WORKER,
  ], {
    cwd: workingDirectory,
    env: sanitizedEnvironment(workingDirectory),
    input: JSON.stringify({ modulePath: target, exportName, args, cwd: workingDirectory, operation, globals }),
    encoding: "utf8",
    windowsHide: true,
    timeout: timeoutMs,
    maxBuffer: 1024 * 1024,
  });
  if (result.error) throw result.error;
  if (result.signal) throw new Error(`candidate process terminated by ${result.signal}`);
  if (result.status !== 0) throw new Error(`candidate process exited ${result.status}: ${result.stderr.trim()}`);
  const lines = result.stdout.split("\n").map((line) => line.trim()).filter(Boolean);
  let response;
  try {
    response = JSON.parse(lines.at(-1) ?? "");
  } catch {
    throw new Error(`candidate process returned invalid protocol output: ${result.stdout.slice(-512)}`);
  }
  if (response?.ok !== true) {
    const detail = response?.error ?? {};
    const error = new Error(`${detail.code ? `${detail.code}: ` : ""}${detail.message ?? "candidate operation failed"}`);
    if (detail.code) error.code = detail.code;
    throw error;
  }
  return response.value;
}
