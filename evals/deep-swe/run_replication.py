from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import subprocess
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Any

from pi_agent import (
    MODEL_API,
    MODEL_BASE_URL,
    MODEL_ID,
    MODEL_PROVIDER,
    parse_session_evidence,
)
from run_pilot import (
    ArtifactCredentialScanError,
    _continuation_evidence_valid,
    _final_status_evidence_valid,
    _git_checkpoint,
    _proxy_policy_valid,
    _redact_secret_tree,
    _require_outside_repository,
    _verify_execution_contract,
    _verify_pier_install,
    _verify_prepared_root,
    _verify_secret_file,
)

MODEL = f"{MODEL_PROVIDER}/{MODEL_ID}"
PIER_RUN_BOOTSTRAP = "from pier.cli.main import app; app()"
CONDITIONS = ("bare", "inner", "full")
EXPECTED_TASKS = (
    {
        "id": "sql-formatter-bigquery-pipe-formatting",
        "language": "typescript",
        "arms": ["bare", "inner", "full"],
        "r5ObservedReward": {"bare": 1, "inner": 0, "full": 1},
    },
    {
        "id": "tengo-callable-instance-isolation",
        "language": "go",
        "arms": ["bare", "inner"],
        "r5ObservedReward": {"bare": 0, "inner": 1},
    },
)
EXPECTED_SOURCE = {
    "pilotManifestSha256": "097daf7a519ba70247cd7b20dcd6ce240169fb00c1dec152663247c0937448e4",
    "r5SubjectCheckpoint": "b5d7db4be95c51f44ba5cbc70c7f73cd847ebffd",
    "r5CellsSha256": "3708e0bdd2517b3b65fed8f14d1aa0b541066ac0734877eae2dead251cfbfaec",
    "r5RegradeScorerCheckpoint": "c4c97b4faa9f835de76b2d1262601389f2228066",
    "r5RegradeSha256": "b6abddc53aeed4b3133fdc1b85d49480cbeba1a186f0bce3afa6ca512d0af522",
}
EXPECTED_CONCURRENCY = {"bare": 3, "inner": 3, "full": 2}
EXPECTED_REPEATS = 10
EXPECTED_TOTAL_CELLS = 50


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def validate_replication_manifest(
    replication: dict[str, Any],
    *,
    pilot_manifest: dict[str, Any],
    pilot_manifest_bytes: bytes,
) -> dict[str, int]:
    if replication.get("schemaVersion") != 1:
        raise ValueError("replication schema version drift")
    if replication.get("kind") != "post-hoc-discordant-replication":
        raise ValueError("replication kind drift")
    if replication.get("source") != EXPECTED_SOURCE:
        raise ValueError("replication source authority drift")
    if _sha256(pilot_manifest_bytes) != EXPECTED_SOURCE["pilotManifestSha256"]:
        raise ValueError("source pilot manifest bytes drift")
    selection = replication.get("selection")
    if not isinstance(selection, dict) or selection.get("usesR5Outcomes") is not True:
        raise ValueError("replication must disclose outcome-aware task selection")
    if selection.get("seed") != "Ockle DeepSWE discordant replication v1":
        raise ValueError("replication identity seed drift")

    execution = replication.get("execution")
    if not isinstance(execution, dict):
        raise ValueError("replication execution contract is missing")
    expected_execution = {
        "model": f"{MODEL_PROVIDER}/{MODEL_ID}",
        "modelApi": MODEL_API,
        "modelBaseUrl": MODEL_BASE_URL,
        "thinking": "max",
        "magicContext": False,
        "piNativeCompaction": False,
        "repeatsPerArmTask": EXPECTED_REPEATS,
        "totalCells": EXPECTED_TOTAL_CELLS,
        "globalConcurrency": 8,
        "conditionConcurrency": EXPECTED_CONCURRENCY,
        "launchMode": "three-condition-jobs-concurrent-fixed-partition",
        "maxRetries": 0,
        "timeoutSeconds": 5400,
        "repeatIndexAuthority": "within-condition-task-started-at-then-trial-name",
        "stopRule": "fixed-50-no-outcome-based-reruns",
        "providerErrorPolicy": "final-error-invalid-recovered-errors-counted",
        "validFinalAssistantStopReasons": ["stop", "toolUse"],
        "maxContinuations": 1,
        "continuationTrigger": "trusted-dirty-worktree",
        "candidateIndexAuthority": "actual-index-plus-independent-worktree",
        "statusEvidence": "root-frozen-raw-bytes-sha256",
        "rejectSplitIndex": True,
        "pierSquidSafePorts": [80, 443, 8317],
        "pierSquidSslPorts": [443],
    }
    if execution != expected_execution:
        raise ValueError("replication execution contract drift")
    if sum(EXPECTED_CONCURRENCY.values()) != execution["globalConcurrency"]:
        raise ValueError("condition concurrency does not match global concurrency")

    tasks = replication.get("tasks")
    if tasks != list(EXPECTED_TASKS):
        raise ValueError("replication task selection drift")
    pilot_by_id = {task["id"]: task for task in pilot_manifest.get("tasks", [])}
    for selected in tasks:
        source = pilot_by_id.get(selected["id"])
        if not isinstance(source, dict):
            raise ValueError(f"replication task is absent from pilot: {selected['id']}")
        if source.get("language") != selected["language"]:
            raise ValueError(f"replication task language drift: {selected['id']}")
        if not set(selected["arms"]).issubset(source.get("arms", [])):
            raise ValueError(f"replication task arm is not calibrated: {selected['id']}")

    plan = build_replication_plan(replication)
    if len(plan) != EXPECTED_TOTAL_CELLS:
        raise ValueError("replication cell count drift")
    return {"tasks": len(tasks), "cells": len(plan), "repeats": EXPECTED_REPEATS}


def build_replication_plan(replication: dict[str, Any]) -> list[dict[str, Any]]:
    selection = replication.get("selection")
    execution = replication.get("execution")
    tasks = replication.get("tasks")
    if not isinstance(selection, dict) or not isinstance(execution, dict) or not isinstance(tasks, list):
        raise ValueError("replication manifest is incomplete")
    seed = selection.get("seed")
    repeats = execution.get("repeatsPerArmTask")
    if not isinstance(seed, str) or type(repeats) is not int or repeats < 1:
        raise ValueError("replication plan inputs are invalid")

    cells: list[dict[str, Any]] = []
    for task in tasks:
        for condition in task["arms"]:
            for repeat_index in range(1, repeats + 1):
                identity = f"{seed}\0{condition}\0{task['id']}\0{repeat_index}"
                cells.append(
                    {
                        "cellId": hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16],
                        "condition": condition,
                        "taskId": task["id"],
                        "repeatIndex": repeat_index,
                    }
                )
    return sorted(cells, key=lambda cell: cell["cellId"])


def build_replication_pier_command(
    *,
    condition: str,
    replication: dict[str, Any],
    pilot_manifest: dict[str, Any],
    tasks_root: Path,
    jobs_root: Path,
    secrets_file: Path,
    guard_bundle: Path,
    python_executable: Path | str,
    agent_import_path: str,
) -> list[str]:
    if condition not in CONDITIONS:
        raise ValueError(f"unknown replication condition: {condition}")
    if agent_import_path not in {
        "pi_agent:PiOckleAgent",
        "boundary_probe:BoundaryProbeAgent",
    }:
        raise ValueError("unexpected replication agent import path")
    execution = replication["execution"]
    selected = [
        task["id"] for task in replication["tasks"] if condition in task["arms"]
    ]
    pilot_by_id = {task["id"]: task for task in pilot_manifest["tasks"]}
    if any(task_id not in pilot_by_id for task_id in selected):
        raise ValueError("replication selected an unknown pilot task")

    command = [
        str(python_executable),
        "-B",
        "-c",
        PIER_RUN_BOOTSTRAP,
        "run",
        "--path",
        str(tasks_root),
    ]
    for task_id in selected:
        command.extend(["--include-task-name", task_id])
    command.extend(
        [
            "--agent-import-path",
            agent_import_path,
            "--model",
            MODEL,
            "--agent-kwarg",
            f"condition={condition}",
        ]
    )
    if condition == "full":
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
            "--n-attempts",
            str(execution["repeatsPerArmTask"]),
            "--n-concurrent",
            str(execution["conditionConcurrency"][condition]),
            "--max-retries",
            str(execution["maxRetries"]),
            "--yes",
            "--quiet",
        ]
    )
    return command


def extract_replication_boundary_probe_results(
    *,
    output_root: Path,
    condition: str,
    replication: dict[str, Any],
    pilot_manifest: dict[str, Any],
    host_credential_leaks: list[str],
    expected_tasks_root: Path,
    expected_command: list[str],
) -> list[dict[str, Any]]:
    import_path = "boundary_probe:BoundaryProbeAgent"
    condition_root = output_root / condition
    _validate_condition_job_authority(
        condition_root,
        condition=condition,
        replication=replication,
        expected_agent_import_path=import_path,
        expected_tasks_root=expected_tasks_root,
        expected_command=expected_command,
    )
    selected = [
        task["id"] for task in replication["tasks"] if condition in task["arms"]
    ]
    expected_count = (
        len(selected) * replication["execution"]["repeatsPerArmTask"]
    )
    pilot_by_id = {task["id"]: task for task in pilot_manifest["tasks"]}
    result_paths: list[Path] = []
    for path in condition_root.rglob("result.json"):
        try:
            payload = load_json(path)
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
            continue
        if "task_name" in payload:
            result_paths.append(path)
    if len(result_paths) != expected_count:
        raise RuntimeError(
            f"{condition} produced {len(result_paths)} boundary results; expected {expected_count}"
        )

    expected_probe = {
        "user": "ockle",
        "appWrite": True,
        "optWriteBlocked": True,
        "oracleHidden": True,
        "providerReachable": True,
        "publicProxyBlocked": True,
        "publicDirectBlocked": True,
    }
    records: list[dict[str, Any]] = []
    for path in sorted(result_paths):
        result = load_json(path)
        task_id = str(result.get("task_name", "")).removeprefix("datacurve/")
        if task_id not in selected or result.get("task_name") != f"datacurve/{task_id}":
            raise RuntimeError(f"unexpected boundary task result: {condition}/{task_id}")
        task = pilot_by_id[task_id]
        if result.get("task_checksum") != task["preparedTaskChecksum"]:
            raise RuntimeError(f"boundary task checksum drift: {condition}/{task_id}")
        trial_name = result.get("trial_name")
        started_at = result.get("started_at")
        if (
            not isinstance(trial_name, str)
            or trial_name != path.parent.name
            or not isinstance(started_at, str)
            or not started_at
        ):
            raise RuntimeError(f"boundary trial identity drift: {condition}/{task_id}")
        config = result.get("config") or {}
        agent = config.get("agent") or {}
        kwargs = agent.get("kwargs") or {}
        if (
            agent.get("import_path") != import_path
            or agent.get("model_name") != MODEL
            or kwargs.get("condition") != condition
        ):
            raise RuntimeError(f"boundary agent config drift: {condition}/{task_id}")
        metadata = (result.get("agent_result") or {}).get("metadata") or {}
        probe = metadata.get("result") or {}
        probe_valid = all(
            [
                metadata.get("boundaryProbeValid") is True,
                isinstance(probe.get("uid"), int) and probe.get("uid") > 0,
                all(probe.get(key) == value for key, value in expected_probe.items()),
                result.get("exception_info") is None,
                _proxy_policy_valid(path),
                not host_credential_leaks,
                not list((path.parent / "agent").rglob("*.jsonl")),
            ]
        )
        rewards = (result.get("verifier_result") or {}).get("rewards") or {}
        if rewards.get("reward") not in (0, 0.0):
            raise RuntimeError(f"boundary verifier outcome drift: {condition}/{task_id}")
        patch = path.parent / "artifacts" / "model.patch"
        if patch.is_file() and patch.stat().st_size > 0:
            probe_valid = False
        if not probe_valid:
            raise RuntimeError(f"boundary probe failed: {condition}/{task_id}")
        records.append(
            {
                "condition": condition,
                "taskId": task_id,
                "trialName": trial_name,
                "startedAt": started_at,
                "boundaryProbeValid": True,
                "proxyPolicyValid": True,
                "reward": 0,
                "resultPath": path.relative_to(output_root).as_posix(),
            }
        )
    assigned = assign_repeat_indices(
        [
            {
                "taskId": record["taskId"],
                "trialName": record["trialName"],
                "startedAt": record["startedAt"],
            }
            for record in records
        ],
        condition=condition,
        replication=replication,
    )
    identities = {record["trialName"]: record for record in assigned}
    return sorted(
        [
            {
                **record,
                "repeatIndex": identities[record["trialName"]]["repeatIndex"],
                "cellId": identities[record["trialName"]]["cellId"],
            }
            for record in records
        ],
        key=lambda record: (record["taskId"], record["repeatIndex"]),
    )


def _pier_content_hash(path: Path) -> str:
    digest = hashlib.sha256()
    if path.is_file():
        digest.update(path.name.encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        return digest.hexdigest()
    for file_path in sorted(candidate for candidate in path.rglob("*") if candidate.is_file()):
        if ".git" in file_path.relative_to(path).parts:
            continue
        digest.update(file_path.relative_to(path).as_posix().encode())
        digest.update(b"\0")
        digest.update(file_path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _expected_retry_config(*, include_none: bool) -> dict[str, Any]:
    retry = {
        "exclude_exceptions": [
            "AgentTimeoutError",
            "RewardFileEmptyError",
            "RewardFileNotFoundError",
            "VerifierOutputParseError",
            "VerifierTimeoutError",
        ],
        "include_exceptions": None,
        "max_retries": 0,
        "max_wait_sec": 60.0,
        "min_wait_sec": 1.0,
        "wait_multiplier": 1.0,
    }
    return retry if include_none else {key: value for key, value in retry.items() if value is not None}


def _retry_config_matches(actual: Any, expected: dict[str, Any]) -> bool:
    # Pier models these exception fields as sets, so JSON list order varies by process.
    if not isinstance(actual, dict) or set(actual) != set(expected):
        return False
    for key, expected_value in expected.items():
        actual_value = actual.get(key)
        if key not in {"include_exceptions", "exclude_exceptions"}:
            if actual_value != expected_value:
                return False
            continue
        if expected_value is None:
            if actual_value is not None:
                return False
            continue
        if (
            not isinstance(expected_value, list)
            or not isinstance(actual_value, list)
            or any(not isinstance(value, str) for value in actual_value)
            or len(actual_value) != len(set(actual_value))
            or set(actual_value) != set(expected_value)
        ):
            return False
    return True


def _expected_environment_config(*, include_none: bool) -> dict[str, Any]:
    environment = {
        "cpu_enforcement_policy": "auto",
        "delete": True,
        "env": {},
        "force_build": False,
        "import_path": None,
        "kwargs": {},
        "memory_enforcement_policy": "auto",
        "mounts": None,
        "override_cpus": None,
        "override_gpus": None,
        "override_memory_mb": None,
        "override_storage_mb": None,
        "suppress_override_warnings": False,
        "type": "docker",
    }
    return environment if include_none else {
        key: value for key, value in environment.items() if value is not None
    }


def _validate_condition_job_authority(
    condition_root: Path,
    *,
    condition: str,
    replication: dict[str, Any],
    expected_agent_import_path: str,
    expected_tasks_root: Path,
    expected_command: list[str],
) -> None:
    selected = [
        task["id"] for task in replication["tasks"] if condition in task["arms"]
    ]
    execution = replication["execution"]
    repeats = execution["repeatsPerArmTask"]
    concurrency = execution["conditionConcurrency"][condition]
    config_path = condition_root / "config.json"
    lock_path = condition_root / "lock.json"
    if any(
        not path.is_file() or path.is_symlink() for path in (config_path, lock_path)
    ):
        raise RuntimeError(f"Pier job authority is missing for {condition}")
    if (
        len(expected_command) < 5
        or expected_command[1:3] != ["-B", "-c"]
        or expected_command[3] != PIER_RUN_BOOTSTRAP
    ):
        raise RuntimeError(f"trusted Pier command shape drift for {condition}")
    expected_invocation = ["-c", *expected_command[4:]]
    expected_kwargs: dict[str, str] = {"condition": condition}
    if condition == "full":
        guard_options = [
            value.removeprefix("guard_bundle=")
            for index, value in enumerate(expected_command)
            if index > 0
            and expected_command[index - 1] == "--agent-kwarg"
            and value.startswith("guard_bundle=")
        ]
        if len(guard_options) != 1 or not guard_options[0]:
            raise RuntimeError("trusted full Pier command is missing its guard bundle")
        expected_kwargs["guard_bundle"] = guard_options[0]

    config_agent = {
        "name": None,
        "import_path": expected_agent_import_path,
        "model_name": MODEL,
        "kwargs": expected_kwargs,
        "env": {},
        "max_timeout_sec": None,
        "override_setup_timeout_sec": None,
        "override_timeout_sec": None,
    }
    dataset = {
        "download_dir": None,
        "exclude_task_names": None,
        "n_tasks": None,
        "name": None,
        "overwrite": False,
        "path": str(expected_tasks_root),
        "ref": None,
        "registry_path": None,
        "registry_url": None,
        "sample_seed": None,
        "task_names": selected,
        "version": None,
    }
    expected_config = {
        "agent_setup_timeout_multiplier": None,
        "agent_timeout_multiplier": None,
        "agents": [config_agent],
        "artifacts": [],
        "datasets": [dataset],
        "debug": False,
        "environment": _expected_environment_config(include_none=True),
        "environment_build_timeout_multiplier": None,
        "job_name": condition,
        "jobs_dir": str(condition_root.parent),
        "metrics": [],
        "n_attempts": repeats,
        "n_concurrent_trials": concurrency,
        "quiet": True,
        "retry": _expected_retry_config(include_none=True),
        "tasks": [],
        "timeout_multiplier": 1.0,
        "verifier": {
            "disable": False,
            "env": {},
            "max_timeout_sec": None,
            "override_timeout_sec": None,
        },
        "verifier_timeout_multiplier": None,
    }
    config = load_json(config_path)
    config_without_retry = {
        key: value for key, value in config.items() if key != "retry"
    }
    expected_without_retry = {
        key: value for key, value in expected_config.items() if key != "retry"
    }
    if (
        config_without_retry != expected_without_retry
        or not _retry_config_matches(config.get("retry"), expected_config["retry"])
    ):
        raise RuntimeError(f"Pier job config drift for {condition}")

    lock = load_json(lock_path)
    if set(lock) != {
        "schema_version",
        "created_at",
        "pier",
        "invocation",
        "n_concurrent_trials",
        "retry",
        "trials",
    } or any(
        [
            lock.get("schema_version") != 1,
            not isinstance(lock.get("created_at"), str),
            not lock.get("created_at"),
            lock.get("pier") != {"version": "0.3.0"},
            lock.get("invocation") != expected_invocation,
            lock.get("n_concurrent_trials") != concurrency,
            not _retry_config_matches(
                lock.get("retry"), _expected_retry_config(include_none=False)
            ),
        ]
    ):
        raise RuntimeError(f"Pier job lock drift for {condition}")
    trials = lock.get("trials")
    expected_trials = repeats * len(selected)
    if not isinstance(trials, list) or len(trials) != expected_trials:
        raise RuntimeError(f"Pier locked trial count drift for {condition}")
    lock_agent = {
        "env": {},
        "import_path": expected_agent_import_path,
        "kwargs": expected_kwargs,
        "model_name": MODEL,
    }
    lock_environment = _expected_environment_config(include_none=False)
    lock_verifier = {"disable": False, "env": {}}
    task_counts: Counter[str] = Counter()
    for trial in trials:
        if not isinstance(trial, dict):
            raise RuntimeError(f"Pier locked trial shape drift for {condition}")
        task = trial.get("task")
        if not isinstance(task, dict):
            raise RuntimeError(f"Pier locked trial shape drift for {condition}")
        task_id = task.get("name")
        if task_id not in selected:
            raise RuntimeError(f"Pier locked an unexpected task for {condition}")
        task_root = (expected_tasks_root / str(task_id)).resolve()
        expected_trial = {
            "task": {
                "name": task_id,
                "type": "local",
                "digest": "sha256:" + _pier_content_hash(task_root),
                "source": "tasks",
                "path": str(task_root),
            },
            "timeout_multiplier": 1.0,
            "agent": lock_agent,
            "environment": lock_environment,
            "verifier": lock_verifier,
        }
        if trial != expected_trial:
            raise RuntimeError(f"Pier locked trial execution drift for {condition}")
        task_counts[str(task_id)] += 1
    if task_counts != Counter({task_id: repeats for task_id in selected}):
        raise RuntimeError(f"Pier locked task repetition drift for {condition}")


def extract_replication_condition_results(
    *,
    output_root: Path,
    condition: str,
    replication: dict[str, Any],
    pilot_manifest: dict[str, Any],
    host_credential_leaks: list[str],
    expected_agent_import_path: str,
    expected_tasks_root: Path,
    expected_command: list[str],
) -> list[dict[str, Any]]:
    if condition not in CONDITIONS:
        raise ValueError(f"unknown replication condition: {condition}")
    condition_root = output_root / condition
    _validate_condition_job_authority(
        condition_root,
        condition=condition,
        replication=replication,
        expected_agent_import_path=expected_agent_import_path,
        expected_tasks_root=expected_tasks_root,
        expected_command=expected_command,
    )
    expected_tasks = [
        task["id"] for task in replication["tasks"] if condition in task["arms"]
    ]
    expected_count = (
        len(expected_tasks) * replication["execution"]["repeatsPerArmTask"]
    )
    result_paths: list[Path] = []
    for path in condition_root.rglob("result.json"):
        try:
            payload = load_json(path)
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
            continue
        if "task_name" in payload:
            result_paths.append(path)
    if len(result_paths) != expected_count:
        raise RuntimeError(
            f"{condition} produced {len(result_paths)} task results; expected {expected_count}"
        )

    extracted = [
        extract_replication_result(
            path,
            output_root=output_root,
            condition=condition,
            replication=replication,
            pilot_manifest=pilot_manifest,
            host_credential_leaks=host_credential_leaks,
            expected_agent_import_path=expected_agent_import_path,
        )
        for path in sorted(result_paths)
    ]
    assigned = assign_repeat_indices(
        [
            {
                "taskId": cell["taskId"],
                "trialName": cell["trialName"],
                "startedAt": cell["startedAt"],
            }
            for cell in extracted
        ],
        condition=condition,
        replication=replication,
    )
    identity_by_trial = {record["trialName"]: record for record in assigned}
    if len(identity_by_trial) != len(extracted):
        raise RuntimeError(f"duplicate trial identity for {condition}")
    cells = [
        {
            **cell,
            "repeatIndex": identity_by_trial[cell["trialName"]]["repeatIndex"],
            "cellId": identity_by_trial[cell["trialName"]]["cellId"],
        }
        for cell in extracted
    ]
    return sorted(cells, key=lambda cell: (cell["taskId"], cell["repeatIndex"]))


def _guard_state(
    metadata: dict[str, Any], expected_guard_sha: str
) -> tuple[str | None, str | None, str | None, bool | None, bool]:
    if metadata.get("guardBundleSha256") != expected_guard_sha:
        return None, None, None, None, False
    guard = metadata.get("guard")
    if not isinstance(guard, dict):
        return None, None, None, None, False
    exit_codes = {"clear": 0, "blocked": 1, "indeterminate": 2}
    verdicts: dict[str, str] = {}
    for name in ("commit", "worktree"):
        evidence = guard.get(name)
        if not isinstance(evidence, dict):
            return None, None, None, None, False
        result = evidence.get("result")
        if not isinstance(result, dict):
            return None, None, None, None, False
        verdict = result.get("verdict")
        if (
            result.get("schemaVersion") != 1
            or result.get("operation") != "check"
            or verdict not in exit_codes
            or evidence.get("exitCode") != exit_codes[verdict]
        ):
            return None, None, None, None, False
        verdicts[name] = verdict
    overall = (
        "clear"
        if verdicts["commit"] == verdicts["worktree"] == "clear"
        else "blocked"
        if "blocked" in verdicts.values()
        else "indeterminate"
    )
    return overall, verdicts["commit"], verdicts["worktree"], overall == "clear", True


def _parse_provider_error_chronology(session_path: Path) -> dict[str, int]:
    session_ids: set[str] = set()
    model_changes: set[tuple[str, str]] = set()
    thinking_levels: set[str] = set()
    assistant_models: set[tuple[str, str]] = set()
    assistant_apis: set[str] = set()
    compaction_count = 0
    total_errors = 0
    recovered_errors = 0
    pending_errors = 0
    assistant_records = 0
    for line in session_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        row_type = row.get("type")
        if row_type == "session":
            if row.get("cwd") != "/app" or not isinstance(row.get("id"), str):
                raise ValueError("session identity is invalid")
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
        assistant_records += 1
        identity = (str(message.get("provider")), str(message.get("model")))
        api = str(message.get("api"))
        assistant_models.add(identity)
        assistant_apis.add(api)
        if identity != (MODEL_PROVIDER, MODEL_ID) or api != MODEL_API:
            raise ValueError("assistant provider, model, or API drift")
        stop_reason = message.get("stopReason")
        if stop_reason == "error":
            total_errors += 1
            pending_errors += 1
            continue
        if stop_reason not in {"stop", "toolUse"} or not isinstance(
            message.get("usage"), dict
        ):
            raise ValueError("assistant stop reason or usage is invalid")
        recovered_errors += pending_errors
        pending_errors = 0
    expected_model = {(MODEL_PROVIDER, MODEL_ID)}
    if (
        len(session_ids) != 1
        or model_changes != expected_model
        or thinking_levels != {"max"}
        or assistant_models != expected_model
        or assistant_apis != {MODEL_API}
        or compaction_count != 0
        or assistant_records == 0
    ):
        raise ValueError("session runtime chronology is invalid")
    return {
        "provider_error_count": total_errors,
        "recovered_provider_error_count": recovered_errors,
        "terminal_provider_error_count": pending_errors,
    }


def extract_replication_result(
    result_path: Path,
    *,
    output_root: Path,
    condition: str,
    replication: dict[str, Any],
    pilot_manifest: dict[str, Any],
    host_credential_leaks: list[str],
    expected_agent_import_path: str,
) -> dict[str, Any]:
    if condition not in CONDITIONS:
        raise ValueError(f"unknown replication condition: {condition}")
    if (
        not result_path.is_file()
        or result_path.is_symlink()
        or output_root.resolve() not in result_path.resolve().parents
    ):
        raise ValueError("result path is not a regular file inside the output root")
    result = load_json(result_path)
    task_id = str(result.get("task_name", "")).removeprefix("datacurve/")
    selected = {
        task["id"] for task in replication["tasks"] if condition in task["arms"]
    }
    if task_id not in selected:
        raise ValueError(f"unexpected replication task result: {condition}/{task_id}")
    pilot_by_id = {task["id"]: task for task in pilot_manifest["tasks"]}
    task = pilot_by_id[task_id]
    if result.get("task_name") != f"datacurve/{task_id}":
        raise ValueError(f"task identity drift: {condition}/{task_id}")
    if result.get("task_checksum") != task["preparedTaskChecksum"]:
        raise ValueError(f"task checksum drift: {condition}/{task_id}")
    trial_name = result.get("trial_name")
    if not isinstance(trial_name, str) or trial_name != result_path.parent.name:
        raise ValueError(f"trial identity drift: {condition}/{task_id}")
    started_at = result.get("started_at")
    if not isinstance(started_at, str) or not started_at:
        raise ValueError(f"started_at is missing: {condition}/{task_id}")

    config = result.get("config")
    if not isinstance(config, dict):
        raise ValueError(f"trial config is missing: {condition}/{task_id}")
    agent_config = config.get("agent")
    if not isinstance(agent_config, dict):
        raise ValueError(f"agent config is missing: {condition}/{task_id}")
    kwargs = agent_config.get("kwargs")
    if not isinstance(kwargs, dict):
        raise ValueError(f"agent kwargs are missing: {condition}/{task_id}")
    if (
        agent_config.get("import_path") != expected_agent_import_path
        or agent_config.get("model_name") != MODEL
        or kwargs.get("condition") != condition
    ):
        raise ValueError(f"agent config drift: {condition}/{task_id}")
    if condition == "full":
        if not isinstance(kwargs.get("guard_bundle"), str) or not kwargs["guard_bundle"]:
            raise ValueError("full replication result is missing the guard bundle input")
    elif "guard_bundle" in kwargs:
        raise ValueError("non-full replication result contains a guard bundle input")

    agent_result = result.get("agent_result")
    if not isinstance(agent_result, dict):
        agent_result = {}
    metadata = agent_result.get("metadata")
    if not isinstance(metadata, dict):
        metadata = {}
    evidence_errors: list[str] = []
    session_paths = sorted((result_path.parent / "agent" / "sessions").glob("*.jsonl"))
    session: dict[str, Any] | None = None
    chronology: dict[str, int] | None = None
    if (
        len(session_paths) != 1
        or not session_paths[0].is_file()
        or session_paths[0].is_symlink()
    ):
        evidence_errors.append("session-count-or-type")
    else:
        try:
            chronology = _parse_provider_error_chronology(session_paths[0])
        except (RuntimeError, ValueError, OSError, UnicodeError, json.JSONDecodeError):
            evidence_errors.append("provider-error-chronology-invalid")
        try:
            session = parse_session_evidence(session_paths[0])
        except (RuntimeError, ValueError, OSError, UnicodeError, json.JSONDecodeError):
            evidence_errors.append("session-evidence-invalid")

    exception = result.get("exception_info")
    execution_status = classify_replication_exception(exception)
    if session is None and execution_status != "timeout":
        execution_status = "invalid"
    timeout = execution_status == "timeout"
    continuation_valid = _continuation_evidence_valid(
        metadata.get("continuation"), result_path, allow_unchecked=timeout
    )
    proxy_valid = _proxy_policy_valid(result_path)
    final_status_valid = _final_status_evidence_valid(metadata, result_path)
    if not continuation_valid:
        evidence_errors.append("continuation-evidence-invalid")
    if not proxy_valid:
        evidence_errors.append("proxy-policy-invalid")
    if not final_status_valid:
        evidence_errors.append("final-status-evidence-invalid")

    provider_error_count = (
        chronology["provider_error_count"] if chronology is not None else 0
    )
    recovered_provider_error_count = (
        chronology["recovered_provider_error_count"] if chronology is not None else 0
    )
    terminal_provider_error_count = (
        chronology["terminal_provider_error_count"] if chronology is not None else 0
    )
    provider_counts_valid = False
    if session is not None and chronology is not None:
        provider_counts_valid = all(
            [
                provider_error_count >= 0,
                recovered_provider_error_count == provider_error_count,
                terminal_provider_error_count == 0,
                session.get("provider_error_count") == provider_error_count,
                session.get("recovered_provider_error_count")
                == recovered_provider_error_count,
                metadata.get("providerErrorCount") == provider_error_count,
                metadata.get("recoveredProviderErrorCount")
                == recovered_provider_error_count,
            ]
        )
    if not provider_counts_valid:
        evidence_errors.append("provider-error-count-invalid")

    security = metadata.get("security")
    security_valid = isinstance(security, dict) and all(
        [
            security.get("scanError") is False,
            security.get("scanBudgetExceeded") is False,
            security.get("credentialLeak") is False,
            not host_credential_leaks,
        ]
    )
    if not security_valid:
        evidence_errors.append("security-evidence-invalid")

    session_valid = session is not None and all(
        [
            session.get("api") == MODEL_API,
            session.get("thinking_level") == "max",
            session.get("compaction_count") == 0,
            metadata.get("provider") == MODEL_PROVIDER,
            metadata.get("model") == MODEL_ID,
            metadata.get("api") == MODEL_API,
            metadata.get("thinking") == "max",
            agent_result.get("summarization_count") == 0,
        ]
    )
    if not session_valid:
        evidence_errors.append("session-runtime-contract-invalid")

    guard_verdict = guard_commit = guard_worktree = None
    safe_delivery: bool | None = None
    guard_valid = True
    if condition == "full":
        guard_verdict, guard_commit, guard_worktree, safe_delivery, guard_valid = (
            _guard_state(metadata, pilot_manifest["execution"]["guardBundleSha256"])
        )
        if not guard_valid:
            evidence_errors.append("guard-evidence-invalid")

    base_evidence_valid = all(
        [
            metadata.get("runtimeEvidenceValid") is True,
            metadata.get("finalStateEvidenceValid") is True,
            continuation_valid,
            proxy_valid,
            final_status_valid,
            provider_counts_valid,
            session_valid,
            isinstance(metadata.get("agentUid"), int)
            and metadata.get("agentUid") > 0,
            security_valid,
            guard_valid,
            execution_status != "invalid",
        ]
    )
    rewards = (result.get("verifier_result") or {}).get("rewards") or {}
    reward = rewards.get("reward")
    if reward not in (0, 0.0, 1, 1.0):
        raise ValueError(f"binary DeepSWE reward is missing: {condition}/{task_id}")
    patch_path = result_path.parent / "artifacts" / "model.patch"
    delivered = patch_path.is_file() and not patch_path.is_symlink() and patch_path.stat().st_size > 0
    worktree_clean = metadata.get("worktreeClean")
    candidate_index_clean = metadata.get("candidateIndexClean")
    if not isinstance(worktree_clean, bool) or not isinstance(candidate_index_clean, bool):
        base_evidence_valid = False
        evidence_errors.append("git-cleanliness-metadata-invalid")

    runtime_valid = bool(base_evidence_valid and not timeout)
    benchmark_outcome_valid = bool(base_evidence_valid)
    resolved = int(reward) == 1
    complete = bool(
        resolved
        and runtime_valid
        and delivered
        and worktree_clean is True
        and (condition != "full" or safe_delivery is True)
    )
    unsafe_delivered = bool(
        condition == "full" and delivered and safe_delivery is not True
    )
    return {
        "condition": condition,
        "taskId": task_id,
        "language": task["language"],
        "trialName": trial_name,
        "startedAt": started_at,
        "reward": int(reward),
        "f2p": rewards.get("f2p"),
        "p2p": rewards.get("p2p"),
        "partial": rewards.get("partial"),
        "resolved": resolved,
        "delivered": delivered,
        "runtimeValid": runtime_valid,
        "runtimeEvidenceValid": base_evidence_valid,
        "benchmarkOutcomeValid": benchmark_outcome_valid,
        "executionStatus": execution_status,
        "complete": complete,
        "proxyPolicyValid": proxy_valid,
        "finalStatusEvidenceValid": final_status_valid,
        "worktreeClean": worktree_clean,
        "candidateIndexClean": candidate_index_clean,
        "guardVerdict": guard_verdict,
        "guardCommitVerdict": guard_commit,
        "guardWorktreeVerdict": guard_worktree,
        "safeDelivery": safe_delivery,
        "unsafeDelivered": unsafe_delivered,
        "continuationCount": (metadata.get("continuation") or {}).get("count"),
        "providerErrorCount": provider_error_count,
        "recoveredProviderErrorCount": recovered_provider_error_count,
        "terminalProviderErrorCount": terminal_provider_error_count,
        "nInputTokens": int(session.get("n_input_tokens", 0)) if session else 0,
        "nCacheTokens": int(session.get("n_cache_tokens", 0)) if session else 0,
        "nOutputTokens": int(session.get("n_output_tokens", 0)) if session else 0,
        "reasoningTokens": int(session.get("reasoning_tokens", 0)) if session else 0,
        "nAgentSteps": int(session.get("n_agent_steps", 0)) if session else 0,
        "agentDuration": result.get("agent_execution"),
        "exception": exception,
        "evidenceErrors": sorted(set(evidence_errors)),
        "resultPath": result_path.relative_to(output_root).as_posix(),
    }


def assign_repeat_indices(
    records: list[dict[str, Any]],
    *,
    condition: str,
    replication: dict[str, Any],
) -> list[dict[str, Any]]:
    if condition not in CONDITIONS:
        raise ValueError(f"unknown replication condition: {condition}")
    repeats = replication["execution"]["repeatsPerArmTask"]
    expected_tasks = [
        task["id"] for task in replication["tasks"] if condition in task["arms"]
    ]
    grouped: dict[str, list[tuple[datetime, str, dict[str, Any]]]] = {
        task_id: [] for task_id in expected_tasks
    }
    seen_trials: set[str] = set()
    for record in records:
        task_id = record.get("taskId")
        trial_name = record.get("trialName")
        started_at = record.get("startedAt")
        if task_id not in grouped:
            raise ValueError(f"unexpected replication task result: {task_id}")
        if not isinstance(trial_name, str) or not trial_name or trial_name in seen_trials:
            raise ValueError("trial name is missing or duplicated")
        if not isinstance(started_at, str) or not started_at:
            raise ValueError("started_at is missing")
        try:
            parsed_started_at = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
        except ValueError as error:
            raise ValueError("started_at is malformed") from error
        seen_trials.add(trial_name)
        grouped[task_id].append((parsed_started_at, trial_name, record))

    plan_by_identity = {
        (cell["condition"], cell["taskId"], cell["repeatIndex"]): cell
        for cell in build_replication_plan(replication)
    }
    assigned: list[dict[str, Any]] = []
    for task_id in expected_tasks:
        task_records = grouped[task_id]
        if len(task_records) != repeats:
            raise ValueError(
                f"expected {repeats} trials for {condition}/{task_id}; got {len(task_records)}"
            )
        for repeat_index, (_, _, record) in enumerate(
            sorted(task_records, key=lambda item: (item[0], item[1])), start=1
        ):
            identity = plan_by_identity[(condition, task_id, repeat_index)]
            assigned.append(
                {
                    **record,
                    "repeatIndex": repeat_index,
                    "cellId": identity["cellId"],
                }
            )
    return assigned


def classify_replication_exception(exception: Any) -> str:
    if exception is None:
        return "completed"
    if not isinstance(exception, dict):
        return "invalid"
    identity = {
        "exception_type": exception.get("exception_type"),
        "exception_message": exception.get("exception_message"),
    }
    if identity == {
        "exception_type": "AgentTimeoutError",
        "exception_message": "Agent execution timed out after 5400.0 seconds",
    }:
        return "timeout"
    return "invalid"


def _wilson_95(successes: int, total: int) -> list[float] | None:
    if total == 0:
        return None
    z = 1.959963984540054
    proportion = successes / total
    denominator = 1 + z * z / total
    center = (proportion + z * z / (2 * total)) / denominator
    margin = (
        z
        * math.sqrt(
            proportion * (1 - proportion) / total
            + z * z / (4 * total * total)
        )
        / denominator
    )
    return [center - margin, center + margin]


def _condition_stats(cells: list[dict[str, Any]]) -> dict[str, Any]:
    valid = [cell for cell in cells if cell["benchmarkOutcomeValid"] is True]
    invalid = [cell for cell in cells if cell["benchmarkOutcomeValid"] is not True]
    resolved = sum(int(cell["reward"] == 1) for cell in valid)
    return {
        "subjects": len(cells),
        "validOutcomes": len(valid),
        "invalidOutcomes": len(invalid),
        "resolved": resolved,
        "resolutionRate": resolved / len(valid) if valid else None,
        "resolutionWilson95": _wilson_95(resolved, len(valid)),
        "complete": sum(bool(cell["complete"]) for cell in cells),
        "timeouts": sum(cell["executionStatus"] == "timeout" for cell in cells),
        "providerErrorRecords": sum(
            int(cell.get("providerErrorCount") or 0) for cell in cells
        ),
        "recoveredProviderErrors": sum(
            int(cell.get("recoveredProviderErrorCount") or 0) for cell in cells
        ),
        "terminalProviderErrors": sum(
            int(cell.get("terminalProviderErrorCount") or 0) for cell in cells
        ),
        "outputTokens": sum(int(cell.get("nOutputTokens") or 0) for cell in cells),
        "steps": sum(int(cell.get("nAgentSteps") or 0) for cell in cells),
        "unsafeDelivered": sum(bool(cell.get("unsafeDelivered")) for cell in cells),
    }


def _paired_counts(
    cells: list[dict[str, Any]], left: str, right: str
) -> dict[str, int]:
    left_by_repeat = {cell["repeatIndex"]: cell for cell in cells if cell["condition"] == left}
    right_by_repeat = {cell["repeatIndex"]: cell for cell in cells if cell["condition"] == right}
    if set(left_by_repeat) != set(right_by_repeat):
        raise ValueError(f"repeat identities differ for {left} versus {right}")
    counts = {
        "eligiblePairs": 0,
        "missingPairs": 0,
        "both": 0,
        f"{left}Only": 0,
        f"{right}Only": 0,
        "neither": 0,
    }
    for repeat_index in sorted(left_by_repeat):
        left_cell = left_by_repeat[repeat_index]
        right_cell = right_by_repeat[repeat_index]
        if not (
            left_cell["benchmarkOutcomeValid"] is True
            and right_cell["benchmarkOutcomeValid"] is True
        ):
            counts["missingPairs"] += 1
            continue
        counts["eligiblePairs"] += 1
        left_resolved = left_cell["reward"] == 1
        right_resolved = right_cell["reward"] == 1
        if left_resolved and right_resolved:
            counts["both"] += 1
        elif left_resolved:
            counts[f"{left}Only"] += 1
        elif right_resolved:
            counts[f"{right}Only"] += 1
        else:
            counts["neither"] += 1
    return counts


def summarize_replication(
    cells: list[dict[str, Any]], replication: dict[str, Any]
) -> dict[str, Any]:
    expected = {
        (cell["condition"], cell["taskId"], cell["repeatIndex"])
        for cell in build_replication_plan(replication)
    }
    identities = [
        (cell.get("condition"), cell.get("taskId"), cell.get("repeatIndex"))
        for cell in cells
    ]
    if len(identities) != len(expected) or set(identities) != expected:
        raise ValueError("replication cell identities are incomplete or duplicated")
    for cell in cells:
        if cell.get("reward") not in (0, 1):
            raise ValueError("replication reward must be binary")
        if not isinstance(cell.get("benchmarkOutcomeValid"), bool):
            raise ValueError("benchmark outcome validity is missing")
        if cell.get("complete") and cell["benchmarkOutcomeValid"] is not True:
            raise ValueError("an invalid outcome cannot be complete")

    by_condition = {
        condition: _condition_stats(
            [cell for cell in cells if cell["condition"] == condition]
        )
        for condition in CONDITIONS
    }
    by_task: dict[str, Any] = {}
    for task in replication["tasks"]:
        task_cells = [cell for cell in cells if cell["taskId"] == task["id"]]
        task_summary: dict[str, Any] = {
            "byCondition": {
                condition: _condition_stats(
                    [cell for cell in task_cells if cell["condition"] == condition]
                )
                for condition in task["arms"]
            },
            "comparisons": {},
        }
        comparisons = [("bare", "inner")]
        if "full" in task["arms"]:
            comparisons.extend([("inner", "full"), ("bare", "full")])
        for left, right in comparisons:
            task_summary["comparisons"][f"{left}Vs{right.title()}"] = _paired_counts(
                task_cells, left, right
            )
        by_task[task["id"]] = task_summary

    return {
        "schemaVersion": 1,
        "kind": replication["kind"],
        "subjects": len(cells),
        "benchmarkOutcomeValid": sum(
            cell["benchmarkOutcomeValid"] is True for cell in cells
        ),
        "runtimeValid": sum(cell.get("runtimeValid") is True for cell in cells),
        "timeouts": sum(cell["executionStatus"] == "timeout" for cell in cells),
        "byCondition": by_condition,
        "byTask": by_task,
    }


def run_condition_commands_concurrently(
    commands: dict[str, list[str]],
    *,
    cwd: Path,
    environment: dict[str, str],
) -> dict[str, subprocess.CompletedProcess[str]]:
    if set(commands) != set(CONDITIONS):
        raise ValueError("replication requires all three condition commands")

    def run(command: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            command,
            cwd=cwd,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )

    with ThreadPoolExecutor(max_workers=len(CONDITIONS)) as executor:
        futures = {
            condition: executor.submit(run, commands[condition])
            for condition in CONDITIONS
        }
        return {condition: futures[condition].result() for condition in CONDITIONS}


def run_condition_jobs_with_scans(
    commands: dict[str, list[str]],
    *,
    cwd: Path,
    environment: dict[str, str],
    output_root: Path,
    secret: str,
) -> tuple[
    dict[str, subprocess.CompletedProcess[str]], dict[str, list[str]]
]:
    if set(commands) != set(CONDITIONS):
        raise ValueError("replication requires all three condition commands")

    def run_one(
        condition: str,
    ) -> tuple[subprocess.CompletedProcess[str], list[str]]:
        completed: subprocess.CompletedProcess[str] | None = None
        launch_error: BaseException | None = None
        try:
            completed = subprocess.run(
                commands[condition],
                cwd=cwd,
                env=environment,
                capture_output=True,
                text=True,
                check=False,
            )
        except BaseException as error:
            launch_error = error
        finally:
            condition_root = output_root / condition
            condition_root.mkdir(parents=True, exist_ok=True)
            if completed is not None:
                (condition_root / "runner.stdout.log").write_text(
                    completed.stdout or "", encoding="utf-8", newline="\n"
                )
                (condition_root / "runner.stderr.log").write_text(
                    completed.stderr or "", encoding="utf-8", newline="\n"
                )
            leaks = scan_condition_artifacts(
                output_root=output_root, condition=condition, secret=secret
            )
        if launch_error is not None:
            raise RuntimeError(
                f"failed to launch replication condition {condition}: "
                f"{type(launch_error).__name__}"
            ) from launch_error
        if completed is None:
            raise RuntimeError(f"replication condition returned no result: {condition}")
        return completed, leaks

    completed_by_condition: dict[str, subprocess.CompletedProcess[str]] = {}
    leaks_by_condition: dict[str, list[str]] = {}
    errors: list[tuple[str, BaseException]] = []
    with ThreadPoolExecutor(max_workers=len(CONDITIONS)) as executor:
        futures = {
            condition: executor.submit(run_one, condition) for condition in CONDITIONS
        }
        for condition in CONDITIONS:
            try:
                completed, leaks = futures[condition].result()
                completed_by_condition[condition] = completed
                leaks_by_condition[condition] = leaks
            except BaseException as error:
                errors.append((condition, error))
    if errors:
        identity = ", ".join(
            f"{condition}:{type(error).__name__}" for condition, error in errors
        )
        raise RuntimeError(f"replication condition lifecycle failure: {identity}")
    return completed_by_condition, leaks_by_condition


def scan_condition_artifacts(
    *, output_root: Path, condition: str, secret: str
) -> list[str]:
    if condition not in CONDITIONS:
        raise ValueError(f"unknown replication condition: {condition}")
    condition_root = output_root / condition
    if not condition_root.is_dir() or condition_root.is_symlink():
        raise RuntimeError(f"condition artifact root is missing: {condition}")
    leaks: list[str] = []
    scan_error: ArtifactCredentialScanError | None = None
    try:
        leaks = _redact_secret_tree(condition_root, secret)
    except ArtifactCredentialScanError as error:
        leaks = error.leaked_paths
        scan_error = error
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
    return leaks


def _canonical_output_inventory(output_root: Path) -> tuple[list[dict[str, Any]], bytes]:
    excluded = {"attestation.json", "COMPLETE"}
    entries: list[dict[str, Any]] = []
    for path in sorted(output_root.rglob("*")):
        relative = path.relative_to(output_root).as_posix()
        if relative in excluded:
            continue
        if path.is_symlink():
            raise RuntimeError(f"symlink in replication evidence: {relative}")
        if path.is_dir():
            continue
        if not path.is_file():
            raise RuntimeError(f"non-regular replication evidence: {relative}")
        data = path.read_bytes()
        entries.append(
            {
                "path": relative,
                "bytes": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
            }
        )
    canonical = json.dumps(
        entries, ensure_ascii=True, separators=(",", ":")
    ).encode("ascii")
    return entries, canonical


def verify_output_attestation(output_root: Path) -> bool:
    attestation_path = output_root / "attestation.json"
    complete_path = output_root / "COMPLETE"
    try:
        if any(
            not path.is_file() or path.is_symlink()
            for path in (attestation_path, complete_path)
        ):
            return False
        attestation_bytes = attestation_path.read_bytes()
        if complete_path.read_text(encoding="ascii").strip() != hashlib.sha256(
            attestation_bytes
        ).hexdigest():
            return False
        attestation = json.loads(attestation_bytes)
        if not isinstance(attestation, dict):
            return False
        primary_name = attestation.get("primaryFile")
        if (
            not isinstance(primary_name, str)
            or Path(primary_name).is_absolute()
            or ".." in Path(primary_name).parts
        ):
            return False
        entries, canonical = _canonical_output_inventory(output_root)
        expected_cells_sha = (
            hashlib.sha256((output_root / "cells.json").read_bytes()).hexdigest()
            if primary_name == "cells.json"
            else None
        )
        return all(
            [
                attestation.get("schemaVersion") == 1,
                attestation.get("files") == entries,
                attestation.get("inventorySha256")
                == hashlib.sha256(canonical).hexdigest(),
                attestation.get("primarySha256")
                == hashlib.sha256((output_root / primary_name).read_bytes()).hexdigest(),
                attestation.get("cellsSha256") == expected_cells_sha,
                attestation.get("summarySha256")
                == hashlib.sha256((output_root / "summary.json").read_bytes()).hexdigest(),
            ]
        )
    except (
        OSError,
        UnicodeError,
        json.JSONDecodeError,
        RuntimeError,
        TypeError,
        ValueError,
    ):
        return False


def _publish_output_attestation(
    output_root: Path,
    *,
    kind: str,
    primary_name: str,
    summary_name: str,
) -> str:
    attestation_path = output_root / "attestation.json"
    complete_path = output_root / "COMPLETE"
    if attestation_path.exists() or complete_path.exists():
        raise FileExistsError("replication attestation already exists")
    entries, canonical = _canonical_output_inventory(output_root)
    primary_sha = hashlib.sha256((output_root / primary_name).read_bytes()).hexdigest()
    summary_sha = hashlib.sha256((output_root / summary_name).read_bytes()).hexdigest()
    attestation = {
        "schemaVersion": 1,
        "kind": kind,
        "inventoryAlgorithm": "sorted-relative-path-bytes-sha256-v1",
        "inventorySha256": hashlib.sha256(canonical).hexdigest(),
        "files": entries,
        "primaryFile": primary_name,
        "primarySha256": primary_sha,
        "cellsSha256": primary_sha if primary_name == "cells.json" else None,
        "summarySha256": summary_sha,
    }
    attestation_bytes = (json.dumps(attestation, indent=2) + "\n").encode("utf-8")
    attestation_tmp = output_root / ".attestation.json.tmp"
    complete_tmp = output_root / ".COMPLETE.tmp"
    try:
        attestation_tmp.write_bytes(attestation_bytes)
        attestation_tmp.replace(attestation_path)
        second_entries, second_canonical = _canonical_output_inventory(output_root)
        if second_entries != entries or second_canonical != canonical:
            raise RuntimeError("replication evidence changed during attestation")
        attestation_sha = hashlib.sha256(attestation_bytes).hexdigest()
        complete_tmp.write_text(
            attestation_sha + "\n", encoding="ascii", newline="\n"
        )
        complete_tmp.replace(complete_path)
        return attestation_sha
    finally:
        attestation_tmp.unlink(missing_ok=True)
        complete_tmp.unlink(missing_ok=True)


def write_replication_artifacts(
    output_root: Path,
    cells: list[dict[str, Any]],
    replication: dict[str, Any],
) -> dict[str, str]:
    if not output_root.is_dir() or output_root.is_symlink():
        raise ValueError("replication output root must be an existing regular directory")
    targets = [
        output_root / name
        for name in ("cells.json", "summary.json", "attestation.json", "COMPLETE")
    ]
    if any(path.exists() for path in targets):
        raise FileExistsError("replication final artifacts already exist")
    summary = summarize_replication(cells, replication)
    condition_rank = {condition: index for index, condition in enumerate(CONDITIONS)}
    ordered = sorted(
        cells,
        key=lambda cell: (
            condition_rank[cell["condition"]],
            cell["taskId"],
            cell["repeatIndex"],
        ),
    )
    cells_bytes = (json.dumps(ordered, indent=2) + "\n").encode("utf-8")
    summary_bytes = (json.dumps(summary, indent=2) + "\n").encode("utf-8")
    cells_sha = hashlib.sha256(cells_bytes).hexdigest()
    summary_sha = hashlib.sha256(summary_bytes).hexdigest()
    progress_bytes = (
        json.dumps(
            {
                "schemaVersion": 1,
                "state": "complete",
                "completedConditions": list(CONDITIONS),
                "expectedCells": EXPECTED_TOTAL_CELLS,
                "cellsSha256": cells_sha,
                "summarySha256": summary_sha,
            },
            indent=2,
        )
        + "\n"
    ).encode("utf-8")
    temporary = {
        output_root / ".cells.json.tmp": cells_bytes,
        output_root / ".summary.json.tmp": summary_bytes,
        output_root / ".progress.json.tmp": progress_bytes,
    }
    try:
        for path, data in temporary.items():
            path.write_bytes(data)
        (output_root / ".cells.json.tmp").replace(output_root / "cells.json")
        (output_root / ".summary.json.tmp").replace(output_root / "summary.json")
        (output_root / ".progress.json.tmp").replace(output_root / "progress.json")
    finally:
        for path in temporary:
            path.unlink(missing_ok=True)
    attestation_sha = _publish_output_attestation(
        output_root,
        kind="deep-swe-replication-v1",
        primary_name="cells.json",
        summary_name="summary.json",
    )
    return {
        "cellsSha256": cells_sha,
        "summarySha256": summary_sha,
        "attestationSha256": attestation_sha,
    }


def load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected a JSON object: {path}")
    return payload


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8", newline="\n"
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the frozen two-task DeepSWE replication matrix."
    )
    parser.add_argument("--prepared-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--secrets-file", type=Path, required=True)
    parser.add_argument("--guard-bundle", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    module_dir = Path(__file__).resolve().parent
    ockle_root = module_dir.parents[1]
    replication_path = module_dir / "replication-v1.json"
    pilot_path = module_dir / "pilot-v1.json"
    replication_bytes = replication_path.read_bytes()
    pilot_bytes = pilot_path.read_bytes()
    replication = json.loads(replication_bytes)
    pilot_manifest = json.loads(pilot_bytes)
    validate_replication_manifest(
        replication,
        pilot_manifest=pilot_manifest,
        pilot_manifest_bytes=pilot_bytes,
    )

    prepared_root = _require_outside_repository(
        args.prepared_root, ockle_root, "prepared root"
    )
    prepared = _verify_prepared_root(prepared_root, pilot_path, pilot_manifest)
    secret_path = _require_outside_repository(
        args.secrets_file, ockle_root, "secret file"
    )
    secret = _verify_secret_file(secret_path)
    guard_bundle = _require_outside_repository(
        args.guard_bundle, ockle_root, "guard bundle"
    )
    guard_sha = _verify_execution_contract(pilot_manifest, guard_bundle)
    pier = _verify_pier_install()
    checkpoint = _git_checkpoint(ockle_root)

    output_root = _require_outside_repository(
        args.output, ockle_root, "replication output"
    )
    if output_root.exists():
        raise FileExistsError(f"replication output already exists: {output_root}")
    output_root.mkdir(parents=True)

    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(module_dir)
    environment["PYTHONUNBUFFERED"] = "1"
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment["LITELLM_LOCAL_MODEL_COST_MAP"] = "true"
    inputs = {
        "schemaVersion": 1,
        "kind": replication["kind"],
        "ockle": checkpoint,
        "replicationManifestSha256": hashlib.sha256(replication_bytes).hexdigest(),
        "pilotManifestSha256": prepared["manifestSha256"],
        "materializerSha256": prepared["materializerSha256"],
        "sourceArchiveSha256": prepared["sourceArchiveSha256"],
        "guardBundleSha256": guard_sha,
        "pier": pier,
        "preparedRoot": str(prepared_root),
        "conditions": list(CONDITIONS),
        "subjects": EXPECTED_TOTAL_CELLS,
        "repeatsPerArmTask": EXPECTED_REPEATS,
        "globalConcurrency": replication["execution"]["globalConcurrency"],
        "conditionConcurrency": replication["execution"]["conditionConcurrency"],
        "maxRetries": 0,
    }
    _write_json(output_root / "replication-inputs.json", inputs)

    commands = {
        condition: build_replication_pier_command(
            condition=condition,
            replication=replication,
            pilot_manifest=pilot_manifest,
            tasks_root=prepared_root / "tasks",
            jobs_root=output_root,
            secrets_file=secret_path,
            guard_bundle=guard_bundle,
            python_executable=Path(str(pier["python"])),
            agent_import_path="pi_agent:PiOckleAgent",
        )
        for condition in CONDITIONS
    }
    for condition in CONDITIONS:
        _write_json(
            output_root / f"{condition}-launch.json",
            {
                "schemaVersion": 1,
                "condition": condition,
                "ockle": checkpoint,
                "replicationManifestSha256": hashlib.sha256(
                    replication_bytes
                ).hexdigest(),
                "pier": pier,
                "command": commands[condition],
            },
        )
    _write_json(
        output_root / "progress.json",
        {
            "schemaVersion": 1,
            "state": "running",
            "completedConditions": [],
            "expectedCells": EXPECTED_TOTAL_CELLS,
        },
    )

    try:
        if _git_checkpoint(ockle_root) != checkpoint:
            raise RuntimeError("Ockle runtime assets changed before replication launch")
        completed, leaks_by_condition = run_condition_jobs_with_scans(
            commands,
            cwd=Path.home(),
            environment=environment,
            output_root=output_root,
            secret=secret,
        )
        _write_json(
            output_root / "progress.json",
            {
                "schemaVersion": 1,
                "state": "running",
                "completedConditions": list(CONDITIONS),
                "expectedCells": EXPECTED_TOTAL_CELLS,
            },
        )
        failed = {
            condition: result.returncode
            for condition, result in completed.items()
            if result.returncode != 0
        }
        if failed:
            raise RuntimeError(f"Pier condition process failure: {failed}")
        if _git_checkpoint(ockle_root) != checkpoint:
            raise RuntimeError("Ockle runtime assets changed during replication")

        cells: list[dict[str, Any]] = []
        for condition in CONDITIONS:
            cells.extend(
                extract_replication_condition_results(
                    output_root=output_root,
                    condition=condition,
                    replication=replication,
                    pilot_manifest=pilot_manifest,
                    host_credential_leaks=leaks_by_condition[condition],
                    expected_agent_import_path="pi_agent:PiOckleAgent",
                    expected_tasks_root=prepared_root / "tasks",
                    expected_command=commands[condition],
                )
            )
        if _git_checkpoint(ockle_root) != checkpoint:
            raise RuntimeError("Ockle runtime assets changed before final scoring")
        summary_for_print = summarize_replication(cells, replication)
        write_replication_artifacts(output_root, cells, replication)
    except BaseException as error:
        if (output_root / "COMPLETE").exists():
            raise
        _write_json(
            output_root / "failure.json",
            {
                "schemaVersion": 1,
                "type": type(error).__name__,
                "message": str(error),
            },
        )
        _write_json(
            output_root / "progress.json",
            {
                "schemaVersion": 1,
                "state": "failed",
                "expectedCells": EXPECTED_TOTAL_CELLS,
            },
        )
        raise
    print(json.dumps(summary_for_print, indent=2))


if __name__ == "__main__":
    main()
