from __future__ import annotations

import argparse
import hashlib
import json
import statistics
from pathlib import Path
from typing import Any

OFFICIAL_CONFIG = "mini_swe_agent_deepseek_v4_flash_max"


def summarize_official_trials(
    manifest: dict[str, Any], trial_rows: list[dict[str, Any]]
) -> dict[str, Any]:
    selected_ids = [task["id"] for task in manifest["tasks"]]
    rows = [
        row
        for row in trial_rows
        if row.get("task_name") in selected_ids
        and row.get("source") == "deep-swe"
        and row.get("eval_scope") == "full"
        and row.get("model") == "deepseek-v4-flash"
        and row.get("provider") == "deepseek"
        and row.get("harness") == "mini-swe-agent"
        and row.get("config") == OFFICIAL_CONFIG
        and row.get("reasoning_effort") == "max"
        and row.get("included_in_score") is True
    ]
    tasks: list[dict[str, Any]] = []
    for task_id in selected_ids:
        task_rows = sorted(
            (row for row in rows if row["task_name"] == task_id),
            key=lambda row: (row.get("started_at") or "", row.get("trial_name") or ""),
        )
        if len(task_rows) != 4:
            raise ValueError(f"expected four official trials for {task_id}")
        if any(row.get("errored") for row in task_rows):
            raise ValueError(f"official trial error is present for {task_id}")
        tasks.append(
            {
                "taskId": task_id,
                "passes": sum(bool(row["passed"]) for row in task_rows),
                "attempts": 4,
                "outcomes": [row["outcome"] for row in task_rows],
                "meanSteps": statistics.mean(row["n_agent_steps"] for row in task_rows),
                "meanInputTokens": statistics.mean(
                    row["n_input_tokens"] for row in task_rows
                ),
                "meanOutputTokens": statistics.mean(
                    row["n_output_tokens"] for row in task_rows
                ),
                "meanAgentSeconds": statistics.mean(
                    row["agent_duration_seconds"] for row in task_rows
                ),
            }
        )
    total_passes = sum(task["passes"] for task in tasks)
    return {
        "schemaVersion": 1,
        "role": "external difficulty calibration; not a Pi/Ockle control arm",
        "officialHarness": "mini-swe-agent",
        "officialConfig": OFFICIAL_CONFIG,
        "tasks": tasks,
        "aggregate": {
            "passes": total_passes,
            "attempts": len(tasks) * 4,
            "passRate": total_passes / (len(tasks) * 4),
            "zeroOfFourTasks": sum(task["passes"] == 0 for task in tasks),
            "mixedTasks": sum(0 < task["passes"] < 4 for task in tasks),
            "fourOfFourTasks": sum(task["passes"] == 4 for task in tasks),
            "meanSteps": statistics.mean(task["meanSteps"] for task in tasks),
            "meanOutputTokens": statistics.mean(
                task["meanOutputTokens"] for task in tasks
            ),
            "meanAgentSeconds": statistics.mean(
                task["meanAgentSeconds"] for task in tasks
            ),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trials", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(f"output already exists: {args.output}")
    manifest_path = Path(__file__).with_name("pilot-v1.json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    trial_bytes = args.trials.read_bytes()
    trial_document = json.loads(trial_bytes)
    summary = summarize_official_trials(manifest, trial_document["rows"])
    summary["source"] = {
        "url": "https://deepswe.datacurve.ai/data/v1.1",
        "snapshotSha256": hashlib.sha256(trial_bytes).hexdigest(),
        "reportedTrials": trial_document.get("n_trials"),
    }
    args.output.write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8", newline="\n"
    )


if __name__ == "__main__":
    main()
