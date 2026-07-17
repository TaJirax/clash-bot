"""Persistent base-layout memory built from verified building detections.

Positions are stored in camera-normalized coordinates (screen pixels divided
by the detection's camera scale) so the same building matches itself across
small zoom differences. The tracker is meant for the anchored home view the
play loop returns to between cycles; panned survey views belong to the
mapper/scanner modules instead.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from .upgrades import BuildingTarget

# Two detections of the same category within this normalized-pixel distance
# are the same physical building. Roughly half a small building's footprint
# at the 1280x720 reference resolution.
MATCH_RADIUS = 55.0
# A building reported this many times is part of the confirmed layout.
CONFIRMATIONS_FOR_STABLE = 2
# A building seen only once and then missing for this many updates was a
# transient false positive and is forgotten.
PRUNE_AFTER = 4


@dataclass
class LayoutBuilding:
    category: str
    name: str
    x: float  # camera-normalized
    y: float
    score: float
    confirmations: int
    last_seen: str
    last_update: int = 0

    @property
    def stable(self) -> bool:
        return self.confirmations >= CONFIRMATIONS_FOR_STABLE


@dataclass(frozen=True)
class LayoutUpdate:
    seen: int
    new: int
    confirmed: int
    total: int
    stable_total: int
    pruned: int = 0


class BaseLayout:
    """Merge per-frame detections into one stable map of the player's base."""

    def __init__(self, path: str | Path | None = None,
                 *, match_radius: float = MATCH_RADIUS):
        self.path = Path(path) if path is not None else None
        self.match_radius = match_radius
        self.buildings: list[LayoutBuilding] = []
        self.updates = 0
        if self.path is not None and self.path.is_file():
            data = json.loads(self.path.read_text(encoding="utf-8"))
            self.updates = int(data.get("updates", 0))
            self.buildings = [LayoutBuilding(**item)
                              for item in data.get("buildings", [])]

    def update(self, targets: Iterable[BuildingTarget]) -> LayoutUpdate:
        now = datetime.now(timezone.utc).isoformat()
        self.updates += 1
        seen = new = confirmed = 0
        matched: set[int] = set()
        targets = list(targets)
        # One shared scale per frame: per-detection scale estimates flicker
        # between the recognizer's discrete steps, which would shift each
        # building's normalized position and split it into duplicate records.
        scales = sorted(target.camera_scale for target in targets
                        if target.camera_scale > 0)
        frame_scale = scales[len(scales) // 2] if scales else 1.0
        for target in targets:
            nx, ny = target.x / frame_scale, target.y / frame_scale
            seen += 1
            nearest_index: int | None = None
            nearest_distance = self.match_radius
            for index, record in enumerate(self.buildings):
                if record.category != target.category or index in matched:
                    continue
                distance = ((record.x - nx) ** 2 + (record.y - ny) ** 2) ** 0.5
                if distance < nearest_distance:
                    nearest_distance = distance
                    nearest_index = index
            if nearest_index is None:
                self.buildings.append(LayoutBuilding(
                    category=target.category, name=target.name,
                    x=nx, y=ny, score=target.score,
                    confirmations=1, last_seen=now,
                    last_update=self.updates,
                ))
                matched.add(len(self.buildings) - 1)
                new += 1
                continue
            record = self.buildings[nearest_index]
            # Small positional drift between frames is smoothed instead of
            # trusted outright; the best-scoring level name wins.
            record.x = 0.7 * record.x + 0.3 * nx
            record.y = 0.7 * record.y + 0.3 * ny
            if target.score >= record.score:
                record.score = target.score
                record.name = target.name
            record.confirmations += 1
            record.last_seen = now
            record.last_update = self.updates
            matched.add(nearest_index)
            confirmed += 1
        before = len(self.buildings)
        self.buildings = [
            record for record in self.buildings
            if record.stable or self.updates - record.last_update < PRUNE_AFTER
        ]
        pruned = before - len(self.buildings)
        if self.path is not None:
            self.save()
        return LayoutUpdate(
            seen=seen, new=new, confirmed=confirmed,
            total=len(self.buildings),
            stable_total=sum(1 for record in self.buildings if record.stable),
            pruned=pruned,
        )

    def counts(self, *, stable_only: bool = False) -> dict[str, int]:
        out: dict[str, int] = {}
        for record in self.buildings:
            if stable_only and not record.stable:
                continue
            out[record.category] = out.get(record.category, 0) + 1
        return dict(sorted(out.items()))

    def save(self) -> None:
        if self.path is None:
            raise ValueError("this layout has no backing file")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "updates": self.updates,
            "buildings": [asdict(record) for record in self.buildings],
        }
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        temporary.replace(self.path)
