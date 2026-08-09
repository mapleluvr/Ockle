import assert from "node:assert/strict";
import { existsSync, readFileSync, readdirSync, statSync } from "node:fs";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const skillsRoot = path.join(root, "skills");
const coreSkills = [
  "test-driven-development",
  "systematic-debugging",
  "receiving-code-review",
];

function walkFiles(directory) {
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const absolute = path.join(directory, entry.name);
    return entry.isDirectory() ? walkFiles(absolute) : [absolute];
  });
}

function parseFrontmatter(markdown, source) {
  const lines = markdown.replaceAll("\r\n", "\n").split("\n");
  assert.equal(lines[0], "---", `${source}: missing frontmatter start`);
  const end = lines.indexOf("---", 1);
  assert.notEqual(end, -1, `${source}: missing frontmatter end`);

  const metadata = {};
  for (const line of lines.slice(1, end)) {
    const separator = line.indexOf(":");
    assert.ok(separator > 0, `${source}: invalid frontmatter field`);
    const key = line.slice(0, separator).trim();
    assert.equal(Object.hasOwn(metadata, key), false, `${source}: duplicate ${key}`);
    metadata[key] = line.slice(separator + 1).trim();
  }
  return metadata;
}

function markdownTargets(markdown) {
  return [...markdown.matchAll(/!?\[[^\]]*\]\(([^)]+)\)/g)]
    .map((match) => match[1].trim().replace(/^<|>$/g, ""))
    .filter((target) => target && !target.startsWith("#") && !/^[a-z]+:/i.test(target));
}

test("core skill entrypoints expose bounded Agent Skills metadata", () => {
  for (const skill of coreSkills) {
    const entrypoint = path.join(skillsRoot, skill, "SKILL.md");
    const markdown = readFileSync(entrypoint, "utf8");
    const metadata = parseFrontmatter(markdown, path.relative(root, entrypoint));

    assert.deepEqual(Object.keys(metadata).sort(), ["description", "name"]);
    assert.equal(metadata.name, skill);
    assert.ok(metadata.description.length > 0);
    assert.ok(metadata.description.length <= 300);

    const words = markdown.trim().split(/\s+/).length;
    assert.ok(words <= 1600, `${skill}: ${words} words exceeds the 1600-word entrypoint budget`);
  }
});

test("core runtime text contains no extension or legacy process vocabulary", () => {
  const forbidden = [
    /\b(?:milestone|package|frontier|fullctl|subagent|worktree)\b/i,
    /dispatch group|workflow transition|state\.json/i,
    /superpowers:/i,
  ];

  for (const skill of coreSkills) {
    for (const file of walkFiles(path.join(skillsRoot, skill))) {
      if (!/[.](?:md|ts|js|mjs|sh)$/.test(file)) continue;
      const text = readFileSync(file, "utf8");
      for (const pattern of forbidden) {
        assert.doesNotMatch(text, pattern, `${path.relative(root, file)} leaks extension vocabulary`);
      }
    }
  }
});

test("core skill references resolve inside the owning skill directory", () => {
  for (const skill of coreSkills) {
    const directory = path.join(skillsRoot, skill);
    for (const file of walkFiles(directory).filter((candidate) => candidate.endsWith(".md"))) {
      const markdown = readFileSync(file, "utf8");
      for (const target of markdownTargets(markdown)) {
        const pathname = target.split("#", 1)[0];
        const resolved = path.resolve(path.dirname(file), pathname);
        const relative = path.relative(directory, resolved);
        assert.ok(relative && !relative.startsWith("..") && !path.isAbsolute(relative));
        assert.ok(existsSync(resolved), `${path.relative(root, file)}: unresolved ${target}`);
      }
    }
  }
});

test("runtime files have provenance entries without freezing local prose", () => {
  const manifest = JSON.parse(readFileSync(path.join(root, "upstream-manifest.json"), "utf8"));
  const recorded = new Set(manifest.files.map((entry) => entry.path.replaceAll("/", path.sep)));
  const runtime = coreSkills.flatMap((skill) => walkFiles(path.join(skillsRoot, skill)))
    .map((file) => path.relative(root, file));

  assert.deepEqual([...recorded].sort(), runtime.sort());
  for (const file of runtime) assert.ok(statSync(path.join(root, file)).isFile());
});
