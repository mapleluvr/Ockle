import { readFileSync, readdirSync } from "node:fs";
import path from "node:path";

function readJsonl(file) {
  return readFileSync(file, "utf8")
    .split("\n")
    .filter((line) => line.length > 0)
    .map((line, index) => {
      try {
        return JSON.parse(line);
      } catch (error) {
        throw new Error(`invalid session JSONL at line ${index + 1}: ${error.message}`);
      }
    });
}

function platformPath(value) {
  if (process.platform !== "win32") return value;
  const match = /^\/([A-Za-z])\/(.*)$/.exec(value.replaceAll("\\", "/"));
  return match ? `${match[1]}:/${match[2]}` : value;
}

function canonical(value) {
  const normalized = path.resolve(platformPath(value)).replaceAll("\\", "/");
  return process.platform === "win32" ? normalized.toLowerCase() : normalized;
}

function within(candidate, root) {
  return candidate === root || candidate.startsWith(`${root}/`);
}

function textParts(content) {
  if (typeof content === "string") return [content];
  if (!Array.isArray(content)) return [];
  return content.filter((part) => part.type === "text" && typeof part.text === "string").map((part) => part.text);
}

export function findSessionFile(sessionDirectory) {
  const files = readdirSync(sessionDirectory)
    .filter((name) => name.endsWith(".jsonl"))
    .map((name) => path.join(sessionDirectory, name));
  if (files.length !== 1) throw new Error(`expected one Pi session file, found ${files.length}`);
  return files[0];
}

export function readSessionEvidence({
  sessionFile,
  repository,
  allowedSkillPaths = [],
  allowedReadRoots = [],
}) {
  const entries = readJsonl(sessionFile);
  const repositoryRoot = canonical(repository);
  const allowedSkills = new Map(allowedSkillPaths.map((file) => [canonical(file), file]));
  const allowedRoots = [
    ...allowedSkillPaths.map((file) => canonical(path.dirname(file))),
    ...allowedReadRoots.map(canonical),
  ];
  const skillReads = new Set();
  const externalFileAccesses = new Set();
  const externalFileCallIds = new Set();
  const suspiciousBashCommands = [];
  const usage = { input: 0, output: 0, reasoning: 0, cacheRead: 0, cacheWrite: 0, totalTokens: 0 };
  const toolCallsByName = {};
  let assistantTurns = 0;
  let toolCalls = 0;
  let finalText = "";
  let sessionId = null;

  for (const entry of entries) {
    if (entry.type === "session") sessionId = entry.id ?? sessionId;
    if (entry.type !== "message") continue;
    const message = entry.message;
    if (message?.role !== "assistant") continue;
    assistantTurns += 1;
    for (const key of Object.keys(usage)) usage[key] += Number(message.usage?.[key] ?? 0);
    const texts = textParts(message.content);
    if (texts.length > 0) finalText = texts.join("\n");
    if (!Array.isArray(message.content)) continue;
    for (const part of message.content) {
      if (part.type !== "toolCall") continue;
      toolCalls += 1;
      toolCallsByName[part.name] = (toolCallsByName[part.name] ?? 0) + 1;
      const argumentsValue = part.arguments ?? {};
      if (["read", "edit", "write"].includes(part.name) && typeof argumentsValue.path === "string") {
        const nativePath = platformPath(argumentsValue.path);
        const resolved = canonical(path.isAbsolute(nativePath)
          ? nativePath
          : path.join(repository, nativePath));
        if (allowedSkills.has(resolved)) skillReads.add(allowedSkills.get(resolved));
        else if (!within(resolved, repositoryRoot) && !allowedRoots.some((root) => within(resolved, root))) {
          externalFileAccesses.add(argumentsValue.path);
          externalFileCallIds.add(part.id ?? part.toolCallId ?? null);
        }
      }
      if (part.name === "bash" && typeof argumentsValue.command === "string") {
        const command = argumentsValue.command;
        if (/(^|[\s"'])\.\.[\\/]|[A-Za-z]:[\\/]|\/(?:home|tmp|var|Users|mnt)\//.test(command)) {
          suspiciousBashCommands.push(command);
        }
      }
    }
  }

  return {
    sessionId,
    assistantTurns,
    toolCalls,
    toolCallsByName,
    skillReads: [...skillReads],
    externalFileAccesses: [...externalFileAccesses],
    externalFileCallIds: [...externalFileCallIds],
    suspiciousBashCommands,
    usage,
    finalTextBytes: Buffer.byteLength(finalText),
  };
}
