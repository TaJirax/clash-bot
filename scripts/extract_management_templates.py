"""Create live builder/laboratory UI templates from a labelled home screenshot."""

from pathlib import Path

import cv2


SOURCE = Path("captures/management/status_retry.png")
OUT = Path("assets/templates")


def crop(image, box, output: Path) -> None:
    x1, y1, x2, y2 = box
    if not cv2.imwrite(str(output), image[y1:y2, x1:x2]):
        raise RuntimeError(f"could not write {output}")


def main() -> None:
    image = cv2.imread(str(SOURCE), cv2.IMREAD_COLOR)
    if image is None:
        raise FileNotFoundError(SOURCE)
    OUT.mkdir(parents=True, exist_ok=True)
    # Stable visual controls from the 1280x720 Home Village HUD.
    crop(image, (398, 6, 542, 78), OUT / "builder_free_1of1.png")
    crop(image, (744, 121, 851, 169), OUT / "laboratory_research_ready.png")


if __name__ == "__main__":
    main()
