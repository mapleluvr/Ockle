import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const manifestPath = path.join(root, "evals", "deep-swe", "pilot-v1.json");
const manifest = JSON.parse(readFileSync(manifestPath, "utf8"));

const expectedIds = [
  "fastapi-implicit-head-options",
  "go-critic-doc-link-checker",
  "helm-array-merge-strategies",
  "kombu-virtual-queue-dead-lettering",
  "koota-composite-trait-aspects",
  "pest-character-class-coalescing",
  "sql-formatter-bigquery-pipe-formatting",
  "superjson-error-stack-serialization",
  "tengo-callable-instance-isolation",
  "testem-bail-on-test-failure",
  "vulture-persistent-analysis-cache",
  "yjs-map-conflict-detection",
];

test("DeepSWE pilot pins source and outcome-independent selection", () => {
  assert.equal(manifest.schemaVersion, 1);
  assert.equal(manifest.benchmark.name, "DeepSWE v1.1");
  assert.equal(manifest.benchmark.commit, "435ee89ec2f2e2289f33b0da4f992f0b7b7266b9");
  assert.equal(manifest.runner.name, "Pier");
  assert.equal(manifest.runner.commit, "0daf53d3599e58c4506cf0bcff5e12c77dc282d2");
  assert.equal(manifest.selection.seed, "Ockle DeepSWE v1.1 pilot 1");
  assert.deepEqual(manifest.selection.languageQuotas, {
    typescript: 3,
    javascript: 2,
    go: 3,
    python: 3,
    rust: 1,
  });
  assert.deepEqual(manifest.tasks.map(({ id }) => id).sort(), expectedIds);
  assert.equal(new Set(manifest.tasks.map(({ id }) => id)).size, 12);
});

test("DeepSWE pilot pairs bare and inner everywhere and full only on JS/TS", () => {
  for (const task of manifest.tasks) {
    assert.deepEqual(task.arms.slice(0, 2), ["bare", "inner"]);
    const guardApplies = task.language === "javascript" || task.language === "typescript";
    assert.equal(task.arms.includes("full"), guardApplies, task.id);
    assert.match(task.baseCommit, /^[0-9a-f]{40}$/);
    assert.match(task.image, /^public\.ecr\.aws\//);
    assert.match(task.imageDigest, /^sha256:[0-9a-f]{64}$/);
    assert.match(task.selectionRank, /^[0-9a-f]{64}$/);
  }
  assert.equal(manifest.tasks.reduce((total, task) => total + task.arms.length, 0), 29);
});

test("DeepSWE pilot manifest contains no public outcomes or reference patches", () => {
  const serialized = JSON.stringify(manifest).toLowerCase();
  for (const forbidden of ["reward", "pass@", "trial", "solution", "reference_patch"]) {
    assert.equal(serialized.includes(forbidden), false, forbidden);
  }
});
