"""Resumably reconstruct selected installed-game SC families.

Every family is staged and processed independently, so an interrupted batch
can resume safely. The original extracted APK and decoded source cache are
never modified.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


GROUP_ORDER = ("buildings", "units", "heroes", "pets", "unit_ui", "ui", "other")


def group_for(name: str) -> str:
    stem = Path(name).stem.lower()
    if stem in {"buildings", "buildings2", "buildings_cc", "building_bases"}:
        return "buildings"
    if stem.startswith("chr_"):
        return "units"
    if stem.startswith("hero_"):
        return "heroes"
    if stem.startswith("pet_"):
        return "pets"
    if stem.startswith("info_") or stem == "unit_icons":
        return "unit_ui"
    if stem in {"buttons", "hud", "icons", "ui", "ui_bb2", "ui_cc", "shop", "matchsearch"}:
        return "ui"
    return "other"


def discover(input_root: Path) -> list[dict]:
    records = []
    for path in sorted(input_root.rglob("*.sc"), key=lambda item: item.name.lower()):
        family = path.stem
        records.append({
            "family": family,
            "group": group_for(path.name),
            "source": path.relative_to(input_root).as_posix(),
        })
    return records


def completed(stage: Path, family: str) -> bool:
    project = stage / family / family / "LIBRARY"
    return (project / "resources").is_dir() or (project / "exports").is_dir()


def load_previous(path: Path) -> dict[str, dict]:
    if not path.is_file():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        return {item["family"]: item for item in json.load(handle).get("records", [])}


def write_manifest(path: Path, records: list[dict]) -> None:
    summary = Counter(record.get("status", "queued") for record in records)
    payload = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": dict(sorted(summary.items())),
        "records": records,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=Path("assets/derived_cache/game_package"))
    parser.add_argument("--sanitized", type=Path, default=Path("assets/derived_cache/sctx_sanitized"))
    parser.add_argument("--stage", type=Path, default=Path("assets/derived_cache/sc2fla_staging"))
    parser.add_argument("--manifest", type=Path, default=Path("assets/derived_cache/sc2fla_queue/manifest.json"))
    parser.add_argument("--group", choices=GROUP_ORDER, action="append",
                        help="repeat to include several groups; default is all")
    parser.add_argument("--limit", type=int, help="maximum queued families to process")
    parser.add_argument("--run", action="store_true", help="perform extraction; without this only build queue")
    parser.add_argument("--retry-failed", action="store_true",
                        help="return failed families to the queue after their staged copy is removed")
    args = parser.parse_args()
    if args.limit is not None and args.limit < 1:
        raise SystemExit("--limit must be positive")

    previous = load_previous(args.manifest)
    records = discover(args.input)
    requested = set(args.group or GROUP_ORDER)
    for record in records:
        family = record["family"]
        if completed(args.stage, family):
            record["status"] = "complete"
        elif previous.get(family, {}).get("status") == "failed" and not args.retry_failed:
            record["status"] = "failed"
            record["error"] = previous[family].get("error", "previous failure")
        else:
            record["status"] = "queued"

    queue = [record for record in records if record["group"] in requested and record["status"] == "queued"]
    queue.sort(key=lambda record: (GROUP_ORDER.index(record["group"]), record["family"].lower()))
    if not args.run:
        write_manifest(args.manifest, records)
        print(f"queued {len(queue)} family/families; use --run to extract")
        return

    runner = Path(__file__).with_name("extract_sc2fla_project.py").resolve()
    for record in queue[:args.limit]:
        command = [
            sys.executable, str(runner), record["family"],
            "--input", str(args.input), "--sanitized", str(args.sanitized), "--output", str(args.stage),
        ]
        print(f"extracting {record['family']} ({record['group']})")
        result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace")
        if result.returncode == 0 and completed(args.stage, record["family"]):
            record["status"] = "complete"
        else:
            record["status"] = "failed"
            record["error"] = (result.stderr or result.stdout)[-2000:]
        write_manifest(args.manifest, records)
    print(json.dumps(Counter(record["status"] for record in records), indent=2))
    print(f"manifest: {args.manifest}")


if __name__ == "__main__":
    main()
