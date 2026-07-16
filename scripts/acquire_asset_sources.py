"""Acquire approved external asset/tool repositories into an ignored cache.

The script never copies third-party code or artwork into tracked project paths.
It records the exact commit and source policy in a provenance manifest.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path


SAFE_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run(*args: str, cwd: Path | None = None) -> str:
    result = subprocess.run(
        list(args), cwd=cwd, check=True, capture_output=True, text=True,
        encoding="utf-8", errors="replace",
    )
    return result.stdout.strip()


def git(root: Path, *args: str) -> str:
    """Run Git against one exact externally-owned cache checkout."""
    return run("git", "-c", f"safe.directory={root}", *args, cwd=root)


def load_sources(config: Path) -> list[dict]:
    data = json.loads(config.read_text(encoding="utf-8"))
    if data.get("schema_version") != 1:
        raise ValueError("unsupported asset source schema")
    sources = data.get("sources")
    if not isinstance(sources, list):
        raise ValueError("sources must be a list")
    for source in sources:
        source_id = str(source.get("id", ""))
        if not SAFE_ID.fullmatch(source_id):
            raise ValueError(f"unsafe source id: {source_id!r}")
        if not str(source.get("url", "")).startswith("https://github.com/"):
            raise ValueError(f"only approved GitHub HTTPS sources are supported: {source_id}")
    return sources


def inventory(root: Path) -> tuple[int, int, list[dict]]:
    tracked = [name for name in git(root, "ls-files", "-z").split("\0") if name]
    files = [root / name for name in tracked if (root / name).is_file()]
    noteworthy = []
    for name in ("LICENSE", "LICENSE.md", "COPYING", "README.md", "requirements.txt", "package.json"):
        path = root / name
        if path.is_file():
            noteworthy.append({
                "file": name,
                "bytes": path.stat().st_size,
                "sha256": sha256(path),
            })
    return len(files), sum(path.stat().st_size for path in files), noteworthy


def acquire(source: dict, cache_root: Path, *, update: bool) -> dict:
    source_id = source["id"]
    resolved_cache = cache_root.resolve()
    destination = (resolved_cache / source_id).resolve()
    if resolved_cache not in destination.parents:
        raise ValueError("source destination escaped cache root")
    if destination.exists():
        if not (destination / ".git").is_dir():
            raise RuntimeError(f"existing source cache is not a Git checkout: {destination}")
        if update:
            git(destination, "fetch", "--depth=1", "origin")
            branch = git(destination, "symbolic-ref", "--short", "HEAD")
            git(destination, "merge", "--ff-only", f"origin/{branch}")
    else:
        destination.parent.mkdir(parents=True, exist_ok=True)
        run("git", "clone", "--depth=1", source["url"], str(destination))

    commit = git(destination, "rev-parse", "HEAD")
    file_count, byte_count, noteworthy = inventory(destination)
    return {
        **source,
        "path": destination.relative_to(Path.cwd().resolve()).as_posix(),
        "commit": commit,
        "files": file_count,
        "bytes": byte_count,
        "noteworthy_files": noteworthy,
        "acquired_at": datetime.now(timezone.utc).isoformat(),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=Path("scripts/asset_sources.json"))
    parser.add_argument("--cache-root", type=Path, default=Path("assets/source_cache/github"))
    parser.add_argument("--source", action="append", default=[])
    parser.add_argument("--update", action="store_true")
    args = parser.parse_args()

    sources = load_sources(args.config)
    selected = set(args.source)
    if selected:
        unknown = selected - {source["id"] for source in sources}
        if unknown:
            raise SystemExit(f"unknown source(s): {', '.join(sorted(unknown))}")
    chosen = [
        source for source in sources
        if source.get("enabled", False) and (not selected or source["id"] in selected)
    ]
    args.cache_root.mkdir(parents=True, exist_ok=True)
    final = args.cache_root / "acquisition_manifest.json"
    existing = {}
    if selected and final.is_file():
        previous = json.loads(final.read_text(encoding="utf-8"))
        existing = {
            record["id"]: record
            for record in previous.get("sources", [])
            if isinstance(record, dict) and "id" in record
        }
    acquired = {}
    for source in chosen:
        print(f"acquiring {source['id']}...")
        acquired[source["id"]] = acquire(source, args.cache_root, update=args.update)
    records = [
        acquired.get(source["id"], existing.get(source["id"]))
        for source in sources
        if acquired.get(source["id"], existing.get(source["id"])) is not None
    ]
    manifest = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "sources": records,
    }
    temporary = args.cache_root / "acquisition_manifest.json.tmp"
    temporary.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    temporary.replace(final)
    for record in records:
        print(f"{record['id']}: {record['files']} files, {record['bytes'] / 1048576:.1f} MiB, {record['commit'][:12]}")
    print(f"manifest: {final}")


if __name__ == "__main__":
    main()
