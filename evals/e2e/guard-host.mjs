import { sign } from "node:crypto";
import { mkdirSync, writeFileSync } from "node:fs";
import path from "node:path";
import { checkGuard, detailsGuard } from "../../guard/src/index.mjs";
import { createAuthorizationReceipt } from "./grading.mjs";

function expandFindings(repository, storePath, first) {
  const items = [...first.findings.items];
  let cursor = first.findings.nextCursor;
  while (cursor !== null) {
    const page = detailsGuard({ repository, storePath, runId: first.runId, cursor });
    if (page.runId !== first.runId) throw new Error("guard details changed run ID");
    if (page.input?.digest !== first.input?.digest) throw new Error("guard details changed input digest");
    if (page.findings.total !== first.findings.total) throw new Error("guard details changed finding total");
    items.push(...page.findings.items);
    cursor = page.findings.nextCursor;
  }
  if (items.length !== first.findings.total) {
    throw new Error(`guard pagination returned ${items.length}/${first.findings.total} findings`);
  }
  const ids = new Set(items.map((finding) => finding.id));
  if (ids.size !== items.length) throw new Error("guard pagination returned duplicate finding IDs");
  return {
    ...first,
    findings: {
      ...first.findings,
      returned: items.length,
      nextCursor: null,
      items,
    },
  };
}

export function runTrustedGuard({
  repository,
  base,
  candidate,
  authorization,
  storePath,
}) {
  if (!storePath) throw new Error("trusted guard storePath is required");
  mkdirSync(path.dirname(storePath), { recursive: true });
  const first = checkGuard({ repository, base, candidate, authorization, storePath });
  return expandFindings(repository, storePath, first);
}

export function authorizeCandidate({ repository, trustedDirectory, check, authority, signingKey }) {
  if (!signingKey) throw new Error("trusted authorization signing key is required");
  const receipt = createAuthorizationReceipt(check, authority);
  const payload = JSON.stringify(receipt);
  const envelope = {
    schemaVersion: 1,
    algorithm: "Ed25519",
    payload,
    signature: sign(null, Buffer.from(payload), signingKey).toString("base64"),
  };
  mkdirSync(trustedDirectory, { recursive: true });
  const trustedPath = path.join(trustedDirectory, "authorization.json");
  writeFileSync(trustedPath, `${JSON.stringify(envelope, null, 2)}\n`, "utf8");

  const hookDirectory = path.join(repository, ".git", "ockle-e2e");
  mkdirSync(hookDirectory, { recursive: true });
  const hookPath = path.join(hookDirectory, "authorization.json");
  writeFileSync(hookPath, `${JSON.stringify(envelope)}\n`, "utf8");
  return { receipt, envelope, trustedPath, hookPath };
}
