from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import tarfile
import tempfile
import tomllib
from pathlib import Path, PurePosixPath
from typing import Any

EXPECTED_BENCHMARK_COMMIT = "435ee89ec2f2e2289f33b0da4f992f0b7b7266b9"
EXPECTED_SOURCE_ARCHIVE_SHA256 = "34c6fabd3dad1770d753829378a81c3d8bb658ff255de9f01f3606e213cd2b46"
EXPECTED_PIER_COMMIT = "0daf53d3599e58c4506cf0bcff5e12c77dc282d2"
EXPECTED_QUOTAS = {
    "typescript": 3,
    "javascript": 2,
    "go": 3,
    "python": 3,
    "rust": 1,
}
SELECTION_PREFIX = "Ockle DeepSWE v1.1 pilot 1\n"


def validate_pilot_manifest(manifest: dict[str, Any]) -> dict[str, int]:
    if manifest.get("schemaVersion") != 1:
        raise ValueError("unsupported pilot manifest schema")
    benchmark = manifest.get("benchmark", {})
    if benchmark.get("commit") != EXPECTED_BENCHMARK_COMMIT:
        raise ValueError("unexpected DeepSWE commit")
    if benchmark.get("sourceArchiveSha256") != EXPECTED_SOURCE_ARCHIVE_SHA256:
        raise ValueError("unexpected DeepSWE source archive digest")
    if manifest.get("runner", {}).get("commit") != EXPECTED_PIER_COMMIT:
        raise ValueError("unexpected Pier commit")
    selection = manifest.get("selection", {})
    if selection.get("seed") != SELECTION_PREFIX.rstrip("\n"):
        raise ValueError("unexpected selection seed")
    if selection.get("languageQuotas") != EXPECTED_QUOTAS:
        raise ValueError("unexpected language quotas")
    execution = manifest.get("execution", {})
    for key in (
        "piTarballSha256",
        "piShrinkwrapSha256",
        "nodeArchiveSha256",
        "guardBundleSha256",
    ):
        if not re.fullmatch(r"[0-9a-f]{64}", str(execution.get(key))):
            raise ValueError(f"invalid execution digest: {key}")

    tasks = manifest.get("tasks")
    if not isinstance(tasks, list) or len(tasks) != 12:
        raise ValueError("pilot must contain exactly 12 tasks")
    ids = [task.get("id") for task in tasks]
    if len(set(ids)) != 12 or any(not isinstance(task_id, str) for task_id in ids):
        raise ValueError("pilot task IDs must be unique strings")

    counts = {language: 0 for language in EXPECTED_QUOTAS}
    subjects = 0
    guard_tasks = 0
    for task in tasks:
        task_id = task["id"]
        language = task.get("language")
        if language not in counts:
            raise ValueError(f"unsupported language for {task_id}")
        counts[language] += 1
        expected_rank = hashlib.sha256(
            f"{SELECTION_PREFIX}{task_id}".encode("utf-8")
        ).hexdigest()
        if task.get("selectionRank") != expected_rank:
            raise ValueError(f"selection rank mismatch for {task_id}")
        if not re.fullmatch(r"[0-9a-f]{40}", str(task.get("baseCommit"))):
            raise ValueError(f"invalid base commit for {task_id}")
        if not re.fullmatch(r"[0-9a-f]{64}", str(task.get("taskChecksum"))):
            raise ValueError(f"invalid task checksum for {task_id}")
        if not re.fullmatch(r"[0-9a-f]{64}", str(task.get("preparedTaskChecksum"))):
            raise ValueError(f"invalid prepared task checksum for {task_id}")
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", str(task.get("imageDigest"))):
            raise ValueError(f"invalid image digest for {task_id}")
        arms = task.get("arms")
        expected_arms = (
            ["bare", "inner", "full"]
            if language in {"javascript", "typescript"}
            else ["bare", "inner"]
        )
        if arms != expected_arms:
            raise ValueError(f"arm mismatch for {task_id}")
        subjects += len(arms)
        guard_tasks += int("full" in arms)

    if counts != EXPECTED_QUOTAS:
        raise ValueError("manifest language counts do not match quotas")
    serialized = json.dumps(manifest, sort_keys=True).lower()
    for forbidden in ("reference_patch", "pass@", '"reward"', '"solution"'):
        if forbidden in serialized:
            raise ValueError(f"public outcome field is forbidden: {forbidden}")
    return {"tasks": len(tasks), "subjects": subjects, "guardTasks": guard_tasks}


def _insert_table_setting(task_toml: str, table: str, setting: str) -> str:
    header = f"[{table}]"
    pattern = re.compile(rf"(?m)^{re.escape(header)}[ \t]*$")
    matches = list(pattern.finditer(task_toml))
    if len(matches) != 1:
        raise ValueError(f"expected exactly one {header} table")
    insertion = matches[0].end()
    return task_toml[:insertion] + f"\n{setting}" + task_toml[insertion:]


def harden_task_config(task_toml: str, base_commit: str) -> str:
    if not re.fullmatch(r"[0-9a-f]{40}", base_commit):
        raise ValueError("invalid base commit")
    parsed = tomllib.loads(task_toml)
    if parsed.get("metadata", {}).get("base_commit_hash") not in (None, base_commit):
        raise ValueError("task metadata base commit mismatch")
    if "user" in parsed.get("agent", {}):
        raise ValueError("agent user is already declared")
    if "allow_internet" in parsed.get("environment", {}):
        raise ValueError("agent internet policy is already declared")
    verifier_environment = parsed.get("verifier", {}).get("environment", {})
    if "allow_internet" in verifier_environment:
        raise ValueError("verifier internet policy is already declared")

    expected_collect = (
        "cd /app && mkdir -p /logs/artifacts && "
        "git config --global --add safe.directory /app && "
        f"git diff --binary {base_commit} HEAD > /logs/artifacts/model.patch"
    )
    collect = parsed.get("verifier", {}).get("collect")
    if not isinstance(collect, list) or len(collect) != 1:
        raise ValueError("expected exactly one verifier collect command")
    if collect[0].get("command") != expected_collect:
        raise ValueError("unexpected verifier collect command")
    hardened_collect = (
        "mkdir -p /logs/artifacts && cd /app && "
        "env GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1 "
        "GIT_ATTR_NOSYSTEM=1 GIT_NO_REPLACE_OBJECTS=1 "
        "git -c safe.directory=/app -c diff.external= -c core.pager=cat "
        f"diff --no-ext-diff --no-textconv --no-renames --binary {base_commit} HEAD -- . "
        "> /logs/artifacts/model.patch"
    )
    quoted_expected = f"command = {json.dumps(expected_collect)}"
    quoted_hardened = f"command = {json.dumps(hardened_collect)}"
    if task_toml.count(quoted_expected) != 1:
        raise ValueError("collect command text is not uniquely replaceable")
    hardened = task_toml.replace(quoted_expected, quoted_hardened)
    hardened = _insert_table_setting(hardened, "agent", 'user = "ockle"')
    hardened = _insert_table_setting(hardened, "environment", "allow_internet = false")
    hardened = _insert_table_setting(
        hardened, "verifier.environment", "allow_internet = false"
    )
    effective = tomllib.loads(hardened)
    if effective["agent"]["user"] != "ockle":
        raise ValueError("agent user hardening failed")
    if effective["environment"]["allow_internet"] is not False:
        raise ValueError("agent network hardening failed")
    if effective["verifier"]["environment"]["allow_internet"] is not False:
        raise ValueError("verifier network hardening failed")
    return hardened


def pin_image_reference(task_toml: str, image: str, digest: str) -> str:
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
        raise ValueError("invalid image digest")
    pattern = re.compile(
        rf'(?m)^docker_image[ \t]*=[ \t]*"{re.escape(image)}"[ \t]*$'
    )
    matches = list(pattern.finditer(task_toml))
    if len(matches) != 1:
        raise ValueError("expected exactly one matching docker_image line")
    return pattern.sub(f'docker_image = "{image}@{digest}"', task_toml)


def _verify_selection(source_tasks: Path, manifest: dict[str, Any]) -> dict[str, int]:
    seed = manifest["selection"]["seed"] + "\n"
    by_language: dict[str, list[str]] = {language: [] for language in EXPECTED_QUOTAS}
    for task_dir in sorted(path for path in source_tasks.iterdir() if path.is_dir()):
        task_toml = task_dir / "task.toml"
        if not task_toml.is_file():
            continue
        metadata = tomllib.loads(task_toml.read_text(encoding="utf-8"))["metadata"]
        language = metadata["language"].lower()
        if language in by_language:
            by_language[language].append(metadata["task_id"])

    for language, quota in EXPECTED_QUOTAS.items():
        ranked = sorted(
            by_language[language],
            key=lambda task_id: hashlib.sha256(
                f"{seed}{task_id}".encode("utf-8")
            ).hexdigest(),
        )
        selected = {
            task["id"] for task in manifest["tasks"] if task["language"] == language
        }
        if selected != set(ranked[:quota]):
            raise ValueError(f"selection drift for {language}")
    return {language: len(ids) for language, ids in by_language.items()}


def _reject_symlinks(root: Path) -> None:
    symlinks = [path for path in root.rglob("*") if path.is_symlink()]
    if symlinks:
        relative = ", ".join(str(path.relative_to(root)) for path in symlinks[:5])
        raise ValueError(f"task package contains symlinks: {relative}")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def extract_source_archive(source_archive: Path, destination: Path) -> Path:
    source_archive = source_archive.resolve()
    if _sha256_file(source_archive) != EXPECTED_SOURCE_ARCHIVE_SHA256:
        raise ValueError("DeepSWE source archive digest mismatch")
    destination.mkdir(parents=True, exist_ok=False)
    expected_root = f"deep-swe-{EXPECTED_BENCHMARK_COMMIT}"
    names: set[str] = set()
    total_size = 0
    with tarfile.open(source_archive, mode="r:gz") as archive:
        members = archive.getmembers()
        if not members:
            raise ValueError("DeepSWE source archive is empty")
        safe_members: list[tarfile.TarInfo] = []
        skipped_readme = f"{expected_root}/tasks/README.md"
        for member in members:
            path = PurePosixPath(member.name)
            if path.is_absolute() or ".." in path.parts:
                raise ValueError("DeepSWE source archive contains an unsafe path")
            if not path.parts or path.parts[0] != expected_root:
                raise ValueError("DeepSWE source archive has an unexpected root")
            if member.name in names:
                raise ValueError("DeepSWE source archive contains duplicate paths")
            names.add(member.name)
            if member.name == skipped_readme and member.issym() and member.linkname == "../README.md":
                continue
            if not (member.isdir() or member.isfile()):
                raise ValueError("DeepSWE source archive contains a non-regular entry")
            total_size += member.size
            if total_size > 512 * 1024 * 1024:
                raise ValueError("DeepSWE source archive exceeds the extraction budget")
            safe_members.append(member)
        archive.extractall(destination, members=safe_members, filter="data")
    tasks = destination / expected_root / "tasks"
    if not tasks.is_dir():
        raise ValueError("DeepSWE source archive has no tasks directory")
    return tasks


def materialize_pilot(
    source_archive: Path,
    output_root: Path,
    manifest_path: Path,
) -> dict[str, Any]:
    from pier.models.task.task import Task

    manifest_bytes = manifest_path.read_bytes()
    manifest = json.loads(manifest_bytes)
    validate_pilot_manifest(manifest)
    output_root = output_root.resolve()
    if output_root.exists():
        raise FileExistsError(f"output already exists: {output_root}")

    output_root.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(
        tempfile.mkdtemp(prefix=f".{output_root.name}-", dir=output_root.parent)
    )
    source_workspace = Path(tempfile.mkdtemp(prefix="ockle-deepswe-source-"))
    records: list[dict[str, str]] = []
    try:
        source_tasks = extract_source_archive(source_archive, source_workspace / "source")
        selection_candidates = _verify_selection(source_tasks, manifest)
        prepared_tasks = temporary / "tasks"
        prepared_tasks.mkdir()
        for entry in manifest["tasks"]:
            task_id = entry["id"]
            source = source_tasks / task_id
            if not source.is_dir():
                raise FileNotFoundError(f"missing source task: {task_id}")
            _reject_symlinks(source)
            source_checksum = Task(task_dir=source).checksum
            if source_checksum != entry["taskChecksum"]:
                raise ValueError(f"source task checksum mismatch for {task_id}")

            task_config_path = source / "task.toml"
            with task_config_path.open("rb") as stream:
                task_config = tomllib.load(stream)
            metadata = task_config.get("metadata", {})
            environment = task_config.get("environment", {})
            checks = {
                "task_id": task_id,
                "language": entry["language"],
                "base_commit_hash": entry["baseCommit"],
            }
            for key, expected in checks.items():
                if metadata.get(key) != expected:
                    raise ValueError(f"{key} mismatch for {task_id}")
            if environment.get("docker_image") != entry["image"]:
                raise ValueError(f"image tag mismatch for {task_id}")

            destination = prepared_tasks / task_id
            shutil.copytree(source, destination)
            destination_toml = destination / "task.toml"
            pinned = pin_image_reference(
                destination_toml.read_text(encoding="utf-8"),
                entry["image"],
                entry["imageDigest"],
            )
            hardened = harden_task_config(pinned, entry["baseCommit"])
            destination_toml.write_text(hardened, encoding="utf-8", newline="\n")
            prepared_checksum = Task(task_dir=destination).checksum
            if prepared_checksum != entry["preparedTaskChecksum"]:
                raise ValueError(f"prepared task checksum mismatch for {task_id}")
            records.append(
                {
                    "id": task_id,
                    "sourceTaskChecksum": source_checksum,
                    "preparedTaskChecksum": prepared_checksum,
                    "image": f'{entry["image"]}@{entry["imageDigest"]}',
                }
            )

        prepared = {
            "schemaVersion": 1,
            "manifestSha256": hashlib.sha256(manifest_bytes).hexdigest(),
            "materializerSha256": _sha256_file(Path(__file__).resolve()),
            "benchmarkCommit": EXPECTED_BENCHMARK_COMMIT,
            "sourceArchiveSha256": EXPECTED_SOURCE_ARCHIVE_SHA256,
            "selectionCandidates": selection_candidates,
            "tasks": records,
        }
        (temporary / "prepared.json").write_text(
            json.dumps(prepared, indent=2) + "\n", encoding="utf-8", newline="\n"
        )
        shutil.copy2(manifest_path, temporary / "pilot-v1.json")
        temporary.replace(output_root)
        return prepared
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    finally:
        shutil.rmtree(source_workspace, ignore_errors=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-archive", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    manifest = Path(__file__).with_name("pilot-v1.json")
    prepared = materialize_pilot(args.source_archive, args.output, manifest)
    print(json.dumps(prepared, indent=2))


if __name__ == "__main__":
    main()
