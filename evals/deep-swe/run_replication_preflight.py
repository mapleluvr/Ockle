from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any

from run_pilot import (
    _git_checkpoint,
    _require_outside_repository,
    _verify_execution_contract,
    _verify_pier_install,
    _verify_prepared_root,
    _verify_secret_file,
)
from run_replication import (
    CONDITIONS,
    EXPECTED_TOTAL_CELLS,
    build_replication_pier_command,
    extract_replication_boundary_probe_results,
    run_condition_jobs_with_scans,
    validate_replication_manifest,
    _publish_output_attestation,
)


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8", newline="\n"
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the frozen 50-cell DeepSWE replication boundary preflight."
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
        args.output, ockle_root, "replication preflight output"
    )
    if output_root.exists():
        raise FileExistsError(
            f"replication preflight output already exists: {output_root}"
        )
    output_root.mkdir(parents=True)
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(module_dir)
    environment["PYTHONUNBUFFERED"] = "1"
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment["LITELLM_LOCAL_MODEL_COST_MAP"] = "true"

    inputs = {
        "schemaVersion": 1,
        "kind": "replication-boundary-preflight",
        "ockle": checkpoint,
        "replicationManifestSha256": hashlib.sha256(replication_bytes).hexdigest(),
        "pilotManifestSha256": prepared["manifestSha256"],
        "materializerSha256": prepared["materializerSha256"],
        "sourceArchiveSha256": prepared["sourceArchiveSha256"],
        "guardBundleSha256": guard_sha,
        "pier": pier,
        "preparedRoot": str(prepared_root),
        "subjects": EXPECTED_TOTAL_CELLS,
        "globalConcurrency": replication["execution"]["globalConcurrency"],
        "conditionConcurrency": replication["execution"]["conditionConcurrency"],
        "modelCalls": 0,
    }
    _write_json(output_root / "preflight-inputs.json", inputs)
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
            agent_import_path="boundary_probe:BoundaryProbeAgent",
        )
        for condition in CONDITIONS
    }
    for condition in CONDITIONS:
        _write_json(
            output_root / f"{condition}-launch.json",
            {
                "schemaVersion": 1,
                "condition": condition,
                "agentImportPath": "boundary_probe:BoundaryProbeAgent",
                "command": commands[condition],
            },
        )
    _write_json(
        output_root / "progress.json",
        {"schemaVersion": 1, "state": "running", "expectedCells": 50},
    )

    try:
        if _git_checkpoint(ockle_root) != checkpoint:
            raise RuntimeError("Ockle runtime assets changed before preflight launch")
        completed, leaks = run_condition_jobs_with_scans(
            commands,
            cwd=Path.home(),
            environment=environment,
            output_root=output_root,
            secret=secret,
        )
        failed = {
            condition: result.returncode
            for condition, result in completed.items()
            if result.returncode != 0
        }
        if failed:
            raise RuntimeError(f"Pier preflight condition process failure: {failed}")
        if _git_checkpoint(ockle_root) != checkpoint:
            raise RuntimeError("Ockle runtime assets changed during preflight")

        probes: list[dict[str, Any]] = []
        for condition in CONDITIONS:
            probes.extend(
                extract_replication_boundary_probe_results(
                    output_root=output_root,
                    condition=condition,
                    replication=replication,
                    pilot_manifest=pilot_manifest,
                    host_credential_leaks=leaks[condition],
                    expected_tasks_root=prepared_root / "tasks",
                    expected_command=commands[condition],
                )
            )
        identities = {
            (probe["condition"], probe["taskId"], probe["repeatIndex"])
            for probe in probes
        }
        if len(probes) != EXPECTED_TOTAL_CELLS or len(identities) != EXPECTED_TOTAL_CELLS:
            raise RuntimeError("preflight did not produce the exact 50-cell matrix")
        if _git_checkpoint(ockle_root) != checkpoint:
            raise RuntimeError("Ockle runtime assets changed before preflight scoring")

        probes.sort(
            key=lambda probe: (
                CONDITIONS.index(probe["condition"]),
                probe["taskId"],
                probe["repeatIndex"],
            )
        )
        probe_bytes = (json.dumps(probes, indent=2) + "\n").encode("utf-8")
        (output_root / "probe-results.json").write_bytes(probe_bytes)
        summary = {
            "schemaVersion": 1,
            "subjects": len(probes),
            "passed": sum(probe["boundaryProbeValid"] for probe in probes),
            "byCondition": {
                condition: sum(
                    probe["condition"] == condition
                    and probe["boundaryProbeValid"]
                    for probe in probes
                )
                for condition in CONDITIONS
            },
            "modelCalls": 0,
        }
        probe_sha = hashlib.sha256(probe_bytes).hexdigest()
        summary_bytes = (json.dumps(summary, indent=2) + "\n").encode("utf-8")
        (output_root / "summary.json").write_bytes(summary_bytes)
        _write_json(
            output_root / "progress.json",
            {
                "schemaVersion": 1,
                "state": "complete",
                "expectedCells": EXPECTED_TOTAL_CELLS,
                "probeResultsSha256": probe_sha,
                "summarySha256": hashlib.sha256(summary_bytes).hexdigest(),
            },
        )
        _publish_output_attestation(
            output_root,
            kind="deep-swe-replication-v1-boundary-preflight",
            primary_name="probe-results.json",
            summary_name="summary.json",
        )
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
            {"schemaVersion": 1, "state": "failed", "expectedCells": 50},
        )
        raise
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
