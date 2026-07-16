"""Recognition: find things on the game screen with template matching.

Phase 2. The bot takes a screenshot (raw PNG bytes from `AdbClient`),
then locates known sprites — collect bubbles, buttons, UI icons — by
matching small template images against the full scene. Each hit comes back
with a centre point that feeds straight into `HumanInput.tap`, so behaviour
is driven by what's on screen instead of hardcoded coordinates.

Two kinds of template are supported:

- **Screen crops** (resource bubbles, buttons cropped from real gameplay):
  opaque, already at the emulator's resolution. Match at a single scale.
- **Catalog icons** (e.g. the MIT-licensed troop/spell icons vendored under
  assets/icons/): transparent PNGs authored at a larger size than they render
  in-game. `load_template` turns their alpha channel into a match *mask* so
  the transparent corners are ignored, and `find` can sweep a range of
  `scales` to handle the size difference.
"""

from __future__ import annotations

from dataclasses import dataclass
import time

import cv2
import numpy as np

# Resolution the bundled templates (collect bubbles) were cropped at. At runtime
# we scale templates by the actual screenshot size / this, so the same templates
# work on 1280x720, 1920x1080, 960x540, etc. Assumes a 16:9 screen (the emulator
# norm); on those, width- and height-scaling are identical.
REFERENCE_SIZE = (1280, 720)  # (width, height)


def scale_for(scene: np.ndarray) -> float:
    """Factor to resize reference-resolution templates to match `scene`'s
    resolution (1.0 at 1280x720, 1.5 at 1920x1080, ...)."""
    # Use the limiting dimension. Width-only scaling over-sizes templates when
    # an emulator adds letterboxing or exposes a non-16:9 viewport.
    return min(
        scene.shape[1] / REFERENCE_SIZE[0],
        scene.shape[0] / REFERENCE_SIZE[1],
    )


@dataclass
class Match:
    name: str
    x: int          # top-left
    y: int
    w: int
    h: int
    score: float    # 0..1 match confidence
    scale: float = 1.0

    @property
    def center(self) -> tuple[int, int]:
        return self.x + self.w // 2, self.y + self.h // 2


def decode(png_bytes: bytes) -> np.ndarray:
    """Decode PNG bytes (e.g. from AdbClient.screenshot()) to a BGR image."""
    arr = np.frombuffer(png_bytes, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("could not decode image bytes as PNG")
    return img


def is_corrupt_frame(scene: np.ndarray, *, max_black_fraction: float = 0.18) -> bool:
    """Detect MEmu frames with large pure-black, unrendered tile regions."""
    if scene.size == 0:
        return True
    black = np.all(scene <= 2, axis=2)
    return float(np.mean(black)) > max_black_fraction


def capture(client, *, attempts: int = 4, delay: float = 0.4) -> np.ndarray:
    """Capture a complete frame, retrying transient emulator render corruption."""
    if attempts < 1:
        raise ValueError("attempts must be positive")
    for attempt in range(attempts):
        scene = decode(client.screenshot())
        if not is_corrupt_frame(scene):
            return scene
        if attempt + 1 < attempts:
            time.sleep(delay)
    raise RuntimeError(f"emulator returned {attempts} corrupted screenshots")


def load(path: str) -> np.ndarray:
    """Load a template/scene image from disk as BGR (alpha dropped)."""
    img = cv2.imread(path, cv2.IMREAD_COLOR)
    if img is None:
        raise FileNotFoundError(path)
    return img


def load_template(path: str) -> tuple[np.ndarray, np.ndarray | None]:
    """Load a template as (bgr, mask). If the PNG has an alpha channel, the
    mask is that alpha (so transparent pixels are ignored when matching);
    otherwise mask is None. Use this for the vendored icons."""
    img = cv2.imread(path, cv2.IMREAD_UNCHANGED)
    if img is None:
        raise FileNotFoundError(path)
    if img.ndim == 3 and img.shape[2] == 4:
        bgr = np.ascontiguousarray(img[:, :, :3])
        mask = np.ascontiguousarray(img[:, :, 3])
        return bgr, mask
    if img.ndim == 2:  # grayscale
        img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    return img, None


def _match(scene: np.ndarray, template: np.ndarray,
           mask: np.ndarray | None) -> np.ndarray:
    """matchTemplate result map, masked if a mask is given. Masked
    TM_CCOEFF_NORMED can emit inf/nan where the mask is degenerate; scrub
    those to 0 so downstream min/max and thresholds behave."""
    if template.shape[0] > scene.shape[0] or template.shape[1] > scene.shape[1]:
        # template bigger than scene at this scale -> no possible match
        return np.zeros((1, 1), dtype=np.float32)
    result = cv2.matchTemplate(scene, template, cv2.TM_CCOEFF_NORMED, mask=mask)
    return np.nan_to_num(result, nan=0.0, posinf=0.0, neginf=0.0)


def _resized(template: np.ndarray, mask: np.ndarray | None, scale: float):
    if not np.isfinite(scale) or scale <= 0:
        raise ValueError(f"scale must be a positive finite number, got {scale!r}")
    if scale == 1.0:
        return template, mask
    h, w = template.shape[:2]
    size = (max(1, round(w * scale)), max(1, round(h * scale)))
    interp = cv2.INTER_AREA if scale < 1 else cv2.INTER_LINEAR
    t = cv2.resize(template, size, interpolation=interp)
    m = cv2.resize(mask, size, interpolation=interp) if mask is not None else None
    return t, m


def find(scene: np.ndarray, template: np.ndarray, *, name: str = "",
         threshold: float = 0.85, mask: np.ndarray | None = None,
         scales: list[float] | None = None) -> Match | None:
    """Return the single best match of `template` in `scene`, or None if the
    best score is below `threshold`.

    `mask` ignores template pixels where the mask is 0 (pass alpha for icons).
    `scales` sweeps the template over several sizes (e.g. [0.4, 0.5, 0.6]) and
    keeps the best across all of them — use it when a catalog icon renders at a
    different size than it was authored.
    """
    best: Match | None = None
    for s in (scales or [1.0]):
        t, m = _resized(template, mask, s)
        result = _match(scene, t, m)
        _min_v, max_v, _min_l, max_l = cv2.minMaxLoc(result)
        if best is None or max_v > best.score:
            h, w = t.shape[:2]
            best = Match(name=name, x=int(max_l[0]), y=int(max_l[1]),
                         w=w, h=h, score=float(max_v), scale=s)
    if best is None or best.score < threshold:
        return None
    return best


def find_all(scene: np.ndarray, template: np.ndarray, *, name: str = "",
             threshold: float = 0.85, mask: np.ndarray | None = None,
             min_gap: int | None = None, scale: float = 1.0,
             scales: list[float] | tuple[float, ...] | None = None,
             max_matches: int | None = None) -> list[Match]:
    """Return every match at or above `threshold`, de-duplicated so a single
    on-screen instance yields one hit (matchTemplate lights up a cluster of
    near-identical positions around each real match).

    `scale` resizes the template once before matching — pass `scale_for(scene)`
    so reference-resolution templates match the current screen resolution.
    `min_gap` is the minimum pixel distance between two accepted matches;
    defaults to half the (scaled) template's smaller side. Results are sorted by
    score, best first.
    """
    requested_scales = list(scales) if scales is not None else [scale]
    if not requested_scales:
        raise ValueError("scales must contain at least one value")
    if max_matches is not None and max_matches < 1:
        raise ValueError("max_matches must be positive")

    candidates: list[Match] = []
    for candidate_scale in requested_scales:
        resized, resized_mask = _resized(template, mask, candidate_scale)
        h, w = resized.shape[:2]
        result = _match(scene, resized, resized_mask)
        if max_matches is None:
            ys, xs = np.where(result >= threshold)
        else:
            # At relaxed thresholds matchTemplate can produce thousands of
            # adjacent pixels for one object. Keep only spatial local maxima;
            # this avoids sorting/allocating the entire plateau when callers
            # only need a bounded number of buildings.
            gap = min_gap if min_gap is not None else max(1, min(w, h) // 2)
            kernel = cv2.getStructuringElement(
                cv2.MORPH_RECT, (2 * gap + 1, 2 * gap + 1)
            )
            maxima = cv2.dilate(result, kernel)
            ys, xs = np.where((result >= threshold) & (result >= maxima - 1e-7))
        candidates.extend(
            Match(name=name, x=int(x), y=int(y), w=w, h=h,
                  score=float(result[y, x]), scale=candidate_scale)
            for x, y in zip(xs, ys)
        )
    candidates.sort(key=lambda m: m.score, reverse=True)

    kept: list[Match] = []
    for c in candidates:
        cx, cy = c.center
        candidate_gap = min_gap if min_gap is not None else max(1, min(c.w, c.h) // 2)
        if all(
            (cx - k.center[0]) ** 2 + (cy - k.center[1]) ** 2
            >= max(candidate_gap, min(k.w, k.h) // 2) ** 2
            for k in kept
        ):
            kept.append(c)
            if max_matches is not None and len(kept) >= max_matches:
                break
    return kept


def annotate(scene: np.ndarray, matches: list[Match]) -> np.ndarray:
    """Draw boxes + scores on a copy of the scene, for debugging what matched."""
    out = scene.copy()
    for m in matches:
        cv2.rectangle(out, (m.x, m.y), (m.x + m.w, m.y + m.h), (0, 255, 0), 2)
        label = f"{m.name} {m.score:.2f}" if m.name else f"{m.score:.2f}"
        cv2.putText(out, label, (m.x, max(m.y - 5, 12)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1, cv2.LINE_AA)
    return out
