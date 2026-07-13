"""Resource gathering: the first real bot behaviour (phase 3).

A collector "sweep" is: screenshot the base, find every resource-collect
bubble on screen (the coin/droplet that pops over a full gold mine or elixir
collector), human-tap each one to collect it, then press BACK to dismiss any
building panel a slightly-off tap may have opened. `run()` repeats sweeps on
an interval so the bot keeps collecting as resources regenerate.

Recognition is driven entirely by the `collect_*.png` templates under
assets/templates/ (cropped from real gameplay), so there are no hardcoded
screen coordinates — add a new bubble type by dropping in another template.

Out of scope here (later phases): panning the base to reach off-screen
collectors, training army, attacking, and building upgrades.
"""

from __future__ import annotations

import glob
import os
import time
from dataclasses import dataclass

from . import vision
from .adb_client import AdbClient
from .human import HumanInput


@dataclass
class SweepResult:
    collected: list[vision.Match]

    @property
    def count(self) -> int:
        return len(self.collected)


# When a building is selected its info panel (Info / Upgrade / Collect) sits at
# the bottom-centre. The purple droplet on that "Collect" button looks like an
# elixir bubble, so we ignore any match landing in this band to avoid tapping
# panel UI. Expressed as fractions of (width, height) so it holds at any
# resolution: x1, y1, x2, y2. (Values are the 1280x720 pixel region / 1280,720.)
INFO_PANEL_FRAC = (400 / 1280, 495 / 720, 905 / 1280, 640 / 720)


class Collector:
    def __init__(self, client: AdbClient, human: HumanInput | None = None,
                 templates_dir: str = "assets/templates", threshold: float = 0.82,
                 exclude: tuple[float, float, float, float] | None = INFO_PANEL_FRAC):
        self.client = client
        self.human = human or HumanInput(client)
        self.threshold = threshold
        self.exclude = exclude  # fractional (x1,y1,x2,y2) of the screen, or None
        self.templates = self._load_templates(templates_dir)
        if not self.templates:
            raise FileNotFoundError(
                f"no collect_*.png templates in {templates_dir!r} — crop a resource "
                f"bubble from a screenshot first")

    @staticmethod
    def _load_templates(d: str) -> list[tuple[str, "vision.np.ndarray"]]:
        out = []
        for p in sorted(glob.glob(os.path.join(d, "collect_*.png"))):
            name = os.path.splitext(os.path.basename(p))[0]
            out.append((name, vision.load(p)))
        return out

    def find_bubbles(self, scene) -> list[vision.Match]:
        """All collect bubbles in `scene`, de-duplicated across templates so a
        single on-screen bubble isn't reported by two similar templates.
        Templates are scaled to the screenshot's resolution, so this works at
        any (16:9) resolution the emulator reports."""
        h, w = scene.shape[:2]
        scale = vision.scale_for(scene)

        matches: list[vision.Match] = []
        for name, tmpl in self.templates:
            matches += vision.find_all(scene, tmpl, name=name, threshold=self.threshold,
                                       scale=scale)
        matches.sort(key=lambda m: m.score, reverse=True)

        excl = None
        if self.exclude is not None:
            fx1, fy1, fx2, fy2 = self.exclude
            excl = (fx1 * w, fy1 * h, fx2 * w, fy2 * h)

        kept: list[vision.Match] = []
        for m in matches:
            cx, cy = m.center
            if excl is not None and excl[0] <= cx <= excl[2] and excl[1] <= cy <= excl[3]:
                continue  # inside the info-panel band — not a real bubble
            gap = min(m.w, m.h)
            if all((cx - k.center[0]) ** 2 + (cy - k.center[1]) ** 2 >= gap ** 2 for k in kept):
                kept.append(m)
        return kept

    def sweep(self, dry_run: bool = False) -> SweepResult:
        scene = vision.decode(self.client.screenshot())
        bubbles = self.find_bubbles(scene)
        if not dry_run:
            for m in bubbles:
                cx, cy = m.center
                self.human.tap(cx, cy, radius=min(m.w, m.h) / 2)
            # NOTE: do NOT press BACK here to deselect — on the home base with no
            # menu open, Android BACK pops the "quit game?" dialog. Tapping a
            # resource bubble collects without opening a panel anyway; if an
            # off-bubble tap does select a building, its info panel sits at the
            # bottom and doesn't hide the collectors, so the next sweep is fine.
        return SweepResult(collected=bubbles)

    def run(self, loops: int = 1, interval: float = 8.0, dry_run: bool = False,
            log=print) -> int:
        """Run `loops` sweeps, pausing `interval` seconds between them.
        Returns the total number of bubbles collected."""
        total = 0
        for i in range(loops):
            result = self.sweep(dry_run=dry_run)
            total += result.count
            names = ", ".join(m.name.replace("collect_", "") for m in result.collected) or "none"
            verb = "would collect" if dry_run else "collected"
            log(f"sweep {i + 1}/{loops}: {verb} {result.count} ({names})")
            if i < loops - 1:
                time.sleep(interval)
        return total
