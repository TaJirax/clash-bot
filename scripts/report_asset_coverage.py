"""Report the bot-visible local asset cache without loading image data."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from clashbot.asset_catalog import AssetCatalog


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--derived-root", type=Path, default=Path("assets/derived_cache"))
    parser.add_argument("--fankit-root", type=Path, default=Path("assets/supercell_fankit"))
    parser.add_argument("--no-fankit", action="store_true")
    parser.add_argument("--label", help="show exact normalized label matches")
    args = parser.parse_args()

    catalog = AssetCatalog(
        derived_root=args.derived_root,
        fankit_root=None if args.no_fankit else args.fankit_root,
    )
    report: dict[str, object] = catalog.summary()
    if args.label:
        report["query"] = args.label
        report["matches"] = [
            {
                "source": record.source,
                "role": record.role,
                "category": record.category,
                "level": record.level,
                "path": str(record.path),
            }
            for record in catalog.find(args.label)
        ]
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
