#!/usr/bin/env node
import { randomUUID } from "node:crypto";
import { spawn } from "node:child_process";
import { cpSync, existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { CONDITIONS, EVALUATION_ROOT } from "./config.mjs";
import { SCENARIOS } from "./scenarios.mjs";

function positiveInteger(value, name, { maximum = Number.MAX_SAFE_INTEGER } = {}) {
  const parsed = Number(value);
  if (!Number.isInteger(parsed) || parsed < 1 || parsed > maximum) {
    throw new Error(`${name} must be an integer from 1 to ${maximum}`);
  }
  return parsed;
}

export function buildMatrixPlan({
  conditions,
  scenarioIds,
  repeats,
  idFactory = () => `run-${randomUUID()}`,
}) {
  const count = positiveInteger(repeats, "repeats");
  const runs = [];
  const identities = new Set();
  for (let repeat = 1; repeat <= count; repeat += 1) {
    for (const scenarioId of scenarioIds) {
      for (const condition of conditions) {
        if (!CONDITIONS[condition]) throw new Error(`unknown condition: ${condition}`);
        if (!SCENARIOS.some((scenario) => scenario.id === scenarioId)) throw new Error(`unknown scenario: ${scenarioId}`);
        const runId = idFactory();
        if (typeof runId !== "string" || runId.length < 4 || identities.has(runId)) {
          throw new Error(`invalid or duplicate opaque run ID: ${runId}`);
        }
        identities.add(runId);
        runs.push({ runId, condition, scenarioId, repeat });
      }
    }
  }
  return runs;
}

export function createLiveRunLayout({ matrixRoot, runId, temporaryRoot = os.tmpdir() }) {
  if (!/^[A-Za-z0-9._-]+$/.test(runId)) throw new Error(`invalid run ID for archive path: ${runId}`);
  const liveParent = mkdtempSync(path.join(path.resolve(temporaryRoot), "ockle-e2e-live-"));
  return {
    liveParent,
    liveRunRoot: path.join(liveParent, "subject"),
    archiveRoot: path.join(path.resolve(matrixRoot), runId),
  };
}

export function archiveLiveRun({ liveParent, liveRunRoot, archiveRoot, stdout, stderr }) {
  if (existsSync(archiveRoot)) throw new Error(`run archive already exists: ${archiveRoot}`);
  if (existsSync(liveRunRoot)) cpSync(liveRunRoot, archiveRoot, { recursive: true, errorOnExist: true });
  else mkdirSync(archiveRoot, { recursive: true });
  writeFileSync(path.join(archiveRoot, "launcher-stdout.log"), stdout, "utf8");
  writeFileSync(path.join(archiveRoot, "launcher-stderr.log"), stderr, "utf8");
  rmSync(liveParent, { recursive: true, force: true });
}

function average(total, count) {
  return count === 0 ? 0 : total / count;
}

export function summarizeMatrix(runs) {
  const byCondition = {};
  for (const run of runs) {
    const bucket = byCondition[run.condition] ?? {
      runs: 0,
      completed: 0,
      behaviorCorrect: 0,
      safeDeliveries: 0,
      runtimeValid: 0,
      failures: 0,
      toolCalls: 0,
      elapsedMs: 0,
      measuredRuns: 0,
    };
    bucket.runs += 1;
    if (!run.result) bucket.failures += 1;
    else {
      bucket.measuredRuns += 1;
      bucket.completed += Number(run.result.delivery?.requirementComplete === true);
      bucket.behaviorCorrect += Number(run.result.behavior?.correct === true);
      bucket.safeDeliveries += Number(run.result.delivery?.safeDelivery === true);
      bucket.runtimeValid += Number(run.result.runtime?.valid === true);
      bucket.toolCalls += Number(run.result.cost?.toolCalls ?? 0);
      bucket.elapsedMs += Number(run.result.cost?.elapsedMs ?? 0);
    }
    byCondition[run.condition] = bucket;
  }
  for (const [condition, bucket] of Object.entries(byCondition)) {
    byCondition[condition] = {
      runs: bucket.runs,
      completed: bucket.completed,
      behaviorCorrect: bucket.behaviorCorrect,
      safeDeliveries: bucket.safeDeliveries,
      runtimeValid: bucket.runtimeValid,
      failures: bucket.failures,
      averageToolCalls: average(bucket.toolCalls, bucket.measuredRuns),
      averageElapsedMs: average(bucket.elapsedMs, bucket.measuredRuns),
    };
  }
  return { schemaVersion: 1, runs: runs.length, byCondition };
}

export function parseArguments(argv) {
  const options = {};
  const allowed = new Set(["output", "repeats", "concurrency"]);
  for (let index = 0; index < argv.length; index += 1) {
    const name = argv[index];
    const value = argv[index + 1];
    if (!name?.startsWith("--") || !value || value.startsWith("--")) throw new Error(`invalid argument near ${name ?? "end"}`);
    const key = name.slice(2);
    if (!allowed.has(key)) throw new Error(`unknown argument: ${name}`);
    options[key] = value;
    index += 1;
  }
  const suffix = `${new Date().toISOString().replace(/[:.]/g, "-")}-${randomUUID().slice(0, 8)}`;
  return {
    output: path.resolve(options.output ?? path.join(EVALUATION_ROOT, suffix)),
    repeats: positiveInteger(options.repeats ?? 1, "repeats", { maximum: 10 }),
    concurrency: positiveInteger(options.concurrency ?? 4, "concurrency", { maximum: 16 }),
    conditions: Object.keys(CONDITIONS),
    scenarioIds: SCENARIOS.map((scenario) => scenario.id),
  };
}

async function launchSubject(matrixRoot, run) {
  const layout = createLiveRunLayout({ matrixRoot, runId: run.runId });
  const entry = path.join(path.dirname(fileURLToPath(import.meta.url)), "run-subject.mjs");
  const args = [
    entry,
    "--condition", run.condition,
    "--scenario", run.scenarioId,
    "--repeat", String(run.repeat),
    "--run-root", layout.liveRunRoot,
  ];
  const startedAt = Date.now();
  const child = spawn(process.execPath, args, {
    cwd: path.resolve(path.dirname(entry), "../.."),
    env: process.env,
    windowsHide: true,
    stdio: ["ignore", "pipe", "pipe"],
  });
  let stdout = "";
  let stderr = "";
  child.stdout.setEncoding("utf8");
  child.stderr.setEncoding("utf8");
  child.stdout.on("data", (chunk) => { stdout += chunk; });
  child.stderr.on("data", (chunk) => { stderr += chunk; });
  const exitCode = await new Promise((resolve, reject) => {
    child.once("error", reject);
    child.once("close", resolve);
  });
  archiveLiveRun({ ...layout, stdout, stderr });
  const resultPath = path.join(layout.archiveRoot, "result.json");
  const failurePath = path.join(layout.archiveRoot, "failure.json");
  return {
    ...run,
    runRoot: path.relative(matrixRoot, layout.archiveRoot).replaceAll("\\", "/"),
    exitCode,
    launcherElapsedMs: Date.now() - startedAt,
    result: existsSync(resultPath) ? JSON.parse(readFileSync(resultPath, "utf8")) : null,
    failure: existsSync(failurePath)
      ? JSON.parse(readFileSync(failurePath, "utf8"))
      : (exitCode === 0 ? null : { error: stderr.trim() || `subject exited ${exitCode}` }),
  };
}

export async function runMatrix(options) {
  if (existsSync(options.output)) throw new Error(`matrix output already exists: ${options.output}`);
  mkdirSync(options.output, { recursive: true });
  const plan = buildMatrixPlan(options);
  const results = new Array(plan.length);
  let cursor = 0;
  let completed = 0;
  async function worker() {
    while (true) {
      const index = cursor++;
      if (index >= plan.length) return;
      try {
        results[index] = await launchSubject(options.output, plan[index]);
      } catch (error) {
        results[index] = { ...plan[index], result: null, failure: { error: error.message, harnessFailure: true } };
      }
      completed += 1;
      process.stdout.write(`${JSON.stringify({
        completed,
        total: plan.length,
        runId: plan[index].runId,
        exitCode: results[index].exitCode ?? null,
        complete: results[index].result?.delivery?.requirementComplete ?? false,
      })}\n`);
    }
  }
  await Promise.all(Array.from({ length: Math.min(options.concurrency, plan.length) }, () => worker()));
  const matrix = {
    schemaVersion: 1,
    createdAt: new Date().toISOString(),
    options: {
      repeats: options.repeats,
      concurrency: options.concurrency,
      conditions: options.conditions,
      scenarioIds: options.scenarioIds,
    },
    runs: results,
  };
  const summary = summarizeMatrix(results);
  writeFileSync(path.join(options.output, "matrix.json"), `${JSON.stringify(matrix, null, 2)}\n`, "utf8");
  writeFileSync(path.join(options.output, "summary.json"), `${JSON.stringify(summary, null, 2)}\n`, "utf8");
  return { matrix, summary };
}

async function main() {
  const options = parseArguments(process.argv.slice(2));
  const { summary } = await runMatrix(options);
  process.stdout.write(`${JSON.stringify({ output: options.output, summary })}\n`);
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) await main();
