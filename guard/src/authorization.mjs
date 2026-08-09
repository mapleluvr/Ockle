import { createHash } from "node:crypto";

function stable(value) {
  if (Array.isArray(value)) return value.map(stable);
  if (!value || typeof value !== "object") return value;
  return Object.fromEntries(Object.keys(value).sort().map((key) => [key, stable(value[key])]));
}

function digest(value) {
  return createHash("sha256").update(JSON.stringify(stable(value))).digest("hex");
}

function metadata(status, receipt, {
  applied = 0,
  remaining = 0,
  reason = null,
} = {}) {
  const authority = receipt?.authority
    && typeof receipt.authority.kind === "string"
    && typeof receipt.authority.id === "string"
    ? {
      kind: receipt.authority.kind.slice(0, 128),
      id: receipt.authority.id.slice(0, 128),
    }
    : null;
  return {
    status,
    receiptId: receipt ? digest(receipt) : null,
    applied,
    remaining,
    authority,
    reason,
  };
}

function reject(result, receipt, reason) {
  return {
    verdict: result.verdict,
    findings: result.findings,
    authorization: metadata("rejected", receipt, {
      remaining: result.findings.length,
      reason,
    }),
  };
}

export function applyAuthorization({ result, input, policy, receipt }) {
  if (!receipt) {
    return {
      verdict: result.verdict,
      findings: result.findings,
      authorization: metadata("none", null, { remaining: result.findings.length }),
    };
  }
  if (result.coverage !== "complete") return reject(result, receipt, "coverage-not-complete");
  if (receipt.schemaVersion !== 1) return reject(result, receipt, "schema-version-mismatch");
  if (receipt.policy?.id !== policy.id || receipt.policy?.version !== policy.version) {
    return reject(result, receipt, "policy-mismatch");
  }
  if (receipt.inputDigest !== input.digest) return reject(result, receipt, "input-digest-mismatch");
  if (!Array.isArray(receipt.findingIds) || receipt.findingIds.some((id) => typeof id !== "string")) {
    return reject(result, receipt, "invalid-finding-ids");
  }
  if (!receipt.authority
    || typeof receipt.authority.kind !== "string"
    || typeof receipt.authority.id !== "string"
    || !receipt.authority.kind
    || !receipt.authority.id
    || receipt.authority.kind.length > 128
    || receipt.authority.id.length > 128) {
    return reject(result, receipt, "invalid-authority");
  }

  if (result.findings.length === 0) return reject(result, receipt, "no-findings-to-authorize");

  const known = new Set(result.findings.map((finding) => finding.id));
  const requested = new Set(receipt.findingIds);
  if ([...requested].some((id) => !known.has(id))) {
    return reject(result, receipt, "unknown-finding-id");
  }

  const findings = result.findings.filter((finding) => !requested.has(finding.id));
  const applied = result.findings.length - findings.length;
  if (findings.length > 0) {
    return {
      verdict: "blocked",
      findings,
      authorization: metadata("partial", receipt, {
        applied,
        remaining: findings.length,
      }),
    };
  }
  return {
    verdict: "clear",
    findings,
    authorization: metadata("applied", receipt, { applied, remaining: 0 }),
  };
}
