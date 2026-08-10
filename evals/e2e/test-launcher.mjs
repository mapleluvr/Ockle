#!/usr/bin/env node
import { spawnSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

function sanitizedEnvironment(cwd, auditPath) {
  const env = { NO_COLOR: "1", TEMP: cwd, TMP: cwd };
  for (const name of ["SystemRoot", "WINDIR"]) {
    if (typeof process.env[name] === "string") env[name] = process.env[name];
  }
  if (auditPath) env.OCKLE_E2E_TEST_AUDIT_PATH = auditPath;
  return env;
}

export function runRestrictedTests({ repository, mode, auditPath = null, timeoutMs = 60000 }) {
  if (!new Set(["public", "ci"]).has(mode)) throw new Error(`unsupported test mode: ${mode}`);
  const root = path.resolve(repository);
  const args = [
    "--permission",
    ...["src", "test", "scripts"].map((value) => `--allow-fs-read=${path.join(root, value)}`),
    `--allow-fs-read=${path.join(root, ".ocklerc.json")}`,
  ];
  if (auditPath) args.push(`--allow-fs-write=${path.resolve(auditPath)}`);
  args.push(path.join(root, "scripts", "test-runner.mjs"), mode);
  const result = spawnSync(process.execPath, args, {
    cwd: root,
    env: sanitizedEnvironment(root, auditPath ? path.resolve(auditPath) : null),
    encoding: "utf8",
    windowsHide: true,
    timeout: timeoutMs,
    maxBuffer: 1024 * 1024,
  });
  return {
    command: `node --permission scripts/test-runner.mjs ${mode}`,
    status: result.status,
    stdout: result.stdout ?? "",
    stderr: result.stderr ?? "",
    passed: result.status === 0 && !result.error,
    error: result.error?.message ?? null,
  };
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const result = runRestrictedTests({
    repository: process.cwd(),
    mode: process.argv[2] ?? "public",
    auditPath: process.env.OCKLE_E2E_TEST_AUDIT_PATH ?? null,
  });
  if (result.stdout) process.stdout.write(result.stdout);
  if (result.stderr) process.stderr.write(result.stderr);
  if (result.error) process.stderr.write(`${result.error}\n`);
  process.exit(result.status ?? 1);
}
