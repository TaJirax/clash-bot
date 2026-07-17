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


def cmd_recognize_army(args: argparse.Namespace) -> None:
    """Report learned troop portraits on the current Barracks army screen."""
    from . import vision
    from .army import TroopRecognizer

    scene = vision.decode(adb_client.AdbClient(args.serial).screenshot())
    cards = TroopRecognizer(args.templates, threshold=args.threshold).find(scene)
    if not cards:
        print("no learned troop cards found", file=sys.stderr)
        sys.exit(2)
    for card in cards:
        print(f"{card.name} at ({card.x}, {card.y}), score={card.score:.3f}")


def cmd_check_state(args: argparse.Namespace) -> None:
    """Report the current learned game-menu state without tapping."""
    from . import vision
    from .menus import MenuRecognizer

    state = MenuRecognizer(args.templates, threshold=args.threshold).classify(
        vision.decode(adb_client.AdbClient(args.serial).screenshot())
    )
    if state is None:
        print("current screen is not a learned menu state", file=sys.stderr)
        sys.exit(2)
    print(f"state={state.name}, score={state.score:.3f}")


def cmd_manage_status(args: argparse.Namespace) -> None:
    """Inspect verified base-management evidence without tapping."""
    from . import vision
    from .base_management import BaseManagementInspector, plan_base_management
    from .upgrades import ReferenceCatalog

    status = BaseManagementInspector(ReferenceCatalog(args.catalog)).inspect(
        vision.capture(adb_client.AdbClient(args.serial))
    )
    print(f"recognized_buildings={status.recognized_buildings}")
    print(f"menu_state={status.menu_state or 'none'}")
    print(f"builders_available={status.builders_available if status.builders_available is not None else 'unverified'}")
    print(f"research_available={status.research_available if status.research_available is not None else 'unverified'}")
    print(f"upgrade_affordable={status.upgrade_affordable if status.upgrade_affordable is not None else 'unverified'}")
    print(f"boost_auras={status.boost_auras} (informational; not a click target)")
    print(status.next_step)
    plan = plan_base_management(status)
    print(f"plan_action={plan.action}")
    print(f"plan_reason={plan.reason}")


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


def cmd_scan_base(args: argparse.Namespace) -> None:
    """Let the bot capture and recover its own live base observations."""
    from .autonomy import AutonomousBaseScanner
    from .camera import controller_from_catalog
    from .asset_catalog import AssetCatalog
    from .fankit import FanKitIndex
    from .multitouch import AdbPinchZoom
    from .upgrades import BuildingRecognizer, ReferenceCatalog

    route = [part.strip().lower() for part in args.route.split(",") if part.strip()]
    if any(part not in ("up", "down", "left", "right") for part in route):
        print("route must contain only up, down, left, right", file=sys.stderr)
        sys.exit(2)
    client = adb_client.AdbClient(args.serial)
    catalog = ReferenceCatalog(args.catalog)
    asset_catalog = AssetCatalog(args.derived_assets, args.fankit)
    recognizer = BuildingRecognizer(catalog, asset_catalog=asset_catalog)
    zoom = controller_from_catalog(
        client, args.catalog, actuator=AdbPinchZoom(client)
    )
    # Share recognition state so a measured scale is reused by capture, zoom,
    # and subsequent panned views.
    zoom.recognizer = recognizer
    scanner = AutonomousBaseScanner(
        client,
        recognizer,
        zoom=zoom,
        fankit=FanKitIndex(args.fankit),
        asset_catalog=asset_catalog,
        root=args.root,
    )
    report = scanner.run(
        args.session,
        route=route,
        min_detections=args.min_detections,
        min_categories=args.min_categories,
    )
    print(f"bot captured {len(report.views)} view(s); best=view {report.best_view}")
    print("buildings=" + (", ".join(
        f"{name}:{count}" for name, count in sorted(report.counts.items())
    ) or "none"))
    covered = sum(1 for count in report.reference_assets.values() if count)
    print(
        f"asset-catalog coverage={covered}/{len(report.counts)} detected categories; "
        f"recovery={', '.join(report.recovery_actions) or 'not needed'}"
    )
    if report.blocked_reason:
        print(f"blocked={report.blocked_reason}", file=sys.stderr)
    if report.unresolved_categories:
        print("unresolved=" + ", ".join(report.unresolved_categories))
    print(f"report={scanner.root / args.session / 'report.json'}")


def cmd_asset_status(args: argparse.Namespace) -> None:
    """Show the exact local game-reference data available to bot decisions."""
    from .asset_catalog import AssetCatalog

    catalog = AssetCatalog(args.derived_assets, args.fankit)
    summary = catalog.summary()
    print("assets=" + str(summary["assets"]))
    print("roles=" + ", ".join(
        f"{name}:{count}" for name, count in summary["roles"].items()
    ))
    if not args.label:
        return
    matches = catalog.find(args.label)
    by_role = {}
    for record in matches:
        by_role[record.role] = by_role.get(record.role, 0) + 1
    levels = sorted({record.level for record in matches if record.level is not None})
    print(f"query={args.label}; matches={len(matches)}; roles={by_role}")
    print("levels=" + (",".join(map(str, levels)) if levels else "unknown"))


def cmd_asset_train(args: argparse.Namespace) -> None:
    """Build the local retrieval index used by asset-aware recognition."""
    from pathlib import Path
    from scripts.train_asset_model import train_model

    manifest = train_model(Path(args.derived_assets), Path(args.output))
    print("trained=" + str(manifest["model"]))
    print("samples=" + str(manifest["samples"]))
    print("labels=" + str(manifest["labels"]))
    print("sources=" + ", ".join(
        f"{name}:{count}" for name, count in manifest["sources"].items()
    ))


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


def cmd_check_battle(args: argparse.Namespace) -> None:
    """Report verified opponent-screen controls and currently deployable troops."""
    from .attack import BattleInspector

    result = BattleInspector(adb_client.AdbClient(args.serial)).inspect()
    if not result.verified:
        print("opponent battle screen was not verified", file=sys.stderr)
        sys.exit(2)
    if not result.troops:
        print("opponent screen verified; no learned deployable troops found")
        return
    print("opponent screen verified; deployable troops:")
    for card in result.troops:
        print(f"- {card.name} at ({card.x}, {card.y}), score={card.score:.3f}")


def cmd_loot_attack(args: argparse.Namespace) -> None:
    """Deploy a small verified wave and persist screenshots/events for learning."""
    from .attack_execution import LootAttackExecutor

    try:
        result = LootAttackExecutor(adb_client.AdbClient(args.serial)).run(
            session=args.session, root=args.root, aggressive=args.aggressive,
        )
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(2)
    print(f"deployed {len(result.deployed)} recognised troops: {', '.join(result.deployed)}")
    print(f"attack evidence -> {result.log_path}")


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
    priority = [part.strip() for part in args.priority.split(",") if part.strip()]
    bot = UpgradeBot(client, catalog_path=args.catalog, priority=priority or None)
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


def cmd_play(args: argparse.Namespace) -> None:
    """Run the full collect/manage/upgrade/attack loop."""
    from .player import GamePlayer

    player = GamePlayer(adb_client.AdbClient(args.serial), root=args.root)
    try:
        report = player.run(
            session=args.session,
            cycles=args.cycles,
            interval=args.interval,
            dry_run=args.dry_run,
            attack_mode=args.attack,
            upgrade=not args.no_upgrade,
            battle_timeout=args.battle_timeout,
        )
    except KeyboardInterrupt:
        print("stopped")
        return
    attacks = sum(1 for cycle in report.cycles if cycle.attack_attempted)
    collected = sum(cycle.collected for cycle in report.cycles)
    print(
        f"done: {len(report.cycles)} cycle(s), {collected} bubble(s) collected, "
        f"{attacks} attack attempt(s)"
    )
    print(f"session log -> {report.log_path}")


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

    p = sub.add_parser(
        "scan-base",
        help="autonomously capture, recover camera, and recognize the live base",
    )
    p.add_argument("serial")
    p.add_argument("session")
    p.add_argument("--route", default="right,left,up,down")
    p.add_argument("--catalog", default="assets/buildings.json")
    p.add_argument("--fankit", default="assets/supercell_fankit")
    p.add_argument("--derived-assets", default="assets/derived_cache")
    p.add_argument("--root", default="captures/autonomous")
    p.add_argument("--min-detections", type=int, default=14)
    p.add_argument("--min-categories", type=int, default=8)
    p.set_defaults(func=cmd_scan_base)

    p = sub.add_parser("asset-status", help="report local asset data available to bot scans")
    p.add_argument("--label", help="optional building/unit, e.g. archer or cannon")
    p.add_argument("--fankit", default="assets/supercell_fankit")
    p.add_argument("--derived-assets", default="assets/derived_cache")
    p.set_defaults(func=cmd_asset_status)

    p = sub.add_parser("asset-train", help="train the local asset retrieval index")
    p.add_argument("--derived-assets", default="assets/derived_cache")
    p.add_argument("--output", default="assets/derived_cache/model/asset_retrieval.npz")
    p.set_defaults(func=cmd_asset_train)

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

    p = sub.add_parser("check-battle", help="verify opponent battle HUD and report deployable troops")
    p.add_argument("serial")
    p.set_defaults(func=cmd_check_battle)

    p = sub.add_parser("loot-attack", help="deploy a small verified loot wave and save attack evidence")
    p.add_argument("serial")
    p.add_argument("session", help="unique evidence-log session name")
    p.add_argument("--root", default="captures/attacks")
    p.add_argument("--aggressive", action="store_true",
                   help="deploy a larger recognised wave for a test-account attack")
    p.set_defaults(func=cmd_loot_attack)

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

    p = sub.add_parser("recognize-army", help="report learned troop cards without tapping")
    p.add_argument("serial")
    p.add_argument("--templates", default="assets/templates")
    p.add_argument("--threshold", type=float, default=0.86)
    p.set_defaults(func=cmd_recognize_army)

    p = sub.add_parser("check-state", help="recognize a learned menu state without tapping")
    p.add_argument("serial")
    p.add_argument("--templates", default="assets/templates")
    p.add_argument("--threshold", type=float, default=0.86)
    p.set_defaults(func=cmd_check_state)

    p = sub.add_parser("manage-status", help="report verified base-management state without tapping")
    p.add_argument("serial")
    p.add_argument("--catalog", default="assets/buildings.json")
    p.set_defaults(func=cmd_manage_status)

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
    p.add_argument(
        "--priority",
        default="",
        help="comma-separated upgrade order, e.g. town_hall,gold_storage,cannon",
    )
    p.add_argument("--dry-run", action="store_true",
                   help="recognise and report only; do not tap")
    p.set_defaults(func=cmd_upgrade)

    p = sub.add_parser(
        "play",
        help="run the full collect/manage/upgrade/attack loop in cycles",
    )
    p.add_argument("serial")
    p.add_argument("session", nargs="?", default="play")
    p.add_argument("--cycles", type=int, default=1)
    p.add_argument("--interval", type=float, default=60.0,
                   help="seconds between cycles")
    p.add_argument("--attack", choices=("off", "policy", "always"), default="policy",
                   help="policy attacks only when verified base work is clear")
    p.add_argument("--battle-timeout", type=float, default=180.0,
                   help="seconds to wait for a verified return home after a battle")
    p.add_argument("--no-upgrade", action="store_true",
                   help="skip the upgrade phase even when a builder is free")
    p.add_argument("--root", default="captures/play")
    p.add_argument("--dry-run", action="store_true",
                   help="recognize, plan, and report only; never tap")
    p.set_defaults(func=cmd_play)

    args = parser.parse_args()
    try:
        args.func(args)
    except adb_client.AdbError as e:
        print(f"ADB error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
