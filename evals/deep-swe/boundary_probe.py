from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pier.agents.installed.base import NonZeroAgentExitCodeError
from pier.environments.base import BaseEnvironment
from pier.models.agent.context import AgentContext

from pi_agent import (
    AGENT_USER,
    MODEL_ID,
    MODEL_PROVIDER,
    PiOckleAgent,
)


class FullPostRunProbeAgent(PiOckleAgent):
    def __init__(
        self,
        probe_delete_test: bool | str = False,
        probe_oversized_secret_log: bool | str = False,
        probe_core_worktree_decoy: bool | str = False,
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
if curl -sS -o /dev/null --max-time 20 https://la.mapleluv.icu/v1/models; then provider_reachable=true; fi
if ! curl -fsS -o /dev/null --max-time 20 https://github.com/datacurve-ai/deep-swe; then public_proxy_blocked=true; fi
if ! env -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY -u http_proxy -u https_proxy -u all_proxy curl -fsS -o /dev/null --max-time 10 https://deepswe.datacurve.ai/data/v1.1; then public_direct_blocked=true; fi
printf '{"uid":%s,"user":"%s","appWrite":%s,"optWriteBlocked":%s,"oracleHidden":%s,"providerReachable":%s,"publicProxyBlocked":%s,"publicDirectBlocked":%s}\n' "$uid" "$user" "$app_write" "$opt_write_blocked" "$oracle_hidden" "$provider_reachable" "$public_proxy_blocked" "$public_direct_blocked" > /logs/agent/boundary-probe.json
"""
        result = await environment.exec(
            command=script,
            env=environment.agent_process_env({}),
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
