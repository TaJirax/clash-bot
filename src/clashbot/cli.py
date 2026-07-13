"""Command-line entry point for phase 1: connect, look, act.

Usage:
    python -m clashbot devices
    python -m clashbot screenshot <serial> [outfile.png]
    python -m clashbot tap <serial> <x> <y>
    python -m clashbot swipe <serial> <x1> <y1> <x2> <y2> [duration_ms]
"""

from __future__ import annotations

import argparse
import sys

from . import adb_client, emulators


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
    client.tap(args.x, args.y)


def cmd_swipe(args: argparse.Namespace) -> None:
    client = adb_client.AdbClient(args.serial)
    client.swipe(args.x1, args.y1, args.x2, args.y2, args.duration_ms)


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
    p.set_defaults(func=cmd_tap)

    p = sub.add_parser("swipe")
    p.add_argument("serial")
    p.add_argument("x1", type=int)
    p.add_argument("y1", type=int)
    p.add_argument("x2", type=int)
    p.add_argument("y2", type=int)
    p.add_argument("duration_ms", type=int, nargs="?", default=300)
    p.set_defaults(func=cmd_swipe)

    args = parser.parse_args()
    try:
        args.func(args)
    except adb_client.AdbError as e:
        print(f"ADB error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
