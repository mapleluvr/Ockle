from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from collections import Counter
from pathlib import Path

MODULE_DIR = Path(__file__).resolve().parent
if str(MODULE_DIR) not in sys.path:
    sys.path.insert(0, str(MODULE_DIR))
REPLICATION_MODULE = MODULE_DIR / "run_replication.py"
REPLICATION_MANIFEST = MODULE_DIR / "replication-v1.json"
PILOT_MANIFEST = MODULE_DIR / "pilot-v1.json"


def load_replication_module():
    if not REPLICATION_MODULE.is_file():
        raise AssertionError("run_replication.py must implement the frozen repeat matrix")
    spec = importlib.util.spec_from_file_location(
        "ockle_deepswe_replication", REPLICATION_MODULE
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class DeepSWEReplicationTests(unittest.TestCase):
    def test_manifest_freezes_two_tasks_ten_attempts_and_fifty_cells(self):
        module = load_replication_module()
        self.assertTrue(REPLICATION_MANIFEST.is_file())
        replication_bytes = REPLICATION_MANIFEST.read_bytes()
        replication = json.loads(replication_bytes)
        pilot_bytes = PILOT_MANIFEST.read_bytes()
        pilot = json.loads(pilot_bytes)

        validated = module.validate_replication_manifest(
            replication,
            pilot_manifest=pilot,
            pilot_manifest_bytes=pilot_bytes,
        )

        self.assertEqual(validated, {"tasks": 2, "cells": 50, "repeats": 10})
        self.assertEqual(replication["kind"], "post-hoc-discordant-replication")
        self.assertTrue(replication["selection"]["usesR5Outcomes"])
        self.assertEqual(
            replication["source"]["pilotManifestSha256"],
            hashlib.sha256(pilot_bytes).hexdigest(),
        )
        self.assertEqual(
            replication["source"]["r5CellsSha256"],
            "3708e0bdd2517b3b65fed8f14d1aa0b541066ac0734877eae2dead251cfbfaec",
        )
        self.assertEqual(
            replication["source"]["r5RegradeSha256"],
            "b6abddc53aeed4b3133fdc1b85d49480cbeba1a186f0bce3afa6ca512d0af522",
        )
        self.assertEqual(replication["execution"]["repeatsPerArmTask"], 10)
        self.assertEqual(replication["execution"]["globalConcurrency"], 8)
        self.assertEqual(
            replication["execution"]["conditionConcurrency"],
            {"bare": 3, "inner": 3, "full": 2},
        )
        self.assertEqual(replication["execution"]["maxRetries"], 0)
        self.assertEqual(
            [task["id"] for task in replication["tasks"]],
            [
                "sql-formatter-bigquery-pipe-formatting",
                "tengo-callable-instance-isolation",
            ],
        )
        self.assertEqual(replication["tasks"][0]["arms"], ["bare", "inner", "full"])
        self.assertEqual(replication["tasks"][1]["arms"], ["bare", "inner"])
        self.assertEqual(
            replication["tasks"][0]["r5ObservedReward"],
            {"bare": 1, "inner": 0, "full": 1},
        )
        self.assertEqual(
            replication["tasks"][1]["r5ObservedReward"],
            {"bare": 0, "inner": 1},
        )

    def test_cell_plan_has_exact_unique_repeat_identities(self):
        module = load_replication_module()
        replication = json.loads(REPLICATION_MANIFEST.read_text(encoding="utf-8"))

        plan = module.build_replication_plan(replication)

        self.assertEqual(len(plan), 50)
        self.assertEqual(len({cell["cellId"] for cell in plan}), 50)
        self.assertTrue(
            all(
                isinstance(cell["cellId"], str)
                and len(cell["cellId"]) == 16
                and all(character in "0123456789abcdef" for character in cell["cellId"])
                for cell in plan
            )
        )
        self.assertEqual(
            Counter(cell["condition"] for cell in plan),
            Counter({"bare": 20, "inner": 20, "full": 10}),
        )
        identities = {
            (cell["condition"], cell["taskId"], cell["repeatIndex"])
            for cell in plan
        }
        self.assertEqual(len(identities), 50)
        for task in replication["tasks"]:
            for condition in task["arms"]:
                self.assertEqual(
                    sorted(
                        cell["repeatIndex"]
                        for cell in plan
                        if cell["condition"] == condition
                        and cell["taskId"] == task["id"]
                    ),
                    list(range(1, 11)),
                )

    def test_commands_use_native_attempts_fixed_partition_and_no_retries(self):
        module = load_replication_module()
        replication = json.loads(REPLICATION_MANIFEST.read_text(encoding="utf-8"))
        pilot = json.loads(PILOT_MANIFEST.read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            common = {
                "replication": replication,
                "pilot_manifest": pilot,
                "tasks_root": root / "tasks",
                "jobs_root": root / "jobs",
                "secrets_file": root / "secrets.env",
                "guard_bundle": root / "guard.tar.gz",
                "python_executable": Path("/verified/python"),
                "agent_import_path": "pi_agent:PiOckleAgent",
            }
            commands = {
                condition: module.build_replication_pier_command(
                    condition=condition, **common
                )
                for condition in ("bare", "inner", "full")
            }

        expected_tasks = {
            "bare": {
                "sql-formatter-bigquery-pipe-formatting",
                "tengo-callable-instance-isolation",
            },
            "inner": {
                "sql-formatter-bigquery-pipe-formatting",
                "tengo-callable-instance-isolation",
            },
            "full": {"sql-formatter-bigquery-pipe-formatting"},
        }
        for condition, command in commands.items():
            self.assertEqual(command[command.index("--n-attempts") + 1], "10")
            self.assertEqual(command[command.index("--max-retries") + 1], "0")
            self.assertEqual(
                command[command.index("--n-concurrent") + 1],
                str(replication["execution"]["conditionConcurrency"][condition]),
            )
            selected = {
                command[index + 1]
                for index, value in enumerate(command)
                if value == "--include-task-name"
            }
            self.assertEqual(selected, expected_tasks[condition])
            self.assertEqual(command.count("--agent-import-path"), 1)
            self.assertEqual(
                command[command.index("--agent-import-path") + 1],
                "pi_agent:PiOckleAgent",
            )
            guard_args = [value for value in command if value.startswith("guard_bundle=")]
            self.assertEqual(len(guard_args), int(condition == "full"))

    def test_repeat_indices_follow_started_time_then_trial_name(self):
        module = load_replication_module()
        replication = json.loads(REPLICATION_MANIFEST.read_text(encoding="utf-8"))
        records = []
        for task_id in (
            "sql-formatter-bigquery-pipe-formatting",
            "tengo-callable-instance-isolation",
        ):
            for number in reversed(range(1, 11)):
                records.append(
                    {
                        "taskId": task_id,
                        "trialName": f"{task_id[:8]}-{number:02d}",
                        "startedAt": f"2026-08-10T00:{number:02d}:00+00:00",
                    }
                )

        assigned = module.assign_repeat_indices(
            records, condition="bare", replication=replication
        )

        for task_id in {record["taskId"] for record in records}:
            selected = [record for record in assigned if record["taskId"] == task_id]
            self.assertEqual(
                [(record["repeatIndex"], record["trialName"]) for record in selected],
                [
                    (number, f"{task_id[:8]}-{number:02d}")
                    for number in range(1, 11)
                ],
            )
            self.assertTrue(all(len(record["cellId"]) == 16 for record in selected))

        with self.assertRaisesRegex(ValueError, "expected 10 trials"):
            module.assign_repeat_indices(
                records[:-1], condition="bare", replication=replication
            )
        malformed = [dict(record) for record in records]
        malformed[0]["startedAt"] = None
        with self.assertRaisesRegex(ValueError, "started_at"):
            module.assign_repeat_indices(
                malformed, condition="bare", replication=replication
            )

    def test_summary_excludes_invalid_cells_and_keeps_exact_timeout_as_failure(self):
        module = load_replication_module()
        replication = json.loads(REPLICATION_MANIFEST.read_text(encoding="utf-8"))
        cells = [
            {
                **identity,
                "benchmarkOutcomeValid": True,
                "runtimeValid": True,
                "reward": 0,
                "complete": False,
                "executionStatus": "completed",
                "providerErrorCount": 0,
                "recoveredProviderErrorCount": 0,
                "terminalProviderErrorCount": 0,
                "nOutputTokens": 10,
                "nAgentSteps": 1,
                "unsafeDelivered": False,
            }
            for identity in module.build_replication_plan(replication)
        ]

        def cell(condition, task_id, repeat):
            return next(
                item
                for item in cells
                if item["condition"] == condition
                and item["taskId"] == task_id
                and item["repeatIndex"] == repeat
            )

        sql = "sql-formatter-bigquery-pipe-formatting"
        cell("bare", sql, 1)["reward"] = 1
        cell("bare", sql, 2)["reward"] = 1
        cell("bare", sql, 4)["reward"] = 1
        cell("inner", sql, 1).update(
            benchmarkOutcomeValid=False,
            runtimeValid=False,
            reward=1,
            executionStatus="invalid",
            providerErrorCount=1,
            recoveredProviderErrorCount=0,
            terminalProviderErrorCount=1,
        )
        cell("inner", sql, 2).update(
            providerErrorCount=1,
            recoveredProviderErrorCount=1,
        )
        cell("inner", sql, 3)["reward"] = 1
        cell("inner", sql, 4)["reward"] = 1
        cell("full", sql, 1).update(
            runtimeValid=False,
            executionStatus="timeout",
        )

        summary = module.summarize_replication(cells, replication)

        sql_summary = summary["byTask"][sql]
        self.assertEqual(
            sql_summary["byCondition"]["bare"]["resolved"], 3
        )
        self.assertEqual(
            sql_summary["byCondition"]["bare"]["validOutcomes"], 10
        )
        self.assertEqual(
            sql_summary["byCondition"]["bare"]["resolutionWilson95"],
            [0.10779126740630099, 0.6032218525388546],
        )
        self.assertEqual(
            sql_summary["byCondition"]["inner"]["resolved"], 2
        )
        self.assertEqual(
            sql_summary["byCondition"]["inner"]["validOutcomes"], 9
        )
        self.assertEqual(
            sql_summary["byCondition"]["inner"]["invalidOutcomes"], 1
        )
        self.assertEqual(
            sql_summary["byCondition"]["inner"]["providerErrorRecords"], 2
        )
        self.assertEqual(
            sql_summary["byCondition"]["inner"]["recoveredProviderErrors"], 1
        )
        self.assertEqual(
            sql_summary["byCondition"]["inner"]["terminalProviderErrors"], 1
        )
        self.assertEqual(sql_summary["byCondition"]["full"]["timeouts"], 1)
        self.assertEqual(
            sql_summary["byCondition"]["full"]["validOutcomes"], 10
        )
        comparison = sql_summary["comparisons"]["bareVsInner"]
        self.assertEqual(
            comparison,
            {
                "eligiblePairs": 9,
                "missingPairs": 1,
                "both": 1,
                "bareOnly": 1,
                "innerOnly": 1,
                "neither": 6,
            },
        )
        self.assertEqual(summary["subjects"], 50)
        self.assertEqual(summary["benchmarkOutcomeValid"], 49)
        self.assertEqual(summary["timeouts"], 1)

        timeout = {
            "exception_type": "AgentTimeoutError",
            "exception_message": "Agent execution timed out after 5400.0 seconds",
        }
        self.assertEqual(module.classify_replication_exception(None), "completed")
        self.assertEqual(module.classify_replication_exception(timeout), "timeout")
        self.assertEqual(
            module.classify_replication_exception(
                {
                    "exception_type": "NonZeroAgentExitCodeError",
                    "exception_message": "provider failed",
                }
            ),
            "invalid",
        )

    def test_three_condition_commands_really_start_concurrently(self):
        module = load_replication_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            script = """
import pathlib, sys, time
root = pathlib.Path(sys.argv[1])
marker = root / (sys.argv[2] + '.started')
marker.write_text('started', encoding='ascii')
deadline = time.monotonic() + 5
while time.monotonic() < deadline:
    if len(list(root.glob('*.started'))) == 3:
        raise SystemExit(0)
    time.sleep(0.02)
raise SystemExit(9)
"""
            commands = {
                condition: [sys.executable, "-c", script, str(root), condition]
                for condition in ("bare", "inner", "full")
            }
            completed = module.run_condition_commands_concurrently(
                commands, cwd=root, environment=os.environ.copy()
            )

        self.assertEqual(set(completed), {"bare", "inner", "full"})
        self.assertTrue(all(result.returncode == 0 for result in completed.values()))

    def test_final_artifacts_require_exact_fifty_identities_and_bind_full_attestation(self):
        module = load_replication_module()
        replication = json.loads(REPLICATION_MANIFEST.read_text(encoding="utf-8"))
        cells = [
            {
                **identity,
                "benchmarkOutcomeValid": True,
                "runtimeValid": True,
                "reward": 0,
                "complete": False,
                "executionStatus": "completed",
                "providerErrorCount": 0,
                "recoveredProviderErrorCount": 0,
                "terminalProviderErrorCount": 0,
                "nOutputTokens": 0,
                "nAgentSteps": 0,
                "unsafeDelivered": False,
            }
            for identity in module.build_replication_plan(replication)
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "complete"
            output.mkdir()
            raw_input = output / "replication-inputs.json"
            raw_input.write_text('{"checkpoint":"frozen"}\n', encoding="utf-8")
            artifact = module.write_replication_artifacts(output, cells, replication)
            cells_bytes = (output / "cells.json").read_bytes()
            attestation_bytes = (output / "attestation.json").read_bytes()
            self.assertEqual(
                (output / "COMPLETE").read_text(encoding="ascii").strip(),
                hashlib.sha256(attestation_bytes).hexdigest(),
            )
            self.assertEqual(artifact["cellsSha256"], hashlib.sha256(cells_bytes).hexdigest())
            self.assertEqual(artifact["attestationSha256"], hashlib.sha256(attestation_bytes).hexdigest())
            attestation = json.loads(attestation_bytes)
            self.assertIn(
                "replication-inputs.json",
                [entry["path"] for entry in attestation["files"]],
            )
            self.assertTrue(module.verify_output_attestation(output))
            self.assertEqual(
                json.loads((output / "summary.json").read_text(encoding="utf-8"))[
                    "subjects"
                ],
                50,
            )
            raw_input.write_text('{"checkpoint":"changed"}\n', encoding="utf-8")
            self.assertFalse(module.verify_output_attestation(output))

            incomplete = Path(temp_dir) / "incomplete"
            incomplete.mkdir()
            with self.assertRaisesRegex(ValueError, "cell identities"):
                module.write_replication_artifacts(
                    incomplete, cells[:-1], replication
                )
            self.assertFalse((incomplete / "COMPLETE").exists())

    def test_host_credential_scan_redacts_and_records_condition_leak(self):
        module = load_replication_module()
        secret = "s" * 32
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir)
            condition_root = output / "bare"
            condition_root.mkdir()
            leak = condition_root / "leak.txt"
            leak.write_text(f"before {secret} after", encoding="utf-8")

            leaks = module.scan_condition_artifacts(
                output_root=output, condition="bare", secret=secret
            )

            self.assertEqual(leaks, ["leak.txt"])
            self.assertNotIn(secret, leak.read_text(encoding="utf-8"))
            security = json.loads(
                (output / "bare-security.json").read_text(encoding="utf-8")
            )
            self.assertEqual(security["credentialLeakPaths"], ["leak.txt"])
            self.assertIsNone(security["scanError"])

    def test_concurrent_condition_jobs_scan_each_artifact_tree(self):
        module = load_replication_module()
        secret = "k" * 32
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir)
            script = """
import pathlib, sys, time
root = pathlib.Path(sys.argv[1])
condition = sys.argv[2]
secret = sys.argv[3]
condition_root = root / condition
condition_root.mkdir()
(condition_root / 'credential.txt').write_text(secret, encoding='ascii')
(condition_root / 'started').write_text('1', encoding='ascii')
deadline = time.monotonic() + 5
while time.monotonic() < deadline:
    if sum((root / name / 'started').is_file() for name in ('bare','inner','full')) == 3:
        raise SystemExit(0)
    time.sleep(0.02)
raise SystemExit(9)
"""
            commands = {
                condition: [
                    sys.executable,
                    "-c",
                    script,
                    str(output),
                    condition,
                    secret,
                ]
                for condition in ("bare", "inner", "full")
            }
            completed, leaks = module.run_condition_jobs_with_scans(
                commands,
                cwd=output,
                environment=os.environ.copy(),
                output_root=output,
                secret=secret,
            )

            self.assertTrue(
                all(result.returncode == 0 for result in completed.values())
            )
            self.assertEqual(
                leaks,
                {condition: ["credential.txt"] for condition in ("bare", "inner", "full")},
            )
            for condition in ("bare", "inner", "full"):
                self.assertNotIn(
                    secret,
                    (output / condition / "credential.txt").read_text(encoding="utf-8"),
                )
                self.assertTrue((output / f"{condition}-security.json").is_file())


if __name__ == "__main__":
    unittest.main()
