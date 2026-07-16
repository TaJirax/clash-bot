"""Copy the installed Clash APK and readable update assets from an emulator.

Only files owned by the installed app package are read. Nothing is modified on
the emulator. Outputs live under the ignored source cache with hashes and
remote provenance.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from clashbot.adb_client import adb_executable


DEFAULT_EXTENSIONS = {
    ".apk", ".sc", ".sctx", ".glb", ".gltf", ".bin", ".json",
    ".csv", ".meta", ".si", ".toml", ".png", ".jpg", ".jpeg",
    ".webp", ".ktx", ".astc",
}


def adb(serial: str, *args: str, check: bool = True) -> str:
    result = subprocess.run(
        [adb_executable(), "-s", serial, *args], check=check,
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    return result.stdout.strip()


def hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_relative(remote: str) -> Path:
    source = PurePosixPath(remote)
    if ".." in source.parts:
        raise ValueError(f"unsafe remote path: {remote}")
    parts = [part for part in source.parts if part not in ("/", "", ".")]
    return Path(*parts)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("serial")
    parser.add_argument("--package", default="com.supercell.clashofclans")
    parser.add_argument("--output", type=Path, default=Path("assets/source_cache/memu"))
    parser.add_argument("--extensions", default=",".join(sorted(DEFAULT_EXTENSIONS)))
    args = parser.parse_args()
    extensions = {item.strip().lower() for item in args.extensions.split(",") if item.strip()}

    paths = []
    package_output = adb(args.serial, "shell", "pm", "path", args.package)
    for line in package_output.splitlines():
        if line.startswith("package:"):
            paths.append(line.removeprefix("package:").strip())

    external_roots = (
        f"/sdcard/Android/data/{args.package}",
        f"/storage/emulated/0/Android/data/{args.package}",
    )
    for root in external_roots:
        # Android versions differ in which external-storage alias is readable.
        # A missing alias is expected and must not abort the APK capture.
        listing = adb(args.serial, "shell", "find", root, "-type", "f", check=False)
        paths.extend(line.strip() for line in listing.splitlines() if line.strip())

    unique = []
    seen = set()
    for remote in paths:
        if remote in seen:
            continue
        seen.add(remote)
        suffix = PurePosixPath(remote).suffix.lower()
        if remote.endswith(".apk") or suffix in extensions:
            unique.append(remote)

    destination = args.output / args.package
    destination.mkdir(parents=True, exist_ok=True)
    records = []
    for remote in unique:
        local = destination / safe_relative(remote)
        local.parent.mkdir(parents=True, exist_ok=True)
        print(f"pulling {remote}")
        subprocess.run(
            [adb_executable(), "-s", args.serial, "pull", remote, str(local)],
            check=True,
        )
        records.append({
            "remote": remote,
            "local": local.relative_to(args.output).as_posix(),
            "bytes": local.stat().st_size,
            "sha256": hash_file(local),
        })

    manifest = {
        "schema_version": 1,
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "serial": args.serial,
        "package": args.package,
        "files": records,
    }
    manifest_path = destination / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"pulled {len(records)} files -> {destination}")


if __name__ == "__main__":
    main()
