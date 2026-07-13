"""Recognition tests. Pure image processing — no emulator/ADB needed."""

import cv2
import numpy as np

from clashbot import vision


def _scene_with(template, positions, size=(300, 400)):
    """A blank scene with `template` pasted at each (x, y) top-left position."""
    scene = np.full((size[0], size[1], 3), 30, dtype=np.uint8)
    th, tw = template.shape[:2]
    for x, y in positions:
        scene[y:y + th, x:x + tw] = template
    return scene


def _template():
    t = np.zeros((20, 20, 3), dtype=np.uint8)
    t[5:15, 5:15] = (0, 200, 255)  # a distinctive orange square
    return t


def test_find_locates_single_template():
    tmpl = _template()
    scene = _scene_with(tmpl, [(100, 60)])

    m = vision.find(scene, tmpl, name="x", threshold=0.9)

    assert m is not None
    assert (m.x, m.y) == (100, 60)
    assert m.center == (110, 70)
    assert m.score > 0.99


def test_find_returns_none_below_threshold():
    tmpl = _template()
    scene = np.full((200, 200, 3), 30, dtype=np.uint8)  # template absent

    assert vision.find(scene, tmpl, threshold=0.9) is None


def test_find_all_dedupes_to_one_hit_per_instance():
    tmpl = _template()
    scene = _scene_with(tmpl, [(40, 40), (200, 150), (120, 250)])

    matches = vision.find_all(scene, tmpl, threshold=0.9)

    assert len(matches) == 3
    centers = sorted(m.center for m in matches)
    assert centers == [(50, 50), (130, 260), (210, 160)]


def test_multi_scale_finds_shrunken_template():
    # Author a template large, render it half-size into the scene: only a
    # scale sweep should locate it.
    tmpl = np.zeros((40, 40, 3), dtype=np.uint8)
    tmpl[10:30, 10:30] = (0, 200, 255)
    small = cv2.resize(tmpl, (20, 20), interpolation=cv2.INTER_AREA)
    scene = _scene_with(small, [(100, 60)])

    assert vision.find(scene, tmpl, threshold=0.9) is None  # single-scale misses
    m = vision.find(scene, tmpl, threshold=0.9, scales=[0.5, 0.75, 1.0])
    assert m is not None
    assert m.scale == 0.5
    assert abs(m.center[0] - 110) <= 2 and abs(m.center[1] - 70) <= 2


def test_mask_ignores_transparent_pixels():
    # A template whose border differs from the scene but is masked out should
    # still match on its opaque, textured core.
    grad = np.linspace(0, 255, 10).astype(np.uint8)
    core = np.stack([np.tile(grad, (10, 1))] * 3, axis=-1)  # 10x10 textured patch

    template = np.full((20, 20, 3), 100, dtype=np.uint8)    # border filler...
    template[5:15, 5:15] = core                             # ...opaque core
    mask = np.zeros((20, 20), dtype=np.uint8)
    mask[5:15, 5:15] = 255

    scene = np.full((200, 200, 3), 30, dtype=np.uint8)      # border area != 100
    scene[55:65, 55:65] = core                              # core present at (50,50)

    m = vision.find(scene, template, threshold=0.9, mask=mask)
    assert m is not None
    assert (m.x, m.y) == (50, 50)


def test_load_template_splits_alpha(tmp_path):
    import cv2 as _cv2
    rgba = np.zeros((16, 16, 4), dtype=np.uint8)
    rgba[:, :, :3] = (10, 20, 30)
    rgba[4:12, 4:12, 3] = 255  # opaque core, transparent border
    path = str(tmp_path / "icon.png")
    _cv2.imwrite(path, rgba)

    bgr, mask = vision.load_template(path)
    assert bgr.shape == (16, 16, 3)
    assert mask is not None and mask.shape == (16, 16)
    assert mask[8, 8] == 255 and mask[0, 0] == 0


def test_decode_roundtrips_png_bytes():
    import cv2
    tmpl = _template()
    ok, buf = cv2.imencode(".png", tmpl)
    assert ok

    img = vision.decode(buf.tobytes())

    assert img.shape == tmpl.shape
    assert np.array_equal(img, tmpl)
