from __future__ import annotations

import asyncio
import hashlib
import json
import re
import shlex
from pathlib import Path
from typing import Any

from pier.agents.installed.base import BaseInstalledAgent, NonZeroAgentExitCodeError
from pier.environments.base import BaseEnvironment
from pier.models.agent.context import AgentContext
from pier.models.agent.install import AgentInstallSpec, InstallStep
from pier.models.agent.network import NetworkAllowlist

PI_VERSION = "0.84.1"
PI_TARBALL_URL = "https://registry.npmjs.org/@earendil-works/pi-coding-agent/-/pi-coding-agent-0.84.1.tgz"
PI_TARBALL_SHA256 = "a69a18596017e91955fd0fd677be69fab5b6ea01d5b06207bcee34ee1522bc20"
PI_SHRINKWRAP_SHA256 = "a724da15dc849d0ab2fe346845f8986b059ab89339a03a365b5910b23217c0c3"
NODE_VERSION = "24.18.0"
NODE_SHA256 = "55aa7153f9d88f28d765fcdad5ae6945b5c0f98a36881703817e4c450fa76742"
MODEL_PROVIDER = "Mapleluv"
MODEL_ID = "deepseek-v4-flash"
CONDITIONS = frozenset({"bare", "inner", "full"})
REMOTE_PI_DIR = "/opt/ockle/pi"
REMOTE_SKILLS_DIR = "/opt/ockle/skills"
REMOTE_SESSION_DIR = "/logs/agent/sessions"
GUARD_ROOT = "/opt/ockle/guard"
GUARD_BIN = f"{GUARD_ROOT}/bin/ockle-guard.mjs"
GUARD_BASE_FILE = "/opt/ockle/base-commit"
GUARD_FINAL_COMMIT = "/logs/agent/guard-final-commit.json"
GUARD_FINAL_COMMIT_EXIT = "/logs/agent/guard-final-commit-exit.txt"
GUARD_FINAL_WORKTREE = "/logs/agent/guard-final-worktree.json"
GUARD_FINAL_WORKTREE_EXIT = "/logs/agent/guard-final-worktree-exit.txt"
GIT_FINAL_STATUS = "/logs/agent/git-final-status.txt"
GIT_FINAL_STATUS_EXIT = "/logs/agent/git-final-status-exit.txt"
SECRET_SCAN_PATH = "/opt/ockle/secret-scan.cjs"
AGENT_USER = "ockle"

SKILL_NAMES = (
    "test-driven-development",
    "systematic-debugging",
    "receiving-code-review",
)

SYSTEM_APPEND = """You are running inside a DeepSWE agent container. Work only in the repository at /app. Complete the user's feature request, run relevant tests, and commit every intended change to the current branch; uncommitted changes are not delivered. Do not inspect /logs or evaluator artifacts."""


def build_models_config() -> dict[str, Any]:
    return {
        "providers": {
            MODEL_PROVIDER: {
                "baseUrl": "https://la.mapleluv.icu/v1",
                "api": "openai-responses",
                "apiKey": "$MAPLELUV_API_KEY",
                "models": [
                    {
                        "id": MODEL_ID,
                        "name": "DeepSeek V4 Flash",
                        "reasoning": True,
                        "input": ["text"],
                        "contextWindow": 1_048_000,
                        "maxTokens": 384_000,
                        "cost": {
                            "input": 0,
                            "output": 0,
                            "cacheRead": 0,
                            "cacheWrite": 0,
                        },
                        "thinkingLevelMap": {
                            "off": "none",
                            "minimal": "minimal",
                            "low": "low",
                            "medium": "medium",
                            "high": "high",
                            "xhigh": "xhigh",
                            "max": "max",
                        },
                        "compat": {
                            "supportsDeveloperRole": False,
                            "supportsReasoningEffort": True,
                            "supportsStore": False,
                            "sendSessionIdHeader": True,
                        },
                    }
                ],
            }
        }
    }


def build_settings() -> dict[str, Any]:
    return {
        "packages": [],
        "extensions": [],
        "skills": [],
        "prompts": [],
        "themes": [],
        "defaultProjectTrust": "never",
        "defaultProvider": MODEL_PROVIDER,
        "defaultModel": MODEL_ID,
        "defaultThinkingLevel": "max",
        "compaction": {"enabled": False},
        "retry": {
            "enabled": True,
            "maxRetries": 3,
            "baseDelayMs": 2000,
            "provider": {
                "timeoutMs": 3_600_000,
                "maxRetries": 0,
                "maxRetryDelayMs": 60_000,
            },
        },
    }


def build_pi_arguments(condition: str, instruction: str) -> list[str]:
    if condition not in CONDITIONS:
        raise ValueError(f"unknown condition: {condition}")
    if not instruction:
        raise ValueError("instruction is required")

    args = [
        "pi",
        "--mode",
        "json",
        "--print",
        "--no-extensions",
        "--no-skills",
    ]
    if condition != "bare":
        for name in SKILL_NAMES:
            args.extend(["--skill", f"{REMOTE_SKILLS_DIR}/{name}/SKILL.md"])
    args.extend(
        [
            "--no-prompt-templates",
            "--no-themes",
            "--append-system-prompt",
            SYSTEM_APPEND,
            "--session-dir",
            REMOTE_SESSION_DIR,
            "--model",
            f"{MODEL_PROVIDER}/{MODEL_ID}",
            "--thinking",
            "max",
            instruction,
        ]
    )
    return args


def trusted_git_environment(*, final_index: bool = False) -> str:
    config = {
        "safe.directory": "/app",
        "diff.external": "",
        "core.attributesfile": "/dev/null",
        "core.hooksPath": "/dev/null",
        "core.fsmonitor": "false",
        "core.untrackedCache": "false",
        "core.worktree": "/app",
        "core.bare": "false",
    }
    index_path = "/tmp/ockle-final-index" if final_index else "/app/.git/index"
    parts = [
        "env",
        "-u GIT_DIR",
        "-u GIT_WORK_TREE",
        "-u GIT_COMMON_DIR",
        "-u GIT_OBJECT_DIRECTORY",
        "-u GIT_ALTERNATE_OBJECT_DIRECTORIES",
        "-u GIT_NAMESPACE",
        "-u GIT_CONFIG_PARAMETERS",
        "-u GIT_EXTERNAL_DIFF",
        "GIT_DIR=/app/.git",
        "GIT_WORK_TREE=/app",
        "GIT_COMMON_DIR=/app/.git",
        f"GIT_INDEX_FILE={index_path}",
        "GIT_OBJECT_DIRECTORY=/app/.git/objects",
        "GIT_ALTERNATE_OBJECT_DIRECTORIES=",
        "GIT_ATTR_SOURCE=$base",
        "GIT_CONFIG_GLOBAL=/dev/null",
        "GIT_CONFIG_NOSYSTEM=1",
        "GIT_ATTR_NOSYSTEM=1",
        "GIT_NO_REPLACE_OBJECTS=1",
        "GIT_PAGER=cat",
        f"GIT_CONFIG_COUNT={len(config)}",
    ]
    for index, (key, value) in enumerate(config.items()):
        parts.append(f"GIT_CONFIG_KEY_{index}={shlex.quote(key)}")
        parts.append(f"GIT_CONFIG_VALUE_{index}={shlex.quote(value)}")
    return " ".join(parts)


def build_guard_hook() -> str:
    trusted = trusted_git_environment()
    return "\n".join(
        [
            "#!/bin/sh",
            "set -eu",
            f"base=$(cat {GUARD_BASE_FILE})",
            f"exec {trusted} node {GUARD_BIN} check --base $base --candidate index --no-store",
            "",
        ]
    )


def build_guard_final_command() -> str:
    trusted = trusted_git_environment(final_index=True)
    return " ".join(
        [
            "set +e;",
            "cd /app;",
            f"base=$(cat {GUARD_BASE_FILE});",
            f"{trusted} node {GUARD_BIN} check --base $base --candidate HEAD --no-store >{GUARD_FINAL_COMMIT};",
            "commit_code=$?;",
            f"printf '%s\\n' $commit_code >{GUARD_FINAL_COMMIT_EXIT};",
            f"{trusted} node {GUARD_BIN} check --base $base --candidate worktree --no-store >{GUARD_FINAL_WORKTREE};",
            "worktree_code=$?;",
            f"printf '%s\\n' $worktree_code >{GUARD_FINAL_WORKTREE_EXIT};",
            f"{trusted} git -c safe.directory=/app -C /app status --porcelain=v1 --untracked-files=all >{GIT_FINAL_STATUS};",
            "status_code=$?;",
            f"printf '%s\\n' $status_code >{GIT_FINAL_STATUS_EXIT};",
            "exit 0",
        ]
    )


def build_git_status_command() -> str:
    trusted = trusted_git_environment(final_index=True)
    return " ".join(
        [
            "set +e;",
            f"base=$(cat {GUARD_BASE_FILE});",
            f"{trusted} git -c safe.directory=/app -C /app status --porcelain=v1 --untracked-files=all >{GIT_FINAL_STATUS};",
            "status_code=$?;",
            f"printf '%s\\n' $status_code >{GIT_FINAL_STATUS_EXIT};",
            "exit 0",
        ]
    )


def build_post_run_sanitize_command() -> str:
    trusted = trusted_git_environment(final_index=True)
    return " ".join(
        [
            "set -eu;",
            f"base=$(cat {GUARD_BASE_FILE});",
            f"uid=$(id -u {AGENT_USER});",
            "test \"$uid\" -ne 0;",
            "pkill -KILL -u \"$uid\" 2>/dev/null || true;",
            "test -d /app/.git;",
            "test ! -L /app/.git;",
            "if find /app/.git ! \\( -type f -o -type d \\) -print -quit | grep -q .; then exit 1; fi;",
            "rm -rf /tmp/ockle-pi /app/.git/refs/replace;",
            "rm -f /app/.git/info/grafts /app/.git/objects/info/alternates /app/.git/objects/info/http-alternates /tmp/ockle-final-index;",
            "rm -f /app/.git/config /app/.git/config.worktree;",
            "umask 077;",
            "printf '[core]\\nrepositoryformatversion = 0\\nbare = false\\nworktree = /app\\n' > /app/.git/config;",
            "chown root:root /app/.git/config;",
            "chmod 0600 /app/.git/config;",
            f"{trusted} git read-tree --reset HEAD;",
            "test -f /tmp/ockle-final-index;",
            "test ! -L /tmp/ockle-final-index;",
            "chown root:root /tmp/ockle-final-index;",
            "chmod 0600 /tmp/ockle-final-index;",
            "test ! -e /tmp/ockle-pi;",
            "test ! -e /app/.git/refs/replace;",
            "test ! -e /app/.git/info/grafts;",
            "test ! -e /app/.git/objects/info/alternates;",
            "test ! -e /app/.git/objects/info/http-alternates",
        ]
    )


def build_secret_scan_script() -> str:
    return r"""'use strict';
const fs = require('node:fs');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const secret = process.env.MAPLELUV_API_KEY;
const securityPath = '/logs/agent/security.json';
const maxFiles = 10000;
const maxBytes = 1024 * 1024 * 1024;
if (typeof secret !== 'string' || secret.length < 8) process.exit(44);
const needle = Buffer.from(secret);
const replacement = Buffer.from('[REDACTED]');
let credentialLeak = false;
let scanBudgetExceeded = false;
let scannedBytes = 0;
let scannedFiles = 0;
function containsSecret(data) { return data.indexOf(needle) !== -1; }
function replaceSecret(data) {
  const parts = [];
  let start = 0;
  while (true) {
    const index = data.indexOf(needle, start);
    if (index === -1) { parts.push(data.subarray(start)); break; }
    parts.push(data.subarray(start, index), replacement);
    start = index + needle.length;
  }
  return Buffer.concat(parts);
}
function git(args) {
  const env = {
    ...process.env,
    GIT_CONFIG_GLOBAL: '/dev/null',
    GIT_CONFIG_NOSYSTEM: '1',
    GIT_ATTR_NOSYSTEM: '1',
    GIT_NO_REPLACE_OBJECTS: '1',
    GIT_CONFIG_COUNT: '3',
    GIT_CONFIG_KEY_0: 'diff.external',
    GIT_CONFIG_VALUE_0: '',
    GIT_CONFIG_KEY_1: 'core.fsmonitor',
    GIT_CONFIG_VALUE_1: 'false',
    GIT_CONFIG_KEY_2: 'core.hooksPath',
    GIT_CONFIG_VALUE_2: '/dev/null',
  };
  delete env.MAPLELUV_API_KEY;
  return spawnSync('git', ['-c', 'safe.directory=/app', '-c', 'core.pager=cat', '-C', '/app', ...args], { env, encoding: null, maxBuffer: 512 * 1024 * 1024 });
}
function resetCandidate() {
  git(['reset', '--hard', fs.readFileSync('/opt/ockle/base-commit', 'utf8').trim()]);
  git(['clean', '-fdx']);
}
function purgeLogs() {
  fs.rmSync('/logs/agent', { recursive: true, force: true });
  fs.mkdirSync('/logs/agent', { recursive: true });
}
function failClosed(reason) {
  try { resetCandidate(); } catch {}
  try { purgeLogs(); } catch {}
  try {
    fs.mkdirSync('/logs/agent', { recursive: true });
    fs.writeFileSync(securityPath, JSON.stringify({ credentialLeak, scanError: true, scanBudgetExceeded, reason }) + '\n');
  } catch {}
  process.exit(43);
}
function scanLogs(target) {
  if (!fs.existsSync(target)) return;
  if (scanBudgetExceeded) {
    fs.rmSync(target, { recursive: true, force: true });
    return;
  }
  const stat = fs.lstatSync(target);
  if (stat.isSymbolicLink()) {
    scanBudgetExceeded = true;
    fs.unlinkSync(target);
    return;
  }
  if (stat.isDirectory()) {
    for (const entry of fs.readdirSync(target)) scanLogs(path.join(target, entry));
    return;
  }
  if (!stat.isFile()) return;
  scannedFiles += 1;
  scannedBytes += stat.size;
  if (scannedFiles > maxFiles || scannedBytes > maxBytes) {
    scanBudgetExceeded = true;
    fs.rmSync(target, { force: true });
    return;
  }
  const data = fs.readFileSync(target);
  if (!containsSecret(data)) return;
  credentialLeak = true;
  fs.writeFileSync(target, replaceSecret(data));
}
try {
  const base = fs.readFileSync('/opt/ockle/base-commit', 'utf8').trim();
  const delivery = git(['diff', '--no-ext-diff', '--no-textconv', '--no-renames', '--binary', base, 'HEAD', '--', '.']);
  if (delivery.status !== 0 || !Buffer.isBuffer(delivery.stdout)) failClosed('delivery-scan-failed');
  if (containsSecret(delivery.stdout)) credentialLeak = true;
  scanLogs('/logs/agent');
  if (scanBudgetExceeded) failClosed('artifact-scan-budget');
  if (credentialLeak) resetCandidate();
  fs.writeFileSync(securityPath, JSON.stringify({ credentialLeak, scanError: false, scanBudgetExceeded: false }) + '\n');
  if (credentialLeak) process.exit(42);
} catch {
  failClosed('artifact-scan-exception');
}
"""


def parse_session_evidence(session_path: Path) -> dict[str, int | float | str]:
    total_input = 0
    total_cache = 0
    total_output = 0
    total_reasoning = 0
    total_cost = 0.0
    peak_context = 0
    steps = 0
    session_ids: set[str] = set()
    model_changes: set[tuple[str, str]] = set()
    thinking_levels: set[str] = set()
    assistant_models: set[tuple[str, str]] = set()
    compaction_count = 0

    for line in session_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        row_type = row.get("type")
        if row_type == "session":
            if row.get("cwd") != "/app" or not isinstance(row.get("id"), str):
                raise ValueError("session identity or cwd is invalid")
            session_ids.add(row["id"])
        elif row_type == "model_change":
            model_changes.add((str(row.get("provider")), str(row.get("modelId"))))
        elif row_type == "thinking_level_change":
            thinking_levels.add(str(row.get("thinkingLevel")))
        elif row_type == "compaction":
            compaction_count += 1

        message = row.get("message") if row_type == "message" else None
        if not isinstance(message, dict) or message.get("role") != "assistant":
            continue
        usage = message.get("usage")
        if not isinstance(usage, dict):
            continue
        assistant_models.add((str(message.get("provider")), str(message.get("model"))))
        input_tokens = int(usage.get("input") or 0)
        cache_tokens = int(usage.get("cacheRead") or 0) + int(
            usage.get("cacheWrite") or 0
        )
        output_tokens = int(usage.get("output") or 0)
        reasoning_tokens = int(usage.get("reasoning") or 0)
        cost = usage.get("cost")
        cost_total = cost.get("total", 0) if isinstance(cost, dict) else 0

        total_input += input_tokens + cache_tokens
        total_cache += cache_tokens
        total_output += output_tokens
        total_reasoning += reasoning_tokens
        total_cost += float(cost_total or 0)
        peak_context = max(peak_context, input_tokens + cache_tokens)
        steps += 1

    expected_model = {(MODEL_PROVIDER, MODEL_ID)}
    if session_ids == set() or len(session_ids) != 1:
        raise ValueError("expected exactly one persisted session identity")
    if model_changes != expected_model or assistant_models != expected_model:
        raise ValueError("provider or model evidence does not match the formal contract")
    if thinking_levels != {"max"}:
        raise ValueError("thinking level evidence is not exactly max")
    if compaction_count != 0:
        raise ValueError("Pi native compaction occurred")
    if steps == 0:
        raise ValueError("session contains no assistant usage evidence")

    return {
        "n_input_tokens": total_input,
        "n_cache_tokens": total_cache,
        "n_output_tokens": total_output,
        "reasoning_tokens": total_reasoning,
        "cost_usd": total_cost,
        "peak_context_tokens": peak_context,
        "n_agent_steps": steps,
        "session_id": next(iter(session_ids)),
        "thinking_level": "max",
        "compaction_count": compaction_count,
    }


def parse_final_state_evidence(logs_dir: Path, condition: str) -> dict[str, Any]:
    status_path = logs_dir / Path(GIT_FINAL_STATUS).name
    status_exit_path = logs_dir / Path(GIT_FINAL_STATUS_EXIT).name
    if not status_path.is_file() or not status_exit_path.is_file():
        raise ValueError("trusted final Git status evidence is missing")
    status_exit = int(status_exit_path.read_text(encoding="utf-8").strip())
    if status_exit != 0:
        raise ValueError("trusted final Git status failed")
    status_bytes = status_path.read_bytes()
    evidence: dict[str, Any] = {
        "worktreeClean": status_bytes == b"",
        "worktreeStatusSha256": hashlib.sha256(status_bytes).hexdigest(),
        "worktreeStatusBytes": len(status_bytes),
    }
    if condition != "full":
        return evidence

    guard_evidence: dict[str, Any] = {}
    exit_codes = {"clear": 0, "blocked": 1, "indeterminate": 2}
    for name, result_remote, exit_remote in (
        ("commit", GUARD_FINAL_COMMIT, GUARD_FINAL_COMMIT_EXIT),
        ("worktree", GUARD_FINAL_WORKTREE, GUARD_FINAL_WORKTREE_EXIT),
    ):
        result_path = logs_dir / Path(result_remote).name
        exit_path = logs_dir / Path(exit_remote).name
        if not result_path.is_file() or not exit_path.is_file():
            raise ValueError(f"trusted final {name} guard evidence is missing")
        result = json.loads(result_path.read_text(encoding="utf-8"))
        exit_code = int(exit_path.read_text(encoding="utf-8").strip())
        verdict = result.get("verdict") if isinstance(result, dict) else None
        if (
            result.get("schemaVersion") != 1
            or result.get("operation") != "check"
            or verdict not in exit_codes
            or exit_code != exit_codes.get(verdict)
        ):
            raise ValueError(f"trusted final {name} guard evidence is invalid")
        guard_evidence[name] = {"exitCode": exit_code, "result": result}
    evidence["guard"] = guard_evidence
    return evidence


class PiOckleAgent(BaseInstalledAgent):
    def __init__(
        self,
        condition: str = "bare",
        guard_bundle: str | Path | None = None,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        if condition not in CONDITIONS:
            raise ValueError(f"unknown condition: {condition}")
        if condition == "full" and guard_bundle is None:
            raise ValueError("guard_bundle is required for the full condition")
        self.condition = condition
        self.guard_bundle = Path(guard_bundle).resolve() if guard_bundle else None
        if self.guard_bundle is not None and not self.guard_bundle.is_file():
            raise ValueError(f"guard_bundle does not exist: {self.guard_bundle}")
        self.guard_bundle_sha256 = (
            hashlib.sha256(self.guard_bundle.read_bytes()).hexdigest()
            if self.guard_bundle is not None
            else None
        )
        self.runtime_evidence: dict[str, int | float | str] | None = None
        self.final_state_evidence: dict[str, Any] | None = None
        self.agent_uid: int | None = None
        super().__init__(*args, **kwargs)

    @staticmethod
    def name() -> str:
        return "pi-ockle"

    def install_spec(self) -> AgentInstallSpec:
        node_archive = f"node-v{NODE_VERSION}-linux-x64.tar.xz"
        install = " && ".join(
            [
                "apt-get update",
                "DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends ca-certificates curl procps xz-utils",
                f"getent passwd {AGENT_USER} >/dev/null || useradd --create-home --shell /bin/bash {AGENT_USER}",
                f"test \"$(id -u {AGENT_USER})\" -ne 0",
                f"curl -fsSLo /tmp/{node_archive} https://nodejs.org/dist/v{NODE_VERSION}/{node_archive}",
                f"echo '{NODE_SHA256}  /tmp/{node_archive}' | sha256sum -c -",
                f"tar -xJf /tmp/{node_archive} -C /usr/local --strip-components=1",
                f"rm -f /tmp/{node_archive}",
                "npm config set update-notifier false",
                f"curl -fsSLo /tmp/pi-coding-agent.tgz {PI_TARBALL_URL}",
                f"echo '{PI_TARBALL_SHA256}  /tmp/pi-coding-agent.tgz' | sha256sum -c -",
                f"tar -xOf /tmp/pi-coding-agent.tgz package/npm-shrinkwrap.json | sha256sum | grep -F '{PI_SHRINKWRAP_SHA256}  -'",
                "npm install -g --ignore-scripts /tmp/pi-coding-agent.tgz",
                "rm -f /tmp/pi-coding-agent.tgz && rm -rf /var/lib/apt/lists/*",
                "pi --version",
            ]
        )
        return AgentInstallSpec(
            agent_name=self.name(),
            version=PI_VERSION,
            steps=[InstallStep(run=install, user="root")],
            verification_command=f"pi --version | grep -F '{PI_VERSION}'",
            cache_key=f"pi-ockle-node-{NODE_VERSION}-pi-{PI_TARBALL_SHA256[:16]}",
            metadata={
                "node_sha256": NODE_SHA256,
                "pi_tarball_sha256": PI_TARBALL_SHA256,
                "pi_shrinkwrap_sha256": PI_SHRINKWRAP_SHA256,
            },
        )

    def network_allowlist(self) -> NetworkAllowlist:
        return NetworkAllowlist(domains=["la.mapleluv.icu"])

    def get_version_command(self) -> str | None:
        return "pi --version"

    def parse_version(self, stdout: str) -> str:
        match = re.search(r"\d+\.\d+\.\d+", stdout)
        return match.group(0) if match else stdout.strip()

    async def setup(self, environment: BaseEnvironment) -> None:
        await super().setup(environment)
        setup_dir = self.logs_dir / "setup"
        setup_dir.mkdir(parents=True, exist_ok=True)
        models_path = setup_dir / "models.json"
        settings_path = setup_dir / "settings.json"
        scanner_path = setup_dir / "secret-scan.cjs"
        models_path.write_text(
            json.dumps(build_models_config(), indent=2) + "\n", encoding="utf-8"
        )
        settings_path.write_text(
            json.dumps(build_settings(), indent=2) + "\n", encoding="utf-8"
        )
        scanner_path.write_text(build_secret_scan_script(), encoding="utf-8", newline="\n")

        await environment.exec(
            command=(
                f"mkdir -p {REMOTE_PI_DIR} {REMOTE_SKILLS_DIR} {REMOTE_SESSION_DIR} && "
                f"install -d -o {AGENT_USER} -g {AGENT_USER} /home/{AGENT_USER} {REMOTE_SESSION_DIR}"
            ),
            user="root",
        )
        await environment.upload_file(models_path, f"{REMOTE_PI_DIR}/models.json")
        await environment.upload_file(settings_path, f"{REMOTE_PI_DIR}/settings.json")
        await environment.upload_file(scanner_path, SECRET_SCAN_PATH)

        if self.condition != "bare":
            root = Path(__file__).resolve().parents[2]
            for skill_name in SKILL_NAMES:
                source_dir = root / "skills" / skill_name
                if not source_dir.is_dir():
                    raise RuntimeError(f"missing Ockle skill: {source_dir}")
                remote_dir = f"{REMOTE_SKILLS_DIR}/{skill_name}"
                await environment.exec(command=f"mkdir -p {remote_dir}", user="root")
                for source in sorted(source_dir.rglob("*")):
                    if source.is_file():
                        relative = source.relative_to(source_dir).as_posix()
                        destination = f"{remote_dir}/{relative}"
                        parent = destination.rsplit("/", 1)[0]
                        await environment.exec(command=f"mkdir -p {shlex.quote(parent)}", user="root")
                        await environment.upload_file(source, destination)

        await environment.exec(
            command=(
                f"env GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1 "
                f"GIT_NO_REPLACE_OBJECTS=1 git -c safe.directory=/app -C /app rev-parse HEAD > {GUARD_BASE_FILE} && "
                f"chown -R {AGENT_USER}:{AGENT_USER} /app && "
                f"chown -R root:root /opt/ockle && chmod -R a-w /opt/ockle && chmod -R a+rX /opt/ockle && "
                f"chown -R {AGENT_USER}:{AGENT_USER} {REMOTE_SESSION_DIR} /home/{AGENT_USER}"
            ),
            user="root",
        )

        if self.condition == "full":
            await self._setup_guard(environment, setup_dir)

        identity = await environment.exec(command="id -u && id -un")
        identity_lines = (identity.stdout or "").splitlines()
        if identity.return_code != 0 or len(identity_lines) != 2:
            raise RuntimeError("failed to verify the effective agent identity")
        self.agent_uid = int(identity_lines[0])
        if self.agent_uid == 0 or identity_lines[1] != AGENT_USER:
            raise RuntimeError("Pi agent would execute as root")


    async def _setup_guard(
        self, environment: BaseEnvironment, setup_dir: Path
    ) -> None:
        assert self.guard_bundle is not None
        hook_path = setup_dir / "pre-commit"
        hook_path.write_text(build_guard_hook(), encoding="utf-8", newline="\n")
        await environment.exec(
            command=f"mkdir -p {GUARD_ROOT} /app/.git/hooks && test ! -e /app/.git/hooks/pre-commit",
            user="root",
        )
        await environment.upload_file(
            self.guard_bundle, "/tmp/ockle-guard-runtime.tar.gz"
        )
        await environment.exec(
            command=(
                f"tar -xzf /tmp/ockle-guard-runtime.tar.gz -C {GUARD_ROOT} && "
                f"rm -f /tmp/ockle-guard-runtime.tar.gz && "
                f"node --check {GUARD_BIN} && "
                f"test \"$(cat {GUARD_BASE_FILE})\" = \"$(env GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1 GIT_NO_REPLACE_OBJECTS=1 git -c safe.directory=/app -C /app rev-parse HEAD)\""
            ),
            user="root",
        )
        await environment.upload_file(hook_path, "/app/.git/hooks/pre-commit")
        await environment.exec(
            command=(
                "chown -R root:root /opt/ockle && chmod -R a-w /opt/ockle && "
                "chmod -R a+rX /opt/ockle && "
                "chown root:root /app/.git/hooks /app/.git/hooks/pre-commit && "
                "chmod 0555 /app/.git/hooks /app/.git/hooks/pre-commit"
            ),
            user="root",
        )

    async def run(
        self,
        instruction: str,
        environment: BaseEnvironment,
        context: AgentContext,
    ) -> None:
        api_key = self._get_env("MAPLELUV_API_KEY")
        if not api_key:
            raise ValueError("MAPLELUV_API_KEY is required")

        rendered = self.render_instruction(instruction)
        args = build_pi_arguments(self.condition, rendered)
        event_path = "/logs/agent/pi-events.jsonl"
        stderr_path = "/logs/agent/pi.stderr.log"
        process_env = environment.agent_process_env(
            {
                "MAPLELUV_API_KEY": api_key,
                "HOME": f"/home/{AGENT_USER}",
                "PI_CODING_AGENT_DIR": "/tmp/ockle-pi",
                "PI_OFFLINE": "1",
                "PI_SKIP_VERSION_CHECK": "1",
                "NO_COLOR": "1",
            }
        )
        command = (
            "set -o pipefail; "
            "rm -rf /tmp/ockle-pi; install -d -m 0700 /tmp/ockle-pi; "
            f"cp {REMOTE_PI_DIR}/models.json {REMOTE_PI_DIR}/settings.json /tmp/ockle-pi/; "
            "chmod 0600 /tmp/ockle-pi/models.json /tmp/ockle-pi/settings.json; "
            "cd /app; mkdir -p /logs/agent; "
            f"{shlex.join(args)} 2>{stderr_path} | tee {event_path}"
        )
        result = None
        launch_error: Exception | None = None
        post_errors: list[str] = []
        try:
            try:
                result = await environment.exec(
                    command=command,
                    env=process_env,
                    timeout_sec=5_400,
                )
            except Exception as exc:
                launch_error = exc
        finally:
            cleanup_task = asyncio.create_task(
                self._post_run_boundary(environment, process_env)
            )
            try:
                post_errors = await asyncio.shield(cleanup_task)
            except asyncio.CancelledError:
                post_errors = await cleanup_task
                raise

        if post_errors:
            raise NonZeroAgentExitCodeError(
                "trusted post-run boundary failed: " + "; ".join(post_errors)
            )
        if launch_error is not None:
            if isinstance(launch_error, NonZeroAgentExitCodeError):
                raise launch_error
            raise NonZeroAgentExitCodeError(f"Pi launch failed: {launch_error}")
        if result is None or result.return_code != 0:
            return_code = result.return_code if result is not None else "missing"
            raise NonZeroAgentExitCodeError(
                f"Pi exited with {return_code}; see {stderr_path}"
            )

    async def _post_run_boundary(
        self, environment: BaseEnvironment, process_env: dict[str, str]
    ) -> list[str]:
        errors: list[str] = []
        try:
            sanitized = await environment.exec(
                command=build_post_run_sanitize_command(), user="root"
            )
            if sanitized.return_code != 0:
                errors.append("git/process sanitization failed")
        except Exception as exc:
            errors.append(f"git/process sanitization error: {exc}")

        try:
            scan = await environment.exec(
                command=f"node {SECRET_SCAN_PATH}",
                user="root",
                env=process_env,
            )
            if scan.return_code == 42:
                errors.append("provider credential appeared in delivery bytes or agent logs")
            elif scan.return_code != 0:
                errors.append(f"provider credential scan failed with {scan.return_code}")
        except Exception as exc:
            errors.append(f"provider credential scan error: {exc}")

        if self.condition == "full":
            try:
                guard = await environment.exec(
                    command=build_guard_final_command(), user="root"
                )
                if guard.return_code != 0:
                    errors.append("trusted final guard wrapper failed")
            except Exception as exc:
                errors.append(f"trusted final guard error: {exc}")
        else:
            try:
                status = await environment.exec(
                    command=build_git_status_command(), user="root"
                )
                if status.return_code != 0:
                    errors.append("trusted final Git status wrapper failed")
            except Exception as exc:
                errors.append(f"trusted final Git status error: {exc}")

        try:
            self.final_state_evidence = parse_final_state_evidence(
                self.logs_dir, self.condition
            )
        except Exception as exc:
            errors.append(f"trusted final state evidence invalid: {exc}")

        try:
            sessions_dir = self.logs_dir / "sessions"
            session_paths = (
                sorted(sessions_dir.rglob("*.jsonl")) if sessions_dir.exists() else []
            )
            if len(session_paths) != 1:
                raise ValueError(
                    f"expected exactly one Pi session file, found {len(session_paths)}"
                )
            runtime_evidence = parse_session_evidence(session_paths[0])
            runtime_evidence["agent_uid"] = int(self.agent_uid or 0)
            (self.logs_dir / "runtime-evidence.json").write_text(
                json.dumps(runtime_evidence, indent=2) + "\n", encoding="utf-8"
            )
            self.runtime_evidence = runtime_evidence
        except Exception as exc:
            errors.append(f"session evidence invalid: {exc}")

        try:
            permissions = await environment.exec(
                command="chown -R root:root /logs/agent && chmod -R go-w /logs/agent",
                user="root",
            )
            if permissions.return_code != 0:
                errors.append("failed to freeze agent logs")
        except Exception as exc:
            errors.append(f"agent log freeze error: {exc}")
        return errors

    def populate_context_post_run(self, context: AgentContext) -> None:
        evidence = self.runtime_evidence
        if evidence is not None:
            context.n_input_tokens = int(evidence["n_input_tokens"])
            context.n_cache_tokens = int(evidence["n_cache_tokens"])
            context.n_output_tokens = int(evidence["n_output_tokens"])
            context.cost_usd = float(evidence["cost_usd"])
            context.peak_context_tokens = int(evidence["peak_context_tokens"])
            context.summarization_count = int(evidence["compaction_count"])
            context.n_agent_steps = int(evidence["n_agent_steps"])

        metadata: dict[str, Any] = {
            "condition": self.condition,
            "pi_version": PI_VERSION,
            "runtimeEvidenceValid": evidence is not None,
            "provider": MODEL_PROVIDER,
            "model": MODEL_ID,
            "thinking": evidence.get("thinking_level") if evidence else None,
            "sessionId": evidence.get("session_id") if evidence else None,
            "reasoningTokens": evidence.get("reasoning_tokens") if evidence else None,
            "agentUid": evidence.get("agent_uid") if evidence else self.agent_uid,
        }
        security_path = self.logs_dir / "security.json"
        metadata["security"] = (
            json.loads(security_path.read_text(encoding="utf-8"))
            if security_path.exists()
            else {"scanError": True, "credentialLeak": None}
        )
        final_evidence = self.final_state_evidence
        metadata["finalStateEvidenceValid"] = final_evidence is not None
        if final_evidence is not None:
            metadata.update(final_evidence)
        else:
            metadata.update(
                {
                    "worktreeClean": None,
                    "worktreeStatusSha256": None,
                    "worktreeStatusBytes": None,
                }
            )
        if self.condition == "full":
            metadata["guardBundleSha256"] = self.guard_bundle_sha256
            metadata["guard"] = (
                final_evidence.get("guard") if final_evidence is not None else None
            )
        context.metadata = metadata
