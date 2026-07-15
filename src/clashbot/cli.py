"""Command-line entry point.

Phase 1 (interaction):
    python -m clashbot devices
    python -m clashbot screenshot <serial> [outfile.png]
    python -m clashbot menu-capture <serial> <session> <state> [options]
    python -m clashbot tap <serial> <x> <y> [--raw] [--radius N]
    python -m clashbot swipe <serial> <x1> <y1> <x2> <y2> [duration_ms] [--raw]
    python -m clashbot zoom-in|zoom-out <serial> [--steps N]
    python -m clashbot normalize-zoom <serial> [--target SCALE]

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


def cmd_menu_capture(args: argparse.Namespace) -> None:
    from .menu_capture import MenuDataset

    client = adb_client.AdbClient(args.serial)
    dataset = MenuDataset(args.root, args.session)
    record = dataset.capture(
        client.screenshot(),
        state=args.state,
        description=args.description,
        after=args.after,
        action=args.action,
    )
    print(
        f"captured #{record['id']} state={record['state']} "
        f"({record['width']}x{record['height']}) -> "
        f"{dataset.directory / record['file']}"
    )


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


def _show_zoom_result(result) -> bool:
    before = "unknown" if result.before_scale is None else f"{result.before_scale:.2f}x"
    after = "unknown" if result.after_scale is None else f"{result.after_scale:.2f}x"
    status = "verified" if result.verified else "NOT VERIFIED"
    print(f"zoom {result.direction}: {before} -> {after} ({status})")
    return result.verified


def cmd_zoom(args: argparse.Namespace) -> None:
    from .camera import controller_from_catalog
    from .memu_input import MEmuInputError, MEmuZoom, infer_instance
    from .multitouch import AdbPinchZoom, MultiTouchError
    from .windows_input import WindowsCtrlWheel, WindowsInputError

    if args.backend == "windows":
        actuator = WindowsCtrlWheel(args.window_title)
    elif args.backend == "multitouch":
        actuator = AdbPinchZoom(adb_client.AdbClient(args.serial))
    elif args.backend == "memu":
        instance = args.memu_instance
        if instance is None:
            instance = infer_instance(args.serial)
        if instance is None:
            print("could not infer MEmu instance; pass --memu-instance", file=sys.stderr)
            sys.exit(2)
        actuator = MEmuZoom(instance)
    else:
        actuator = None
    controller = controller_from_catalog(
        adb_client.AdbClient(args.serial), args.catalog, actuator=actuator
    )
    try:
        result = controller.adjust(args.direction, steps=args.steps)
    except (WindowsInputError, MEmuInputError, MultiTouchError) as error:
        print(f"zoom input error: {error}", file=sys.stderr)
        sys.exit(2)
    if not _show_zoom_result(result):
        print(
            "The game did not show the requested scale change. The input backend "
            "may be unsupported, or too few buildings were recognized.",
            file=sys.stderr,
        )
        sys.exit(2)


def cmd_normalize_zoom(args: argparse.Namespace) -> None:
    from .camera import controller_from_catalog
    from .memu_input import MEmuInputError, MEmuZoom, infer_instance
    from .multitouch import AdbPinchZoom, MultiTouchError
    from .windows_input import WindowsCtrlWheel, WindowsInputError

    if args.backend == "windows":
        actuator = WindowsCtrlWheel(args.window_title)
    elif args.backend == "multitouch":
        actuator = AdbPinchZoom(adb_client.AdbClient(args.serial))
    elif args.backend == "memu":
        instance = args.memu_instance
        if instance is None:
            instance = infer_instance(args.serial)
        if instance is None:
            print("could not infer MEmu instance; pass --memu-instance", file=sys.stderr)
            sys.exit(2)
        actuator = MEmuZoom(instance)
    else:
        actuator = None
    controller = controller_from_catalog(
        adb_client.AdbClient(args.serial), args.catalog, actuator=actuator
    )
    initial = controller.measure()
    if initial is None:
        print("could not estimate camera scale from visible buildings", file=sys.stderr)
        sys.exit(2)
    try:
        results = controller.normalize(args.target, max_steps=args.max_steps)
    except (WindowsInputError, MEmuInputError, MultiTouchError) as error:
        print(f"zoom input error: {error}", file=sys.stderr)
        sys.exit(2)
    if not results:
        print(f"camera already near target: {initial:.2f}x")
        return
    for result in results:
        if not _show_zoom_result(result):
            sys.exit(2)
    final = results[-1].after_scale
    if final is None or abs(final - args.target) > 0.06:
        print(f"stopped at {final:.2f}x before reaching {args.target:.2f}x", file=sys.stderr)
        sys.exit(2)


def cmd_pan_camera(args: argparse.Namespace) -> None:
    from .navigation import CameraPanController

    result = CameraPanController(adb_client.AdbClient(args.serial)).pan(
        args.direction, distance=args.distance
    )
    status = "verified" if result.verified else "BLOCKED/NOT VERIFIED"
    print(
        f"pan {result.direction}: content shift "
        f"({result.content_dx:.1f}, {result.content_dy:.1f}), "
        f"response={result.response:.2f} ({status})"
    )
    if not result.verified:
        sys.exit(2)


def cmd_map_base(args: argparse.Namespace) -> None:
    from .camera import controller_from_catalog
    from .multitouch import AdbPinchZoom
    from .navigation import BaseMapper, CameraPanController
    from .upgrades import BuildingRecognizer, ReferenceCatalog

    route = [part.strip().lower() for part in args.route.split(",") if part.strip()]
    invalid = [part for part in route if part not in ("up", "down", "left", "right")]
    if invalid:
        print(f"invalid route direction(s): {', '.join(invalid)}", file=sys.stderr)
        sys.exit(2)
    client = adb_client.AdbClient(args.serial)
    if not args.skip_zoom_normalize:
        zoom = controller_from_catalog(
            client, args.catalog, actuator=AdbPinchZoom(client)
        )
        initial = zoom.measure()
        if initial is None:
            print("could not estimate camera scale before mapping", file=sys.stderr)
            sys.exit(2)
        results = zoom.normalize(args.zoom_target, max_steps=args.zoom_steps)
        if results and not all(result.verified for result in results):
            print("camera zoom normalization failed; mapping stopped", file=sys.stderr)
            sys.exit(2)
        final_scale = results[-1].after_scale if results else initial
        print(f"mapping camera scale: {final_scale:.2f}x")
    mapper = BaseMapper(
        client,
        BuildingRecognizer(ReferenceCatalog(args.catalog)),
        CameraPanController(client),
        root=args.root,
        session=args.session,
    )
    manifest = mapper.scan(route)
    print(
        f"mapped {len(manifest['buildings'])} building(s) across "
        f"{len(manifest['views'])} view(s) -> {mapper.directory / 'map.json'}"
    )


def cmd_find_building(args: argparse.Namespace) -> None:
    from .navigation import CameraPanController
    from .upgrades import BuildingRecognizer, ReferenceCatalog
    from . import vision

    route = [part.strip().lower() for part in args.route.split(",") if part.strip()]
    if any(part not in ("up", "down", "left", "right") for part in route):
        print("route must contain only up, down, left, right", file=sys.stderr)
        sys.exit(2)
    client = adb_client.AdbClient(args.serial)
    recognizer = BuildingRecognizer(ReferenceCatalog(args.catalog))
    pan = CameraPanController(client)
    for view_id, direction in enumerate([None, *route], start=1):
        if direction is not None:
            pan.pan(direction)
        targets = [
            target for target in recognizer.find(vision.decode(client.screenshot()))
            if target.category == args.category
        ]
        if not targets:
            continue
        target = max(targets, key=lambda item: item.score)
        print(
            f"found {target.category}/{target.name} in view {view_id} at "
            f"({target.x}, {target.y}), score={target.score:.3f}"
        )
        if args.tap:
            HumanInput(client).tap(target.x, target.y, radius=target.radius)
            print("building tapped; its game menu should now be open")
        return
    print(f"no {args.category!r} building found along route", file=sys.stderr)
    sys.exit(2)


def cmd_open_attack(args: argparse.Namespace) -> None:
    from .attack import AttackNavigator

    result = AttackNavigator(adb_client.AdbClient(args.serial)).open()
    if not result.opened:
        print("Attack button/menu could not be visually verified", file=sys.stderr)
        sys.exit(2)
    print(
        f"Attack menu opened and verified "
        f"(button={result.button_score:.3f}, menu={result.menu_score:.3f})"
    )


def cmd_anti_afk(args: argparse.Namespace) -> None:
    from .anti_afk import AntiAfk

    try:
        completed = AntiAfk(adb_client.AdbClient(args.serial)).run(
            loops=args.loops,
            interval=(args.interval_min, args.interval_max),
            dry_run=args.dry_run,
        )
    except KeyboardInterrupt:
        print("stopped")
        return
    print(f"done: {completed} anti-afk check(s)")


def cmd_find_match(args: argparse.Namespace) -> None:
    from .attack import FindMatchNavigator

    if args.stay and not args.confirm:
        print("--stay requires --confirm", file=sys.stderr)
        sys.exit(2)
    result = FindMatchNavigator(adb_client.AdbClient(args.serial)).find(
        confirm=args.confirm,
        return_home=not args.stay,
    )
    if not result.prepared:
        print("Find Match or army confirmation was not verified", file=sys.stderr)
        sys.exit(2)
    if not args.confirm:
        print("army confirmation opened and verified; matchmaking not started")
        return
    if not result.opponent_found:
        print("opponent scouting screen was not verified", file=sys.stderr)
        sys.exit(2)
    if args.stay:
        print("opponent found and verified; scouting screen left open")
    elif result.returned_home:
        print("opponent found and verified; exited safely without deploying troops")
    else:
        print("opponent found, but safe return home was not verified", file=sys.stderr)
        sys.exit(2)


def cmd_check_upgrade_ui(args: argparse.Namespace) -> None:
    """Open upgrade details and verify controls without confirming a spend."""
    from . import vision
    from .upgrades import (BuildingRecognizer, ReferenceCatalog, SafeIdleTouch,
                           UpgradeUi)

    client = adb_client.AdbClient(args.serial)
    human = HumanInput(client)
    catalog = ReferenceCatalog(args.catalog)
    targets = [
        target for target in BuildingRecognizer(catalog).find(
            vision.capture(client)
        ) if target.category == args.category
    ]
    if not targets:
        print(f"no {args.category!r} building found", file=sys.stderr)
        sys.exit(2)
    target = max(targets, key=lambda item: item.score)
    print(f"selecting {target.name} at ({target.x}, {target.y}), score={target.score:.3f}")
    human.tap(target.x, target.y, radius=target.radius)
    ui = UpgradeUi(catalog)
    selected = vision.capture(client)
    hammer = ui.find_hammer(selected)
    if hammer is None:
        human.wait(0.7, 1.0)
        selected = vision.capture(client)
        hammer = ui.find_hammer(selected)
    if hammer is None:
        # ADB/emulator occasionally drops a touch while rendering. A second
        # verified building tap is safer than guessing at toolbar coordinates.
        human.tap(target.x, target.y, radius=max(5.0, target.radius * 0.65))
        selected = vision.capture(client)
        hammer = ui.find_hammer(selected)
    if hammer is None:
        print("upgrade hammer was not recognized", file=sys.stderr)
        sys.exit(2)
    print(f"upgrade hammer verified at {hammer.center}, score={hammer.score:.3f}")
    human.tap(*hammer.center, radius=max(6.0, min(hammer.w, hammer.h) * 0.20))
    details = vision.capture(client)
    confirm = ui.find_resource_confirm(details)
    client.back()
    human.wait(0.5, 0.8)
    base = vision.capture(client)
    safe = SafeIdleTouch().point(base)
    if safe is not None:
        human.tap(*safe, radius=4.0)
    if confirm is None:
        print("upgrade resource confirmation was not available/recognized", file=sys.stderr)
        sys.exit(2)
    print(
        f"resource confirmation verified at {confirm.center}, "
        f"score={confirm.score:.3f}; not clicked"
    )


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

    p = sub.add_parser(
        "menu-capture",
        help="capture a labeled menu screen and optionally record how it was reached",
    )
    p.add_argument("serial")
    p.add_argument("session", help="dataset/session name, e.g. th2_menus")
    p.add_argument("state", help="current screen name, e.g. army_overview")
    p.add_argument("--description", default="", help="what is visible or what this menu does")
    p.add_argument("--after", help="previous state name")
    p.add_argument("--action", help="action taken in the previous state")
    p.add_argument("--root", default="captures/menus", help="menu dataset directory")
    p.set_defaults(func=cmd_menu_capture)

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

    for command, direction in (("zoom-in", "in"), ("zoom-out", "out")):
        p = sub.add_parser(command, help=f"visually verified camera zoom {direction}")
        p.add_argument("serial")
        p.add_argument("--steps", type=int, default=1)
        p.add_argument("--catalog", default="assets/buildings.json")
        p.add_argument("--backend", choices=("multitouch", "memu", "windows", "android"), default="multitouch")
        p.add_argument("--memu-instance", type=int)
        p.add_argument("--window-title", default="MEmu")
        p.set_defaults(func=cmd_zoom, direction=direction)

    p = sub.add_parser("normalize-zoom", help="move camera toward a known mapping scale")
    p.add_argument("serial")
    p.add_argument("--target", type=float, default=0.80)
    p.add_argument("--max-steps", type=int, default=6)
    p.add_argument("--catalog", default="assets/buildings.json")
    p.add_argument("--backend", choices=("multitouch", "memu", "windows", "android"), default="multitouch")
    p.add_argument("--memu-instance", type=int)
    p.add_argument("--window-title", default="MEmu")
    p.set_defaults(func=cmd_normalize_zoom)

    for command, direction in (("pan-up", "up"), ("pan-down", "down"),
                               ("pan-left", "left"), ("pan-right", "right")):
        p = sub.add_parser(command, help=f"move the village camera {direction} and verify it")
        p.add_argument("serial")
        p.add_argument("--distance", type=float, default=0.22)
        p.set_defaults(func=cmd_pan_camera, direction=direction)

    p = sub.add_parser("map-base", help="scan several camera positions into one base map")
    p.add_argument("serial")
    p.add_argument("session")
    p.add_argument("--route", default="right,left,up,down")
    p.add_argument("--zoom-target", type=float, default=0.55)
    p.add_argument("--zoom-steps", type=int, default=6)
    p.add_argument("--skip-zoom-normalize", action="store_true")
    p.add_argument("--catalog", default="assets/buildings.json")
    p.add_argument("--root", default="captures/maps")
    p.set_defaults(func=cmd_map_base)

    p = sub.add_parser("find-building", help="search camera views for a building category")
    p.add_argument("serial")
    p.add_argument("category", help="e.g. town_hall, gold_mine, elixir_collector")
    p.add_argument("--route", default="right,left,up,down")
    p.add_argument("--catalog", default="assets/buildings.json")
    p.add_argument("--tap", action="store_true", help="tap the best verified detection")
    p.set_defaults(func=cmd_find_building)

    p = sub.add_parser("open-attack", help="visually verify and open the Attack menu")
    p.add_argument("serial")
    p.set_defaults(func=cmd_open_attack)

    p = sub.add_parser("find-match", help="open and optionally confirm multiplayer search")
    p.add_argument("serial")
    p.add_argument("--confirm", action="store_true",
                   help="spend the displayed search cost and find an opponent")
    p.add_argument("--stay", action="store_true",
                   help="leave opponent scouting open; deployment countdown continues")
    p.set_defaults(func=cmd_find_match)

    p = sub.add_parser("check-upgrade-ui",
                       help="verify hammer and resource button without upgrading")
    p.add_argument("serial")
    p.add_argument("--category", default="gold_mine")
    p.add_argument("--catalog", default="assets/buildings.json")
    p.set_defaults(func=cmd_check_upgrade_ui)

    p = sub.add_parser("anti-afk", help="periodically touch verified empty home-village grass")
    p.add_argument("serial")
    p.add_argument("--loops", type=int, default=0, help="0 runs until Ctrl+C")
    p.add_argument("--interval-min", type=float, default=35.0)
    p.add_argument("--interval-max", type=float, default=65.0)
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(func=cmd_anti_afk)

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
