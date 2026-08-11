from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

MODULE_DIR = Path(__file__).resolve().parent
if str(MODULE_DIR) not in sys.path:
    sys.path.insert(0, str(MODULE_DIR))

from pi_agent import (  # noqa: E402
    MODEL_API,
    MODEL_ID,
    MODEL_PROVIDER,
    PIER_SQUID_BOOTSTRAP_SHA256,
    combine_final_status_bytes,
)
from pier.environments.agent_setup import squid_bootstrap_command  # noqa: E402

REPLICATION_MODULE = MODULE_DIR / "run_replication.py"
REPLICATION_MANIFEST = json.loads(
    (MODULE_DIR / "replication-v1.json").read_text(encoding="utf-8")
)
PILOT_MANIFEST = json.loads((MODULE_DIR / "pilot-v1.json").read_text(encoding="utf-8"))


def load_replication_module():
    spec = importlib.util.spec_from_file_location(
        "ockle_deepswe_replication_artifacts", REPLICATION_MODULE
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _session_rows(*, recovered_error: bool = False, final_error: bool = False):
    rows = [
        {"type": "session", "id": "replication-session", "cwd": "/app"},
        {"type": "model_change", "provider": MODEL_PROVIDER, "modelId": MODEL_ID},
        {"type": "thinking_level_change", "thinkingLevel": "max"},
        {"type": "message", "message": {"role": "user", "content": "task"}},
    ]
    if recovered_error:
        rows.append(
            {
                "type": "message",
                "message": {
                    "role": "assistant",
                    "provider": MODEL_PROVIDER,
                    "model": MODEL_ID,
                    "api": MODEL_API,
                    "stopReason": "error",
                    "errorMessage": "Anthropic stream ended without a stop reason",
                    "usage": {
                        "input": 0,
                        "cacheRead": 0,
                        "cacheWrite": 0,
                        "output": 0,
                        "reasoning": 0,
                        "cost": {"total": 0},
                    },
                },
            }
        )
    rows.append(
        {
            "type": "message",
            "message": {
                "role": "assistant",
                "provider": MODEL_PROVIDER,
                "model": MODEL_ID,
                "api": MODEL_API,
                "stopReason": "toolUse" if final_error else "stop",
                "content": [{"type": "text", "text": "done"}],
                "usage": {
                    "input": 11,
                    "cacheRead": 7,
                    "cacheWrite": 0,
                    "output": 5,
                    "reasoning": 3,
                    "cost": {"total": 0},
                },
            },
        }
    )
    if final_error:
        rows.append(
            {
                "type": "message",
                "message": {
                    "role": "assistant",
                    "provider": MODEL_PROVIDER,
                    "model": MODEL_ID,
                    "api": MODEL_API,
                    "stopReason": "error",
                    "errorMessage": "terminal provider failure",
                    "usage": {
                        "input": 0,
                        "cacheRead": 0,
                        "cacheWrite": 0,
                        "output": 0,
                        "reasoning": 0,
                        "cost": {"total": 0},
                    },
                },
            }
        )
    return rows


def _write_trial(
    root: Path,
    *,
    condition: str,
    task_id: str,
    reward: int,
    recovered_error: bool = False,
    final_error: bool = False,
    timeout: bool = False,
    guard_verdict: str = "clear",
    trial_number: int = 1,
) -> Path:
    task = next(entry for entry in PILOT_MANIFEST["tasks"] if entry["id"] == task_id)
    trial = root / condition / f"{task_id[:24]}__trial-{trial_number:02d}"
    agent = trial / "agent"
    sessions = agent / "sessions"
    sessions.mkdir(parents=True)
    (trial / "egress-proxy").mkdir()
    (trial / "artifacts").mkdir()

    session_rows = _session_rows(
        recovered_error=recovered_error,
        final_error=final_error,
    )
    (sessions / "session.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in session_rows),
        encoding="utf-8",
        newline="\n",
    )
    (trial / "egress-proxy" / "start-squid.sh").write_text(
        squid_bootstrap_command(), encoding="utf-8", newline="\n"
    )
    self_check = hashlib.sha256(squid_bootstrap_command().encode("utf-8")).hexdigest()
    assert self_check != PIER_SQUID_BOOTSTRAP_SHA256

    empty_sha = hashlib.sha256(b"").hexdigest()
    metadata = {
        "runtimeEvidenceValid": True,
        "finalStateEvidenceValid": True,
        "provider": MODEL_PROVIDER,
        "model": MODEL_ID,
        "api": MODEL_API,
        "thinking": "max",
        "agentUid": 1000,
        "providerErrorCount": int(recovered_error or final_error),
        "recoveredProviderErrorCount": int(recovered_error),
        "reasoningTokens": 3,
        "continuation": {
            "schemaVersion": 1,
            "maxContinuations": 1,
            "count": 0,
            "statusChecked": not timeout,
            "triggeredByDirtyWorktree": False,
            "statusBytes": 0 if not timeout else None,
            "statusSha256": empty_sha if not timeout else None,
        },
        "independentWorktreeClean": True,
        "independentWorktreeStatusBytes": 0,
        "independentWorktreeStatusSha256": empty_sha,
        "candidateIndexClean": True,
        "candidateIndexStatusBytes": 0,
        "candidateIndexStatusSha256": empty_sha,
        "worktreeClean": True,
        "worktreeStatusBytes": 0,
        "worktreeStatusSha256": hashlib.sha256(
            combine_final_status_bytes(b"", b"")
        ).hexdigest(),
        "security": {
            "scanError": False,
            "scanBudgetExceeded": False,
            "credentialLeak": False,
        },
    }
    if not timeout:
        (agent / "continuation-status.txt").write_bytes(b"")
    (agent / "git-final-status.txt").write_bytes(b"")
    (agent / "git-final-index-status.txt").write_bytes(b"")

    if condition == "full":
        exit_code = {"clear": 0, "blocked": 1, "indeterminate": 2}[guard_verdict]
        metadata["guardBundleSha256"] = PILOT_MANIFEST["execution"][
            "guardBundleSha256"
        ]
        metadata["guard"] = {
            name: {
                "exitCode": exit_code,
                "result": {
                    "schemaVersion": 1,
                    "operation": "check",
                    "verdict": guard_verdict,
                },
            }
            for name in ("commit", "worktree")
        }

    if reward == 1 or guard_verdict == "blocked":
        (trial / "artifacts" / "model.patch").write_text(
            "diff --git a/a b/a\n", encoding="utf-8", newline="\n"
        )
    exception = None
    if timeout:
        exception = {
            "exception_type": "AgentTimeoutError",
            "exception_message": "Agent execution timed out after 5400.0 seconds",
        }
    elif final_error:
        exception = {
            "exception_type": "NonZeroAgentExitCodeError",
            "exception_message": "trusted post-run boundary failed",
        }

    result = {
        "task_name": f"datacurve/{task_id}",
        "trial_name": trial.name,
        "task_checksum": task["preparedTaskChecksum"],
        "started_at": f"2026-08-10T01:{trial_number:02d}:00+00:00",
        "config": {
            "agent": {
                "import_path": "pi_agent:PiOckleAgent",
                "model_name": f"{MODEL_PROVIDER}/{MODEL_ID}",
                "kwargs": {
                    "condition": condition,
                    **(
                        {"guard_bundle": "/trusted/guard.tar.gz"}
                        if condition == "full"
                        else {}
                    ),
                },
            }
        },
        "agent_result": {
            "metadata": metadata,
            "summarization_count": 0,
            "n_input_tokens": 999,
            "n_cache_tokens": 999,
            "n_output_tokens": 999,
            "n_agent_steps": 999,
        },
        "verifier_result": {
            "rewards": {"reward": reward, "f2p": reward, "p2p": 1, "partial": reward}
        },
        "exception_info": exception,
        "agent_execution": {
            "started_at": "2026-08-10T01:00:00+00:00",
            "finished_at": "2026-08-10T01:10:00+00:00",
        },
    }
    result_path = trial / "result.json"
    result_path.write_text(
        json.dumps(result, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    return result_path


def _write_boundary_probe_trial(
    root: Path, *, condition: str, task_id: str, trial_number: int
) -> Path:
    result_path = _write_trial(
        root,
        condition=condition,
        task_id=task_id,
        reward=0,
        trial_number=trial_number,
    )
    result = json.loads(result_path.read_text(encoding="utf-8"))
    result["config"]["agent"]["import_path"] = "boundary_probe:BoundaryProbeAgent"
    result["agent_result"] = {
        "metadata": {
            "boundaryProbeValid": True,
            "result": {
                "uid": 1000,
                "user": "ockle",
                "appWrite": True,
                "optWriteBlocked": True,
                "oracleHidden": True,
                "providerReachable": True,
                "publicProxyBlocked": True,
                "publicDirectBlocked": True,
            },
        }
    }
    sessions = result_path.parent / "agent" / "sessions"
    for path in sessions.glob("*"):
        path.unlink()
    sessions.rmdir()
    result_path.write_text(
        json.dumps(result, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    return result_path


def _pier_content_hash(path: Path) -> str:
    digest = hashlib.sha256()
    for file_path in sorted(candidate for candidate in path.rglob("*") if candidate.is_file()):
        if ".git" in file_path.relative_to(path).parts:
            continue
        digest.update(file_path.relative_to(path).as_posix().encode())
        digest.update(b"\0")
        digest.update(file_path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _write_job_authority(
    module,
    root: Path,
    *,
    condition: str,
    task_ids: list[str],
    concurrency: int,
    agent_import_path: str = "pi_agent:PiOckleAgent",
) -> Path:
    condition_root = root / condition
    condition_root.mkdir(parents=True, exist_ok=True)
    prepared_tasks_root = root / "prepared-tasks"
    for task_id in task_ids:
        task_root = prepared_tasks_root / task_id
        task_root.mkdir(parents=True, exist_ok=True)
        (task_root / "task.toml").write_text(
            f'schema_version = "1.3"\n[task]\nname = "datacurve/{task_id}"\n',
            encoding="utf-8",
            newline="\n",
        )
    agent_kwargs = {
        "condition": condition,
        **(
            {"guard_bundle": "/trusted/guard.tar.gz"}
            if condition == "full"
            else {}
        ),
    }
    config_agent = {
        "name": None,
        "import_path": agent_import_path,
        "model_name": f"{MODEL_PROVIDER}/{MODEL_ID}",
        "kwargs": agent_kwargs,
        "env": {},
        "max_timeout_sec": None,
        "override_setup_timeout_sec": None,
        "override_timeout_sec": None,
    }
    retry = {
        "exclude_exceptions": [
            "VerifierTimeoutError",
            "AgentTimeoutError",
            "VerifierOutputParseError",
            "RewardFileEmptyError",
            "RewardFileNotFoundError",
        ],
        "include_exceptions": None,
        "max_retries": 0,
        "max_wait_sec": 60.0,
        "min_wait_sec": 1.0,
        "wait_multiplier": 1.0,
    }
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
    verifier = {
        "disable": False,
        "env": {},
        "max_timeout_sec": None,
        "override_timeout_sec": None,
    }
    dataset = {
        "download_dir": None,
        "exclude_task_names": None,
        "n_tasks": None,
        "name": None,
        "overwrite": False,
        "path": str(prepared_tasks_root),
        "ref": None,
        "registry_path": None,
        "registry_url": None,
        "sample_seed": None,
        "task_names": task_ids,
        "version": None,
    }
    config = {
        "agent_setup_timeout_multiplier": None,
        "agent_timeout_multiplier": None,
        "agents": [config_agent],
        "artifacts": [],
        "datasets": [dataset],
        "debug": False,
        "environment": environment,
        "environment_build_timeout_multiplier": None,
        "job_name": condition,
        "jobs_dir": str(root),
        "metrics": [],
        "n_attempts": 10,
        "n_concurrent_trials": concurrency,
        "quiet": True,
        "retry": retry,
        "tasks": [],
        "timeout_multiplier": 1.0,
        "verifier": verifier,
        "verifier_timeout_multiplier": None,
    }
    (condition_root / "config.json").write_text(
        json.dumps(config, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    lock_agent = {
        "env": {},
        "import_path": agent_import_path,
        "kwargs": agent_kwargs,
        "model_name": f"{MODEL_PROVIDER}/{MODEL_ID}",
    }
    lock_environment = {
        key: value
        for key, value in environment.items()
        if value is not None
    }
    lock_verifier = {"disable": False, "env": {}}
    trials = []
    for _ in range(10):
        for task_id in task_ids:
            task_root = prepared_tasks_root / task_id
            trials.append(
                {
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
            )
    lock = {
        "schema_version": 1,
        "created_at": "2026-01-01T00:00:00Z",
        "pier": {"version": "0.3.0"},
        "invocation": [],
        "n_concurrent_trials": concurrency,
        "retry": {key: value for key, value in retry.items() if value is not None},
        "trials": trials,
    }
    command = module.build_replication_pier_command(
        condition=condition,
        replication=REPLICATION_MANIFEST,
        pilot_manifest=PILOT_MANIFEST,
        tasks_root=prepared_tasks_root,
        jobs_root=root,
        secrets_file=root / "secrets.env",
        guard_bundle=(
            Path("/trusted/guard.tar.gz") if condition == "full" else None
        ),
        python_executable=Path("/pier/python"),
        agent_import_path=agent_import_path,
    )
    lock["invocation"] = ["-c", *command[4:]]
    (condition_root / "lock.json").write_text(
        json.dumps(lock, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    return prepared_tasks_root, command


class DeepSWEReplicationArtifactTests(unittest.TestCase):
    def test_completed_and_recovered_sessions_are_valid(self):
        module = load_replication_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            completed_path = _write_trial(
                root,
                condition="bare",
                task_id="sql-formatter-bigquery-pipe-formatting",
                reward=1,
            )
            recovered_path = _write_trial(
                root,
                condition="inner",
                task_id="tengo-callable-instance-isolation",
                reward=1,
                recovered_error=True,
            )
            completed = module.extract_replication_result(
                completed_path,
                output_root=root,
                condition="bare",
                replication=REPLICATION_MANIFEST,
                pilot_manifest=PILOT_MANIFEST,
                host_credential_leaks=[],
                expected_agent_import_path="pi_agent:PiOckleAgent",
            )
            recovered = module.extract_replication_result(
                recovered_path,
                output_root=root,
                condition="inner",
                replication=REPLICATION_MANIFEST,
                pilot_manifest=PILOT_MANIFEST,
                host_credential_leaks=[],
                expected_agent_import_path="pi_agent:PiOckleAgent",
            )

        self.assertTrue(
            completed["benchmarkOutcomeValid"], completed["evidenceErrors"]
        )
        self.assertTrue(completed["runtimeValid"], completed["evidenceErrors"])
        self.assertTrue(completed["complete"])
        self.assertEqual(completed["nOutputTokens"], 5)
        self.assertEqual(completed["nAgentSteps"], 1)
        self.assertTrue(
            recovered["benchmarkOutcomeValid"], recovered["evidenceErrors"]
        )
        self.assertTrue(recovered["runtimeValid"], recovered["evidenceErrors"])
        self.assertEqual(recovered["providerErrorCount"], 1)
        self.assertEqual(recovered["recoveredProviderErrorCount"], 1)
        self.assertEqual(recovered["terminalProviderErrorCount"], 0)

    def test_terminal_provider_error_is_missing_not_reward_zero(self):
        module = load_replication_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            result_path = _write_trial(
                root,
                condition="bare",
                task_id="sql-formatter-bigquery-pipe-formatting",
                reward=1,
                final_error=True,
            )
            cell = module.extract_replication_result(
                result_path,
                output_root=root,
                condition="bare",
                replication=REPLICATION_MANIFEST,
                pilot_manifest=PILOT_MANIFEST,
                host_credential_leaks=[],
                expected_agent_import_path="pi_agent:PiOckleAgent",
            )

        self.assertEqual(cell["reward"], 1)
        self.assertEqual(cell["executionStatus"], "invalid")
        self.assertEqual(cell["providerErrorCount"], 1)
        self.assertEqual(cell["recoveredProviderErrorCount"], 0)
        self.assertEqual(cell["terminalProviderErrorCount"], 1)
        self.assertFalse(cell["benchmarkOutcomeValid"])
        self.assertFalse(cell["runtimeValid"])
        self.assertFalse(cell["complete"])

    def test_exact_timeout_retains_reward_but_cannot_be_complete(self):
        module = load_replication_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            result_path = _write_trial(
                root,
                condition="full",
                task_id="sql-formatter-bigquery-pipe-formatting",
                reward=1,
                timeout=True,
            )
            cell = module.extract_replication_result(
                result_path,
                output_root=root,
                condition="full",
                replication=REPLICATION_MANIFEST,
                pilot_manifest=PILOT_MANIFEST,
                host_credential_leaks=[],
                expected_agent_import_path="pi_agent:PiOckleAgent",
            )

        self.assertEqual(cell["executionStatus"], "timeout")
        self.assertEqual(cell["reward"], 1)
        self.assertTrue(cell["resolved"])
        self.assertTrue(
            cell["runtimeEvidenceValid"], cell["evidenceErrors"]
        )
        self.assertTrue(
            cell["benchmarkOutcomeValid"], cell["evidenceErrors"]
        )
        self.assertFalse(cell["runtimeValid"])
        self.assertFalse(cell["complete"])

    def test_timeout_status_survives_missing_or_malformed_session_evidence(self):
        module = load_replication_module()
        for mutation in ("missing", "malformed"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                result_path = _write_trial(
                    root,
                    condition="bare",
                    task_id="sql-formatter-bigquery-pipe-formatting",
                    reward=1,
                    timeout=True,
                )
                session_path = next(
                    (result_path.parent / "agent" / "sessions").glob("*.jsonl")
                )
                if mutation == "missing":
                    session_path.unlink()
                else:
                    session_path.write_text("{\n", encoding="utf-8")
                cell = module.extract_replication_result(
                    result_path,
                    output_root=root,
                    condition="bare",
                    replication=REPLICATION_MANIFEST,
                    pilot_manifest=PILOT_MANIFEST,
                    host_credential_leaks=[],
                    expected_agent_import_path="pi_agent:PiOckleAgent",
                )
                self.assertEqual(cell["executionStatus"], "timeout")
                self.assertEqual(cell["reward"], 1)
                self.assertTrue(cell["resolved"])
                self.assertFalse(cell["benchmarkOutcomeValid"])
                self.assertFalse(cell["runtimeValid"])
                self.assertFalse(cell["complete"])
                self.assertNotIn(
                    "continuation-evidence-invalid", cell["evidenceErrors"]
                )

    def test_blocked_full_guard_keeps_behavior_but_fails_delivery_safety(self):
        module = load_replication_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            result_path = _write_trial(
                root,
                condition="full",
                task_id="sql-formatter-bigquery-pipe-formatting",
                reward=1,
                guard_verdict="blocked",
            )
            cell = module.extract_replication_result(
                result_path,
                output_root=root,
                condition="full",
                replication=REPLICATION_MANIFEST,
                pilot_manifest=PILOT_MANIFEST,
                host_credential_leaks=[],
                expected_agent_import_path="pi_agent:PiOckleAgent",
            )

        self.assertTrue(
            cell["benchmarkOutcomeValid"], cell["evidenceErrors"]
        )
        self.assertTrue(cell["resolved"])
        self.assertEqual(cell["guardVerdict"], "blocked")
        self.assertFalse(cell["safeDelivery"])
        self.assertTrue(cell["unsafeDelivered"])
        self.assertFalse(cell["complete"])

    def test_condition_extraction_requires_exact_job_authority_and_twenty_results(self):
        module = load_replication_module()
        task_ids = [
            "sql-formatter-bigquery-pipe-formatting",
            "tengo-callable-instance-isolation",
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            prepared_tasks_root, expected_command = _write_job_authority(
                module, root, condition="bare", task_ids=task_ids, concurrency=3
            )
            for task_id in task_ids:
                for repeat in range(1, 11):
                    _write_trial(
                        root,
                        condition="bare",
                        task_id=task_id,
                        reward=int(task_id.startswith("sql") and repeat == 1),
                        trial_number=repeat,
                    )
            cells = module.extract_replication_condition_results(
                output_root=root,
                condition="bare",
                replication=REPLICATION_MANIFEST,
                pilot_manifest=PILOT_MANIFEST,
                host_credential_leaks=[],
                expected_agent_import_path="pi_agent:PiOckleAgent",
                expected_tasks_root=prepared_tasks_root,
                expected_command=expected_command,
            )

            self.assertEqual(len(cells), 20)
            for task_id in task_ids:
                selected = [cell for cell in cells if cell["taskId"] == task_id]
                self.assertEqual(
                    [cell["repeatIndex"] for cell in selected], list(range(1, 11))
                )
                self.assertEqual(len({cell["cellId"] for cell in selected}), 10)

            next((root / "bare").glob("*__trial-10/result.json")).unlink()
            with self.assertRaisesRegex(RuntimeError, "produced 19 task results"):
                module.extract_replication_condition_results(
                    output_root=root,
                    condition="bare",
                    replication=REPLICATION_MANIFEST,
                    pilot_manifest=PILOT_MANIFEST,
                    host_credential_leaks=[],
                    expected_agent_import_path="pi_agent:PiOckleAgent",
                    expected_tasks_root=prepared_tasks_root,
                    expected_command=expected_command,
                )

    def test_job_authority_rejects_every_replay_affecting_drift(self):
        module = load_replication_module()
        task_ids = [
            "sql-formatter-bigquery-pipe-formatting",
            "tengo-callable-instance-isolation",
        ]
        mutations = {
            "global timeout": ("config", ("timeout_multiplier",), 9.0),
            "agent timeout": (
                "config",
                ("agent_timeout_multiplier",),
                0.1,
            ),
            "verifier override": (
                "config",
                ("verifier", "disable"),
                True,
            ),
            "host environment": (
                "config",
                ("environment", "type"),
                "host",
            ),
            "trial timeout": (
                "lock",
                ("trials", 0, "timeout_multiplier"),
                0.1,
            ),
            "trial verifier": (
                "lock",
                ("trials", 0, "verifier", "disable"),
                True,
            ),
            "trial environment": (
                "lock",
                ("trials", 0, "environment", "type"),
                "host",
            ),
            "task digest": (
                "lock",
                ("trials", 0, "task", "digest"),
                "sha256:" + "f" * 64,
            ),
        }
        for label, (filename, keys, replacement) in mutations.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                prepared_tasks_root, expected_command = _write_job_authority(
                    module,
                    root,
                    condition="bare",
                    task_ids=task_ids,
                    concurrency=3,
                )
                path = root / "bare" / f"{filename}.json"
                payload = json.loads(path.read_text(encoding="utf-8"))
                target = payload
                for key in keys[:-1]:
                    target = target[key]
                target[keys[-1]] = replacement
                path.write_text(
                    json.dumps(payload, indent=2) + "\n",
                    encoding="utf-8",
                    newline="\n",
                )
                with self.assertRaisesRegex(RuntimeError, "drift"):
                    module._validate_condition_job_authority(
                        condition_root=root / "bare",
                        condition="bare",
                        replication=REPLICATION_MANIFEST,
                        expected_agent_import_path="pi_agent:PiOckleAgent",
                        expected_tasks_root=prepared_tasks_root,
                        expected_command=expected_command,
                    )

    def test_boundary_probe_condition_requires_all_twenty_valid_results(self):
        module = load_replication_module()
        task_ids = [
            "sql-formatter-bigquery-pipe-formatting",
            "tengo-callable-instance-isolation",
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            prepared_tasks_root, expected_command = _write_job_authority(
                module,
                root,
                condition="bare",
                task_ids=task_ids,
                concurrency=3,
                agent_import_path="boundary_probe:BoundaryProbeAgent",
            )
            paths = []
            for task_id in task_ids:
                for repeat in range(1, 11):
                    paths.append(
                        _write_boundary_probe_trial(
                            root,
                            condition="bare",
                            task_id=task_id,
                            trial_number=repeat,
                        )
                    )
            probes = module.extract_replication_boundary_probe_results(
                output_root=root,
                condition="bare",
                replication=REPLICATION_MANIFEST,
                pilot_manifest=PILOT_MANIFEST,
                host_credential_leaks=[],
                expected_tasks_root=prepared_tasks_root,
                expected_command=expected_command,
            )
            self.assertEqual(len(probes), 20)
            self.assertTrue(all(probe["boundaryProbeValid"] for probe in probes))
            self.assertEqual(
                sorted(
                    probe["repeatIndex"]
                    for probe in probes
                    if probe["taskId"] == task_ids[0]
                ),
                list(range(1, 11)),
            )

            broken = json.loads(paths[0].read_text(encoding="utf-8"))
            broken["agent_result"]["metadata"]["result"][
                "providerReachable"
            ] = False
            paths[0].write_text(
                json.dumps(broken, indent=2) + "\n",
                encoding="utf-8",
                newline="\n",
            )
            with self.assertRaisesRegex(RuntimeError, "boundary probe failed"):
                module.extract_replication_boundary_probe_results(
                    output_root=root,
                    condition="bare",
                    replication=REPLICATION_MANIFEST,
                    pilot_manifest=PILOT_MANIFEST,
                    host_credential_leaks=[],
                    expected_tasks_root=prepared_tasks_root,
                    expected_command=expected_command,
                )


if __name__ == "__main__":
    unittest.main()
