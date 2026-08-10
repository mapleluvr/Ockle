#!/usr/bin/env node
import { createHash } from "node:crypto";
import {
  appendFileSync,
  cpSync,
  existsSync,
  lstatSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  readdirSync,
  rmSync,
} from "node:fs";
import { spawnSync } from "node:child_process";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

function sanitizedEnvironment(cwd) {
  const env = { NO_COLOR: "1", TEMP: cwd, TMP: cwd };
  for (const name of ["SystemRoot", "WINDIR"]) {
    if (typeof process.env[name] === "string") env[name] = process.env[name];
  }
  return env;
}

function copyWithoutGit(source, destination) {
  cpSync(source, destination, {
    recursive: true,
    filter(candidate) {
      const relative = path.relative(source, candidate).replaceAll("\\", "/");
      if (relative === ".git" || relative.startsWith(".git/")) return false;
      if (lstatSync(candidate).isSymbolicLink()) {
        throw new Error(`fixture symlinks are not supported: ${relative || "."}`);
      }
      return true;
    },
  });
}

function filesBelow(directory) {
  if (!existsSync(directory)) return [];
  const found = [];
  for (const entry of readdirSync(directory, { withFileTypes: true })) {
    const target = path.join(directory, entry.name);
    if (entry.isSymbolicLink()) throw new Error(`fixture symlinks are not supported: ${target}`);
    if (entry.isDirectory()) found.push(...filesBelow(target));
    else found.push(target);
  }
  return found;
}

function digestTree(root, directory) {
  const hash = createHash("sha256");
  for (const file of filesBelow(path.join(root, directory)).sort()) {
    hash.update(path.relative(root, file).replaceAll("\\", "/"));
    hash.update(readFileSync(file));
  }
  return hash.digest("hex");
}

function appendTrustedAudit(auditPath, record) {
  if (!auditPath) return;
  const target = path.resolve(auditPath);
  mkdirSync(path.dirname(target), { recursive: true });
  appendFileSync(target, `${JSON.stringify(record)}\n`, "utf8");
}

export function runRestrictedTests({ repository, mode, auditPath = null, timeoutMs = 60000 }) {
  if (!new Set(["public", "ci"]).has(mode)) throw new Error(`unsupported test mode: ${mode}`);
  const source = path.resolve(repository);
  const sandbox = mkdtempSync(path.join(os.tmpdir(), "ockle-e2e-test-copy-"));
  const targets = mode === "ci" ? ["test/public.test.mjs", "test/ci.test.mjs"] : ["test/public.test.mjs"];
  try {
    copyWithoutGit(source, sandbox);
    const record = {
      at: Date.now(),
      mode,
      sourceDigest: digestTree(source, "src"),
      testDigest: digestTree(source, "test"),
      targets,
      passed: false,
    };
    const result = spawnSync(process.execPath, [
      "--permission",
      `--allow-fs-read=${sandbox}`,
      `--allow-fs-write=${sandbox}`,
      path.join(sandbox, "scripts", "test-runner.mjs"),
      mode,
    ], {
      cwd: sandbox,
      env: sanitizedEnvironment(sandbox),
      encoding: "utf8",
      windowsHide: true,
      timeout: timeoutMs,
      maxBuffer: 1024 * 1024,
    });
    record.passed = result.status === 0 && !result.error;
    appendTrustedAudit(auditPath, record);
    return {
      command: `node --permission scripts/test-runner.mjs ${mode}`,
      status: result.status,
      stdout: result.stdout ?? "",
      stderr: result.stderr ?? "",
      passed: record.passed,
      error: result.error?.message ?? null,
    };
  } finally {
    rmSync(sandbox, { recursive: true, force: true });
  }
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
