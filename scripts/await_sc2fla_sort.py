"""Wait for a resumable SC extraction group, then rebuild sorted indexes."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path


def group_pending(manifest: Path, group: str) -> int:
    if not manifest.is_file():
        return 1
    with manifest.open("r", encoding="utf-8") as handle:
        records = json.load(handle).get("records", [])
    return sum(
        record.get("group") == group and record.get("status") == "queued"
        for record in records
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--group", default="units")
    parser.add_argument("--manifest", type=Path,
                        default=Path("assets/derived_cache/sc2fla_queue/manifest.json"))
    parser.add_argument("--interval", type=float, default=20)
    parser.add_argument("--timeout", type=float, default=14400)
    args = parser.parse_args()
    deadline = time.monotonic() + args.timeout
    while pending := group_pending(args.manifest, args.group):
        if time.monotonic() >= deadline:
            raise SystemExit(f"timed out waiting for {pending} queued {args.group} families")
        print(f"waiting: {pending} {args.group} family/families queued", flush=True)
        time.sleep(args.interval)

    root = Path(__file__).resolve().parent
    for script in ("index_sc2fla_dump.py", "sort_sc2fla_assets.py"):
        result = subprocess.run([sys.executable, str(root / script)])
        if result.returncode:
            raise SystemExit(result.returncode)
    print(f"sorted {args.group} extraction output", flush=True)


if __name__ == "__main__":
    main()
