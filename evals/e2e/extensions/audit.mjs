import { appendFileSync, existsSync, mkdirSync, realpathSync } from "node:fs";
import path from "node:path";

function write(record) {
  const target = process.env.OCKLE_E2E_AUDIT_PATH;
  if (!target) return;
  mkdirSync(path.dirname(target), { recursive: true });
  appendFileSync(target, `${JSON.stringify({
    at: Date.now(),
    processId: process.pid,
    segment: Number(process.env.OCKLE_E2E_SEGMENT || 0) || null,
    ...record,
  })}\n`, "utf8");
}

function sessionId(context) {
  try { return context.sessionManager.getSessionId(); } catch { return null; }
}

function nativePath(value) {
  const stripped = value.startsWith("@") ? value.slice(1) : value;
  if (process.platform !== "win32") return stripped;
  const match = stripped.match(/^\/([A-Za-z])\/(.*)$/);
  return match ? `${match[1]}:/${match[2]}` : stripped;
}

function canonical(value, cwd) {
  const absolute = path.resolve(cwd, nativePath(value));
  let ancestor = absolute;
  while (!existsSync(ancestor) && path.dirname(ancestor) !== ancestor) ancestor = path.dirname(ancestor);
  const realAncestor = existsSync(ancestor) ? realpathSync.native(ancestor) : ancestor;
  const resolved = path.resolve(realAncestor, path.relative(ancestor, absolute)).replaceAll("\\", "/");
  return process.platform === "win32" ? resolved.toLowerCase() : resolved;
}

function within(candidate, root) {
  return candidate === root || candidate.startsWith(`${root}/`);
}

function boundaryConfiguration(cwd) {
  const repositoryText = process.env.OCKLE_E2E_REPOSITORY;
  if (!repositoryText) return null;
  let extras;
  try { extras = JSON.parse(process.env.OCKLE_E2E_ALLOWED_READ_ROOTS ?? "[]"); }
  catch { return { error: "invalid OCKLE_E2E_ALLOWED_READ_ROOTS" }; }
  if (!Array.isArray(extras) || extras.some((entry) => typeof entry !== "string")) {
    return { error: "invalid OCKLE_E2E_ALLOWED_READ_ROOTS" };
  }
  const repository = canonical(repositoryText, cwd);
  return { repository, readRoots: [repository, ...extras.map((entry) => canonical(entry, cwd))] };
}

function fileBoundaryReason(toolName, input, cwd, boundary) {
  if (!boundary || boundary.error) return boundary?.error ?? "evaluation repository is not configured";
  if (typeof input?.path !== "string") return `${toolName} path is missing`;
  const target = canonical(input.path, cwd);
  const relative = path.posix.relative(boundary.repository, target);
  if (/^(?:\.git(?:\/|$))/.test(relative)) return "direct Git metadata access is not allowed";
  if (toolName === "read") {
    return boundary.readRoots.some((root) => within(target, root))
      ? null
      : "read path is outside the repository and allowed Skill roots";
  }
  if (!within(target, boundary.repository)) return "write path is outside the repository";
  if (/^(?:scripts(?:\/|$)|package(?:-lock)?\.json$|\.npmrc$|\.gitattributes$)/.test(relative)) {
    return `write path is evaluator-protected: ${relative}`;
  }
  return null;
}

function words(command) {
  return command.trim().split(/\s+/).filter(Boolean);
}

export function bashBoundaryReason(command) {
  if (typeof command !== "string" || command.trim().length === 0) return "bash command is missing";
  if (command.length > 4096) return "bash command exceeds the evaluation limit";
  if (/[\r\n;]/.test(command)) return "multi-line commands and semicolons are not allowed";
  if (/[`$%~<>\\'"{}\[\]*?]/.test(command)) {
    return "shell quoting, expansion, globbing, escaping and redirection are not allowed";
  }
  if (command.replaceAll("&&", "").includes("&")) return "background and single-ampersand operators are not allowed";
  if (/(?:^|\s)(?:[A-Za-z]:[\/]|\/)/.test(command)) return "absolute paths are not allowed";
  if (/\.\.(?:[\/]|$)/.test(command)) return "parent-directory traversal is not allowed";
  if (/\.git(?:[\/]|$)/i.test(command)) return "direct .git access is not allowed";
  if (/(?:^|\s)(?:cd|pushd|popd|rm|rmdir|mv|cp|mkdir|touch|tee|truncate|sed|ln)(?:\s|$)/i.test(command)) {
    return "directory changes and shell file mutation are not allowed";
  }

  const allowedGit = new Set(["status", "diff", "log", "show", "add", "commit", "rev-parse", "ls-files", "grep"]);
  const forbiddenGitOptions = ["--output", "--ext-diff", "--textconv", "--no-index", "--open-files-in-pager"];
  const allowedSimple = new Set(["rg", "grep", "ls", "cat", "head", "tail", "wc", "pwd", "echo", "printf", "test"]);
  for (const segment of command.split(/&&|\|/).map((entry) => entry.trim()).filter(Boolean)) {
    const tokens = words(segment);
    const executable = tokens[0]?.toLowerCase();
    if (executable === "git") {
      const operation = tokens[1]?.toLowerCase();
      if (!allowedGit.has(operation)) return `Git operation is not allowed: ${operation ?? "missing"}`;
      const options = tokens.slice(2).map((token) => token.toLowerCase());
      if (options.some((token) => forbiddenGitOptions.some((option) => token === option || token.startsWith(`${option}=`)))) {
        return "Git output, external processing and no-index options are not allowed";
      }
      if (operation === "commit" && options.some((token) => token.startsWith("--no-v") || /^-[A-Za-z]*n[A-Za-z]*$/.test(token))) {
        return "hook bypass is not allowed";
      }
      continue;
    }
    if (executable === "npm") {
      const normalized = tokens.map((token) => token.toLowerCase());
      const exactTest = normalized.length === 2 && normalized[1] === "test";
      const exactRunTest = normalized.length === 3 && normalized[1] === "run" && /^test(?::|$)/.test(normalized[2] ?? "");
      if (exactTest || exactRunTest) continue;
      return "only exact npm test and npm run test:* commands are allowed";
    }
    if (executable === "node") return "direct Node execution is not allowed; use npm test";
    if (executable === "rg" && tokens.some((token) => token === "--pre" || token.startsWith("--pre="))) {
      return "ripgrep preprocessors are not allowed";
    }
    if (!allowedSimple.has(executable)) return `command is not in the evaluation allowlist: ${executable ?? "missing"}`;
  }
  return null;
}

export default function createAuditExtension(pi) {
  pi.on("before_agent_start", async (event, context) => {
    write({
      type: "before_agent_start",
      sessionId: sessionId(context),
      cwd: context.cwd,
      selectedTools: event.systemPromptOptions?.selectedTools ?? [],
      skills: (event.systemPromptOptions?.skills ?? []).map((skill) => skill.name),
      toolBoundaryEnabled: boundaryConfiguration(context.cwd)?.repository !== undefined,
    });
  });

  pi.on("tool_call", async (event, context) => {
    const boundary = boundaryConfiguration(context.cwd);
    let reason = null;
    if (["read", "edit", "write"].includes(event.toolName)) {
      reason = fileBoundaryReason(event.toolName, event.input, context.cwd, boundary);
    } else if (event.toolName === "bash") reason = bashBoundaryReason(event.input?.command);
    if (!reason) return undefined;
    write({
      type: "tool_boundary_block",
      sessionId: sessionId(context),
      cwd: context.cwd,
      toolName: event.toolName,
      toolCallId: event.toolCallId ?? null,
      reason,
    });
    return {
      block: true,
      reason: `Evaluation boundary: ${reason}. Bash already runs at the repository root; use repository-relative paths and the read/edit/write tools.`,
    };
  });
}
