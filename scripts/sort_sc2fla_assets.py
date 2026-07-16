"""Create a non-duplicating semantic index over SC2FLA output.

Named XFL exports are sorted by game role, unit/building name, and level.
Numeric PNG components remain grouped by their source family because they have
no safe standalone semantic label.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

try:
    from scripts.batch_extract_sc2fla import group_for
except ModuleNotFoundError:  # direct execution: python scripts/sort_sc2fla_assets.py
    from batch_extract_sc2fla import group_for


LEVEL = re.compile(r"(?:^|_)(?:level|lvl)(\d+)(?:_|$)", re.IGNORECASE)
INLINE_LEVEL = re.compile(
    r"^(.*?)(\d+)(?=_(?:attack|cheer|idle|run|walk|die|spawn|shoot|hit|ability|upgrade|icon|base|const|shadow))",
    re.IGNORECASE,
)
STATE_SUFFIXES = {"icon", "upgrade", "upg", "base", "const", "idle", "shadow"}


def semantic_name(label: str, project: str) -> tuple[str, int | None]:
    text = label.lower()
    for prefix in ("chr_", "hero_", "pet_", "info_"):
        if text.startswith(prefix):
            text = text[len(prefix):]
            break
    match = LEVEL.search(text)
    if match:
        level = int(match.group(1))
        text = LEVEL.sub("_", text)
    else:
        inline = INLINE_LEVEL.search(text)
        level = int(inline.group(2)) if inline else None
        if inline:
            text = text[:inline.start(2)] + text[inline.end(2):]
    text = text.strip("_")
    parts = [part for part in text.split("_") if part and part not in STATE_SUFFIXES]
    return ("_".join(parts) or project.lower(), level)


def family_name(project: str) -> str:
    text = project.lower()
    for prefix in ("chr_", "hero_", "pet_", "info_"):
        if text.startswith(prefix):
            return text[len(prefix):]
    return text


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def sort_records(records: list[dict]) -> tuple[dict, dict[str, list[dict]]]:
    groups: dict[str, list[dict]] = defaultdict(list)
    components: dict[str, list[dict]] = defaultdict(list)
    for record in records:
        project = str(record.get("project", "other"))
        if record.get("role") == "vector_composition":
            category = group_for(project + ".sc")
            name, level = semantic_name(str(record.get("label", "")), project)
            item = {
                **record,
                "category": category,
                "family": family_name(project),
                "name": name,
                "level": level,
            }
            groups[category].append(item)
        elif record.get("role") == "resource_sprite":
            components[project].append(record)
    for values in groups.values():
        values.sort(key=lambda item: (item["name"], item["level"] is None, item["level"] or 0, item["label"]))
    for values in components.values():
        values.sort(key=lambda item: item["label"])
    return dict(groups), dict(components)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=Path("assets/derived_cache/sc2fla_index/manifest.json"))
    parser.add_argument("--output", type=Path, default=Path("assets/derived_cache/sorted_sc"))
    args = parser.parse_args()
    with args.input.open("r", encoding="utf-8") as handle:
        source = json.load(handle)
    groups, components = sort_records(source.get("records", []))
    for category, records in groups.items():
        by_name: dict[tuple[str, int | None], list[dict]] = defaultdict(list)
        for record in records:
            by_name[(record["family"], record["level"])].append(record)
        for (family, level), items in by_name.items():
            level_folder = f"level_{level}" if level is not None else "unlevelled"
            write_json(args.output / "exports" / category / family / level_folder / "manifest.json", {
                "category": category,
                "family": family,
                "level": level,
                "records": items,
            })
    for project, records in components.items():
        write_json(args.output / "components" / project / "manifest.json", {
            "project": project, "records": records,
        })
    summary = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_manifest": str(args.input),
        "semantic_exports": sum(len(records) for records in groups.values()),
        "components": sum(len(records) for records in components.values()),
        "export_categories": dict(sorted((key, len(value)) for key, value in groups.items())),
        "named_assets": dict(sorted((key, len({item['name'] for item in value})) for key, value in groups.items())),
        "component_projects": dict(sorted((key, len(value)) for key, value in components.items())),
    }
    write_json(args.output / "manifest.json", summary)
    semantic_records = [item for records in groups.values() for item in records]
    write_json(args.output / "semantic_index.json", {
        "schema_version": 1,
        "generated_at": summary["generated_at"],
        "records": semantic_records,
    })
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
