#!/usr/bin/env node

import { readFileSync } from "node:fs";

import {
  checkGuard,
  detailsGuard,
  EXIT_CODES,
  statusGuard,
} from "../src/index.mjs";

function parseArgs(argv) {
  const values = {};
  const flags = new Set();
  for (let index = 0; index < argv.length; index += 1) {
    const token = argv[index];
    if (!token.startsWith("--")) throw new Error(`Unexpected argument: ${token}`);
    if (token === "--no-store") {
      if (flags.has("no-store")) throw new Error("Duplicate option: --no-store.");
      flags.add("no-store");
      continue;
    }
    const key = token.slice(2);
    if (Object.hasOwn(values, key)) throw new Error(`Duplicate option: --${key}.`);
    const value = argv[index + 1];
    if (!value || value.startsWith("--")) throw new Error(`Missing value for ${token}.`);
    values[key] = value;
    index += 1;
  }
  return { values, flags };
}

function numberOption(values, name) {
  if (!Object.hasOwn(values, name)) return undefined;
  const value = Number(values[name]);
  if (!Number.isInteger(value)) throw new Error(`--${name} must be an integer.`);
  return value;
}

function validateOptions(operation, values, flags) {
  const common = ["repo", "store", "page-size", "max-bytes"];
  const allowed = new Set(operation === "check"
    ? [...common, "base", "candidate", "authorization-file"]
    : operation === "status"
      ? [...common, "base", "candidate"]
      : [...common, "run-id", "cursor"]);
  for (const key of Object.keys(values)) {
    if (!allowed.has(key)) {
      const known = [
        "repo", "store", "page-size", "max-bytes", "base", "candidate",
        "authorization-file", "run-id", "cursor",
      ];
      throw new Error(known.includes(key)
        ? `Option --${key} is not valid for ${operation}.`
        : `Unknown option: --${key}.`);
    }
  }
  if (flags.has("no-store") && operation !== "check") {
    throw new Error(`Option --no-store is not valid for ${operation}.`);
  }
}

function usage() {
  return `Usage:
  ockle-guard check   --base <ref> [--candidate worktree|index|<ref>] [options]
  ockle-guard status  --base <ref> [--candidate worktree|index|<ref>] [options]
  ockle-guard details --run-id <id> [options]

Options:
  --repo <path>       Repository path (default: current directory)
  --store <path>      Guard result directory (default: Git metadata)
  --authorization-file <path>
                       Trusted receipt for check (must be outside candidate)
  --page-size <n>     Findings per response (default: 8)
  --max-bytes <n>     Maximum serialized finding-page size (default: 1024)
  --cursor <n>        Finding cursor for details
  --no-store          Do not persist a check result
  --help              Show this help`;
}

function main(argv) {
  if (argv.length === 0 || argv.includes("--help")) {
    process.stdout.write(`${usage()}\n`);
    return 0;
  }
  const [operation, ...rest] = argv;
  if (!["check", "status", "details"].includes(operation)) {
    throw new Error(`Unknown operation: ${operation}.`);
  }
  const { values, flags } = parseArgs(rest);
  validateOptions(operation, values, flags);
  const options = {
    repository: values.repo ?? process.cwd(),
    storePath: values.store,
    pageSize: numberOption(values, "page-size"),
    maxBytes: numberOption(values, "max-bytes"),
  };
  let result;
  if (operation === "check") {
    result = checkGuard({
      ...options,
      base: values.base,
      candidate: values.candidate ?? "worktree",
      store: !flags.has("no-store"),
      authorization: values["authorization-file"]
        ? JSON.parse(readFileSync(values["authorization-file"], "utf8"))
        : undefined,
    });
  } else if (operation === "status") {
    result = statusGuard({
      ...options,
      base: values.base,
      candidate: values.candidate ?? "worktree",
    });
  } else {
    result = detailsGuard({
      ...options,
      runId: values["run-id"],
      cursor: numberOption(values, "cursor") ?? 0,
    });
  }
  process.stdout.write(`${JSON.stringify(result)}\n`);
  const exitCode = EXIT_CODES[result.verdict];
  if (exitCode === undefined) throw new Error(`Unknown guard verdict: ${result.verdict}`);
  return exitCode;
}

try {
  process.exitCode = main(process.argv.slice(2));
} catch (error) {
  process.stdout.write(`${JSON.stringify({
    schemaVersion: 1,
    operation: "error",
    error: { message: error instanceof Error ? error.message : String(error) },
  })}\n`);
  process.exitCode = 4;
}
