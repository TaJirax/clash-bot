"""Install pinned latest decoder release assets with SHA-256 provenance."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


TOOLS = (
    ("Daniil-SV/ScDowngrade", "ScDowngrade.exe"),
    ("Daniil-SV/SCTX-Converter", "SctxConverter.exe"),
)


def request_json(url: str) -> dict:
    request = urllib.request.Request(url, headers={"User-Agent": "clash-bot-asset-cache"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def download(url: str, destination: Path) -> str:
    if not url.startswith("https://github.com/"):
        raise ValueError(f"unexpected release host: {url}")
    digest = hashlib.sha256()
    request = urllib.request.Request(url, headers={"User-Agent": "clash-bot-asset-cache"})
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    with urllib.request.urlopen(request, timeout=60) as response, temporary.open("wb") as output:
        while chunk := response.read(1024 * 1024):
            digest.update(chunk)
            output.write(chunk)
    temporary.replace(destination)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path(".tools/sc2-decoder/bin"))
    parser.add_argument("--sc2fla-root", type=Path,
                        default=Path("assets/source_cache/github/sc2fla_foss"))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    records = []
    for repository, filename in TOOLS:
        release = request_json(f"https://api.github.com/repos/{repository}/releases/latest")
        matches = [asset for asset in release.get("assets", []) if asset.get("name") == filename]
        if len(matches) != 1:
            raise RuntimeError(f"expected one {filename} release asset in {repository}")
        asset = matches[0]
        destination = args.output / filename
        sha256 = download(asset["browser_download_url"], destination)
        records.append({
            "repository": repository,
            "tag": release.get("tag_name"),
            "published_at": release.get("published_at"),
            "asset": filename,
            "url": asset["browser_download_url"],
            "bytes": destination.stat().st_size,
            "sha256": sha256,
        })
        print(f"installed {repository} {release.get('tag_name')} {filename} ({sha256[:12]})")

    sc2fla_lib = args.sc2fla_root / "lib"
    if sc2fla_lib.is_dir():
        for filename in ("ScDowngrade.exe", "SctxConverter.exe"):
            shutil.copy2(args.output / filename, sc2fla_lib / filename)
    manifest = {
        "schema_version": 1,
        "installed_at": datetime.now(timezone.utc).isoformat(),
        "tools": records,
    }
    (args.output / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
