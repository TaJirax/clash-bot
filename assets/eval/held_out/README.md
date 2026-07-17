# Held-out building recognition annotations

Each `*.json` file here is a hand-labelled screenshot used only for
measuring `BuildingRecognizer` accuracy — never for training. Create one with:

    python scripts/label_buildings.py path/to/screenshot.png

Schema:

    {
      "image": "path/to/screenshot.png",
      "buildings": [
        {"category": "town_hall", "level": 11, "x": 640, "y": 360}
      ]
    }

Run `python scripts/evaluate_building_recognizer.py` to score the current
recognizer against every annotation in this directory. For the report to
say anything about universality (not just this account), label screenshots
from more than one account, zoom level, and layout.
