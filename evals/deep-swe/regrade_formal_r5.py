#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import stat
import subprocess
from pathlib import Path
from typing import Any

from pi_agent import MODEL_API, MODEL_ID, MODEL_PROVIDER, parse_session_evidence
from prepare_pilot import validate_pilot_manifest
from run_pilot import (
    _continuation_evidence_valid,
    _final_status_evidence_valid,
    _proxy_policy_valid,
    _verify_pier_install,
    classify_regrade_exception,
)

SOURCE_CELLS_SHA256 = "3708e0bdd2517b3b65fed8f14d1aa0b541066ac0734877eae2dead251cfbfaec"
SOURCE_CHECKPOINT = "b5d7db4be95c51f44ba5cbc70c7f73cd847ebffd"
SOURCE_MANIFEST_SHA256 = "5037c2b75c8cd313483eed4ef74164c2d4b1bf9b42dcce23b2cd772d382c38a1"
SOURCE_INVENTORY_SHA256 = "a9d233470b7a76d034017caa99e369d6c8826023f607eb6c1cbebf0a428040c2"
DEFAULT_SOURCE_ROOT = Path(
    "/home/administrator/ockle-deepswe/formal-pilot-v1-b5d7db4-r5"
)
DEFAULT_OUTPUT_ROOT = Path(
    "/home/administrator/ockle-deepswe/formal-pilot-v1-b5d7db4-r5-regrade-v1"
)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def build_source_inventory(root: Path) -> bytes:
    records: list[dict[str, Any]] = []
    for path in sorted(
        root.rglob("*"), key=lambda candidate: candidate.relative_to(root).as_posix()
    ):
        relative = path.relative_to(root).as_posix()
        details = path.lstat()
        if stat.S_ISDIR(details.st_mode):
            continue
        if not stat.S_ISREG(details.st_mode) or path.is_symlink():
            raise RuntimeError(f"source artifact is non-regular: {relative}")
        data = path.read_bytes()
        records.append({"path": relative, "size": len(data), "sha256": sha256(data)})
    return b"".join(
        (json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n").encode(
            "utf-8"
        )
        for record in records
    )


def pier_record_set() -> tuple[dict[str, Any], str]:
    provenance = _verify_pier_install()
    distribution = importlib.metadata.distribution("datacurve-pier")
    records: list[dict[str, str]] = []
    for package_path in distribution.files or []:
        expected = package_path.hash
        if expected is None:
            continue
        records.append(
            {
                "path": str(package_path),
                "mode": expected.mode,
                "value": expected.value,
            }
        )
    records.sort(key=lambda record: record["path"])
    record_bytes = b"".join(
        (json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n").encode(
            "utf-8"
        )
        for record in records
    )
    if len(records) != provenance["verifiedFiles"]:
        raise RuntimeError("Pier RECORD count changed after verification")
    return provenance, sha256(record_bytes)


def require_source_integrity(
    source_root: Path,
) -> tuple[list[dict[str, Any]], dict[str, Any], bytes]:
    cells_bytes = (source_root / "cells.json").read_bytes()
    partial_bytes = (source_root / "partial-cells.json").read_bytes()
    digest = sha256(cells_bytes)
    if digest != SOURCE_CELLS_SHA256:
        raise RuntimeError(f"source cells digest drift: {digest}")
    if partial_bytes != cells_bytes:
        raise RuntimeError("source partial-cells differs from cells")
    if (source_root / "COMPLETE").read_text(encoding="utf-8").strip() != digest:
        raise RuntimeError("source COMPLETE does not bind cells")
    formal_inputs = read_json(source_root / "formal-inputs.json")
    if formal_inputs.get("subjects") != 29:
        raise RuntimeError("source subject count is not 29")
    if formal_inputs.get("manifestSha256") != SOURCE_MANIFEST_SHA256:
        raise RuntimeError("source manifest digest drift")
    if (formal_inputs.get("ockle") or {}).get("commit") != SOURCE_CHECKPOINT:
        raise RuntimeError("source checkpoint drift")
    for condition in ("bare", "inner", "full"):
        security = read_json(source_root / f"{condition}-security.json")
        if security != {
            "condition": condition,
            "credentialLeakPaths": [],
            "scanError": None,
            "purgedPaths": [],
        }:
            raise RuntimeError(f"source host security is invalid: {condition}")
    inventory_bytes = build_source_inventory(source_root)
    inventory_digest = sha256(inventory_bytes)
    if inventory_digest != SOURCE_INVENTORY_SHA256:
        raise RuntimeError(f"source inventory digest drift: {inventory_digest}")
    return json.loads(cells_bytes), formal_inputs, inventory_bytes


def guard_state(
    metadata: dict[str, Any], guard_sha: str
) -> tuple[str | None, str | None, str | None, bool | None, bool]:
    if metadata.get("guardBundleSha256") != guard_sha:
        return None, None, None, None, False
    guard = metadata.get("guard")
    if not isinstance(guard, dict):
        return None, None, None, None, False
    expected_exits = {"clear": 0, "blocked": 1, "indeterminate": 2}
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
            or verdict not in expected_exits
            or evidence.get("exitCode") != expected_exits[verdict]
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


def regrade_cell(
    source_root: Path,
    source_cell: dict[str, Any],
    expected_task: dict[str, Any],
    guard_sha: str,
) -> dict[str, Any]:
    result_path = source_root / source_cell["resultPath"]
    result = read_json(result_path)
    condition = source_cell["condition"]
    task_id = source_cell["taskId"]
    if result.get("task_name") != f"datacurve/{task_id}":
        raise RuntimeError(f"task identity drift: {condition}/{task_id}")
    if result.get("task_checksum") != expected_task["preparedTaskChecksum"]:
        raise RuntimeError(f"task checksum drift: {condition}/{task_id}")
    config = result.get("config") or {}
    agent_config = config.get("agent") or {}
    if (
        agent_config.get("import_path") != "pi_agent:PiOckleAgent"
        or agent_config.get("model_name") != f"{MODEL_PROVIDER}/{MODEL_ID}"
        or (agent_config.get("kwargs") or {}).get("condition") != condition
    ):
        raise RuntimeError(f"agent config drift: {condition}/{task_id}")

    agent_result = result.get("agent_result") or {}
    metadata = agent_result.get("metadata") or {}
    session_paths = sorted((result_path.parent / "agent" / "sessions").glob("*.jsonl"))
    if len(session_paths) != 1:
        raise RuntimeError(f"session count drift: {condition}/{task_id}")
    session = parse_session_evidence(session_paths[0])
    provider_error_count = int(session["provider_error_count"])
    execution_status = classify_regrade_exception(
        result.get("exception_info"), provider_error_count=provider_error_count
    )

    continuation_valid = _continuation_evidence_valid(
        metadata.get("continuation"),
        result_path,
        allow_unchecked=execution_status == "timeout",
    )
    proxy_valid = _proxy_policy_valid(result_path)
    final_status_valid = _final_status_evidence_valid(metadata, result_path)
    security = metadata.get("security") or {}
    base_runtime_valid = all(
        [
            continuation_valid,
            proxy_valid,
            final_status_valid,
            session.get("api") == MODEL_API,
            session.get("thinking_level") == "max",
            session.get("compaction_count") == 0,
            isinstance(metadata.get("agentUid"), int),
            metadata.get("agentUid") > 0,
            security.get("scanError") is False,
            security.get("scanBudgetExceeded") is False,
            security.get("credentialLeak") is False,
            execution_status != "invalid",
        ]
    )

    rewards = (result.get("verifier_result") or {}).get("rewards") or {}
    reward = rewards.get("reward")
    if reward not in (0, 0.0, 1, 1.0):
        raise RuntimeError(f"missing binary reward: {condition}/{task_id}")
    if int(reward) != source_cell["reward"]:
        raise RuntimeError(f"reward drift: {condition}/{task_id}")
    patch_path = result_path.parent / "artifacts" / "model.patch"
    delivered = patch_path.is_file() and patch_path.stat().st_size > 0
    worktree_clean = metadata.get("worktreeClean")
    candidate_index_clean = metadata.get("candidateIndexClean")

    guard_verdict = guard_commit = guard_worktree = None
    safe_delivery = None
    guard_valid = True
    if condition == "full":
        guard_verdict, guard_commit, guard_worktree, safe_delivery, guard_valid = (
            guard_state(metadata, guard_sha)
        )
        base_runtime_valid = base_runtime_valid and guard_valid

    runtime_valid = bool(base_runtime_valid and execution_status != "timeout")
    benchmark_outcome_valid = bool(base_runtime_valid)
    resolved = int(reward) == 1
    execution_completed = execution_status in {"completed", "recovered-provider-error"}
    complete = bool(
        resolved
        and base_runtime_valid
        and execution_completed
        and worktree_clean is True
        and (condition != "full" or safe_delivery is True)
    )
    unsafe_delivered = bool(condition == "full" and delivered and safe_delivery is not True)
    return {
        "condition": condition,
        "taskId": task_id,
        "language": source_cell["language"],
        "reward": int(reward),
        "f2p": rewards.get("f2p"),
        "p2p": rewards.get("p2p"),
        "partial": rewards.get("partial"),
        "resolved": resolved,
        "delivered": delivered,
        "runtimeValid": runtime_valid,
        "runtimeEvidenceValid": bool(base_runtime_valid),
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
        "recoveredProviderErrorCount": int(session["recovered_provider_error_count"]),
        "nInputTokens": int(session["n_input_tokens"]),
        "nCacheTokens": int(session["n_cache_tokens"]),
        "nOutputTokens": int(session["n_output_tokens"]),
        "reasoningTokens": int(session["reasoning_tokens"]),
        "nAgentSteps": int(session["n_agent_steps"]),
        "agentDuration": result.get("agent_execution"),
        "originalException": result.get("exception_info"),
        "sourceResultPath": source_cell["resultPath"],
    }


def summarize(cells: list[dict[str, Any]]) -> dict[str, Any]:
    by_condition: dict[str, Any] = {}
    for condition in ("bare", "inner", "full"):
        selected = [cell for cell in cells if cell["condition"] == condition]
        by_condition[condition] = {
            "subjects": len(selected),
            "resolved": sum(cell["resolved"] for cell in selected),
            "complete": sum(cell["complete"] for cell in selected),
            "runtimeValid": sum(cell["runtimeValid"] for cell in selected),
            "runtimeEvidenceValid": sum(
                cell["runtimeEvidenceValid"] for cell in selected
            ),
            "benchmarkOutcomeValid": sum(
                cell["benchmarkOutcomeValid"] for cell in selected
            ),
            "timeouts": sum(cell["executionStatus"] == "timeout" for cell in selected),
            "recoveredProviderCells": sum(
                cell["executionStatus"] == "recovered-provider-error"
                for cell in selected
            ),
            "providerErrorRecords": sum(
                cell["providerErrorCount"] for cell in selected
            ),
            "sessionsWithProviderErrors": sum(
                cell["providerErrorCount"] > 0 for cell in selected
            ),
            "unsafeDelivered": sum(cell["unsafeDelivered"] for cell in selected),
            "inputTokens": sum(cell["nInputTokens"] for cell in selected),
            "cacheTokens": sum(cell["nCacheTokens"] for cell in selected),
            "outputTokens": sum(cell["nOutputTokens"] for cell in selected),
            "steps": sum(cell["nAgentSteps"] for cell in selected),
            "continuations": sum(
                int(cell["continuationCount"] or 0) for cell in selected
            ),
        }
    return {"schemaVersion": 1, "subjects": len(cells), "byCondition": by_condition}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Regrade frozen DeepSWE r5 artifacts after the recovered-error gate correction."
    )
    parser.add_argument("--source-root", type=Path, default=DEFAULT_SOURCE_ROOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_ROOT)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    source_root = args.source_root.resolve()
    output_root = args.output.resolve()
    ockle_root = Path(__file__).resolve().parents[2]
    if source_root == ockle_root or ockle_root in source_root.parents:
        raise ValueError("source artifacts must be outside the Ockle repository")
    if output_root == ockle_root or ockle_root in output_root.parents:
        raise ValueError("regrade output must be outside the Ockle repository")
    if output_root.exists():
        raise FileExistsError(f"regrade output already exists: {output_root}")

    source_cells, formal_inputs, inventory_bytes = require_source_integrity(source_root)
    manifest_path = Path(__file__).with_name("pilot-v1.json")
    manifest_bytes = manifest_path.read_bytes()
    manifest = json.loads(manifest_bytes)
    validate_pilot_manifest(manifest)
    expected = {
        (condition, task["id"]): task
        for task in manifest["tasks"]
        for condition in task["arms"]
    }
    identities = {(cell["condition"], cell["taskId"]) for cell in source_cells}
    if len(source_cells) != 29 or identities != set(expected):
        raise RuntimeError("source cell identities do not match canonical 29-cell design")
    guard_sha = manifest["execution"]["guardBundleSha256"]
    corrected = [
        regrade_cell(
            source_root,
            cell,
            expected[(cell["condition"], cell["taskId"])],
            guard_sha,
        )
        for cell in source_cells
    ]
    corrected.sort(
        key=lambda cell: (
            ("bare", "inner", "full").index(cell["condition"]),
            cell["taskId"],
        )
    )

    git_status = subprocess.run(
        ["git", "status", "--porcelain=v1"],
        cwd=ockle_root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    if git_status:
        raise RuntimeError("regrade scorer checkpoint is dirty")
    scorer_checkpoint = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ockle_root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    pier_provenance, pier_record_sha = pier_record_set()
    scorer_paths = [
        Path(__file__).with_name("pi_agent.py"),
        Path(__file__).with_name("prepare_pilot.py"),
        Path(__file__).with_name("run_pilot.py"),
        Path(__file__).resolve(),
    ]
    scorer_files = {str(path): sha256(path.read_bytes()) for path in scorer_paths}
    scorer_files["pier-record-set"] = pier_record_sha
    scorer_digest = hashlib.sha256()
    for path, digest in sorted(scorer_files.items()):
        scorer_digest.update(path.encode("utf-8") + b"\0" + digest.encode("ascii") + b"\0")
    final_inventory_bytes = build_source_inventory(source_root)
    if final_inventory_bytes != inventory_bytes:
        raise RuntimeError("source artifacts changed while regrade scoring was in progress")

    payload = {
        "schemaVersion": 1,
        "kind": "post-hoc-evidence-gate-correction",
        "source": {
            "root": str(source_root),
            "cellsSha256": SOURCE_CELLS_SHA256,
            "checkpoint": SOURCE_CHECKPOINT,
            "manifestSha256": SOURCE_MANIFEST_SHA256,
            "inventorySha256": SOURCE_INVENTORY_SHA256,
            "inventoryFiles": len(inventory_bytes.splitlines()),
            "formalInputs": formal_inputs,
        },
        "correction": {
            "providerErrorPolicy": "final-error-invalid-recovered-errors-counted",
            "validFinalAssistantStopReasons": ["stop", "toolUse"],
            "timeoutContinuationPolicy": "exact-timeout-allows-unchecked-default",
            "rewardChanged": False,
            "deliveryChanged": False,
            "guardChanged": False,
            "originalArtifactsOverwritten": False,
            "currentManifestSha256": sha256(manifest_bytes),
            "scorerCheckpoint": scorer_checkpoint,
            "scorerFiles": scorer_files,
            "scorerFilesSha256": scorer_digest.hexdigest(),
            "pier": {**pier_provenance, "recordSetSha256": pier_record_sha},
        },
        "summary": summarize(corrected),
        "cells": corrected,
    }
    output_root.mkdir(parents=False)
    output_bytes = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode()
    (output_root / "regrade.json").write_bytes(output_bytes)
    digest = sha256(output_bytes)
    (output_root / "COMPLETE").write_text(digest + "\n", encoding="utf-8")
    print(
        json.dumps(
            {"output": str(output_root), "sha256": digest, "summary": payload["summary"]},
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
