import assert from "node:assert/strict";
import { execFileSync, spawnSync } from "node:child_process";
import {
  existsSync,
  mkdtempSync,
  mkdirSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";

import {
  checkGuard,
  detailsGuard,
  POLICY,
  statusGuard,
} from "../guard/src/index.mjs";
import { defaultStorePath } from "../guard/src/store.mjs";
import { captureGuardSnapshot, verifyGuardSnapshot } from "../guard/src/snapshot.mjs";

const root = path.resolve(new URL("..", import.meta.url).pathname.replace(/^\/(\w):/, "$1:"));
const cli = path.join(root, "guard", "bin", "ockle-guard.mjs");

function git(repository, ...args) {
  return execFileSync("git", ["-C", repository, ...args], {
    encoding: "utf8",
    windowsHide: true,
    stdio: ["ignore", "pipe", "pipe"],
  }).trim();
}

function createRepo(source, file = "test/value.test.js") {
  const repository = mkdtempSync(path.join(os.tmpdir(), "ockle-guard-test-"));
  mkdirSync(path.dirname(path.join(repository, file)), { recursive: true });
  writeFileSync(path.join(repository, file), source);
  git(repository, "init", "-q", "-b", "main");
  git(repository, "config", "user.email", "test@example.invalid");
  git(repository, "config", "user.name", "Ockle test");
  git(repository, "add", ".");
  git(repository, "commit", "-qm", "fixture");
  return { repository, base: git(repository, "rev-parse", "HEAD") };
}

function cleanup(repository) {
  rmSync(repository, { recursive: true, force: true });
}

function writeTest(repository, source, file = "test/value.test.js") {
  writeFileSync(path.join(repository, file), source);
}

function noTruncatedField(value) {
  assert.equal(Object.hasOwn(value, "truncated"), false);
  assert.equal(Object.hasOwn(value.findings, "truncated"), false);
}

test("check returns a bounded machine envelope and status can re-query it", () => {
  const fixture = createRepo(`import assert from "node:assert/strict";\nassert.equal(value(), 1);\n`);
  try {
    writeTest(fixture.repository, `import assert from "node:assert/strict";\nassert.equal(value(), 1);\nassert.equal(other(), 2);\n`);
    const result = checkGuard({ repository: fixture.repository, base: fixture.base, pageSize: 1 });

    assert.equal(result.operation, "check");
    assert.equal(result.verdict, "clear");
    assert.equal(result.coverage, "complete");
    assert.equal(result.findings.total, 0);
    assert.equal(result.findings.returned, 0);
    assert.equal(result.findings.nextCursor, null);
    assert.ok(result.input.digest);
    assert.ok(result.runId);
    noTruncatedField(result);

    const status = statusGuard({ repository: fixture.repository, base: fixture.base, pageSize: 1 });
    assert.equal(status.operation, "status");
    assert.equal(status.verdict, "clear");
    assert.equal(status.runId, result.runId);
    assert.equal(status.input.digest, result.input.digest);
  } finally {
    cleanup(fixture.repository);
  }
});

test("blocked findings are paged and details resumes from nextCursor", () => {
  const fixture = createRepo([
    `import assert from "node:assert/strict";`,
    `assert.equal(first(), 1);`,
    `assert.equal(second(), 2);`,
    `assert.equal(third(), 3);`,
  ].join("\n"));
  try {
    writeTest(fixture.repository, [
      `import assert from "node:assert/strict";`,
      `assert.equal(first(), 10);`,
      `assert.equal(second(), 20);`,
      `assert.equal(third(), 30);`,
    ].join("\n"));
    const result = checkGuard({ repository: fixture.repository, base: fixture.base, pageSize: 1 });
    assert.equal(result.verdict, "blocked");
    assert.equal(result.coverage, "complete");
    assert.equal(result.findings.total, 3);
    assert.equal(result.findings.returned, 1);
    assert.equal(result.findings.nextCursor, 1);
    noTruncatedField(result);

    const middle = detailsGuard({
      repository: fixture.repository,
      runId: result.runId,
      cursor: result.findings.nextCursor,
      pageSize: 1,
    });
    assert.equal(middle.operation, "details");
    assert.equal(middle.findings.cursor, 1);
    assert.equal(middle.findings.returned, 1);
    assert.equal(middle.findings.nextCursor, 2);
    assert.notEqual(middle.findings.items[0].id, result.findings.items[0].id);

    const last = detailsGuard({
      repository: fixture.repository,
      runId: result.runId,
      cursor: middle.findings.nextCursor,
      pageSize: 1,
    });
    assert.equal(last.findings.returned, 1);
    assert.equal(last.findings.nextCursor, null);
  } finally {
    cleanup(fixture.repository);
  }
});

test("blocked finding pages honor the byte budget", () => {
  const assertions = Array.from({ length: 20 }, (_, index) => `assert.equal(value${index}(), ${index});`);
  const fixture = createRepo([`import assert from "node:assert/strict";`, ...assertions].join("\n"));
  try {
    writeTest(fixture.repository, `import assert from "node:assert/strict";\n`);
    const result = checkGuard({
      repository: fixture.repository,
      base: fixture.base,
      pageSize: 100,
      maxBytes: 512,
    });

    assert.equal(result.findings.total, 20);
    assert.ok(result.findings.returned > 0);
    assert.ok(result.findings.nextCursor !== null);
    assert.ok(Buffer.byteLength(JSON.stringify(result.findings)) <= 512);

    const defaultResult = checkGuard({ repository: fixture.repository, base: fixture.base });
    assert.ok(Buffer.byteLength(JSON.stringify(defaultResult)) <= 2048);
  } finally {
    cleanup(fixture.repository);
  }
});

test("an oversized finding is compacted without stalling pagination", () => {
  const fixture = createRepo(`import assert from "node:assert/strict";\nassert.equal(value(), 1);\n`);
  const store = mkdtempSync(path.join(os.tmpdir(), "ockle-long-finding-"));
  try {
    const record = {
      schemaVersion: 1,
      runId: "long-finding-run",
      input: { digest: "input", base: {}, candidate: {} },
      verdict: "blocked",
      coverage: "complete",
      allFindings: [{
        id: "long-finding-id",
        rule: "assertion-change",
        kind: "removed-or-rewritten",
        file: `test/${"segment/".repeat(260)}value.test.js`,
        line: 1,
        column: 0,
        occurrence: 1,
        framework: "node-assert",
        method: "equal",
      }],
      errors: [],
    };
    writeFileSync(path.join(store, "latest.json"), `${JSON.stringify(record)}\n`);
    const result = detailsGuard({
      repository: fixture.repository,
      storePath: store,
      runId: record.runId,
      pageSize: 8,
      maxBytes: 512,
    });

    assert.ok(Buffer.byteLength(JSON.stringify(result.findings)) <= 512);
    assert.equal(result.findings.returned, 1);
    assert.equal(result.findings.nextCursor, null);
    assert.equal(result.findings.items[0].id, "long-finding-id");
    assert.equal(result.findings.items[0].fileTruncated, true);
  } finally {
    cleanup(fixture.repository);
    cleanup(store);
  }
});

test("the result store retains only the latest run", () => {
  const fixture = createRepo(`import assert from "node:assert/strict";\nassert.equal(value(), 1);\n`);
  try {
    const first = checkGuard({ repository: fixture.repository, base: fixture.base });
    writeTest(fixture.repository, `import assert from "node:assert/strict";\nassert.equal(value(), 2);\n`);
    const second = checkGuard({ repository: fixture.repository, base: fixture.base });

    assert.notEqual(first.runId, second.runId);
    assert.throws(
      () => detailsGuard({ repository: fixture.repository, runId: first.runId }),
      /unknown guard run/i,
    );
    assert.equal(
      detailsGuard({ repository: fixture.repository, runId: second.runId }).verdict,
      "blocked",
    );
  } finally {
    cleanup(fixture.repository);
  }
});

test("the common spec directory is part of the supported test scope", () => {
  const fixture = createRepo(
    `import assert from "node:assert/strict";\nassert.equal(value(), 1);\n`,
    "spec/value.js",
  );
  try {
    writeTest(
      fixture.repository,
      `import assert from "node:assert/strict";\nassert.equal(value(), 2);\n`,
      "spec/value.js",
    );
    const result = checkGuard({ repository: fixture.repository, base: fixture.base });
    assert.equal(result.verdict, "blocked");
    assert.equal(result.findings.items[0].file, "spec/value.js");
  } finally {
    cleanup(fixture.repository);
  }
});

test("a no-store check cannot be recovered by status", () => {
  const fixture = createRepo(`import assert from "node:assert/strict";\nassert.equal(value(), 1);\n`);
  try {
    writeTest(fixture.repository, `import assert from "node:assert/strict";\nassert.equal(value(), 2);\n`);
    const result = checkGuard({ repository: fixture.repository, base: fixture.base, store: false });
    const status = statusGuard({ repository: fixture.repository, base: fixture.base });
    assert.equal(result.verdict, "blocked");
    assert.equal(status.verdict, "unchecked");
  } finally {
    cleanup(fixture.repository);
  }
});

test("status ignores changes outside the guard policy input", () => {
  const fixture = createRepo(`import assert from "node:assert/strict";\nassert.equal(value(), 1);\n`);
  try {
    const result = checkGuard({ repository: fixture.repository, base: fixture.base });
    mkdirSync(path.join(fixture.repository, "src"), { recursive: true });
    mkdirSync(path.join(fixture.repository, ".pi-subagents", "artifacts"), { recursive: true });
    writeFileSync(path.join(fixture.repository, "src", "value.js"), "export const value = 2;\n");
    writeFileSync(path.join(fixture.repository, ".pi-subagents", "artifacts", "trace.log"), "dynamic host output\n");
    const status = statusGuard({ repository: fixture.repository, base: fixture.base });

    assert.equal(status.verdict, "clear");
    assert.equal(status.runId, result.runId);
    assert.equal(status.input.digest, result.input.digest);
  } finally {
    cleanup(fixture.repository);
  }
});

test("status becomes unchecked when the candidate identity changes", () => {
  const fixture = createRepo(`import assert from "node:assert/strict";\nassert.equal(value(), 1);\n`);
  try {
    const result = checkGuard({ repository: fixture.repository, base: fixture.base });
    writeTest(fixture.repository, `import assert from "node:assert/strict";\nassert.equal(value(), 1);\n// unrelated candidate change\n`);
    const status = statusGuard({ repository: fixture.repository, base: fixture.base });

    assert.equal(result.verdict, "clear");
    assert.equal(status.verdict, "unchecked");
    assert.equal(status.coverage, "unknown");
    assert.equal(status.runId, null);
    assert.equal(status.findings.total, 0);
    noTruncatedField(status);
  } finally {
    cleanup(fixture.repository);
  }
});

test("snapshot verification detects a relevant concurrent candidate mutation", () => {
  const fixture = createRepo(`import assert from "node:assert/strict";\nassert.equal(value(), 1);\n`);
  try {
    writeTest(fixture.repository, `import assert from "node:assert/strict";\nassert.equal(value(), 2);\n`);
    const snapshot = captureGuardSnapshot({
      repository: fixture.repository,
      base: fixture.base,
      candidate: "worktree",
      policy: POLICY,
      isRelevant: (file) => file.endsWith(".test.js"),
    });
    writeTest(fixture.repository, `import assert from "node:assert/strict";\nassert.equal(value(), 3);\n`);

    assert.equal(verifyGuardSnapshot({
      repository: fixture.repository,
      snapshot,
      policy: POLICY,
      isRelevant: (file) => file.endsWith(".test.js"),
    }), false);
  } finally {
    cleanup(fixture.repository);
  }
});

test("a trusted authorization receipt is scoped to the exact input and findings", () => {
  const fixture = createRepo([
    `import assert from "node:assert/strict";`,
    `assert.equal(first(), 1);`,
    `assert.equal(second(), 2);`,
  ].join("\n"));
  try {
    writeTest(fixture.repository, [
      `import assert from "node:assert/strict";`,
      `assert.equal(first(), 10);`,
      `assert.equal(second(), 20);`,
    ].join("\n"));
    const blocked = checkGuard({ repository: fixture.repository, base: fixture.base, store: false });
    const receipt = {
      schemaVersion: 1,
      policy: POLICY,
      inputDigest: blocked.input.digest,
      findingIds: blocked.findings.items.map((finding) => finding.id),
      authority: { kind: "human-review", id: "review-42" },
    };
    const authorized = checkGuard({
      repository: fixture.repository,
      base: fixture.base,
      authorization: receipt,
      store: false,
    });

    assert.equal(authorized.verdict, "clear");
    assert.equal(authorized.findings.total, 0);
    assert.equal(authorized.authorization.status, "applied");
    assert.equal(authorized.authorization.applied, 2);
    assert.equal(authorized.authorization.authority.id, "review-42");

    git(fixture.repository, "add", "test/value.test.js");
    const staged = checkGuard({
      repository: fixture.repository,
      base: fixture.base,
      candidate: "index",
      authorization: receipt,
      store: false,
    });
    assert.equal(staged.input.digest, blocked.input.digest);
    assert.equal(staged.verdict, "clear");
    assert.equal(staged.authorization.status, "applied");

    git(fixture.repository, "commit", "-qm", "candidate");
    const candidate = git(fixture.repository, "rev-parse", "HEAD");
    const committed = checkGuard({
      repository: fixture.repository,
      base: fixture.base,
      candidate,
      authorization: receipt,
      store: false,
    });
    assert.equal(committed.input.digest, blocked.input.digest);
    assert.equal(committed.verdict, "clear");
    assert.equal(committed.authorization.status, "applied");

    writeTest(fixture.repository, `${readFileSync(path.join(fixture.repository, "test", "value.test.js"), "utf8")}\n// input changed\n`);
    const stale = checkGuard({
      repository: fixture.repository,
      base: fixture.base,
      authorization: receipt,
      store: false,
    });
    assert.equal(stale.verdict, "blocked");
    assert.equal(stale.authorization.status, "rejected");
    assert.equal(stale.authorization.reason, "input-digest-mismatch");
  } finally {
    cleanup(fixture.repository);
  }
});

test("authorization identity preserves deleted test files across commit", () => {
  const fixture = createRepo(`import assert from "node:assert/strict";\nassert.equal(value(), 1);\n`);
  try {
    rmSync(path.join(fixture.repository, "test", "value.test.js"));
    const blocked = checkGuard({ repository: fixture.repository, base: fixture.base, store: false });
    const receipt = {
      schemaVersion: 1,
      policy: POLICY,
      inputDigest: blocked.input.digest,
      findingIds: blocked.findings.items.map((finding) => finding.id),
      authority: { kind: "human-review", id: "review-delete" },
    };
    git(fixture.repository, "add", "-A");
    git(fixture.repository, "commit", "-qm", "delete test");
    const candidate = git(fixture.repository, "rev-parse", "HEAD");
    const authorized = checkGuard({
      repository: fixture.repository,
      base: fixture.base,
      candidate,
      authorization: receipt,
      store: false,
    });

    assert.equal(authorized.input.digest, blocked.input.digest);
    assert.equal(authorized.verdict, "clear");
    assert.equal(authorized.authorization.status, "applied");
  } finally {
    cleanup(fixture.repository);
  }
});

test("partial or unknown finding authorization fails closed", () => {
  const fixture = createRepo([
    `import assert from "node:assert/strict";`,
    `assert.equal(first(), 1);`,
    `assert.equal(second(), 2);`,
  ].join("\n"));
  try {
    writeTest(fixture.repository, [
      `import assert from "node:assert/strict";`,
      `assert.equal(first(), 10);`,
      `assert.equal(second(), 20);`,
    ].join("\n"));
    const blocked = checkGuard({ repository: fixture.repository, base: fixture.base, store: false });
    const baseReceipt = {
      schemaVersion: 1,
      policy: POLICY,
      inputDigest: blocked.input.digest,
      authority: { kind: "human-review", id: "review-43" },
    };
    const partial = checkGuard({
      repository: fixture.repository,
      base: fixture.base,
      authorization: { ...baseReceipt, findingIds: [blocked.findings.items[0].id] },
      store: false,
    });
    const unknown = checkGuard({
      repository: fixture.repository,
      base: fixture.base,
      authorization: { ...baseReceipt, findingIds: ["unknown"] },
      store: false,
    });
    const oversizedAuthority = checkGuard({
      repository: fixture.repository,
      base: fixture.base,
      authorization: {
        ...baseReceipt,
        findingIds: blocked.findings.items.map((finding) => finding.id),
        authority: { kind: "human-review", id: "x".repeat(129), extra: "not-in-envelope" },
      },
      store: false,
    });

    assert.equal(partial.verdict, "blocked");
    assert.equal(partial.findings.total, 1);
    assert.equal(partial.authorization.status, "partial");
    assert.equal(unknown.verdict, "blocked");
    assert.equal(unknown.authorization.status, "rejected");
    assert.equal(unknown.authorization.reason, "unknown-finding-id");
    assert.equal(oversizedAuthority.verdict, "blocked");
    assert.equal(oversizedAuthority.authorization.reason, "invalid-authority");
  } finally {
    cleanup(fixture.repository);
  }
});

test("authorization is rejected when the current input has no findings", () => {
  const fixture = createRepo(`import assert from "node:assert/strict";\nassert.equal(value(), 1);\n`);
  try {
    const clear = checkGuard({ repository: fixture.repository, base: fixture.base, store: false });
    const receipt = {
      schemaVersion: 1,
      policy: POLICY,
      inputDigest: clear.input.digest,
      findingIds: [],
      authority: { kind: "human-review", id: "review-empty" },
    };
    const result = checkGuard({
      repository: fixture.repository,
      base: fixture.base,
      authorization: receipt,
      store: false,
    });

    assert.equal(result.verdict, "clear");
    assert.equal(result.authorization.status, "rejected");
    assert.equal(result.authorization.reason, "no-findings-to-authorize");
  } finally {
    cleanup(fixture.repository);
  }
});

test("a parse failure is stored as indeterminate and never appears clear", () => {
  const fixture = createRepo(`import assert from "node:assert/strict";\nassert.equal(value(), 1);\n`);
  try {
    writeTest(fixture.repository, `import assert from "node:assert/strict";\nassert.equal(value(, 1);\n`);
    const result = checkGuard({ repository: fixture.repository, base: fixture.base });
    const status = statusGuard({ repository: fixture.repository, base: fixture.base });

    assert.equal(result.verdict, "indeterminate");
    assert.equal(result.coverage, "partial");
    assert.equal(result.errors.length, 1);
    assert.equal(status.verdict, "indeterminate");
    assert.equal(status.coverage, "partial");
  } finally {
    cleanup(fixture.repository);
  }
});

test("the index candidate checks staged content rather than the worktree", () => {
  const fixture = createRepo(`import assert from "node:assert/strict";\nassert.equal(value(), 1);\n`);
  try {
    writeTest(fixture.repository, `import assert from "node:assert/strict";\nassert.equal(value(), 2);\n`);
    git(fixture.repository, "add", "test/value.test.js");
    writeTest(fixture.repository, `import assert from "node:assert/strict";\nassert.equal(value(), 1);\n`);

    const indexResult = checkGuard({ repository: fixture.repository, base: fixture.base, candidate: "index", store: false });
    const worktreeResult = checkGuard({ repository: fixture.repository, base: fixture.base, candidate: "worktree", store: false });

    assert.equal(indexResult.input.candidate.kind, "index");
    assert.equal(indexResult.verdict, "blocked");
    assert.equal(worktreeResult.verdict, "clear");
  } finally {
    cleanup(fixture.repository);
  }
});

test("worktree merges a staged deletion with an untracked recreation", () => {
  const fixture = createRepo(`import assert from "node:assert/strict";\nassert.equal(value(), 1);\n`);
  try {
    git(fixture.repository, "rm", "-q", "test/value.test.js");
    mkdirSync(path.join(fixture.repository, "test"), { recursive: true });
    writeTest(fixture.repository, `import assert from "node:assert/strict";\nassert.equal(value(), 2);\n`);

    const worktree = checkGuard({
      repository: fixture.repository,
      base: fixture.base,
      candidate: "worktree",
      store: false,
    });
    const index = checkGuard({
      repository: fixture.repository,
      base: fixture.base,
      candidate: "index",
      store: false,
    });

    assert.equal(worktree.verdict, "blocked");
    assert.equal(worktree.findings.total, 1);
    assert.equal(index.verdict, "blocked");
    assert.equal(index.findings.total, 1);
  } finally {
    cleanup(fixture.repository);
  }
});

test("an unmerged index is indeterminate with partial coverage", () => {
  const fixture = createRepo(`import assert from "node:assert/strict";\nassert.equal(value(), 1);\n`);
  try {
    git(fixture.repository, "checkout", "-qb", "other");
    writeTest(fixture.repository, `import assert from "node:assert/strict";\nassert.equal(value(), 2);\n`);
    git(fixture.repository, "add", "test/value.test.js");
    git(fixture.repository, "commit", "-qm", "other assertion");
    git(fixture.repository, "checkout", "-q", "main");
    writeTest(fixture.repository, `import assert from "node:assert/strict";\nassert.equal(value(), 3);\n`);
    git(fixture.repository, "add", "test/value.test.js");
    git(fixture.repository, "commit", "-qm", "main assertion");
    const merge = spawnSync("git", ["-C", fixture.repository, "merge", "other"], {
      encoding: "utf8",
      windowsHide: true,
    });
    assert.notEqual(merge.status, 0);

    const result = checkGuard({
      repository: fixture.repository,
      base: fixture.base,
      candidate: "index",
    });
    const status = statusGuard({
      repository: fixture.repository,
      base: fixture.base,
      candidate: "index",
    });

    assert.equal(result.verdict, "indeterminate");
    assert.equal(result.coverage, "partial");
    assert.equal(result.errorCount, 1);
    assert.match(result.errors[0].message, /unsupported git change status u/i);
    assert.equal(status.verdict, "indeterminate");
    assert.equal(status.runId, result.runId);
  } finally {
    cleanup(fixture.repository);
  }
});

test("the analyzed bytes, not clean-filter output, define authorization identity", () => {
  const fixture = createRepo(`import assert from "node:assert/strict";\nassert.equal(value(), 1);\n`);
  try {
    writeFileSync(path.join(fixture.repository, "filter.mjs"), `process.stdin.resume();\nprocess.stdin.on("end", () => process.stdout.write("canonical\\n"));\n`);
    writeFileSync(path.join(fixture.repository, ".gitattributes"), "test/*.js filter=ockle-canonical\n");
    git(fixture.repository, "config", "filter.ockle-canonical.clean", "node filter.mjs");
    git(fixture.repository, "add", ".gitattributes", "filter.mjs");
    git(fixture.repository, "commit", "-qm", "configure clean filter");
    fixture.base = git(fixture.repository, "rev-parse", "HEAD");

    writeTest(fixture.repository, `import assert from "node:assert/strict";\nassert.equal(value(), 2);\n`);
    const first = checkGuard({ repository: fixture.repository, base: fixture.base, store: false });
    const receipt = {
      schemaVersion: 1,
      policy: POLICY,
      inputDigest: first.input.digest,
      findingIds: first.findings.items.map((finding) => finding.id),
      authority: { kind: "human-review", id: "review-filtered-input" },
    };

    writeTest(fixture.repository, `import assert from "node:assert/strict";\nassert.equal(value(), 3);\n`);
    const second = checkGuard({
      repository: fixture.repository,
      base: fixture.base,
      authorization: receipt,
      store: false,
    });

    assert.notEqual(second.input.digest, first.input.digest);
    assert.equal(second.verdict, "blocked");
    assert.equal(second.authorization.status, "rejected");
    assert.equal(second.authorization.reason, "input-digest-mismatch");
  } finally {
    cleanup(fixture.repository);
  }
});

test("only changed supported test paths are parsed", () => {
  const fixture = createRepo(`import assert from "node:assert/strict";\nassert.equal(value(), 1);\n`);
  try {
    writeTest(fixture.repository, `import assert from "node:assert/strict";\nassert.equal(value(, 99);\n`, "test/unchanged-legacy.test.js");
    git(fixture.repository, "add", "test/unchanged-legacy.test.js");
    git(fixture.repository, "commit", "-qm", "add unchanged legacy fixture");
    fixture.base = git(fixture.repository, "rev-parse", "HEAD");

    writeTest(fixture.repository, `import assert from "node:assert/strict";\nassert.equal(value(), 1);\nassert.equal(other(), 2);\n`);
    const result = checkGuard({ repository: fixture.repository, base: fixture.base, store: false });

    assert.equal(result.verdict, "clear");
    assert.equal(result.coverage, "complete");
    assert.equal(result.errors.length, 0);
  } finally {
    cleanup(fixture.repository);
  }
});

test("a committed candidate can be checked by ref and default store stays in Git metadata", () => {
  const fixture = createRepo(`import assert from "node:assert/strict";\nassert.equal(value(), 1);\n`);
  try {
    writeTest(fixture.repository, `import assert from "node:assert/strict";\nassert.equal(value(), 2);\n`);
    git(fixture.repository, "add", ".");
    git(fixture.repository, "commit", "-qm", "candidate");
    const candidate = git(fixture.repository, "rev-parse", "HEAD");
    const result = checkGuard({ repository: fixture.repository, base: fixture.base, candidate });
    const store = defaultStorePath(fixture.repository);

    assert.equal(result.input.candidate.kind, "ref");
    assert.equal(result.verdict, "blocked");
    assert.ok(existsSync(path.join(store, "latest.json")));
    assert.equal(git(fixture.repository, "status", "--porcelain"), "");
  } finally {
    cleanup(fixture.repository);
  }
});

test("the CLI accepts a trusted authorization file outside the candidate tree", () => {
  const fixture = createRepo(`import assert from "node:assert/strict";\nassert.equal(value(), 1);\n`);
  const receiptDirectory = mkdtempSync(path.join(os.tmpdir(), "ockle-receipt-test-"));
  try {
    writeTest(fixture.repository, `import assert from "node:assert/strict";\nassert.equal(value(), 2);\n`);
    const blocked = checkGuard({ repository: fixture.repository, base: fixture.base, store: false });
    const receipt = {
      schemaVersion: 1,
      policy: POLICY,
      inputDigest: blocked.input.digest,
      findingIds: blocked.findings.items.map((finding) => finding.id),
      authority: { kind: "human-review", id: "review-44" },
    };
    const receiptFile = path.join(receiptDirectory, "authorization.json");
    writeFileSync(receiptFile, `${JSON.stringify(receipt)}\n`);
    const result = spawnSync(process.execPath, [
      cli,
      "check",
      "--repo", fixture.repository,
      "--base", fixture.base,
      "--authorization-file", receiptFile,
      "--no-store",
    ], { encoding: "utf8", windowsHide: true });

    assert.equal(result.status, 0);
    const output = JSON.parse(result.stdout);
    assert.equal(output.verdict, "clear");
    assert.equal(output.authorization.status, "applied");
    assert.equal(output.authorization.applied, 1);
  } finally {
    cleanup(fixture.repository);
    cleanup(receiptDirectory);
  }
});

test("the CLI keeps a multi-finding machine response within 2 KiB", () => {
  const baseLines = [
    `import assert from "node:assert/strict";`,
    ...Array.from({ length: 12 }, (_, index) => `assert.equal(value(${index + 1}), ${index + 1});`),
  ];
  const candidateLines = [
    `import assert from "node:assert/strict";`,
    ...Array.from({ length: 12 }, (_, index) => `assert.equal(value(${index + 1}), ${index + 101});`),
  ];
  const fixture = createRepo(baseLines.join("\n"));
  try {
    writeTest(fixture.repository, candidateLines.join("\n"));
    const result = spawnSync(process.execPath, [
      cli,
      "check",
      "--repo", fixture.repository,
      "--base", fixture.base,
      "--no-store",
    ], { encoding: "utf8", windowsHide: true });
    assert.equal(result.status, 1);
    assert.ok(Buffer.byteLength(result.stdout, "utf8") <= 2 * 1024);
    const parsed = JSON.parse(result.stdout);
    assert.equal(parsed.findings.total, 12);
    assert.ok(parsed.findings.nextCursor !== null);
  } finally {
    cleanup(fixture.repository);
  }
});

test("the CLI distinguishes indeterminate verdicts from invocation errors", () => {
  const fixture = createRepo(`import assert from "node:assert/strict";\nassert.equal(value(), 1);\n`);
  try {
    writeTest(fixture.repository, `import assert from "node:assert/strict";\nassert.equal(value(, 1);\n`);
    const indeterminate = spawnSync(process.execPath, [
      cli, "check", "--repo", fixture.repository, "--base", fixture.base, "--no-store",
    ], { encoding: "utf8", windowsHide: true });
    const invocationError = spawnSync(process.execPath, [
      cli, "check", "--repo", fixture.repository, "--base", fixture.base, "--unknown", "value",
    ], { encoding: "utf8", windowsHide: true });

    assert.equal(indeterminate.status, 2);
    assert.equal(JSON.parse(indeterminate.stdout).verdict, "indeterminate");
    assert.equal(invocationError.status, 4);
    assert.equal(JSON.parse(invocationError.stdout).operation, "error");
  } finally {
    cleanup(fixture.repository);
  }
});

test("the CLI rejects unknown, duplicate, and operation-inapplicable options", () => {
  const fixture = createRepo(`import assert from "node:assert/strict";\nassert.equal(value(), 1);\n`);
  try {
    const unknown = spawnSync(process.execPath, [
      cli, "check", "--repo", fixture.repository, "--base", fixture.base,
      "--canddiate", "HEAD", "--no-store",
    ], { encoding: "utf8", windowsHide: true });
    const duplicate = spawnSync(process.execPath, [
      cli, "check", "--repo", fixture.repository, "--base", fixture.base,
      "--candidate", "HEAD", "--candidate", "worktree", "--no-store",
    ], { encoding: "utf8", windowsHide: true });
    const inapplicable = spawnSync(process.execPath, [
      cli, "details", "--repo", fixture.repository, "--run-id", "missing", "--base", fixture.base,
    ], { encoding: "utf8", windowsHide: true });

    for (const result of [unknown, duplicate, inapplicable]) {
      assert.equal(result.status, 4);
      assert.equal(JSON.parse(result.stdout).operation, "error");
    }
    assert.match(JSON.parse(unknown.stdout).error.message, /unknown option.*canddiate/i);
    assert.match(JSON.parse(duplicate.stdout).error.message, /duplicate option.*candidate/i);
    assert.match(JSON.parse(inapplicable.stdout).error.message, /not valid.*details/i);
  } finally {
    cleanup(fixture.repository);
  }
});

test("the CLI emits JSON and uses blocked exit code", () => {
  const fixture = createRepo(`import assert from "node:assert/strict";\nassert.equal(value(), 1);\n`);
  try {
    writeTest(fixture.repository, `import assert from "node:assert/strict";\nassert.equal(value(), 2);\n`);
    const result = spawnSync(process.execPath, [cli, "check", "--repo", fixture.repository, "--base", fixture.base, "--no-store"], {
      encoding: "utf8",
      windowsHide: true,
    });
    assert.equal(result.status, 1);
    const output = JSON.parse(result.stdout);
    assert.equal(output.operation, "check");
    assert.equal(output.verdict, "blocked");
    assert.equal(result.stderr, "");
  } finally {
    cleanup(fixture.repository);
  }
});
