from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pier.agents.installed.base import NonZeroAgentExitCodeError
from pier.environments.base import BaseEnvironment
from pier.models.agent.context import AgentContext

from pi_agent import (
    AGENT_USER,
    MODEL_API,
    MODEL_BASE_URL,
    MODEL_ID,
    MODEL_PROVIDER,
    PiOckleAgent,
)


class ContinuationProtocolProbeAgent(PiOckleAgent):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.probe_turn = 0
        super().__init__(*args, **kwargs)

    async def _run_pi_turn(
        self,
        *,
        environment: BaseEnvironment,
        process_env: dict[str, str],
        args: list[str],
        event_path: str,
        stderr_path: str,
    ) -> Any:
        del process_env, event_path, stderr_path
        if self.condition != "bare":
            raise ValueError("continuation protocol probe requires condition=bare")
        session_path = self.logs_dir / "sessions" / "continuation-probe.jsonl"
        session_path.parent.mkdir(parents=True, exist_ok=True)
        if self.probe_turn == 0:
            if "--continue" in args:
                raise NonZeroAgentExitCodeError(
                    "initial continuation probe turn unexpectedly resumed a session"
                )
            rows = [
                {"type": "session", "id": "continuation-probe", "cwd": "/app"},
                {
                    "type": "model_change",
                    "provider": MODEL_PROVIDER,
                    "modelId": MODEL_ID,
                },
                {"type": "thinking_level_change", "thinkingLevel": "max"},
                {
                    "type": "message",
                    "message": {
                        "role": "user",
                        "content": "controlled initial probe turn",
                    },
                },
                {
                    "type": "message",
                    "message": {
                        "role": "assistant",
                        "provider": MODEL_PROVIDER,
                        "model": MODEL_ID,
                        "api": MODEL_API,
                        "content": [{"type": "text", "text": "transition"}],
                        "stopReason": "stop",
                        "usage": {
                            "input": 3,
                            "cacheRead": 0,
                            "cacheWrite": 0,
                            "output": 2,
                            "reasoning": 1,
                            "cost": {"total": 0},
                        },
                    },
                },
            ]
            session_path.write_text(
                "".join(json.dumps(row) + "\n" for row in rows),
                encoding="utf-8",
                newline="\n",
            )
            self.probe_turn += 1
            return await environment.exec(
                command=(
                    "cd /app && test -f package.json && "
                    "printf '\\n' >> package.json && git add package.json && "
                    "git show HEAD:package.json > package.json"
                )
            )
        if self.probe_turn == 1:
            if args.count("--continue") != 1:
                raise NonZeroAgentExitCodeError(
                    "continuation probe did not receive exactly one --continue"
                )
            with session_path.open("a", encoding="utf-8", newline="\n") as stream:
                for row in (
                    {
                        "type": "message",
                        "message": {
                            "role": "user",
                            "content": "controlled continuation probe turn",
                        },
                    },
                    {
                        "type": "message",
                        "message": {
                            "role": "assistant",
                            "provider": MODEL_PROVIDER,
                            "model": MODEL_ID,
                            "api": MODEL_API,
                            "content": [{"type": "text", "text": "delivered"}],
                            "stopReason": "stop",
                            "usage": {
                                "input": 4,
                                "cacheRead": 1,
                                "cacheWrite": 0,
                                "output": 2,
                                "reasoning": 1,
                                "cost": {"total": 0},
                            },
                        },
                    },
                ):
                    stream.write(json.dumps(row) + "\n")
            self.probe_turn += 1
            return await environment.exec(
                command=(
                    "cd /app && "
                    "git -c user.name=Ockle-Probe -c user.email=probe@ockle.invalid "
                    "commit -m continuation-probe && git restore --worktree package.json"
                )
            )
        raise NonZeroAgentExitCodeError("continuation probe exceeded one recovery turn")


class FullPostRunProbeAgent(PiOckleAgent):
    def __init__(
        self,
        probe_delete_test: bool | str = False,
        probe_oversized_secret_log: bool | str = False,
        probe_core_worktree_decoy: bool | str = False,
        probe_staged_only: bool | str = False,
        probe_corrupt_index: bool | str = False,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        self.probe_delete_test = str(probe_delete_test).lower() == "true"
        self.probe_oversized_secret_log = (
            str(probe_oversized_secret_log).lower() == "true"
        )
        self.probe_core_worktree_decoy = (
            str(probe_core_worktree_decoy).lower() == "true"
        )
        self.probe_staged_only = str(probe_staged_only).lower() == "true"
        self.probe_corrupt_index = str(probe_corrupt_index).lower() == "true"
        super().__init__(*args, **kwargs)

    async def run(
        self,
        instruction: str,
        environment: BaseEnvironment,
        context: AgentContext,
    ) -> None:
        if self.condition != "full":
            raise ValueError("full post-run probe requires condition=full")
        if self.probe_core_worktree_decoy:
            decoy = await environment.exec(
                command=(
                    "rm -rf /tmp/ockle-clean-decoy && "
                    "mkdir /tmp/ockle-clean-decoy && "
                    "cp -a /app/. /tmp/ockle-clean-decoy/ && "
                    "git -C /app config core.worktree /tmp/ockle-clean-decoy"
                )
            )
            if decoy.return_code != 0:
                raise NonZeroAgentExitCodeError("failed to prepare core.worktree decoy")
        if self.probe_delete_test:
            mutation = await environment.exec(
                command="test -f /app/src/index.test.ts && rm /app/src/index.test.ts"
            )
            if mutation.return_code != 0:
                raise NonZeroAgentExitCodeError("failed to prepare blocked worktree probe")
        if self.probe_staged_only:
            staged = await environment.exec(
                command=(
                    "cd /app && test -f package.json && "
                    "printf '\\n' >> package.json && git add package.json && "
                    "git show HEAD:package.json > package.json"
                )
            )
            if staged.return_code != 0:
                raise NonZeroAgentExitCodeError("failed to prepare staged-only probe")
        if self.probe_corrupt_index:
            corrupt = await environment.exec(
                command="printf 'not-a-git-index\\n' > /app/.git/index"
            )
            if corrupt.return_code != 0:
                raise NonZeroAgentExitCodeError("failed to prepare corrupt-index probe")
        session_rows = [
            {"type": "session", "id": "full-post-run-probe", "cwd": "/app"},
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
                    "api": MODEL_API,
                    "usage": {
                        "input": 3,
                        "cacheRead": 2,
                        "cacheWrite": 0,
                        "output": 2,
                        "reasoning": 1,
                        "cost": {"total": 0},
                    },
                },
            },
        ]
        source = self.logs_dir / "full-post-run-probe.jsonl"
        source.write_text(
            "".join(json.dumps(row) + "\n" for row in session_rows),
            encoding="utf-8",
            newline="\n",
        )
        await environment.upload_file(
            source, "/logs/agent/sessions/full-post-run-probe.jsonl"
        )
        api_key = self._get_env("MAPLELUV_API_KEY")
        if not api_key:
            raise ValueError("MAPLELUV_API_KEY is required")
        process_env = environment.agent_process_env(
            {"MAPLELUV_API_KEY": api_key, "HOME": f"/home/{AGENT_USER}"}
        )
        if self.probe_oversized_secret_log:
            oversized = await environment.exec(
                command=(
                    "printf '%s' \"$MAPLELUV_API_KEY\" > /logs/agent/oversized-secret.bin && "
                    "truncate -s 1073741825 /logs/agent/oversized-secret.bin"
                ),
                env=process_env,
            )
            if oversized.return_code != 0:
                raise NonZeroAgentExitCodeError("failed to prepare oversized secret probe")
        errors = await self._post_run_boundary(environment, process_env)
        if errors:
            raise NonZeroAgentExitCodeError("; ".join(errors))


class BoundaryProbeAgent(PiOckleAgent):
    async def run(
        self,
        instruction: str,
        environment: BaseEnvironment,
        context: AgentContext,
    ) -> None:
        script = r"""set -u
uid=$(id -u)
user=$(id -un)
app_write=false
opt_write_blocked=false
oracle_hidden=false
provider_reachable=false
public_proxy_blocked=false
public_direct_blocked=false
if printf probe > /app/.ockle-boundary-probe; then app_write=true; rm -f /app/.ockle-boundary-probe; fi
if ! touch /opt/ockle/candidate-write 2>/dev/null; then opt_write_blocked=true; fi
if test ! -e /tests && test ! -e /solution; then oracle_hidden=true; fi
if curl -fsS -o /dev/null --max-time 20 -H "x-api-key: $MAPLELUV_API_KEY" __MODEL_BASE_URL__/v1/models; then provider_reachable=true; fi
if ! curl -fsS -o /dev/null --max-time 20 https://github.com/datacurve-ai/deep-swe; then public_proxy_blocked=true; fi
if ! env -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY -u http_proxy -u https_proxy -u all_proxy curl -fsS -o /dev/null --max-time 10 https://deepswe.datacurve.ai/data/v1.1; then public_direct_blocked=true; fi
printf '{"uid":%s,"user":"%s","appWrite":%s,"optWriteBlocked":%s,"oracleHidden":%s,"providerReachable":%s,"publicProxyBlocked":%s,"publicDirectBlocked":%s}\n' "$uid" "$user" "$app_write" "$opt_write_blocked" "$oracle_hidden" "$provider_reachable" "$public_proxy_blocked" "$public_direct_blocked" > /logs/agent/boundary-probe.json
""".replace("__MODEL_BASE_URL__", MODEL_BASE_URL)
        api_key = self._get_env("MAPLELUV_API_KEY")
        if not api_key:
            raise ValueError("MAPLELUV_API_KEY is required")
        result = await environment.exec(
            command=script,
            env=environment.agent_process_env({"MAPLELUV_API_KEY": api_key}),
            timeout_sec=90,
        )
        if result.return_code != 0:
            raise NonZeroAgentExitCodeError("boundary probe command failed")

    def populate_context_post_run(self, context: AgentContext) -> None:
        path = self.logs_dir / "boundary-probe.json"
        if not path.is_file():
            context.metadata = {"boundaryProbeValid": False, "missing": True}
            return
        result: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        expected = {
            "user": AGENT_USER,
            "appWrite": True,
            "optWriteBlocked": True,
            "oracleHidden": True,
            "providerReachable": True,
            "publicProxyBlocked": True,
            "publicDirectBlocked": True,
        }
        valid = result.get("uid") not in (None, 0) and all(
            result.get(key) == value for key, value in expected.items()
        )
        context.metadata = {"boundaryProbeValid": valid, "result": result}
