import { spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import { existsSync, readFileSync } from "node:fs";
import path from "node:path";

export class GuardInputError extends Error {}
export class GuardScanError extends Error {
  constructor(message, input = null) {
    super(message);
    this.input = input;
  }
}

function runGit(repository, args, ErrorType = GuardScanError) {
  const result = spawnSync("git", ["-C", repository, ...args], {
    encoding: null,
    windowsHide: true,
    maxBuffer: 128 * 1024 * 1024,
  });
  if (result.status !== 0) {
    const detail = Buffer.concat([result.stderr ?? Buffer.alloc(0), result.stdout ?? Buffer.alloc(0)])
      .toString("utf8")
      .trim();
    throw new ErrorType(`git ${args.join(" ")} failed: ${detail || `exit ${result.status}`}`);
  }
  return result.stdout;
}

function gitText(repository, args, ErrorType) {
  return runGit(repository, args, ErrorType).toString("utf8").trim();
}

function digest(value) {
  return createHash("sha256").update(value).digest("hex");
}

function contentDigest(content) {
  return content === null ? null : digest(content);
}

function parseNullList(buffer) {
  return buffer.toString("utf8").split("\0").filter(Boolean);
}

function parseNameStatus(buffer) {
  const fields = parseNullList(buffer);
  if (fields.length % 2 !== 0) throw new GuardScanError("Unexpected git name-status output.");
  const changes = new Map();
  for (let index = 0; index < fields.length; index += 2) {
    const status = fields[index][0];
    const file = fields[index + 1];
    if (!file) throw new GuardScanError("Git reported a change without a path.");
    if (status === "A") changes.set(file, { base: false, candidate: true });
    else if (status === "D") changes.set(file, { base: true, candidate: false });
    else if (status === "M" || status === "T") changes.set(file, { base: true, candidate: true });
    else throw new GuardScanError(`Unsupported git change status ${fields[index]} for ${file}.`);
  }
  return changes;
}

function resolveCommit(repository, ref) {
  return gitText(repository, ["rev-parse", "--verify", `${ref}^{commit}`], GuardInputError);
}

function resolveTree(repository, commit) {
  return gitText(repository, ["rev-parse", "--verify", `${commit}^{tree}`], GuardInputError);
}

function candidateState(repository, candidate) {
  if (candidate === "worktree" || candidate === "index") {
    return { kind: candidate, head: resolveCommit(repository, "HEAD") };
  }
  const commit = resolveCommit(repository, candidate);
  return { kind: "ref", ref: candidate, commit, tree: resolveTree(repository, commit) };
}

function trackedChanges(repository, baseCommit, state) {
  const common = ["diff", "--name-status", "-z", "--no-renames"];
  if (state.kind === "worktree") {
    return parseNameStatus(runGit(repository, [...common, baseCommit, "--"]));
  }
  if (state.kind === "index") {
    return parseNameStatus(runGit(repository, [...common, "--cached", baseCommit, "--"]));
  }
  return parseNameStatus(runGit(repository, [...common, baseCommit, state.commit, "--"]));
}

function changedPaths(repository, baseCommit, state) {
  const changes = trackedChanges(repository, baseCommit, state);
  if (state.kind === "worktree") {
    for (const file of parseNullList(runGit(repository, ["ls-files", "--others", "--exclude-standard", "-z"]))) {
      const existing = changes.get(file);
      changes.set(file, existing?.base
        ? { base: true, candidate: true }
        : { base: false, candidate: true });
    }
  }
  return changes;
}

function readRefFile(repository, commit, file) {
  return runGit(repository, ["show", `${commit}:${file}`]);
}

function readIndexFile(repository, file) {
  return runGit(repository, ["show", `:${file}`]);
}

function readWorktreeFile(repository, file) {
  const absolute = path.join(repository, file);
  if (!existsSync(absolute)) throw new GuardScanError(`Candidate file disappeared during scan: ${file}`);
  try {
    return readFileSync(absolute);
  } catch (error) {
    throw new GuardScanError(`Cannot read candidate file ${file}: ${error.message}`);
  }
}

function readCandidateFile(repository, state, file) {
  if (state.kind === "worktree") return readWorktreeFile(repository, file);
  if (state.kind === "index") return readIndexFile(repository, file);
  return readRefFile(repository, state.commit, file);
}

function failureInput(policy, base, state, message) {
  const candidate = { ...state, identity: null };
  return {
    digest: digest(JSON.stringify({ policy, baseTree: base.tree, candidate: state.kind, error: message })),
    base,
    candidate,
  };
}

function captureResolved({ repository, base, state, policy, isRelevant }) {
  let changes;
  try {
    changes = changedPaths(repository, base.commit, state);
  } catch (error) {
    if (error instanceof GuardInputError) throw error;
    const scanError = error instanceof GuardScanError ? error : new GuardScanError(error.message);
    scanError.input = failureInput(policy, base, state, scanError.message);
    throw scanError;
  }

  const relevant = [...changes]
    .filter(([file]) => isRelevant(file))
    .sort(([left], [right]) => left.localeCompare(right));
  const baseFiles = new Map();
  const candidateFiles = new Map();
  const entries = [];

  try {
    for (const [file, sides] of relevant) {
      const baseContent = sides.base ? readRefFile(repository, base.commit, file) : null;
      const candidateContent = sides.candidate ? readCandidateFile(repository, state, file) : null;
      if (baseContent !== null) baseFiles.set(file, baseContent.toString("utf8"));
      if (candidateContent !== null) candidateFiles.set(file, candidateContent.toString("utf8"));
      entries.push({
        path: file,
        base: contentDigest(baseContent),
        candidate: contentDigest(candidateContent),
      });
    }
  } catch (error) {
    if (error instanceof GuardInputError) throw error;
    const scanError = error instanceof GuardScanError ? error : new GuardScanError(error.message);
    scanError.input = failureInput(policy, base, state, scanError.message);
    throw scanError;
  }

  const identity = digest(JSON.stringify(entries));
  const candidate = { ...state, identity };
  const input = {
    digest: digest(JSON.stringify({ policy, baseTree: base.tree, candidate: identity })),
    base,
    candidate,
  };
  return { input, baseFiles, candidateFiles, entries, state, base };
}

export function captureGuardSnapshot({ repository, base: baseRef, candidate = "worktree", policy, isRelevant }) {
  const baseCommit = resolveCommit(repository, baseRef);
  const base = { ref: baseRef, commit: baseCommit, tree: resolveTree(repository, baseCommit) };
  const state = candidateState(repository, candidate);
  return captureResolved({ repository, base, state, policy, isRelevant });
}

export function verifyGuardSnapshot({ repository, snapshot, policy, isRelevant }) {
  if (snapshot.state.kind === "ref") return true;
  const currentState = candidateState(repository, snapshot.state.kind);
  const current = captureResolved({
    repository,
    base: snapshot.base,
    state: currentState,
    policy,
    isRelevant,
  });
  return current.input.digest === snapshot.input.digest;
}
