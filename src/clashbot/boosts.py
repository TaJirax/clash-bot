"""Recognise the bright-green boost aura without treating it as a building."""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np


@dataclass(frozen=True)
class BoostAura:
    x: int
    y: int
    radius: int


class BoostRecognizer:
    """Detect lime boost-glow components; returns no click targets."""

    def find(self, scene: np.ndarray) -> list[BoostAura]:
        hsv = cv2.cvtColor(scene, cv2.COLOR_BGR2HSV)
        # Boost rings are much brighter/saturated than normal village grass.
        mask = cv2.inRange(hsv, (38, 115, 185), (82, 255, 255))
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
        count, _labels, stats, centers = cv2.connectedComponentsWithStats(mask)
        out: list[BoostAura] = []
        for index in range(1, count):
            x, y, w, h, area = stats[index]
            if area < 80 or w < 18 or h < 18:
                continue
            cx, cy = centers[index]
            out.append(BoostAura(int(round(cx)), int(round(cy)), max(w, h) // 2))
        return sorted(out, key=lambda aura: (aura.y, aura.x))
