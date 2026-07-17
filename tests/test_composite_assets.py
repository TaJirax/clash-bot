import cv2
import numpy as np

from scripts.build_composite_assets import XflRenderer, representative


def test_xfl_renderer_composes_bitmap_shape_and_export(tmp_path):
    library = tmp_path / "LIBRARY"
    for folder in ("resources", "shapes", "exports"):
        (library / folder).mkdir(parents=True)
    image = np.zeros((8, 8, 4), dtype=np.uint8)
    image[:, :, :] = (20, 100, 220, 255)
    assert cv2.imwrite(str(library / "resources" / "0.png"), image)
    (library / "shapes" / "shape_0.xml").write_text(
        '<DOMSymbolItem><timeline><DOMTimeline><layers><DOMLayer><frames><DOMFrame><elements>'
        '<DOMBitmapInstance libraryItemName="resources/0"><matrix><Matrix tx="2" ty="3"/></matrix>'
        '</DOMBitmapInstance></elements></DOMFrame></frames></DOMLayer></layers></DOMTimeline></timeline></DOMSymbolItem>',
        encoding="utf-8",
    )
    export = library / "exports" / "archer1_idle.xml"
    export.write_text(
        '<DOMSymbolItem><timeline><DOMTimeline><layers><DOMLayer><frames><DOMFrame><elements>'
        '<DOMSymbolInstance libraryItemName="shapes/shape_0"/>'
        '</elements></DOMFrame></frames></DOMLayer></layers></DOMTimeline></timeline></DOMSymbolItem>',
        encoding="utf-8",
    )

    rendered = XflRenderer(library, canvas=32).render(export)

    assert rendered.shape == (32, 32, 4)
    assert rendered[19, 18, 3] == 255


def test_representative_prefers_idle_then_attack_per_family_level():
    records = [
        {"category": "units", "family": "archer", "level": 1, "name": "archer_attack"},
        {"category": "units", "family": "archer", "level": 1, "name": "archer_idle"},
        {"category": "units", "family": "archer", "level": 1, "name": "archer_run"},
    ]

    selected = representative(records, 2)

    assert [item["name"] for item in selected] == ["archer_idle", "archer_attack"]
