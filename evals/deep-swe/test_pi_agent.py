import hashlib
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from urllib.parse import urljoin
from unittest import mock

from build_guard_bundle import build_guard_bundle
from pi_agent import (
    MODEL_BASE_URL,
    MODEL_ID,
    MODEL_PROVIDER,
    MAX_CONTINUATIONS,
    NODE_SHA256,
    NODE_VERSION,
    PI_TARBALL_SHA256,
    PI_SHRINKWRAP_SHA256,
    PI_VERSION,
    PiOckleAgent,
    SYSTEM_APPEND,
    CONTINUATION_PROMPT,
    build_models_config,
    build_continuation_status_command,
    build_guard_final_command,
    build_guard_hook,
    build_pi_arguments,
    build_post_run_sanitize_command,
    build_secret_scan_script,
    build_settings,
    combine_final_status_bytes,
    parse_final_state_evidence,
    parse_session_evidence,
    should_continue_after_turn,
)
from prepare_pilot import (
    harden_task_config,
    pin_image_reference,
    validate_pilot_manifest,
)
from run_pilot import (
    _condition_results,
    _redact_secret_tree,
    _require_outside_repository,
    _run_pier_with_credential_scan,
    _verify_pier_install,
    build_pier_command,
)


class PiAgentUnitTests(unittest.TestCase):
    def test_manifest_validation_freezes_twelve_tasks_and_twenty_nine_subjects(self):
        manifest_path = Path(__file__).with_name("pilot-v1.json")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        summary = validate_pilot_manifest(manifest)
        self.assertEqual(summary, {"tasks": 12, "subjects": 29, "guardTasks": 5})
        execution = manifest["execution"]
        self.assertEqual(execution["maxContinuations"], 1)
        self.assertEqual(execution["continuationTrigger"], "trusted-dirty-worktree")
        self.assertEqual(execution["pierSquidSafePorts"], [80, 443, 8317])
        self.assertEqual(execution["pierSquidSslPorts"], [443])
        self.assertEqual(
            execution["candidateIndexAuthority"],
            "actual-index-plus-independent-worktree",
        )
        self.assertEqual(
            execution["statusEvidence"], "root-frozen-raw-bytes-sha256"
        )
        self.assertTrue(execution["rejectSplitIndex"])
        self.assertEqual(
            execution["pierSquidBootstrapSha256"],
            "c955bfa87b87dbc18b91d7e4c89b8a78ac56319a64624c93b15a14f21571d328",
        )

    def test_image_reference_is_replaced_exactly_once_with_digest(self):
        source = '[environment]\ndocker_image = "registry.example/task:v1"\n'
        pinned = pin_image_reference(
            source,
            "registry.example/task:v1",
            "sha256:" + "a" * 64,
        )
        self.assertEqual(
            pinned,
            '[environment]\ndocker_image = "registry.example/task:v1@sha256:'
            + "a" * 64
            + '"\n',
        )
        with self.assertRaisesRegex(ValueError, "exactly one"):
            pin_image_reference(source + source, "registry.example/task:v1", "sha256:" + "a" * 64)
        with self.assertRaisesRegex(ValueError, "exactly one"):
            pin_image_reference(source, "registry.example/other:v1", "sha256:" + "a" * 64)

    def test_prepared_task_enforces_nonroot_no_network_and_hardened_collection(self):
        source = """schema_version = \"1.3\"
[verifier]
environment_mode = \"separate\"
[verifier.environment]
cpus = 2
[[verifier.collect]]
command = \"cd /app && mkdir -p /logs/artifacts && git config --global --add safe.directory /app && git diff --binary aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa HEAD > /logs/artifacts/model.patch\"
[agent]
network_mode = \"no-network\"
timeout_sec = 5400.0
[environment]
docker_image = \"example/image:v1\"
"""
        hardened = harden_task_config(source, "a" * 40)
        import tomllib

        parsed = tomllib.loads(hardened)
        self.assertEqual(parsed["agent"]["user"], "ockle")
        self.assertFalse(parsed["environment"]["allow_internet"])
        self.assertFalse(parsed["verifier"]["environment"]["allow_internet"])
        collect = parsed["verifier"]["collect"][0]["command"]
        self.assertIn("GIT_NO_REPLACE_OBJECTS=1", collect)
        self.assertIn("GIT_CONFIG_GLOBAL=/dev/null", collect)
        self.assertIn("--no-ext-diff", collect)
        self.assertIn("--no-textconv", collect)
        self.assertIn("git -c safe.directory=/app", collect)
        self.assertNotIn("git config --global", collect)
        with self.assertRaisesRegex(ValueError, "collect command"):
            harden_task_config(source.replace("git diff --binary", "git status && git diff --binary"), "a" * 40)

    def test_formal_pier_commands_select_frozen_arm_cells_without_secrets(self):
        manifest_path = Path(__file__).with_name("pilot-v1.json")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        common = {
            "manifest": manifest,
            "tasks_root": Path("/pilot/tasks"),
            "jobs_root": Path("/jobs"),
            "secrets_file": Path("/secrets.env"),
            "concurrency": 4,
        }
        bare = build_pier_command(condition="bare", guard_bundle=None, **common)
        inner = build_pier_command(condition="inner", guard_bundle=None, **common)
        full = build_pier_command(
            condition="full", guard_bundle=Path("/guard.tar.gz"), **common
        )

        self.assertEqual(bare[0], str(Path(__import__("sys").executable)))
        self.assertEqual(bare[1:4], ["-B", "-c", "from pier.cli.main import app; app()"])
        self.assertEqual(bare.count("--include-task-name"), 12)
        self.assertEqual(inner.count("--include-task-name"), 12)
        self.assertEqual(full.count("--include-task-name"), 5)
        self.assertNotIn("guard_bundle", " ".join(bare))
        self.assertNotIn("guard_bundle", " ".join(inner))
        self.assertIn("guard_bundle=/guard.tar.gz", full)
        self.assertNotIn("MAPLELUV_API_KEY", " ".join(bare + inner + full))
        with self.assertRaisesRegex(ValueError, "guard bundle"):
            build_pier_command(condition="full", guard_bundle=None, **common)

    def test_formal_paths_must_resolve_outside_the_repository(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository = root / "repository"
            repository.mkdir()
            inside = repository / "raw-results"
            outside = root / "formal-results"
            with self.assertRaisesRegex(ValueError, "outside the Ockle repository"):
                _require_outside_repository(inside, repository, "formal output")
            self.assertEqual(
                _require_outside_repository(outside, repository, "formal output"),
                outside.resolve(),
            )

    def test_official_deepseek_calibration_is_external_and_not_a_control_arm(self):
        path = Path(__file__).with_name("official-deepseek-v4-flash-max.json")
        calibration = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(calibration["aggregate"]["passes"], 15)
        self.assertEqual(calibration["aggregate"]["attempts"], 48)
        self.assertEqual(calibration["aggregate"]["zeroOfFourTasks"], 4)
        self.assertEqual(calibration["aggregate"]["mixedTasks"], 8)
        self.assertEqual(calibration["aggregate"]["fourOfFourTasks"], 0)
        self.assertIn("not a Pi/Ockle control arm", calibration["role"])
        self.assertEqual(
            {task["taskId"] for task in calibration["tasks"]},
            {
                task["id"]
                for task in json.loads(
                    Path(__file__).with_name("pilot-v1.json").read_text(encoding="utf-8")
                )["tasks"]
            },
        )

    def test_pier_install_is_invoked_through_the_verified_python_distribution(self):
        evidence = _verify_pier_install()
        self.assertEqual(evidence["commit"], "0daf53d3599e58c4506cf0bcff5e12c77dc282d2")
        self.assertGreaterEqual(evidence["verifiedFiles"], 100)
        self.assertEqual(
            Path(evidence["python"]), Path(__import__("sys").executable).absolute()
        )
        imported = subprocess.run(
            [evidence["python"], "-B", "-c", "import pier; print(pier.__file__)"],
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertIn("site-packages/pier", imported.stdout)

    def test_host_credential_scan_redacts_exact_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "nested").mkdir()
            target = root / "nested" / "artifact.bin"
            target.write_bytes(b"before-secret-value-after")
            leaked = _redact_secret_tree(root, "secret-value")
            self.assertEqual(leaked, ["nested/artifact.bin"])
            self.assertEqual(target.read_bytes(), b"before-[REDACTED]-after")

    def test_host_credential_scan_purges_oversized_unscanned_artifacts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "oversized.bin"
            with target.open("wb") as stream:
                stream.write(b"secret-value")
                stream.truncate(1024 * 1024 * 1024 + 1)
            with self.assertRaisesRegex(RuntimeError, "scan budget"):
                _redact_secret_tree(root, "secret-value")
            self.assertFalse(target.exists())

    def test_host_credential_scan_runs_when_pier_launch_raises(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            condition = output / "bare"
            condition.mkdir()
            artifact = condition / "artifact.txt"
            artifact.write_text("before-secret-value-after", encoding="utf-8")
            with mock.patch(
                "run_pilot.subprocess.run", side_effect=RuntimeError("launch failed")
            ):
                with self.assertRaisesRegex(RuntimeError, "launch failed"):
                    _run_pier_with_credential_scan(
                        command=["pier"],
                        cwd=output,
                        environment={},
                        output_root=output,
                        condition="bare",
                        secret="secret-value",
                    )
            self.assertEqual(
                artifact.read_text(encoding="utf-8"), "before-[REDACTED]-after"
            )
            security = json.loads(
                (output / "bare-security.json").read_text(encoding="utf-8")
            )
            self.assertEqual(security["credentialLeakPaths"], ["artifact.txt"])
            self.assertIsNone(security["scanError"])

    def test_guard_bundle_is_byte_reproducible(self):
        repository = Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory() as directory:
            first = Path(directory) / "first.tar.gz"
            second = Path(directory) / "second.tar.gz"
            first_hash = build_guard_bundle(repository, first)
            second_hash = build_guard_bundle(repository, second)
        self.assertEqual(first_hash, second_hash)
        manifest = json.loads(
            Path(__file__).with_name("pilot-v1.json").read_text(encoding="utf-8")
        )
        self.assertEqual(first_hash, manifest["execution"]["guardBundleSha256"])

    def test_models_config_references_secret_without_embedding_it(self):
        config = build_models_config()
        serialized = json.dumps(config)
        provider = config["providers"][MODEL_PROVIDER]
        model = provider["models"][0]

        self.assertEqual(provider["apiKey"], "$MAPLELUV_API_KEY")
        self.assertEqual(provider["baseUrl"], "http://38.148.253.23:8317")
        self.assertEqual(
            urljoin(provider["baseUrl"] + "/", "v1/messages"),
            "http://38.148.253.23:8317/v1/messages",
        )
        self.assertEqual(provider["api"], "anthropic-messages")
        self.assertEqual(model["id"], MODEL_ID)
        self.assertEqual(model["contextWindow"], 1_048_000)
        self.assertEqual(model["maxTokens"], 384_000)
        self.assertEqual(model["thinkingLevelMap"]["max"], "max")
        self.assertNotIn("thinkingLevelMap", model["compat"])
        self.assertNotIn("sk-", serialized)

    def test_settings_disable_magic_and_native_compaction(self):
        settings = build_settings()
        self.assertEqual(settings["packages"], [])
        self.assertEqual(settings["extensions"], [])
        self.assertEqual(settings["compaction"], {"enabled": False})
        self.assertEqual(settings["defaultProjectTrust"], "never")

    def test_pi_arguments_keep_conditions_blind_and_load_only_expected_skills(self):
        bare = build_pi_arguments("bare", "Implement the task")
        inner = build_pi_arguments("inner", "Implement the task")
        full = build_pi_arguments("full", "Implement the task")

        for args in (bare, inner, full):
            self.assertIn("--mode", args)
            self.assertIn("json", args)
            self.assertIn("--print", args)
            self.assertIn("--no-extensions", args)
            self.assertIn("--no-skills", args)
            self.assertIn("--no-prompt-templates", args)
            self.assertIn("--no-themes", args)
            self.assertIn("--model", args)
            self.assertIn(f"{MODEL_PROVIDER}/{MODEL_ID}", args)
            self.assertIn("Mapleluv-Main-MSG/deepseek-v4-flash", args)
            self.assertIn("--thinking", args)
            self.assertIn("max", args)
            self.assertNotIn("bare", " ".join(args).lower())
            self.assertNotIn("inner", " ".join(args).lower())
            self.assertNotIn("full", " ".join(args).lower())

        self.assertEqual(bare.count("--skill"), 0)
        self.assertEqual(inner.count("--skill"), 3)
        self.assertEqual(full.count("--skill"), 3)

    def test_dirty_worktree_gets_one_same_session_continuation(self):
        initial = build_pi_arguments("inner", "Implement the task")
        resumed = build_pi_arguments(
            "inner", CONTINUATION_PROMPT, continue_session=True
        )

        self.assertNotIn("--continue", initial)
        self.assertIn("--continue", resumed)
        self.assertIn("--session-dir", resumed)
        self.assertEqual(resumed[-1], CONTINUATION_PROMPT)
        self.assertEqual(MAX_CONTINUATIONS, 1)
        self.assertTrue(
            should_continue_after_turn(
                return_code=0,
                trusted_worktree_status=" M src/example.ts\n",
                continuation_count=0,
            )
        )
        self.assertFalse(
            should_continue_after_turn(
                return_code=0,
                trusted_worktree_status="",
                continuation_count=0,
            )
        )
        self.assertFalse(
            should_continue_after_turn(
                return_code=1,
                trusted_worktree_status=" M src/example.ts\n",
                continuation_count=0,
            )
        )
        self.assertFalse(
            should_continue_after_turn(
                return_code=0,
                trusted_worktree_status=" M src/example.ts\n",
                continuation_count=1,
            )
        )
        self.assertIn("text-only response ends", SYSTEM_APPEND)

    def test_continuation_status_uses_trusted_git_inputs(self):
        command = build_continuation_status_command()
        self.assertIn("GIT_DIR=/app/.git", command)
        self.assertIn("GIT_WORK_TREE=/app", command)
        self.assertIn("GIT_INDEX_FILE=/tmp/ockle-continuation-index", command)
        self.assertIn("GIT_INDEX_FILE=/app/.git/index", command)
        self.assertIn("test -f /app/.git/index", command)
        self.assertIn("test ! -L /app/.git/index", command)
        self.assertIn("git rev-parse --shared-index-path", command)
        self.assertIn("git diff-index --cached", command)
        self.assertIn("GIT_NO_REPLACE_OBJECTS=1", command)
        self.assertIn("git read-tree --reset HEAD", command)
        self.assertIn("status --porcelain=v1 --untracked-files=all", command)
        self.assertNotIn("/logs", command)

    def test_continuation_arguments_are_condition_blind(self):
        for condition in ("bare", "inner", "full"):
            args = build_pi_arguments(
                condition, CONTINUATION_PROMPT, continue_session=True
            )
            self.assertEqual(args.count("--continue"), 1)
            rendered = " ".join(args).lower()
            self.assertNotIn("bare", rendered)
            self.assertNotIn("inner", rendered)
            self.assertNotIn("full", rendered)

    def test_unknown_condition_fails_before_launch(self):
        with self.assertRaisesRegex(ValueError, "unknown condition"):
            build_pi_arguments("unknown", "Implement the task")

    def test_full_agent_records_exact_guard_bundle_digest(self):
        with tempfile.NamedTemporaryFile() as bundle:
            bundle.write(b"guard-bundle")
            bundle.flush()
            agent = PiOckleAgent(
                logs_dir=Path(tempfile.mkdtemp()),
                model_name=f"{MODEL_PROVIDER}/{MODEL_ID}",
                condition="full",
                guard_bundle=bundle.name,
            )
        self.assertEqual(
            agent.guard_bundle_sha256,
            "99c675b93c0f307d967cc00399161ba92cb475c49c7284666970b8b2b91a488d",
        )

    def test_full_guard_uses_staged_feedback_and_immutable_final_check(self):
        hook = build_guard_hook()
        final_command = build_guard_final_command()
        sanitizer = build_post_run_sanitize_command()

        self.assertIn("GIT_NO_REPLACE_OBJECTS=1", hook)
        self.assertIn("--candidate index", hook)
        self.assertIn("--no-store", hook)
        self.assertNotIn("authorization", hook.lower())
        self.assertIn("GIT_NO_REPLACE_OBJECTS=1", final_command)
        self.assertIn("--candidate HEAD", final_command)
        self.assertIn("--candidate worktree", final_command)
        self.assertIn("git-final-status", final_command)
        self.assertIn("--no-store", final_command)
        self.assertNotIn("authorization", final_command.lower())
        self.assertIn("GIT_DIR=/app/.git", final_command)
        self.assertIn("GIT_WORK_TREE=/app", final_command)
        self.assertIn("GIT_INDEX_FILE=/tmp/ockle-final-index", final_command)
        self.assertIn("core.worktree", final_command)
        self.assertIn("git read-tree --reset HEAD", sanitizer)
        self.assertIn("objects/info/alternates", sanitizer)
        self.assertIn("/opt/ockle/base-commit", hook)
        self.assertIn("/opt/ockle/base-commit", final_command)

    def test_full_result_requires_clear_commit_and_worktree_guards_plus_clean_git(self):
        manifest = json.loads(
            Path(__file__).with_name("pilot-v1.json").read_text(encoding="utf-8")
        )
        selected = [task for task in manifest["tasks"] if "full" in task["arms"]]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for task in selected:
                trial = root / "full" / task["id"]
                (trial / "artifacts").mkdir(parents=True)
                (trial / "artifacts" / "model.patch").write_text("patch")
                from pier.environments.agent_setup import squid_bootstrap_command

                (trial / "egress-proxy").mkdir()
                (trial / "egress-proxy" / "start-squid.sh").write_text(
                    squid_bootstrap_command(), encoding="utf-8"
                )
                (trial / "agent").mkdir()
                (trial / "agent" / "continuation-status.txt").write_bytes(b"")
                (trial / "agent" / "git-final-status.txt").write_bytes(b"")
                (trial / "agent" / "git-final-index-status.txt").write_bytes(b"")
                empty_sha = hashlib.sha256(b"").hexdigest()
                combined_status_sha = hashlib.sha256(
                    combine_final_status_bytes(b"", b"")
                ).hexdigest()
                guard = {
                    candidate: {
                        "exitCode": 0,
                        "result": {
                            "schemaVersion": 1,
                            "operation": "check",
                            "verdict": "clear",
                        },
                    }
                    for candidate in ("commit", "worktree")
                }
                payload = {
                    "task_name": f"datacurve/{task['id']}",
                    "task_checksum": task["preparedTaskChecksum"],
                    "config": {
                        "agent": {
                            "import_path": "pi_agent:PiOckleAgent",
                            "model_name": f"{MODEL_PROVIDER}/{MODEL_ID}",
                            "kwargs": {"condition": "full"},
                        }
                    },
                    "agent_result": {
                        "summarization_count": 0,
                        "n_input_tokens": 1,
                        "n_cache_tokens": 0,
                        "n_output_tokens": 1,
                        "n_agent_steps": 1,
                        "metadata": {
                            "runtimeEvidenceValid": True,
                            "finalStateEvidenceValid": True,
                            "provider": MODEL_PROVIDER,
                            "model": MODEL_ID,
                            "api": "anthropic-messages",
                            "thinking": "max",
                            "agentUid": 1000,
                            "continuation": {
                                "schemaVersion": 1,
                                "maxContinuations": 1,
                                "count": 0,
                                "statusChecked": True,
                                "triggeredByDirtyWorktree": False,
                                "statusBytes": 0,
                                "statusSha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
                            },
                            "security": {"scanError": False, "credentialLeak": False},
                            "worktreeClean": True,
                            "worktreeStatusSha256": combined_status_sha,
                            "worktreeStatusBytes": 0,
                            "independentWorktreeClean": True,
                            "independentWorktreeStatusSha256": empty_sha,
                            "independentWorktreeStatusBytes": 0,
                            "candidateIndexClean": True,
                            "candidateIndexStatusSha256": empty_sha,
                            "candidateIndexStatusBytes": 0,
                            "guardBundleSha256": manifest["execution"]["guardBundleSha256"],
                            "guard": guard,
                        },
                    },
                    "verifier_result": {
                        "rewards": {"reward": 1, "f2p": 1.0, "p2p": 1.0, "partial": 1.0}
                    },
                    "exception_info": None,
                    "agent_execution": {"started_at": "a", "finished_at": "b"},
                }
                (trial / "result.json").write_text(json.dumps(payload), encoding="utf-8")

            cells = _condition_results(
                output_root=root,
                condition="full",
                manifest=manifest,
                host_credential_leaks=[],
            )
            self.assertTrue(all(cell["complete"] for cell in cells))
            self.assertTrue(all(cell["proxyPolicyValid"] for cell in cells))
            self.assertTrue(all(cell["continuationCount"] == 0 for cell in cells))

            target_path = root / "full" / selected[0]["id"] / "result.json"
            continuation_status_path = target_path.parent / "agent" / "continuation-status.txt"
            continuation_status_path.write_bytes(b"M  src/example.ts\n")
            cells = _condition_results(
                output_root=root,
                condition="full",
                manifest=manifest,
                host_credential_leaks=[],
            )
            invalid_status_bytes = next(
                cell for cell in cells if cell["taskId"] == selected[0]["id"]
            )
            self.assertFalse(invalid_status_bytes["runtimeValid"])
            continuation_status_path.write_bytes(b"")

            proxy_path = target_path.parent / "egress-proxy" / "start-squid.sh"
            valid_proxy = proxy_path.read_text(encoding="utf-8")
            proxy_path.write_text(
                valid_proxy.replace("acl Safe_ports port 80 443 8317", "acl Safe_ports port 80 443"),
                encoding="utf-8",
            )
            cells = _condition_results(
                output_root=root,
                condition="full",
                manifest=manifest,
                host_credential_leaks=[],
            )
            invalid_proxy = next(
                cell for cell in cells if cell["taskId"] == selected[0]["id"]
            )
            self.assertFalse(invalid_proxy["proxyPolicyValid"])
            self.assertFalse(invalid_proxy["runtimeValid"])
            proxy_path.write_text(valid_proxy, encoding="utf-8")

            target = json.loads(target_path.read_text(encoding="utf-8"))
            valid_continuation = target["agent_result"]["metadata"]["continuation"]
            target["agent_result"]["metadata"]["continuation"] = {
                **valid_continuation,
                "count": 1,
                "triggeredByDirtyWorktree": False,
            }
            target_path.write_text(json.dumps(target), encoding="utf-8")
            cells = _condition_results(
                output_root=root,
                condition="full",
                manifest=manifest,
                host_credential_leaks=[],
            )
            invalid_continuation = next(
                cell for cell in cells if cell["taskId"] == selected[0]["id"]
            )
            self.assertFalse(invalid_continuation["runtimeValid"])
            self.assertFalse(invalid_continuation["complete"])

            target["agent_result"]["metadata"]["continuation"] = valid_continuation
            target["agent_result"]["metadata"]["guard"]["worktree"] = {
                "exitCode": 1,
                "result": {
                    "schemaVersion": 1,
                    "operation": "check",
                    "verdict": "blocked",
                },
            }
            target_path.write_text(json.dumps(target), encoding="utf-8")
            cells = _condition_results(
                output_root=root,
                condition="full",
                manifest=manifest,
                host_credential_leaks=[],
            )
            blocked = next(cell for cell in cells if cell["taskId"] == selected[0]["id"])
            self.assertFalse(blocked["complete"])
            self.assertFalse(blocked["safeDelivery"])
            self.assertTrue(blocked["unsafeDelivered"])
            self.assertEqual(blocked["guardCommitVerdict"], "clear")
            self.assertEqual(blocked["guardWorktreeVerdict"], "blocked")

    def test_full_agent_requires_a_guard_bundle_but_other_arms_do_not(self):
        for condition in ("bare", "inner"):
            PiOckleAgent(
                logs_dir=Path(tempfile.mkdtemp()),
                model_name=f"{MODEL_PROVIDER}/{MODEL_ID}",
                condition=condition,
            )
        with self.assertRaisesRegex(ValueError, "guard_bundle"):
            PiOckleAgent(
                logs_dir=Path(tempfile.mkdtemp()),
                model_name=f"{MODEL_PROVIDER}/{MODEL_ID}",
                condition="full",
            )

    def test_install_and_network_contracts_are_pinned(self):
        agent = PiOckleAgent(
            logs_dir=Path(tempfile.mkdtemp()),
            model_name=f"{MODEL_PROVIDER}/{MODEL_ID}",
            condition="bare",
        )
        spec = agent.install_spec()
        commands = "\n".join(step.run for step in spec.steps)

        self.assertEqual(agent.name(), "pi-ockle")
        self.assertEqual(spec.version, PI_VERSION)
        self.assertIn(NODE_VERSION, commands)
        self.assertIn(NODE_SHA256, commands)
        self.assertIn(PI_TARBALL_SHA256, commands)
        self.assertIn(PI_SHRINKWRAP_SHA256, commands)
        self.assertIn("useradd", commands)
        self.assertIn("ockle", commands)
        self.assertNotIn(f"npm install -g --ignore-scripts @earendil-works/pi-coding-agent@{PI_VERSION}", commands)
        self.assertEqual(agent.network_allowlist().domains, ["38.148.253.23"])
        from pier.environments.agent_setup import squid_bootstrap_command

        proxy_script = squid_bootstrap_command()
        self.assertIn("acl Safe_ports port 80 443 8317", proxy_script)
        self.assertNotIn("acl Safe_ports port 1-65535", proxy_script)
        self.assertEqual(proxy_script.count("8317"), 1)
        self.assertEqual(MODEL_BASE_URL, "http://38.148.253.23:8317")

    def test_final_state_combines_independent_worktree_and_candidate_index(self):
        with tempfile.TemporaryDirectory() as directory:
            logs = Path(directory)
            (logs / "git-final-status.txt").write_bytes(b"")
            (logs / "git-final-status-exit.txt").write_text("0\n", encoding="utf-8")
            (logs / "git-final-index-status.txt").write_bytes(b"M\tsrc/example.ts\n")
            (logs / "git-final-index-status-exit.txt").write_text("0\n", encoding="utf-8")

            evidence = parse_final_state_evidence(logs, "bare")

            self.assertFalse(evidence["worktreeClean"])
            self.assertTrue(evidence["independentWorktreeClean"])
            self.assertFalse(evidence["candidateIndexClean"])
            self.assertEqual(evidence["candidateIndexStatusBytes"], 17)

            (logs / "git-final-index-status-exit.txt").write_text(
                "128\n", encoding="utf-8"
            )
            with self.assertRaisesRegex(ValueError, "trusted final Git status failed"):
                parse_final_state_evidence(logs, "bare")

    def test_post_run_boundary_sanitizes_git_and_scans_exact_delivery_bytes(self):
        sanitize = build_post_run_sanitize_command()
        scanner = build_secret_scan_script()
        self.assertIn("pkill", sanitize)
        self.assertIn("rm -rf /tmp/ockle-pi", sanitize)
        self.assertIn("test -f /app/.git/index", sanitize)
        self.assertIn("test ! -L /app/.git/index", sanitize)
        self.assertIn("refs/replace", sanitize)
        self.assertIn("info/grafts", sanitize)
        self.assertIn("GIT_NO_REPLACE_OBJECTS", scanner)
        self.assertIn("diff", scanner)
        self.assertIn("HEAD", scanner)
        self.assertIn("/logs/agent", scanner)
        self.assertIn("/app", scanner)
        self.assertIn("credentialLeak", scanner)
        self.assertIn("scanBudgetExceeded", scanner)
        self.assertIn("rmSync('/logs/agent'", scanner)
        source = Path(__file__).with_name("pi_agent.py").read_text(encoding="utf-8")
        self.assertIn("chown root:root /app/.git/hooks", source)
        self.assertIn("chmod 0555 /app/.git/hooks", source)
        self.assertIn('"PI_CODING_AGENT_DIR": "/tmp/ockle-pi"', source)
        self.assertIn("cp {REMOTE_PI_DIR}/models.json", source)
        self.assertLess(
            source.index('"runtime-evidence.json"'),
            source.index('command="chown -R root:root /logs/agent'),
        )

    def test_session_metrics_are_derived_from_validated_structured_usage(self):
        with tempfile.TemporaryDirectory() as directory:
            session = Path(directory, "session.jsonl")
            rows = [
                {"type": "session", "id": "session-1", "cwd": "/app"},
                {
                    "type": "model_change",
                    "provider": MODEL_PROVIDER,
                    "modelId": MODEL_ID,
                },
                {"type": "thinking_level_change", "thinkingLevel": "max"},
                {
                    "type": "message",
                    "message": {
                        "role": "assistant",
                        "provider": MODEL_PROVIDER,
                        "model": MODEL_ID,
                        "api": "anthropic-messages",
                        "usage": {
                            "input": 100,
                            "output": 20,
                            "reasoning": 30,
                            "cacheRead": 40,
                            "cacheWrite": 10,
                            "cost": {"total": 0.03},
                        },
                    },
                },
                {"type": "message", "message": {"role": "user"}},
                {
                    "type": "message",
                    "message": {
                        "role": "assistant",
                        "provider": MODEL_PROVIDER,
                        "model": MODEL_ID,
                        "api": "anthropic-messages",
                        "usage": {
                            "input": 200,
                            "output": 50,
                            "reasoning": 60,
                            "cacheRead": 70,
                            "cacheWrite": 0,
                            "cost": {"total": 0.07},
                        },
                    },
                },
            ]
            session.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")

            evidence = parse_session_evidence(session)

            self.assertEqual(evidence["n_input_tokens"], 420)
            self.assertEqual(evidence["n_cache_tokens"], 120)
            self.assertEqual(evidence["n_output_tokens"], 70)
            self.assertEqual(evidence["reasoning_tokens"], 90)
            self.assertEqual(evidence["cost_usd"], 0.10)
            self.assertEqual(evidence["peak_context_tokens"], 270)
            self.assertEqual(evidence["n_agent_steps"], 2)
            self.assertEqual(evidence["session_id"], "session-1")
            self.assertEqual(evidence["api"], "anthropic-messages")
            self.assertEqual(evidence["thinking_level"], "max")

            rows[2]["thinkingLevel"] = "high"
            session.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "thinking level"):
                parse_session_evidence(session)

            rows[2]["thinkingLevel"] = "max"
            rows[3]["message"]["stopReason"] = "error"
            session.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "assistant provider error"):
                parse_session_evidence(session)

            session.write_text("not-json\n", encoding="utf-8")
            with self.assertRaises(json.JSONDecodeError):
                parse_session_evidence(session)


if __name__ == "__main__":
    unittest.main()
