"""Extract selected asset formats from APK/ZIP packages into derived cache."""

from __future__ import annotations

import argparse
import hashlib
import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath


EXTENSIONS = {
    ".sc", ".sctx", ".glb", ".gltf", ".bin", ".json", ".csv",
    ".meta", ".si", ".toml", ".png", ".jpg", ".jpeg", ".webp",
    ".ktx", ".astc",
}


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def digest_file(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def safe_member(name: str) -> Path | None:
    source = PurePosixPath(name)
    if source.is_absolute() or ".." in source.parts:
        return None
    return Path(*source.parts)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("packages", nargs="+", type=Path)
    parser.add_argument("--output", type=Path, default=Path("assets/derived_cache/game_package"))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    records = []
    for package in args.packages:
        package_id = digest_file(package)[:16]
        package_root = args.output / package_id
        with zipfile.ZipFile(package) as archive:
            for info in archive.infolist():
                relative = safe_member(info.filename)
                if relative is None or info.is_dir() or relative.suffix.lower() not in EXTENSIONS:
                    continue
                data = archive.read(info)
                target = package_root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
                records.append({
                    "package": str(package),
                    "member": info.filename,
                    "output": target.relative_to(args.output).as_posix(),
                    "bytes": len(data),
                    "sha256": digest(data),
                })
    manifest = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "files": records,
    }
    (args.output / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    print(f"extracted {len(records)} files -> {args.output}")


if __name__ == "__main__":
    main()
