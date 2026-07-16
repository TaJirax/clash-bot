"""Index read-only SC2FLA output while preserving semantic boundaries.

PNG resources are component bitmaps. Export XML files are named building/unit
compositions that reference those components. They are intentionally recorded
as different roles so a numeric resource name never becomes a class label.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


LEVEL = re.compile(r"(?:level|lvl)[ _.-]?(\d+)", re.IGNORECASE)


def hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def workspace_path(path: Path, repository_root: Path) -> str:
    try:
        return path.resolve().relative_to(repository_root.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def record(path: Path, project: str, role: str, root: Path) -> dict:
    label = path.stem if role == "vector_composition" else f"{project}/resource_{path.stem}"
    match = LEVEL.search(label)
    return {
        "project": project,
        "role": role,
        "label": label,
        "level": int(match.group(1)) if match else None,
        "output": workspace_path(path, root),
        "bytes": path.stat().st_size,
        "sha256": hash_file(path),
    }


def build_index(staging: Path, repository_root: Path) -> list[dict]:
    records: list[dict] = []
    libraries = sorted(path for path in staging.rglob("LIBRARY") if path.is_dir())
    for library in libraries:
        project_root = library.parent
        project = project_root.name
        resources = library / "resources"
        exports = library / "exports"
        if resources.is_dir():
            for path in sorted(resources.rglob("*.png")):
                records.append(record(path, project, "resource_sprite", repository_root))
        if exports.is_dir():
            for path in sorted(exports.rglob("*.xml")):
                records.append(record(path, project, "vector_composition", repository_root))
    return records


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--staging", type=Path,
                        default=Path("assets/derived_cache/sc2fla_staging"))
    parser.add_argument("--output", type=Path,
                        default=Path("assets/derived_cache/sc2fla_index/manifest.json"))
    parser.add_argument("--repository-root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    if not args.staging.is_dir():
        raise SystemExit(f"SC2FLA staging directory does not exist: {args.staging}")

    records = build_index(args.staging, args.repository_root)
    roles = Counter(item["role"] for item in records)
    projects = Counter(item["project"] for item in records)
    manifest = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "staging": workspace_path(args.staging, args.repository_root),
        "summary": {
            "records": len(records),
            "roles": dict(sorted(roles.items())),
            "projects": dict(sorted(projects.items())),
        },
        "records": records,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + ".tmp")
    temporary.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    temporary.replace(args.output)
    print(json.dumps(manifest["summary"], indent=2))
    print(f"manifest: {args.output}")


if __name__ == "__main__":
    main()
