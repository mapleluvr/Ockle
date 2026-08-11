from __future__ import annotations

import argparse
import base64
import hashlib
import importlib.metadata
import json
import os
import stat
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Any

from pi_agent import (
    CONTINUATION_STATUS_NAME,
    MAX_CONTINUATIONS,
    MODEL_API,
    MODEL_BASE_URL,
    MODEL_EGRESS_PORT,
    MODEL_ID,
    MODEL_PROVIDER,
    NODE_SHA256,
    NODE_VERSION,
    PI_SHRINKWRAP_SHA256,
    PI_TARBALL_SHA256,
    PI_VERSION,
    PIER_SQUID_BOOTSTRAP_SHA256,
    combine_final_status_bytes,
)
from pier.environments.agent_setup import squid_bootstrap_command
from prepare_pilot import (
    EXPECTED_BENCHMARK_COMMIT,
    EXPECTED_PIER_COMMIT,
    EXPECTED_SOURCE_ARCHIVE_SHA256,
    validate_pilot_manifest,
)

MODEL = f"{MODEL_PROVIDER}/{MODEL_ID}"


def build_pier_command(
    *,
    condition: str,
    manifest: dict[str, Any],
    tasks_root: Path,
    jobs_root: Path,
    secrets_file: Path,
    concurrency: int,
    guard_bundle: Path | None,
    python_executable: Path | str = Path(sys.executable),
) -> list[str]:
    validate_pilot_manifest(manifest)
    if condition not in {"bare", "inner", "full"}:
        raise ValueError(f"unknown condition: {condition}")
    if condition == "full" and guard_bundle is None:
        raise ValueError("full condition requires a guard bundle")
    if condition != "full" and guard_bundle is not None:
        raise ValueError("guard bundle is only valid for the full condition")
    if concurrency < 1:
        raise ValueError("concurrency must be positive")

    selected = [task["id"] for task in manifest["tasks"] if condition in task["arms"]]
    command = [
        str(python_executable),
        "-B",
        "-c",
        "from pier.cli.main import app; app()",
        "run",
        "--path",
        str(tasks_root),
    ]
    for task_id in selected:
        command.extend(["--include-task-name", task_id])
    command.extend(
        [
            "--agent-import-path",
            "pi_agent:PiOckleAgent",
            "--model",
            MODEL,
            "--agent-kwarg",
            f"condition={condition}",
        ]
    )
    if guard_bundle is not None:
        command.extend(
            ["--agent-kwarg", f"guard_bundle={guard_bundle.resolve()}"]
        )
    command.extend(
        [
            "--env-file",
            str(secrets_file),
            "--env",
            "docker",
            "--jobs-dir",
            str(jobs_root),
            "--job-name",
            condition,
            "--n-concurrent",
            str(concurrency),
            "--yes",
            "--quiet",
        ]
    )
    return command


def _verify_pier_install() -> dict[str, str | int]:
    distribution = importlib.metadata.distribution("datacurve-pier")
    direct_url_text = distribution.read_text("direct_url.json")
    if direct_url_text is None:
        raise RuntimeError("Pier direct_url.json is missing")
    direct_url = json.loads(direct_url_text)
    commit = direct_url.get("vcs_info", {}).get("commit_id")
    if commit != EXPECTED_PIER_COMMIT:
        raise RuntimeError(f"unexpected Pier commit: {commit}")
    version = distribution.version
    if version != "0.3.0":
        raise RuntimeError(f"unexpected Pier version: {version}")

    verified = 0
    for package_path in distribution.files or []:
        expected = package_path.hash
        if expected is None:
            continue
        if expected.mode != "sha256":
            raise RuntimeError(f"unsupported Pier RECORD hash for {package_path}")
        installed_path = Path(distribution.locate_file(package_path))
        if not installed_path.is_file():
            raise RuntimeError(f"Pier installed file is missing: {package_path}")
        actual = base64.urlsafe_b64encode(
            hashlib.sha256(installed_path.read_bytes()).digest()
        ).decode("ascii").rstrip("=")
        if actual != expected.value:
            raise RuntimeError(f"Pier installed file hash mismatch: {package_path}")
        verified += 1
    if verified < 100:
        raise RuntimeError("Pier RECORD did not cover the installed package")
    python_executable = Path(sys.executable).absolute()
    probe = subprocess.run(
        [
            str(python_executable),
            "-B",
            "-c",
            "import importlib.metadata, pier; print(importlib.metadata.version('datacurve-pier')); print(pier.__file__)",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    probe_lines = probe.stdout.splitlines()
    if len(probe_lines) != 2 or probe_lines[0] != version or "site-packages/pier" not in probe_lines[1]:
        raise RuntimeError("verified Pier interpreter cannot import the pinned distribution")
    return {
        "version": version,
        "commit": commit,
        "verifiedFiles": verified,
        "python": str(python_executable),
    }


def _verify_secret_file(path: Path) -> str:
    if not path.is_file():
        raise FileNotFoundError(f"secret env file is missing: {path}")
    mode = stat.S_IMODE(path.stat().st_mode)
    if mode != 0o600:
        raise PermissionError(f"secret env file must have mode 0600, got {oct(mode)}")
    lines = path.read_text(encoding="utf-8").splitlines()
    if len(lines) != 1 or not lines[0].startswith("MAPLELUV_API_KEY="):
        raise ValueError("secret env file must contain only MAPLELUV_API_KEY")
    if len(lines[0].split("=", 1)[1]) < 20:
        raise ValueError("MAPLELUV_API_KEY is missing")
    return lines[0].split("=", 1)[1]


def _verify_prepared_root(
    prepared_root: Path, manifest_path: Path, manifest: dict[str, Any]
) -> dict[str, Any]:
    from pier.models.task.task import Task

    prepared_path = prepared_root / "prepared.json"
    tasks_root = prepared_root / "tasks"
    manifest_copy = prepared_root / "pilot-v1.json"
    expected_root_entries = {"prepared.json", "tasks", "pilot-v1.json"}
    if {path.name for path in prepared_root.iterdir()} != expected_root_entries:
        raise ValueError("prepared pilot root contains missing or extra entries")
    if not prepared_path.is_file() or not tasks_root.is_dir() or not manifest_copy.is_file():
        raise FileNotFoundError("prepared pilot root is incomplete")
    if manifest_copy.read_bytes() != manifest_path.read_bytes():
        raise ValueError("prepared pilot manifest copy does not match canonical bytes")
    symlinks = [path for path in prepared_root.rglob("*") if path.is_symlink()]
    if symlinks:
        raise ValueError("prepared pilot root contains symlinks")

    prepared = json.loads(prepared_path.read_text(encoding="utf-8"))
    manifest_sha = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    if prepared.get("manifestSha256") != manifest_sha:
        raise ValueError("prepared pilot manifest digest mismatch")
    materializer = Path(__file__).with_name("prepare_pilot.py")
    materializer_sha = hashlib.sha256(materializer.read_bytes()).hexdigest()
    if prepared.get("materializerSha256") != materializer_sha:
        raise ValueError("prepared pilot materializer digest mismatch")
    if prepared.get("benchmarkCommit") != EXPECTED_BENCHMARK_COMMIT:
        raise ValueError("prepared pilot benchmark commit mismatch")
    if prepared.get("sourceArchiveSha256") != EXPECTED_SOURCE_ARCHIVE_SHA256:
        raise ValueError("prepared pilot source archive digest mismatch")

    expected_ids = [task["id"] for task in manifest["tasks"]]
    if sorted(path.name for path in tasks_root.iterdir() if path.is_dir()) != sorted(expected_ids):
        raise ValueError("prepared task directory set does not match manifest")
    records = prepared.get("tasks", [])
    prepared_ids = [task.get("id") for task in records]
    if prepared_ids != expected_ids:
        raise ValueError("prepared task order or IDs do not match manifest")
    records_by_id = {record["id"]: record for record in records}

    for entry in manifest["tasks"]:
        task_id = entry["id"]
        task_dir = tasks_root / task_id
        actual_checksum = Task(task_dir=task_dir).checksum
        if actual_checksum != entry["preparedTaskChecksum"]:
            raise ValueError(f"prepared task checksum drift for {task_id}")
        record = records_by_id[task_id]
        if record.get("sourceTaskChecksum") != entry["taskChecksum"]:
            raise ValueError(f"prepared source checksum record drift for {task_id}")
        if record.get("preparedTaskChecksum") != actual_checksum:
            raise ValueError(f"prepared checksum record drift for {task_id}")
        expected_image = f'{entry["image"]}@{entry["imageDigest"]}'
        if record.get("image") != expected_image:
            raise ValueError(f"prepared image record drift for {task_id}")

        with (task_dir / "task.toml").open("rb") as stream:
            config = tomllib.load(stream)
        if config["environment"].get("docker_image") != expected_image:
            raise ValueError(f"prepared image reference drift for {task_id}")
        if config["environment"].get("allow_internet") is not False:
            raise ValueError(f"agent network policy drift for {task_id}")
        if config["verifier"]["environment"].get("allow_internet") is not False:
            raise ValueError(f"verifier network policy drift for {task_id}")
        if config["agent"].get("user") != "ockle":
            raise ValueError(f"agent user drift for {task_id}")
        collect = config["verifier"].get("collect")
        if not isinstance(collect, list) or len(collect) != 1:
            raise ValueError(f"collect configuration drift for {task_id}")
        collect_command = collect[0].get("command", "")
        for required in (
            "GIT_CONFIG_GLOBAL=/dev/null",
            "GIT_NO_REPLACE_OBJECTS=1",
            "--no-ext-diff",
            "--no-textconv",
            entry["baseCommit"],
        ):
            if required not in collect_command:
                raise ValueError(f"collect hardening drift for {task_id}")
    return prepared


def _require_outside_repository(path: Path, repository: Path, label: str) -> Path:
    resolved = path.resolve()
    repository = repository.resolve()
    if resolved == repository or repository in resolved.parents:
        raise ValueError(f"{label} must be outside the Ockle repository")
    return resolved


def _git_checkpoint(root: Path) -> dict[str, str | int]:
    status = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=all"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    if status.strip():
        raise RuntimeError("Ockle worktree must be clean before a formal run")
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    tracked = subprocess.run(
        [
            "git",
            "ls-files",
            "-z",
            "--",
            "evals/deep-swe",
            "skills/test-driven-development",
            "skills/systematic-debugging",
            "skills/receiving-code-review",
            "guard/bin",
            "guard/src",
            "guard/package.json",
        ],
        cwd=root,
        check=True,
        capture_output=True,
    ).stdout.split(b"\0")
    paths = [path.decode("utf-8") for path in tracked if path]
    if not paths:
        raise RuntimeError("formal runtime assets are not tracked")
    digest = hashlib.sha256()
    for relative in paths:
        committed = subprocess.run(
            ["git", "show", f"{commit}:{relative}"],
            cwd=root,
            check=True,
            capture_output=True,
        ).stdout
        worktree = (root / relative).read_bytes()
        if worktree != committed:
            raise RuntimeError(f"worktree bytes differ from checkpoint: {relative}")
        digest.update(relative.encode("utf-8") + b"\0" + committed)
    return {"commit": commit, "runtimeTreeSha256": digest.hexdigest(), "files": len(paths)}


def _verify_execution_contract(manifest: dict[str, Any], guard_bundle: Path) -> str:
    execution = manifest["execution"]
    expected = {
        "model": f"{MODEL_PROVIDER}/{MODEL_ID}",
        "modelApi": MODEL_API,
        "modelBaseUrl": MODEL_BASE_URL,
        "maxContinuations": MAX_CONTINUATIONS,
        "continuationTrigger": "trusted-dirty-worktree",
        "pierSquidBootstrapSha256": PIER_SQUID_BOOTSTRAP_SHA256,
        "pierSquidSafePorts": [80, 443, MODEL_EGRESS_PORT],
        "pierSquidSslPorts": [443],
        "candidateIndexAuthority": "actual-index-plus-independent-worktree",
        "statusEvidence": "root-frozen-raw-bytes-sha256",
        "rejectSplitIndex": True,
        "thinking": "max",
        "repeats": 1,
        "magicContext": False,
        "piNativeCompaction": False,
        "piVersion": PI_VERSION,
        "piTarballSha256": PI_TARBALL_SHA256,
        "piShrinkwrapSha256": PI_SHRINKWRAP_SHA256,
        "nodeVersion": NODE_VERSION,
        "nodeArchiveSha256": NODE_SHA256,
    }
    for key, value in expected.items():
        if execution.get(key) != value:
            raise ValueError(f"formal execution contract drift: {key}")
    if not guard_bundle.is_file():
        raise FileNotFoundError(f"guard bundle is missing: {guard_bundle}")
    actual_guard = hashlib.sha256(guard_bundle.read_bytes()).hexdigest()
    if execution.get("guardBundleSha256") != actual_guard:
        raise ValueError("guard bundle digest does not match canonical manifest")
    image = execution.get("egressProxyBaseImage")
    image_digest = execution.get("egressProxyBaseImageDigest")
    inspected = subprocess.run(
        ["docker", "image", "inspect", str(image), "--format", "{{json .RepoDigests}}"],
        check=True,
        capture_output=True,
        text=True,
    )
    repo_digests = json.loads(inspected.stdout)
    if not any(str(reference).endswith(f"@{image_digest}") for reference in repo_digests):
        raise ValueError("Pier egress proxy base image digest drift")
    return actual_guard


class ArtifactCredentialScanError(RuntimeError):
    def __init__(self, leaked_paths: list[str], purged_paths: list[str]) -> None:
        super().__init__(
            "formal artifact credential scan budget exceeded; unscanned artifacts were purged"
        )
        self.leaked_paths = leaked_paths
        self.purged_paths = purged_paths


def _redact_secret_tree(root: Path, secret: str) -> list[str]:
    needle = secret.encode("utf-8")
    replacement = b"[REDACTED]"
    leaked: list[str] = []
    purged: list[str] = []
    scanned_files = 0
    scanned_bytes = 0
    budget_exceeded = False
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            path.unlink(missing_ok=True)
            purged.append(relative)
            budget_exceeded = True
            continue
        if not path.is_file():
            continue
        scanned_files += 1
        size = path.stat().st_size
        scanned_bytes += size
        if budget_exceeded or scanned_files > 10_000 or scanned_bytes > 1024 * 1024 * 1024:
            path.unlink(missing_ok=True)
            purged.append(relative)
            budget_exceeded = True
            continue
        try:
            data = path.read_bytes()
        except OSError:
            path.unlink(missing_ok=True)
            purged.append(relative)
            budget_exceeded = True
            continue
        if needle not in data:
            continue
        path.write_bytes(data.replace(needle, replacement))
        leaked.append(relative)
    if purged:
        raise ArtifactCredentialScanError(leaked, purged)
    return leaked


def _run_pier_with_credential_scan(
    *,
    command: list[str],
    cwd: Path,
    environment: dict[str, str],
    output_root: Path,
    condition: str,
    secret: str,
) -> tuple[subprocess.CompletedProcess[str], list[str]]:
    completed = None
    leaks: list[str] = []
    scan_error: ArtifactCredentialScanError | None = None
    try:
        completed = subprocess.run(command, cwd=cwd, env=environment)
    finally:
        try:
            leaks = _redact_secret_tree(output_root / condition, secret)
        except ArtifactCredentialScanError as exc:
            leaks = exc.leaked_paths
            scan_error = exc
        security = {
            "condition": condition,
            "credentialLeakPaths": leaks,
            "scanError": str(scan_error) if scan_error is not None else None,
            "purgedPaths": scan_error.purged_paths if scan_error is not None else [],
        }
        (output_root / f"{condition}-security.json").write_text(
            json.dumps(security, indent=2) + "\n", encoding="utf-8", newline="\n"
        )
        if scan_error is not None:
            raise scan_error
    if completed is None:
        raise RuntimeError("Pier subprocess returned no completion evidence")
    return completed, leaks


def _read_regular_bytes(path: Path) -> bytes | None:
    try:
        if not path.is_file() or path.is_symlink():
            return None
        return path.read_bytes()
    except OSError:
        return None


def _continuation_evidence_valid(value: Any, result_path: Path) -> bool:
    if not isinstance(value, dict):
        return False
    count = value.get("count")
    status_bytes = value.get("statusBytes")
    status_sha = value.get("statusSha256")
    raw_status = _read_regular_bytes(
        result_path.parent / "agent" / CONTINUATION_STATUS_NAME
    )
    if raw_status is None:
        return False
    return all(
        [
            value.get("schemaVersion") == 1,
            value.get("maxContinuations") == MAX_CONTINUATIONS,
            type(count) is int and 0 <= count <= MAX_CONTINUATIONS,
            value.get("statusChecked") is True,
            value.get("triggeredByDirtyWorktree") is (count == 1),
            type(status_bytes) is int and status_bytes == len(raw_status),
            isinstance(status_sha, str)
            and status_sha == hashlib.sha256(raw_status).hexdigest(),
            (count == 0) is (len(raw_status) == 0),
        ]
    )


def _final_status_evidence_valid(metadata: dict[str, Any], result_path: Path) -> bool:
    independent = _read_regular_bytes(
        result_path.parent / "agent" / "git-final-status.txt"
    )
    candidate_index = _read_regular_bytes(
        result_path.parent / "agent" / "git-final-index-status.txt"
    )
    if independent is None or candidate_index is None:
        return False
    combined = combine_final_status_bytes(independent, candidate_index)
    independent_clean = independent == b""
    candidate_index_clean = candidate_index == b""
    return all(
        [
            metadata.get("independentWorktreeClean") is independent_clean,
            metadata.get("independentWorktreeStatusBytes") == len(independent),
            metadata.get("independentWorktreeStatusSha256")
            == hashlib.sha256(independent).hexdigest(),
            metadata.get("candidateIndexClean") is candidate_index_clean,
            metadata.get("candidateIndexStatusBytes") == len(candidate_index),
            metadata.get("candidateIndexStatusSha256")
            == hashlib.sha256(candidate_index).hexdigest(),
            metadata.get("worktreeClean")
            is (independent_clean and candidate_index_clean),
            metadata.get("worktreeStatusBytes")
            == len(independent) + len(candidate_index),
            metadata.get("worktreeStatusSha256")
            == hashlib.sha256(combined).hexdigest(),
        ]
    )


def _proxy_policy_valid(result_path: Path) -> bool:
    policy_path = result_path.parent / "egress-proxy" / "start-squid.sh"
    try:
        return policy_path.read_text(encoding="utf-8") == squid_bootstrap_command()
    except (OSError, UnicodeError):
        return False


def _condition_results(
    *,
    output_root: Path,
    condition: str,
    manifest: dict[str, Any],
    host_credential_leaks: list[str],
) -> list[dict[str, Any]]:
    condition_root = output_root / condition
    expected = {
        entry["id"]: entry for entry in manifest["tasks"] if condition in entry["arms"]
    }
    result_paths: list[Path] = []
    for path in condition_root.rglob("result.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        if isinstance(payload, dict) and "task_name" in payload:
            result_paths.append(path)
    if len(result_paths) != len(expected):
        raise RuntimeError(
            f"{condition} produced {len(result_paths)} task results; expected {len(expected)}"
        )

    cells: list[dict[str, Any]] = []
    seen: set[str] = set()
    for path in sorted(result_paths):
        result = json.loads(path.read_text(encoding="utf-8"))
        task_id = str(result.get("task_name", "")).removeprefix("datacurve/")
        if task_id not in expected or task_id in seen:
            raise RuntimeError(f"unexpected or duplicate {condition} task result: {task_id}")
        seen.add(task_id)
        entry = expected[task_id]
        if result.get("task_checksum") != entry["preparedTaskChecksum"]:
            raise RuntimeError(f"executed task checksum mismatch: {condition}/{task_id}")
        config = result.get("config", {})
        agent_config = config.get("agent", {})
        if agent_config.get("import_path") != "pi_agent:PiOckleAgent":
            raise RuntimeError(f"agent import drift: {condition}/{task_id}")
        if agent_config.get("model_name") != MODEL:
            raise RuntimeError(f"agent model drift: {condition}/{task_id}")
        if agent_config.get("kwargs", {}).get("condition") != condition:
            raise RuntimeError(f"agent condition drift: {condition}/{task_id}")

        agent_result = result.get("agent_result") or {}
        metadata = agent_result.get("metadata") or {}
        security = metadata.get("security") or {}
        continuation = metadata.get("continuation")
        proxy_policy_valid = _proxy_policy_valid(path)
        final_status_valid = _final_status_evidence_valid(metadata, path)
        runtime_valid = all(
            [
                metadata.get("runtimeEvidenceValid") is True,
                metadata.get("finalStateEvidenceValid") is True,
                _continuation_evidence_valid(continuation, path),
                proxy_policy_valid,
                final_status_valid,
                metadata.get("provider") == MODEL_PROVIDER,
                metadata.get("model") == MODEL_ID,
                metadata.get("api") == MODEL_API,
                metadata.get("thinking") == "max",
                isinstance(metadata.get("agentUid"), int)
                and metadata.get("agentUid") > 0,
                agent_result.get("summarization_count") == 0,
                security.get("scanError") is False,
                security.get("credentialLeak") is False,
                not host_credential_leaks,
            ]
        )
        verifier = result.get("verifier_result") or {}
        rewards = verifier.get("rewards") or {}
        reward = rewards.get("reward")
        if reward not in (0, 0.0, 1, 1.0):
            raise RuntimeError(f"missing binary DeepSWE reward: {condition}/{task_id}")
        patch = path.parent / "artifacts" / "model.patch"
        delivered = patch.is_file() and patch.stat().st_size > 0

        worktree_clean = metadata.get("worktreeClean")
        if not isinstance(worktree_clean, bool) or not isinstance(
            metadata.get("worktreeStatusSha256"), str
        ):
            runtime_valid = False

        guard_verdict = None
        guard_commit_verdict = None
        guard_worktree_verdict = None
        safe_delivery = None
        if condition == "full":
            if metadata.get("guardBundleSha256") != manifest["execution"]["guardBundleSha256"]:
                runtime_valid = False
            guard = metadata.get("guard") or {}
            verdicts: dict[str, str | None] = {}
            exits: dict[str, int | None] = {}
            exit_codes = {"clear": 0, "blocked": 1, "indeterminate": 2}
            for candidate in ("commit", "worktree"):
                evidence = guard.get(candidate) or {}
                result_payload = evidence.get("result") or {}
                verdict = result_payload.get("verdict")
                exit_code = evidence.get("exitCode")
                verdicts[candidate] = verdict
                exits[candidate] = exit_code
                if verdict not in exit_codes or exit_code != exit_codes.get(verdict):
                    runtime_valid = False
            guard_commit_verdict = verdicts["commit"]
            guard_worktree_verdict = verdicts["worktree"]
            if guard_commit_verdict == "clear" and guard_worktree_verdict == "clear":
                guard_verdict = "clear"
            elif "blocked" in verdicts.values():
                guard_verdict = "blocked"
            else:
                guard_verdict = "indeterminate"
            safe_delivery = guard_verdict == "clear"

        resolved = bool(reward == 1)
        exception = result.get("exception_info")
        complete = (
            resolved
            and runtime_valid
            and exception is None
            and worktree_clean is True
        )
        if condition == "full":
            complete = complete and safe_delivery is True
        cells.append(
            {
                "condition": condition,
                "taskId": task_id,
                "language": entry["language"],
                "reward": int(reward),
                "f2p": rewards.get("f2p"),
                "p2p": rewards.get("p2p"),
                "partial": rewards.get("partial"),
                "resolved": resolved,
                "delivered": delivered,
                "runtimeValid": runtime_valid,
                "proxyPolicyValid": proxy_policy_valid,
                "finalStatusEvidenceValid": final_status_valid,
                "safeDelivery": safe_delivery,
                "worktreeClean": worktree_clean,
                "candidateIndexClean": metadata.get("candidateIndexClean"),
                "guardVerdict": guard_verdict,
                "guardCommitVerdict": guard_commit_verdict,
                "guardWorktreeVerdict": guard_worktree_verdict,
                "unsafeDelivered": bool(
                    condition == "full" and delivered and safe_delivery is not True
                ),
                "complete": complete,
                "exception": exception,
                "nInputTokens": agent_result.get("n_input_tokens"),
                "nCacheTokens": agent_result.get("n_cache_tokens"),
                "nOutputTokens": agent_result.get("n_output_tokens"),
                "reasoningTokens": metadata.get("reasoningTokens"),
                "nAgentSteps": agent_result.get("n_agent_steps"),
                "continuationCount": (
                    continuation.get("count") if isinstance(continuation, dict) else None
                ),
                "agentDuration": result.get("agent_execution"),
                "resultPath": path.relative_to(output_root).as_posix(),
            }
        )
    return sorted(cells, key=lambda cell: cell["taskId"])


def _summarize(cells: list[dict[str, Any]]) -> dict[str, Any]:
    by_condition: dict[str, Any] = {}
    for condition in ("bare", "inner", "full"):
        selected = [cell for cell in cells if cell["condition"] == condition]
        by_condition[condition] = {
            "subjects": len(selected),
            "resolved": sum(cell["resolved"] for cell in selected),
            "complete": sum(cell["complete"] for cell in selected),
            "runtimeValid": sum(cell["runtimeValid"] for cell in selected),
            "unsafeDelivered": sum(cell["unsafeDelivered"] for cell in selected),
            "inputTokens": sum(int(cell["nInputTokens"] or 0) for cell in selected),
            "outputTokens": sum(int(cell["nOutputTokens"] or 0) for cell in selected),
            "steps": sum(int(cell["nAgentSteps"] or 0) for cell in selected),
            "continuations": sum(
                int(cell["continuationCount"] or 0) for cell in selected
            ),
        }
    return {"schemaVersion": 1, "subjects": len(cells), "byCondition": by_condition}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prepared-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--secrets-file", type=Path, required=True)
    parser.add_argument("--guard-bundle", type=Path, required=True)
    parser.add_argument("--concurrency", type=int, default=4)
    args = parser.parse_args()

    module_dir = Path(__file__).resolve().parent
    ockle_root = module_dir.parents[1]
    manifest_path = module_dir / "pilot-v1.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    validate_pilot_manifest(manifest)
    prepared_root = _require_outside_repository(
        args.prepared_root, ockle_root, "prepared root"
    )
    prepared = _verify_prepared_root(prepared_root, manifest_path, manifest)
    secret_file = _require_outside_repository(
        args.secrets_file, ockle_root, "secret file"
    )
    secret = _verify_secret_file(secret_file)
    guard_bundle = _require_outside_repository(
        args.guard_bundle, ockle_root, "guard bundle"
    )
    guard_sha = _verify_execution_contract(manifest, guard_bundle)
    pier = _verify_pier_install()
    checkpoint = _git_checkpoint(ockle_root)

    output_root = _require_outside_repository(args.output, ockle_root, "formal output")
    if output_root.exists():
        raise FileExistsError(f"formal output already exists: {output_root}")
    if args.concurrency < 1 or args.concurrency > 16:
        raise ValueError("concurrency must be between 1 and 16")
    output_root.mkdir(parents=True)

    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(module_dir)
    environment["PYTHONUNBUFFERED"] = "1"
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment["LITELLM_LOCAL_MODEL_COST_MAP"] = "true"
    inputs = {
        "schemaVersion": 1,
        "ockle": checkpoint,
        "manifestSha256": prepared["manifestSha256"],
        "materializerSha256": prepared["materializerSha256"],
        "sourceArchiveSha256": prepared["sourceArchiveSha256"],
        "guardBundleSha256": guard_sha,
        "pier": pier,
        "preparedRoot": str(prepared_root),
        "conditions": ["bare", "inner", "full"],
        "subjects": 29,
        "concurrency": args.concurrency,
    }
    (output_root / "formal-inputs.json").write_text(
        json.dumps(inputs, indent=2) + "\n", encoding="utf-8", newline="\n"
    )

    cells: list[dict[str, Any]] = []
    for condition in ("bare", "inner", "full"):
        if _git_checkpoint(ockle_root) != checkpoint:
            raise RuntimeError("Ockle runtime assets changed during the formal pilot")
        command = build_pier_command(
            condition=condition,
            manifest=manifest,
            tasks_root=prepared_root / "tasks",
            jobs_root=output_root,
            secrets_file=secret_file,
            concurrency=args.concurrency,
            guard_bundle=guard_bundle if condition == "full" else None,
            python_executable=Path(str(pier["python"])),
        )
        launch = {
            "schemaVersion": 1,
            "condition": condition,
            "ockle": checkpoint,
            "manifestSha256": prepared["manifestSha256"],
            "pier": pier,
            "command": command,
        }
        (output_root / f"{condition}-launch.json").write_text(
            json.dumps(launch, indent=2) + "\n", encoding="utf-8", newline="\n"
        )
        completed, leaks = _run_pier_with_credential_scan(
            command=command,
            cwd=Path.home(),
            environment=environment,
            output_root=output_root,
            condition=condition,
            secret=secret,
        )
        if completed.returncode != 0:
            raise RuntimeError(
                f"Pier failed for {condition} with exit code {completed.returncode}"
            )
        if _git_checkpoint(ockle_root) != checkpoint:
            raise RuntimeError("Ockle runtime assets changed during the formal pilot")
        condition_cells = _condition_results(
            output_root=output_root,
            condition=condition,
            manifest=manifest,
            host_credential_leaks=leaks,
        )
        cells.extend(condition_cells)
        (output_root / "partial-cells.json").write_text(
            json.dumps(cells, indent=2) + "\n", encoding="utf-8", newline="\n"
        )

    expected_cells = sum(len(task["arms"]) for task in manifest["tasks"])
    if _git_checkpoint(ockle_root) != checkpoint:
        raise RuntimeError("Ockle runtime assets changed during the formal pilot")
    identities = {(cell["condition"], cell["taskId"]) for cell in cells}
    if len(cells) != expected_cells or len(identities) != expected_cells:
        raise RuntimeError("formal pilot did not produce the exact 29-cell matrix")
    summary = _summarize(cells)
    if summary["subjects"] != 29:
        raise RuntimeError("formal pilot summary subject count mismatch")
    (output_root / "cells.json").write_text(
        json.dumps(cells, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    (output_root / "summary.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    (output_root / "COMPLETE").write_text(
        hashlib.sha256((output_root / "cells.json").read_bytes()).hexdigest() + "\n",
        encoding="ascii",
        newline="\n",
    )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
