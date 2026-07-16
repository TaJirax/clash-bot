"""Fast semantic index over the downloaded Supercell Fan Kit library.

The raw library is intentionally not decoded at bot startup: it is more than
17 GB and most of it is character/promotional art.  The downloader manifest is
the index.  This module exposes the Home Village building assets and their
levels in milliseconds, so live perception can attach semantic coverage to a
visual detection without walking thousands of files every frame.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from .paths import FANKIT_DIR


_NON_WORD = re.compile(r"[^a-z0-9]+")
_LEVEL = re.compile(r"(?:level|lvl)[ _-]?(\d+)", re.IGNORECASE)


def normalize_category(value: str) -> str:
    return _NON_WORD.sub("_", value.lower()).strip("_")


@dataclass(frozen=True)
class FanKitAsset:
    asset_id: str
    category: str
    level: int | None
    path: Path
    title: str


class FanKitIndex:
    """Read the existing manifest once; never scan/decode 17 GB at runtime."""

    def __init__(self, root: str | Path = FANKIT_DIR):
        self.root = Path(root)
        manifest_path = self.root / "manifest.json"
        with manifest_path.open("r", encoding="utf-8") as handle:
            manifest = json.load(handle)
        self._by_category: dict[str, list[FanKitAsset]] = {}
        for asset_id, record in manifest.get("assets", {}).items():
            relative = record.get("file")
            if not relative or not record.get("is_image", False):
                continue
            parts = Path(relative).parts
            try:
                building_index = parts.index("Buildings")
            except ValueError:
                continue
            if building_index + 1 >= len(parts):
                continue
            filename = parts[-1]
            # Builder Base and Clan Capital art can share category names. The
            # filename prefix is the reliable village discriminator.
            if "_HV_" not in filename and not filename.startswith("HV_"):
                continue
            category = normalize_category(parts[building_index + 1])
            level_match = _LEVEL.search("/".join(parts[building_index + 2:]))
            item = FanKitAsset(
                asset_id=str(asset_id),
                category=category,
                level=int(level_match.group(1)) if level_match else None,
                path=self.root / relative,
                title=str(record.get("title") or Path(filename).stem),
            )
            if item.path.is_file():
                self._by_category.setdefault(category, []).append(item)
        for assets in self._by_category.values():
            assets.sort(key=lambda item: (item.level is None, item.level or 0, item.title))

    @property
    def categories(self) -> tuple[str, ...]:
        return tuple(sorted(self._by_category))

    @property
    def asset_count(self) -> int:
        return sum(len(items) for items in self._by_category.values())

    def assets_for(self, category: str) -> tuple[FanKitAsset, ...]:
        return tuple(self._by_category.get(normalize_category(category), ()))

    def levels_for(self, category: str) -> tuple[int, ...]:
        return tuple(sorted({
            item.level for item in self.assets_for(category) if item.level is not None
        }))

