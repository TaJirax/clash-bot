"""Read the home-screen gold/elixir/gem counters from learned digit glyphs.

The digit templates under ``assets/templates/digits`` are binarized crops of
the game's counter font. Reading is fail-closed: a row containing a glyph
that does not match any learned digit reports ``None`` instead of guessing,
and the unknown glyph is saved so it can be labelled and added to the set.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from .paths import TEMPLATES_DIR

# Fractional (x1, y1, x2, y2) bands of the three top-right resource bars.
ROWS = {
    "gold": (0.78, 0.015, 0.99, 0.095),
    "elixir": (0.78, 0.11, 0.99, 0.19),
    "gems": (0.78, 0.185, 0.99, 0.25),
}
GLYPH_SIZE = (16, 24)  # (width, height) every glyph is normalized to
MIN_GLYPH_SCORE = 0.72


@dataclass(frozen=True)
class ResourceReading:
    gold: int | None
    elixir: int | None
    gems: int | None

    def known(self) -> dict[str, int]:
        return {name: value for name, value in
                (("gold", self.gold), ("elixir", self.elixir), ("gems", self.gems))
                if value is not None}


class ResourceReader:
    def __init__(self, templates_dir: str | Path | None = None,
                 *, unknown_dir: str | Path | None = "captures/digits_unknown"):
        directory = Path(templates_dir) if templates_dir is not None else (
            TEMPLATES_DIR / "digits"
        )
        self.digits: dict[str, np.ndarray] = {}
        for path in sorted(directory.glob("[0-9].png")):
            glyph = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
            if glyph is not None:
                self.digits[path.stem] = self._normalize(glyph)
        if not self.digits:
            raise FileNotFoundError(f"no digit templates in {directory}")
        self.unknown_dir = Path(unknown_dir) if unknown_dir else None

    @staticmethod
    def _normalize(glyph: np.ndarray) -> np.ndarray:
        resized = cv2.resize(glyph, GLYPH_SIZE, interpolation=cv2.INTER_AREA)
        return (resized > 96).astype(np.float32)

    def _classify(self, glyph: np.ndarray) -> tuple[str | None, float]:
        query = self._normalize(glyph)
        best_digit, best_score = None, 0.0
        for digit, reference in self.digits.items():
            # Same-size normalized correlation: 1.0 for an identical glyph.
            score = float(cv2.matchTemplate(
                query, reference, cv2.TM_CCOEFF_NORMED
            )[0, 0])
            if score > best_score:
                best_digit, best_score = digit, score
        if best_score < MIN_GLYPH_SCORE:
            return None, best_score
        return best_digit, best_score

    def _glyphs(self, roi: np.ndarray,
                band_height: int) -> list[tuple[tuple[int, int, int, int], np.ndarray]]:
        white = cv2.inRange(roi, (185, 185, 185), (255, 255, 255))
        count, _labels, stats, _centroids = cv2.connectedComponentsWithStats(white)
        low, high = max(8, int(band_height * 0.18)), int(band_height * 0.62)
        components = sorted(
            (x, y, w, h) for x, y, w, h, area in stats[1:count]
            if low <= h <= high and 3 <= w <= high and area >= 25
            # Digits in this font are taller than wide; the round "+"
            # buttons and other icons are not.
            and h > w * 0.8
        )
        return [
            (box, white[max(0, box[1] - 1):box[1] + box[3] + 1,
                        max(0, box[0] - 1):box[0] + box[2] + 1])
            for box in components
        ]

    def _read_row(self, scene: np.ndarray, name: str) -> int | None:
        h, w = scene.shape[:2]
        fx1, fy1, fx2, fy2 = ROWS[name]
        roi = scene[int(fy1 * h):int(fy2 * h), int(fx1 * w):int(fx2 * w)]
        glyphs = self._glyphs(roi, roi.shape[0])
        if not glyphs:
            return None
        # Every glyph must classify; guessing around an unreadable one would
        # silently report a wrong amount.
        digits: list[str] = []
        for (_box, glyph) in glyphs:
            digit, _score = self._classify(glyph)
            if digit is None:
                if self.unknown_dir is not None:
                    self.unknown_dir.mkdir(parents=True, exist_ok=True)
                    stamp = f"{name}_{int(time.time() * 1000)}"
                    cv2.imwrite(str(self.unknown_dir / f"{stamp}.png"), glyph)
                return None
            digits.append(digit)
        # A glyph hidden by an animation is dropped by the size filter and
        # leaves an oversized horizontal gap; the thousands separator stays
        # well under one glyph height. Refuse to read across such a hole.
        heights = sorted(box[3] for box, _glyph in glyphs)
        glyph_height = heights[len(heights) // 2]
        for (box_a, _a), (box_b, _b) in zip(glyphs, glyphs[1:]):
            gap = box_b[0] - (box_a[0] + box_a[2])
            if gap > glyph_height * 0.8:
                return None
        return int("".join(digits))

    def read(self, scene: np.ndarray) -> ResourceReading:
        return ResourceReading(
            gold=self._read_row(scene, "gold"),
            elixir=self._read_row(scene, "elixir"),
            gems=self._read_row(scene, "gems"),
        )
