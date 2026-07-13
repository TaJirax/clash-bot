"""Command-line entry point.

Phase 1 (interaction):
    python -m clashbot devices
    python -m clashbot screenshot <serial> [outfile.png]
    python -m clashbot tap <serial> <x> <y> [--raw] [--radius N]
    python -m clashbot swipe <serial> <x1> <y1> <x2> <y2> [duration_ms] [--raw]

Phase 2 (recognition):
    python -m clashbot find <serial> <template.png> [--threshold F] [--all]
                            [--tap] [--save annotated.png]

Phase 3 (behaviour):
    python -m clashbot collect <serial> [--loops N] [--interval S] [--dry-run]
    python -m clashbot upgrade <serial> [--scans N] [--scan-interval S] [--dry-run]

Taps and swipes are human-like by default (jittered position, real press
duration, small drift); pass --raw for exact, instantaneous input.
"""

from __future__ import annotations

import argparse
import sys

from . import adb_client, emulators
from .human import HumanInput


def cmd_devices(_args: argparse.Namespace) -> None:
    devices = emulators.discover()
    if not devices:
        print("No emulator found. Make sure it's running and ADB debugging is enabled.")
        return
    for d in devices:
        print(f"{d.serial}\t{d.state}")


def cmd_screenshot(args: argparse.Namespace) -> None:
    client = adb_client.AdbClient(args.serial)
    png_bytes = client.screenshot()
    with open(args.outfile, "wb") as f:
        f.write(png_bytes)
    print(f"Saved {len(png_bytes)} bytes to {args.outfile}")


def cmd_tap(args: argparse.Namespace) -> None:
    client = adb_client.AdbClient(args.serial)
    if args.raw:
        client.tap(args.x, args.y)
    else:
        px, py = HumanInput(client).tap(args.x, args.y, radius=args.radius, settle=False)
        print(f"tapped ({px}, {py})")


def cmd_swipe(args: argparse.Namespace) -> None:
    client = adb_client.AdbClient(args.serial)
    if args.raw:
        client.swipe(args.x1, args.y1, args.x2, args.y2, args.duration_ms)
    else:
        HumanInput(client).swipe(args.x1, args.y1, args.x2, args.y2,
                                 duration_ms=args.duration_ms, settle=False)


def cmd_find(args: argparse.Namespace) -> None:
    from . import vision  # local import so phase-1 commands don't need OpenCV

    client = adb_client.AdbClient(args.serial)
    scene = vision.decode(client.screenshot())
    template = vision.load(args.template)
    name = args.template

    if args.all:
        matches = vision.find_all(scene, template, name=name, threshold=args.threshold)
    else:
        m = vision.find(scene, template, name=name, threshold=args.threshold)
        matches = [m] if m else []

    if not matches:
        print(f"no match >= {args.threshold}")
        sys.exit(2)

    for m in matches:
        cx, cy = m.center
        print(f"{m.score:.3f}  center=({cx},{cy})  box=({m.x},{m.y},{m.w},{m.h})")

    if args.save:
        import cv2
        cv2.imwrite(args.save, vision.annotate(scene, matches))
        print(f"annotated -> {args.save}")

    if args.tap:
        cx, cy = matches[0].center
        px, py = HumanInput(client).tap(cx, cy, radius=min(matches[0].w, matches[0].h) / 2)
        print(f"tapped best match at ({px},{py})")


def cmd_collect(args: argparse.Namespace) -> None:
    from .farming import Collector  # local import so other commands don't need OpenCV

    client = adb_client.AdbClient(args.serial)
    collector = Collector(client, templates_dir=args.templates, threshold=args.threshold)
    total = collector.run(loops=args.loops, interval=args.interval, dry_run=args.dry_run)
    print(f"done: {total} bubble(s) over {args.loops} sweep(s)")


def cmd_upgrade(args: argparse.Namespace) -> None:
    from .upgrades import UpgradeBot

    client = adb_client.AdbClient(args.serial)
    bot = UpgradeBot(client, catalog_path=args.catalog)
    try:
        completed = bot.run(
            scans=args.scans,
            scan_interval=args.scan_interval,
            idle_range=(args.idle_min, args.idle_max),
            dry_run=args.dry_run,
        )
    except KeyboardInterrupt:
        print("stopped")
        return
    print(f"done: {completed} upgrade scan(s)")


def main() -> None:
    parser = argparse.ArgumentParser(prog="clashbot")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("devices").set_defaults(func=cmd_devices)

    p = sub.add_parser("screenshot")
    p.add_argument("serial")
    p.add_argument("outfile", nargs="?", default="screenshot.png")
    p.set_defaults(func=cmd_screenshot)

    p = sub.add_parser("tap")
    p.add_argument("serial")
    p.add_argument("x", type=int)
    p.add_argument("y", type=int)
    p.add_argument("--raw", action="store_true", help="exact instantaneous tap")
    p.add_argument("--radius", type=float, default=None, help="human aim radius in px")
    p.set_defaults(func=cmd_tap)

    p = sub.add_parser("swipe")
    p.add_argument("serial")
    p.add_argument("x1", type=int)
    p.add_argument("y1", type=int)
    p.add_argument("x2", type=int)
    p.add_argument("y2", type=int)
    p.add_argument("duration_ms", type=int, nargs="?", default=None)
    p.add_argument("--raw", action="store_true", help="exact swipe, no jitter")
    p.set_defaults(func=cmd_swipe)

    p = sub.add_parser("find")
    p.add_argument("serial")
    p.add_argument("template", help="path to a template PNG to search for")
    p.add_argument("--threshold", type=float, default=0.85)
    p.add_argument("--all", action="store_true", help="report every match, not just the best")
    p.add_argument("--tap", action="store_true", help="human-tap the best match")
    p.add_argument("--save", help="write an annotated screenshot to this path")
    p.set_defaults(func=cmd_find)

    p = sub.add_parser("collect", help="find resource bubbles and human-tap to collect them")
    p.add_argument("serial")
    p.add_argument("--loops", type=int, default=1, help="number of collect sweeps")
    p.add_argument("--interval", type=float, default=8.0, help="seconds between sweeps")
    p.add_argument("--threshold", type=float, default=0.82)
    p.add_argument("--templates", default="assets/templates", help="dir of collect_*.png")
    p.add_argument("--dry-run", action="store_true", help="report bubbles without tapping")
    p.set_defaults(func=cmd_collect)

    p = sub.add_parser(
        "upgrade",
        help="recognise buildings and attempt upgrades in priority order",
    )
    p.add_argument("serial")
    p.add_argument(
        "--scans",
        type=int,
        default=0,
        help="number of scans; 0 (default) runs until Ctrl+C",
    )
    p.add_argument(
        "--scan-interval",
        type=float,
        default=600.0,
        help="seconds between upgrade scans (default: 600)",
    )
    p.add_argument("--idle-min", type=float, default=30.0,
                   help="minimum seconds between anti-idle touches")
    p.add_argument("--idle-max", type=float, default=60.0,
                   help="maximum seconds between anti-idle touches")
    p.add_argument("--catalog", default="assets/buildings.json",
                   help="building/reference JSON catalog")
    p.add_argument("--dry-run", action="store_true",
                   help="recognise and report only; do not tap")
    p.set_defaults(func=cmd_upgrade)

    args = parser.parse_args()
    try:
        args.func(args)
    except adb_client.AdbError as e:
        print(f"ADB error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
