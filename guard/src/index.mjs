import { randomBytes } from "node:crypto";

import { applyAuthorization } from "./authorization.mjs";
import { checkAssertionChanges } from "./assertion-change.mjs";
import {
  captureGuardSnapshot,
  GuardScanError,
  verifyGuardSnapshot,
} from "./snapshot.mjs";
import {
  defaultStorePath,
  readLatest,
  readRecord,
  writeRecord,
} from "./store.mjs";

export const SCHEMA_VERSION = 1;
export const POLICY = Object.freeze({ id: "assertion-change", version: "1" });
export const EXIT_CODES = Object.freeze({ clear: 0, blocked: 1, indeterminate: 2, unchecked: 3 });

const SOURCE_RE = /\.[cm]?[jt]sx?$/i;
const TEST_RE = /(^|\/)(?:test|tests|spec|specs|__tests__)(?:\/|$)|(?:^|\/)[^/]+\.(?:test|spec)\.[cm]?[jt]sx?$/i;
const MAX_PAGE_SIZE = 100;
const MAX_PAGE_BYTES = 16 * 1024;
const DEFAULT_PAGE_SIZE = 8;
const DEFAULT_PAGE_BYTES = 1024;

function isGuardFile(file) {
  return SOURCE_RE.test(file) && TEST_RE.test(file);
}

function validatePageOptions({ pageSize = DEFAULT_PAGE_SIZE, maxBytes = DEFAULT_PAGE_BYTES } = {}) {
  if (!Number.isInteger(pageSize) || pageSize < 1 || pageSize > MAX_PAGE_SIZE) {
    throw new Error(`pageSize must be an integer from 1 to ${MAX_PAGE_SIZE}.`);
  }
  if (!Number.isInteger(maxBytes) || maxBytes < 512 || maxBytes > MAX_PAGE_BYTES) {
    throw new Error(`maxBytes must be an integer from 512 to ${MAX_PAGE_BYTES}.`);
  }
  return { pageSize, maxBytes };
}

function compactFinding(finding, maxBytes) {
  const compact = {
    id: finding.id,
    rule: finding.rule,
    kind: finding.kind,
    file: finding.file,
    line: finding.line,
    column: finding.column,
    fileTruncated: false,
  };
  const fits = (candidate) => Buffer.byteLength(JSON.stringify({
    total: 1,
    returned: 1,
    items: [candidate],
    nextCursor: null,
    cursor: 0,
  })) <= maxBytes;
  if (fits(compact)) return compact;

  const prefixLength = Math.max(8, Math.min(96, maxBytes - 260));
  return {
    id: finding.id,
    rule: finding.rule,
    kind: finding.kind,
    file: `${String(finding.file).slice(0, prefixLength)}...`,
    line: finding.line,
    column: finding.column,
    fileTruncated: true,
  };
}

function pageFindings(findings, { cursor = 0, pageSize, maxBytes }) {
  if (!Number.isInteger(cursor) || cursor < 0 || cursor > findings.length) {
    throw new Error("cursor must be an integer within the findings list.");
  }
  const items = [];
  let next = cursor;
  while (next < findings.length && items.length < pageSize) {
    const fullCandidate = [...items, findings[next]];
    const fullPage = {
      total: findings.length,
      returned: fullCandidate.length,
      items: fullCandidate,
      nextCursor: next + 1 < findings.length ? next + 1 : null,
      cursor,
    };
    if (Buffer.byteLength(JSON.stringify(fullPage)) <= maxBytes) {
      items.push(findings[next]);
      next += 1;
      continue;
    }

    if (items.length > 0) break;
    const compact = compactFinding(findings[next], maxBytes);
    const compactPage = {
      total: findings.length,
      returned: 1,
      items: [compact],
      nextCursor: next + 1 < findings.length ? next + 1 : null,
      cursor,
    };
    items.push(compact);
    next += 1;
    if (Buffer.byteLength(JSON.stringify(compactPage)) > maxBytes) {
      throw new Error("Finding cannot fit within the configured page budget.");
    }
  }
  return {
    total: findings.length,
    returned: items.length,
    items,
    nextCursor: next < findings.length ? next : null,
    cursor,
  };
}

function boundedErrors(errors) {
  return errors.slice(0, 3).map((error) => ({
    ...error,
    message: String(error.message).slice(0, 240),
  }));
}

function noAuthorization(remaining = 0) {
  return {
    status: "none",
    receiptId: null,
    applied: 0,
    remaining,
    authority: null,
    reason: null,
  };
}

function envelope(record, operation, options) {
  return {
    schemaVersion: SCHEMA_VERSION,
    operation,
    runId: record.runId ?? null,
    policy: POLICY,
    input: record.input,
    verdict: record.verdict,
    coverage: record.coverage,
    findings: pageFindings(record.allFindings ?? [], options),
    errors: boundedErrors(record.errors ?? []),
    errorCount: (record.errors ?? []).length,
    authorization: record.authorization ?? noAuthorization((record.allFindings ?? []).length),
  };
}

function runId() {
  return `${Date.now().toString(36)}-${randomBytes(6).toString("hex")}`;
}

function indeterminateResult(message) {
  return {
    verdict: "indeterminate",
    coverage: "partial",
    findings: [],
    errors: [{ side: "candidate", message }],
  };
}

function capture(repository, base, candidate) {
  return captureGuardSnapshot({
    repository,
    base,
    candidate,
    policy: POLICY,
    isRelevant: isGuardFile,
  });
}

export function checkGuard({
  repository,
  base,
  candidate = "worktree",
  store = true,
  storePath,
  authorization,
  pageSize = DEFAULT_PAGE_SIZE,
  maxBytes = DEFAULT_PAGE_BYTES,
} = {}) {
  const options = validatePageOptions({ pageSize, maxBytes });
  if (!repository) throw new Error("repository is required.");
  if (!base) throw new Error("base is required.");

  let snapshot;
  let result;
  try {
    snapshot = capture(repository, base, candidate);
    result = checkAssertionChanges({
      baseFiles: snapshot.baseFiles,
      candidateFiles: snapshot.candidateFiles,
    });
    if (!verifyGuardSnapshot({
      repository,
      snapshot,
      policy: POLICY,
      isRelevant: isGuardFile,
    })) {
      result = indeterminateResult("Candidate changed while the guard was scanning.");
    }
  } catch (error) {
    if (!(error instanceof GuardScanError)) throw error;
    snapshot = { input: error.input };
    result = indeterminateResult(error.message);
  }

  const authorized = applyAuthorization({
    result,
    input: snapshot.input,
    policy: POLICY,
    receipt: authorization,
  });
  const record = {
    schemaVersion: SCHEMA_VERSION,
    operation: "check",
    runId: runId(),
    createdAt: new Date().toISOString(),
    policy: POLICY,
    input: snapshot.input,
    verdict: authorized.verdict,
    coverage: result.coverage,
    allFindings: authorized.findings,
    errors: result.errors,
    authorization: authorized.authorization,
  };
  if (store) writeRecord(storePath ?? defaultStorePath(repository), record);
  return envelope(record, "check", options);
}

export function statusGuard({
  repository,
  base,
  candidate = "worktree",
  storePath,
  pageSize = DEFAULT_PAGE_SIZE,
  maxBytes = DEFAULT_PAGE_BYTES,
} = {}) {
  const options = validatePageOptions({ pageSize, maxBytes });
  if (!repository) throw new Error("repository is required.");
  if (!base) throw new Error("base is required.");

  let snapshot;
  try {
    snapshot = capture(repository, base, candidate);
  } catch (error) {
    if (!(error instanceof GuardScanError)) throw error;
    const latest = readLatest(storePath ?? defaultStorePath(repository));
    if (latest?.input?.digest === error.input.digest) {
      return envelope({ ...latest, input: error.input }, "status", options);
    }
    return envelope({
      input: error.input,
      runId: null,
      verdict: "indeterminate",
      coverage: "partial",
      allFindings: [],
      errors: [{ side: "candidate", message: error.message }],
      authorization: noAuthorization(0),
    }, "status", options);
  }

  const latest = readLatest(storePath ?? defaultStorePath(repository));
  if (!latest || latest.input?.digest !== snapshot.input.digest) {
    return envelope({
      input: snapshot.input,
      runId: null,
      verdict: "unchecked",
      coverage: "unknown",
      allFindings: [],
      errors: [],
      authorization: noAuthorization(0),
    }, "status", options);
  }
  return envelope({ ...latest, input: snapshot.input }, "status", options);
}

export function detailsGuard({
  repository,
  runId: requestedRunId,
  storePath,
  cursor = 0,
  pageSize = DEFAULT_PAGE_SIZE,
  maxBytes = DEFAULT_PAGE_BYTES,
} = {}) {
  const options = validatePageOptions({ pageSize, maxBytes });
  if (!repository) throw new Error("repository is required.");
  if (!requestedRunId) throw new Error("runId is required.");
  const record = readRecord(storePath ?? defaultStorePath(repository), requestedRunId);
  if (!record) throw new Error(`Unknown guard run: ${requestedRunId}`);
  return envelope(record, "details", { ...options, cursor });
}
