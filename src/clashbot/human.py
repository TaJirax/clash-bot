"""Human-like input on top of the raw ADB tap/swipe primitives.

`adb shell input tap x y` is an instant, pixel-perfect, zero-duration
press: a dead giveaway that a machine is playing. Real fingers land a few
pixels off the intended point, stay down for a moment, drift slightly while
pressed, and lift. Actions are also spaced out by human reaction/think time,
not fired back-to-back.

This module wraps an `AdbClient` and reproduces those traits so the bot
"registers touch" the way a person would:

- taps land within a radius of the target (Gaussian, biased to the centre),
- every tap is a real down -> small drift -> up gesture with a randomised
  hold duration (via `input swipe`, which emits ACTION_DOWN/MOVE/UP), not the
  instantaneous `input tap`,
- swipes follow a slightly curved path over a randomised duration,
- delays between actions are randomised around a configurable think time.
"""

from __future__ import annotations

import math
import random
import time
from dataclasses import dataclass

from .adb_client import AdbClient


@dataclass
class HumanProfile:
    """Tunables for how human the input looks. Defaults are a calm player."""

    # Radius (px) of the circle a tap may land in around its target.
    tap_radius: float = 7.0
    # How long a finger stays down for a tap, in milliseconds.
    hold_ms: tuple[int, int] = (55, 130)
    # Pixels the finger may drift between touch-down and lift.
    tap_drift: float = 3.0
    # Seconds to pause between consecutive actions (reaction / think time).
    think_s: tuple[float, float] = (0.35, 0.9)
    # Duration range (ms) for a full-length swipe.
    swipe_ms: tuple[int, int] = (280, 520)


class HumanInput:
    """Sends taps and swipes that look like they came from a real finger."""

    def __init__(self, client: AdbClient, profile: HumanProfile | None = None,
                 rng: random.Random | None = None):
        self.client = client
        self.profile = profile or HumanProfile()
        self.rng = rng or random.Random()

    # -- internals ---------------------------------------------------------

    def _jitter_point(self, x: int, y: int, radius: float) -> tuple[int, int]:
        """A point near (x, y): Gaussian offset clamped to `radius`, so most
        taps cluster near the centre with the occasional edge landing."""
        angle = self.rng.uniform(0, 2 * math.pi)
        # gauss(0, r/2) keeps ~95% inside the radius; abs+clamp bounds the tail.
        dist = min(abs(self.rng.gauss(0, radius / 2)), radius)
        return int(round(x + dist * math.cos(angle))), int(round(y + dist * math.sin(angle)))

    def _sleep(self, lo: float, hi: float) -> None:
        time.sleep(self.rng.uniform(lo, hi))

    # -- public API --------------------------------------------------------

    def tap(self, x: int, y: int, radius: float | None = None, settle: bool = True) -> tuple[int, int]:
        """Tap near (x, y) like a finger: land off-centre, hold briefly while
        drifting a couple pixels, then lift. Returns the point actually pressed.

        `radius` overrides the profile default (pass the target's size so big
        buttons get a looser aim than small icons). `settle=True` adds a short
        human pause afterwards.
        """
        p = self.profile
        r = p.tap_radius if radius is None else radius
        sx, sy = self._jitter_point(x, y, r)
        # Lift a few pixels away from where we landed -> real ACTION_MOVE events.
        ex, ey = self._jitter_point(sx, sy, p.tap_drift)
        hold = self.rng.randint(*p.hold_ms)
        # swipe with a start≈end and a real duration registers as a held touch,
        # unlike `input tap` which is instantaneous.
        self.client.swipe(sx, sy, ex, ey, duration_ms=hold)
        if settle:
            self._sleep(*p.think_s)
        return sx, sy

    def swipe(self, x1: int, y1: int, x2: int, y2: int,
              duration_ms: int | None = None, settle: bool = True) -> None:
        """Swipe from ~(x1,y1) to ~(x2,y2) with jittered endpoints and a
        randomised duration. Endpoints wobble a little so drags aren't
        pixel-identical run to run."""
        p = self.profile
        sx, sy = self._jitter_point(x1, y1, p.tap_radius)
        ex, ey = self._jitter_point(x2, y2, p.tap_radius)
        dur = duration_ms if duration_ms is not None else self.rng.randint(*p.swipe_ms)
        self.client.swipe(sx, sy, ex, ey, duration_ms=dur)
        if settle:
            self._sleep(*p.think_s)

    def wait(self, lo: float | None = None, hi: float | None = None) -> None:
        """Idle for a human beat. Defaults to the profile's think time."""
        p = self.profile
        self._sleep(p.think_s[0] if lo is None else lo,
                    p.think_s[1] if hi is None else hi)
