#!/usr/bin/env node
import { createHash } from "node:crypto";
import { mkdirSync, readdirSync, readFileSync, writeFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { CONDITIONS, ROOT } from "./config.mjs";
import { getScenario } from "./scenarios.mjs";
import { prepareFixture } from "./fixtures.mjs";
import { resolveRuntimePaths } from "./runtime.mjs";
import { executeSubject } from "./subject-runtime.mjs";
import { gradeRun } from "./grade-run.mjs";

function parseArguments(argv) {
  const options = {};
  const allowed = new Set(["run-root", "scenario", "condition", "repeat"]);
  for (let index = 0; index < argv.length; index += 1) {
    const name = argv[index];
    if (!name.startsWith("--") || !allowed.has(name.slice(2))) throw new Error(`unexpected argument: ${name}`);
    const value = argv[index + 1];
    if (!value || value.startsWith("--")) throw new Error(`missing value for ${name}`);
    options[name.slice(2)] = value;
    index += 1;
  }
  for (const required of allowed) if (!options[required]) throw new Error(`--${required} is required`);
  if (!CONDITIONS[options.condition]) throw new Error(`unknown condition: ${options.condition}`);
  getScenario(options.scenario);
  const repeat = Number(options.repeat);
  if (!Number.isInteger(repeat) || repeat < 1) throw new Error("--repeat must be a positive integer");
  return {
    runRoot: path.resolve(options["run-root"]),
    scenarioId: options.scenario,
    condition: options.condition,
    repeat,
  };
}

function filesBelow(directory) {
  const files = [];
  for (const entry of readdirSync(directory, { withFileTypes: true })) {
    const target = path.join(directory, entry.name);
    if (entry.isDirectory()) files.push(...filesBelow(target));
    else files.push(target);
  }
  return files;
}

function hashTree(directory) {
  const hash = createHash("sha256");
  for (const file of filesBelow(directory).sort()) {
    hash.update(path.relative(directory, file).replaceAll("\\", "/"));
    hash.update(readFileSync(file));
  }
  return hash.digest("hex");
}

function protectedHashes() {
  return {
    guard: hashTree(path.join(ROOT, "guard", "src")),
    skills: hashTree(path.join(ROOT, "skills")),
    evaluator: hashTree(path.join(ROOT, "evals", "e2e")),
  };
}

export async function runSubject(options) {
  mkdirSync(options.runRoot, { recursive: false });
  const repository = path.join(options.runRoot, "repo");
  const guardModule = path.join(ROOT, "guard", "src", "index.mjs");
  const runtime = resolveRuntimePaths();
  const protectedBefore = protectedHashes();
  const manifest = {
    schemaVersion: 1,
    scenarioId: options.scenarioId,
    condition: options.condition,
    repeat: options.repeat,
    startedAt: new Date().toISOString(),
    runtime: {
      piVersion: runtime.piVersion,
      model: "Mapleluv/deepseek-v4-flash:max",
    },
    protectedSourceHashes: protectedBefore,
  };

  const fixture = prepareFixture({
    repository,
    scenarioId: options.scenarioId,
    condition: options.condition,
    guardModule,
  });
  if (fixture.publicTest.status !== 0 || fixture.gitStatus !== "") {
    throw new Error(`invalid baseline fixture: ${JSON.stringify({ publicTest: fixture.publicTest, gitStatus: fixture.gitStatus })}`);
  }

  const execution = await executeSubject({
    runRoot: options.runRoot,
    repository,
    condition: options.condition,
    scenarioId: options.scenarioId,
    fixture,
    runtime,
  });
  const result = await gradeRun({
    runRoot: options.runRoot,
    repository,
    scenarioId: options.scenarioId,
    condition: options.condition,
    fixture,
    execution,
  });
  const protectedAfter = protectedHashes();
  const protectedOckleSourceChanged = Object.keys(protectedBefore)
    .some((name) => protectedBefore[name] !== protectedAfter[name]);
  result.contamination.protectedOckleSourceChanged = protectedOckleSourceChanged;
  if (protectedOckleSourceChanged) {
    result.runtime.valid = false;
    result.runtime.failures.push("protected-ockle-source-changed");
    if (result.delivery.delivered) result.delivery.unsafeDelivered = true;
    result.delivery.safeDelivery = false;
    result.delivery.requirementComplete = false;
  }
  result.repeat = options.repeat;
  result.runId = path.basename(options.runRoot);
  result.finishedAt = new Date().toISOString();
  writeFileSync(path.join(options.runRoot, "manifest.json"), `${JSON.stringify(manifest, null, 2)}\n`, "utf8");
  writeFileSync(path.join(options.runRoot, "result.json"), `${JSON.stringify(result, null, 2)}\n`, "utf8");
  return result;
}

async function main() {
  const options = parseArguments(process.argv.slice(2));
  try {
    const result = await runSubject(options);
    process.stdout.write(`${JSON.stringify({
      runId: result.runId,
      scenarioId: result.scenarioId,
      condition: result.condition,
      repeat: result.repeat,
      complete: result.delivery.requirementComplete,
      behaviorCorrect: result.behavior.correct,
      safeDelivery: result.delivery.safeDelivery,
      runtimeValid: result.runtime.valid,
    })}\n`);
  } catch (error) {
    const failure = {
      schemaVersion: 1,
      scenarioId: options.scenarioId,
      condition: options.condition,
      repeat: options.repeat,
      error: error instanceof Error ? error.message : String(error),
      stack: error instanceof Error ? error.stack : null,
      failedAt: new Date().toISOString(),
    };
    writeFileSync(path.join(options.runRoot, "failure.json"), `${JSON.stringify(failure, null, 2)}\n`, "utf8");
    process.stderr.write(`${failure.error}\n`);
    process.exitCode = 1;
  }
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) await main();
