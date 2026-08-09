import { execFileSync } from "node:child_process";
import { mkdirSync, readFileSync, renameSync, writeFileSync, existsSync } from "node:fs";
import path from "node:path";

function ensureDirectory(directory) {
  mkdirSync(directory, { recursive: true });
}

function writeJsonAtomic(file, value) {
  const temporary = `${file}.${process.pid}.tmp`;
  writeFileSync(temporary, `${JSON.stringify(value, null, 2)}\n`, "utf8");
  renameSync(temporary, file);
}

export function defaultStorePath(repository) {
  const raw = execFileSync("git", ["-C", repository, "rev-parse", "--git-path", "ockle-guard"], {
    encoding: "utf8",
    windowsHide: true,
  }).trim();
  return path.join(path.isAbsolute(raw) ? raw : path.resolve(repository, raw), "runs");
}


export function writeRecord(directory, record) {
  ensureDirectory(directory);
  writeJsonAtomic(path.join(directory, "latest.json"), record);
}

export function readRecord(directory, runId) {
  const latest = readLatest(directory);
  return latest?.runId === runId ? latest : null;
}

export function readLatest(directory) {
  const latestFile = path.join(directory, "latest.json");
  if (!existsSync(latestFile)) return null;
  return JSON.parse(readFileSync(latestFile, "utf8"));
}
