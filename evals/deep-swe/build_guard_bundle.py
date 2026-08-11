from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import tarfile
from pathlib import Path


def _source_entries(repository: Path) -> list[tuple[Path, str]]:
    roots = [
        (repository / "guard" / "package.json", "package.json"),
        (repository / "guard" / "bin", "bin"),
        (repository / "guard" / "src", "src"),
        (repository / "node_modules", "node_modules"),
    ]
    entries: list[tuple[Path, str]] = []
    for source, archive_name in roots:
        if not source.exists():
            raise FileNotFoundError(f"guard bundle input is missing: {source}")
        if source.is_symlink():
            raise ValueError(f"guard bundle input is a symlink: {source}")
        if source.is_file():
            entries.append((source, archive_name))
            continue
        for path in sorted(source.rglob("*"), key=lambda item: item.as_posix()):
            relative = path.relative_to(source).as_posix()
            target = f"{archive_name}/{relative}"
            if (
                target == "node_modules/.bin"
                or target.startswith("node_modules/.bin/")
                or target == "node_modules/.cache"
                or target.startswith("node_modules/.cache/")
            ):
                continue
            if path.is_symlink():
                if target == "node_modules/@ockle/guard":
                    continue
                raise ValueError(f"guard dependency tree contains a symlink: {target}")
            entries.append((path, target))
    return entries


def build_guard_bundle(repository: Path, output: Path) -> str:
    repository = repository.resolve()
    output = output.resolve()
    if output.exists():
        raise FileExistsError(f"guard bundle output already exists: {output}")
    entries = _source_entries(repository)
    tar_buffer = io.BytesIO()
    with tarfile.open(fileobj=tar_buffer, mode="w", format=tarfile.PAX_FORMAT) as archive:
        metadata = {
            "schemaVersion": 1,
            "sourceEntries": sum(path.is_file() for path, _ in entries),
        }
        metadata_bytes = (json.dumps(metadata, sort_keys=True) + "\n").encode("utf-8")
        info = tarfile.TarInfo("BUNDLE.json")
        info.size = len(metadata_bytes)
        info.mode = 0o644
        info.mtime = 0
        info.uid = info.gid = 0
        info.uname = info.gname = "root"
        archive.addfile(info, io.BytesIO(metadata_bytes))

        for source, target in entries:
            info = tarfile.TarInfo(target)
            info.mtime = 0
            info.uid = info.gid = 0
            info.uname = info.gname = "root"
            if source.is_dir():
                info.type = tarfile.DIRTYPE
                info.mode = 0o755
                archive.addfile(info)
                continue
            data = source.read_bytes()
            info.size = len(data)
            executable = target.startswith("bin/") or bool(source.stat().st_mode & 0o111)
            info.mode = 0o755 if executable else 0o644
            archive.addfile(info, io.BytesIO(data))

    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("xb") as destination:
        with gzip.GzipFile(
            filename="", mode="wb", fileobj=destination, mtime=0, compresslevel=9
        ) as compressed:
            compressed.write(tar_buffer.getvalue())
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    return digest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    repository = Path(__file__).resolve().parents[2]
    print(build_guard_bundle(repository, args.output))


if __name__ == "__main__":
    main()
