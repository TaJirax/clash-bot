"""Stable repository paths used by all recognition components.

Recognition must not depend on the shell's current directory: the bot may be
started from an IDE, a scheduled task, or another account profile.
"""

from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
ASSETS_DIR = REPOSITORY_ROOT / "assets"
TEMPLATES_DIR = ASSETS_DIR / "templates"
BUILDING_CATALOG = ASSETS_DIR / "buildings.json"
FANKIT_DIR = ASSETS_DIR / "supercell_fankit"
DERIVED_CACHE_DIR = ASSETS_DIR / "derived_cache"
