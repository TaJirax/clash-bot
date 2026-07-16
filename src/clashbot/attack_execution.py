"""Guarded troop deployment with append-only evidence logs."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np

from . import vision
from .army import BattleTroopRecognizer, TroopCard
from .attack import AttackUi
from .human import HumanInput


@dataclass(frozen=True)
class DeploymentResult:
    deployed: tuple[str, ...]
    log_path: Path


class AttackLog:
    """Write replayable attack evidence without overwriting an older session."""

    def __init__(self, root: str | Path, session: str):
        safe = "".join(c for c in session if c.isalnum() or c in "_-")[:64]
        if not safe:
            raise ValueError("session must contain letters, numbers, _ or -")
        self.directory = Path(root) / safe
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / "events.jsonl"
        self.index = 0
        if self.path.exists():
            self.index = sum(1 for _ in self.path.open("r", encoding="utf-8"))

    def record(self, event: str, scene: np.ndarray, **details: object) -> None:
        self.index += 1
        image_name = f"{self.index:03d}_{event}.png"
        image_path = self.directory / image_name
        if not cv2.imwrite(str(image_path), scene):
            raise RuntimeError(f"could not save {image_path}")
        record = {
            "at": datetime.now(timezone.utc).isoformat(),
            "event": event,
            "screen": image_name,
            **details,
        }
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True) + "\n")


class LootAttackExecutor:
    """Deploy a small, recognised loot wave only on a verified battle HUD.

    This is intentionally a conservative starter: it uses the red deployment
    boundary to choose an exterior point and deploys a few recognised troops.
    The recorded evidence is the training input for later target/path scoring.
    """

    ORDER = ("giant", "goblin", "archer", "barbarian")
    WAVE_SIZE = {"giant": 2, "goblin": 3, "archer": 2, "barbarian": 2}
    AGGRESSIVE_WAVE_SIZE = {"giant": 2, "goblin": 15, "archer": 12, "barbarian": 15}

    def __init__(self, client, ui: AttackUi | None = None,
                 troops: BattleTroopRecognizer | None = None,
                 human: HumanInput | None = None, *, deployment_delay: float = 0.08):
        self.client = client
        self.ui = ui or AttackUi()
        self.troops = troops or BattleTroopRecognizer()
        self.human = human or HumanInput(client)
        self.deployment_delay = max(0.03, deployment_delay)

    @staticmethod
    def deployment_point(scene: np.ndarray) -> tuple[int, int] | None:
        """Find an exterior grass point left of the *outermost* red boundary.

        A percentile of all boundary pixels is unsafe on irregular bases: most
        pixels may be on the right/bottom edges, placing the point inside the
        polygon.  Use only the leftmost boundary segment and step outward.
        """
        hsv = cv2.cvtColor(scene, cv2.COLOR_BGR2HSV)
        # Clash's forbidden boundary is orange-red in the emulator capture,
        # not pure red.  Include that hue range as well as true red.
        red_a = cv2.inRange(hsv, (0, 110, 90), (35, 255, 255))
        red_b = cv2.inRange(hsv, (170, 110, 90), (180, 255, 255))
        red = cv2.bitwise_or(red_a, red_b)
        h, w = red.shape
        # UI icons and loot digits also contain orange.  Deployment boundaries
        # are the long straight segments, so operate only on Hough lines.
        lines = cv2.HoughLinesP(red, 1, np.pi / 180, threshold=45,
                                minLineLength=max(55, w // 16), maxLineGap=10)
        if lines is None:
            return None
        boundary = np.zeros_like(red)
        for x1, y1, x2, y2 in lines.reshape(-1, 4):
            line_length = float(np.hypot(x2 - x1, y2 - y1))
            if line_length < max(55, w // 16):
                continue
            cv2.line(boundary, (int(x1), int(y1)), (int(x2), int(y2)), 255, 7)
        if not np.any(boundary):
            return None
        # Connect small anti-aliased line gaps, then label only regions that
        # reach the frame edge.  Interior regions are never legal deployment.
        boundary = cv2.dilate(boundary, np.ones((9, 9), dtype=np.uint8))
        components, labels = cv2.connectedComponents((boundary == 0).astype(np.uint8))
        exterior = np.zeros_like(boundary, dtype=bool)
        for label in range(1, components):
            touches_edge = (np.any(labels[0] == label) or np.any(labels[-1] == label)
                            or np.any(labels[:, 0] == label) or np.any(labels[:, -1] == label))
            if touches_edge:
                exterior |= labels == label
        distance = cv2.distanceTransform((boundary == 0).astype(np.uint8), cv2.DIST_L2, 3)
        candidates: list[tuple[float, tuple[int, int]]] = []
        for py in range(int(h * 0.18), int(h * 0.62), 8):
            for px in range(int(w * 0.12), int(w * 0.80), 8):
                if not exterior[py, px] or not (28 <= distance[py, px] <= 115):
                    continue
                hue, saturation, value = hsv[py, px]
                if 25 <= int(hue) <= 95 and int(saturation) >= 35 and int(value) >= 45:
                    # Nearer legal exterior grass gives troops a shorter path;
                    # slight left preference keeps clear of the Next button.
                    candidates.append((200 - distance[py, px] - px / w, (px, py)))
        if not candidates:
            return None
        return max(candidates, key=lambda item: item[0])[1]

    def run(self, *, session: str, root: str | Path = "captures/attacks",
            aggressive: bool = False) -> DeploymentResult:
        log = AttackLog(root, session)
        before = vision.capture(self.client)
        anchor = self.ui.find_opponent_scout(before)
        cards = self.troops.find(before)
        battle_verified = anchor is not None or len(cards) >= 2
        log.record("battle_checked", before, battle_verified=battle_verified,
                   troops=[card.name for card in cards])
        if not battle_verified:
            raise RuntimeError("opponent battle HUD was not verified; no troops deployed")
        point = self.deployment_point(before)
        if point is None:
            raise RuntimeError("legal deployment boundary was not verified; no troops deployed")
        by_name = {card.name: card for card in cards}
        deployed: list[str] = []
        wave_size = self.AGGRESSIVE_WAVE_SIZE if aggressive else self.WAVE_SIZE
        for name in self.ORDER:
            card = by_name.get(name)
            if card is None:
                continue
            # Select once; Clash keeps the troop selected as each unit is
            # released.  Short individual delays avoid a single mass drop,
            # while one verification frame per group keeps deployment fast.
            self.human.tap(card.x, card.y, radius=5.0, settle=False)
            for _ in range(wave_size[name]):
                self.human.tap(*point, radius=4.0, settle=False)
                time.sleep(self.deployment_delay)
                deployed.append(name)
            after = vision.capture(self.client)
            # The scouting screen changes End Battle to Surrender when the
            # first troop lands. The troop bar remains stable in active battle.
            still_battle = (self.ui.find_opponent_scout(after) is not None
                            or len(self.troops.find(after)) >= 2)
            log.record("troop_group_tap_attempted", after, troop=name,
                       count=wave_size[name], card=(card.x, card.y), point=point,
                       battle_verified=still_battle)
            if not still_battle:
                raise RuntimeError("battle HUD changed during deployment; stopped immediately")
        if not deployed:
            raise RuntimeError("no recognised troop cards were available; no troops deployed")
        return DeploymentResult(tuple(deployed), log.path)
