"""Capture Clash of Clans Wiki reference pages in a visible browser.

This is a polite, resumable reference collector. It does not bypass Cloudflare:
when a verification page appears, the script leaves Opera visible and waits
for the user to solve it and press Enter in the terminal.

Default scope covers permanent army and village content. Add more MediaWiki
categories with repeated ``--category`` options when needed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
from collections import deque
from pathlib import Path
from urllib.parse import quote, urlencode


BASE_URL = "https://clashofclans.fandom.com"
DEFAULT_CATEGORIES = (
    "Troops",
    "Heroes",
    "Spells",
    "Siege Machines",
    "Pets",
    "Buildings",
    "Traps",
)
CHALLENGE_MARKERS = (
    "verify you are human",
    "performing security verification",
    "checking your browser",
    "just a moment",
    "attention required",
    "cf-chl-",
)


def find_opera() -> Path | None:
    """Return the first installed Opera/Opera GX executable we can find."""
    roots = [
        Path(os.environ.get("LOCALAPPDATA", "")),
        Path(os.environ.get("PROGRAMFILES", "")),
        Path(os.environ.get("PROGRAMFILES(X86)", "")),
    ]
    relative_paths = (
        Path("Programs/Opera GX/opera.exe"),
        Path("Programs/Opera/opera.exe"),
        Path("Opera GX/opera.exe"),
        Path("Opera/opera.exe"),
    )
    for root in roots:
        if not str(root):
            continue
        for relative in relative_paths:
            candidate = root / relative
            if candidate.is_file():
                return candidate
    return None


def safe_name(title: str) -> str:
    readable = re.sub(r"[^a-zA-Z0-9._-]+", "_", title).strip("._-") or "page"
    digest = hashlib.sha1(title.encode("utf-8")).hexdigest()[:8]
    return f"{readable[:80]}_{digest}"


def load_json(path: Path, default):
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def save_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    temporary.replace(path)


def challenge_visible(page) -> bool:
    try:
        title = page.title().casefold()
        text = page.locator("body").inner_text(timeout=2_000).casefold()[:8_000]
        content = f"{title}\n{text}"
        return any(marker in content for marker in CHALLENGE_MARKERS)
    except Exception:
        return False


def wait_for_manual_verification(page) -> None:
    if not challenge_visible(page):
        return
    print("\nCloudflare/security verification detected.")
    print("Complete it in the visible browser. Do not close the browser window.")
    while challenge_visible(page):
        input("Press Enter after verification is complete... ")
        page.wait_for_timeout(1_000)


def navigate(page, url: str, timeout_ms: int) -> None:
    page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
    wait_for_manual_verification(page)
    try:
        page.wait_for_load_state("networkidle", timeout=min(timeout_ms, 12_000))
    except Exception:
        pass  # Fandom often keeps analytics/ad requests alive.


def category_members(page, category: str, timeout_ms: int) -> list[dict]:
    members: list[dict] = []
    continuation: str | None = None
    while True:
        params = {
            "action": "query",
            "list": "categorymembers",
            "cmtitle": f"Category:{category}",
            "cmnamespace": "0|14",
            "cmlimit": "max",
            "format": "json",
            "formatversion": "2",
        }
        if continuation:
            params["cmcontinue"] = continuation
        url = f"{BASE_URL}/api.php?{urlencode(params)}"
        navigate(page, url, timeout_ms)
        raw = page.locator("body").inner_text(timeout=timeout_ms).strip()
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as error:
            raise RuntimeError(
                f"Wiki API did not return JSON for Category:{category}. "
                "Complete any visible verification and retry."
            ) from error
        members.extend(payload.get("query", {}).get("categorymembers", []))
        continuation = payload.get("continue", {}).get("cmcontinue")
        if not continuation:
            return members


def discover_titles(page, categories: list[str], depth: int,
                    max_pages: int, timeout_ms: int, delay: float) -> list[str]:
    queue = deque((category.removeprefix("Category:"), 0) for category in categories)
    visited_categories: set[str] = set()
    titles: set[str] = set()
    while queue and len(titles) < max_pages:
        category, level = queue.popleft()
        if category in visited_categories:
            continue
        visited_categories.add(category)
        print(f"Discovering Category:{category} (depth {level})")
        for member in category_members(page, category, timeout_ms):
            namespace = int(member.get("ns", -1))
            title = str(member.get("title", ""))
            if namespace == 0 and title:
                titles.add(title)
                if len(titles) >= max_pages:
                    break
            elif namespace == 14 and level < depth:
                queue.append((title.removeprefix("Category:"), level + 1))
        time.sleep(delay)
    return sorted(titles)


def apply_capture_style(page, zoom: float) -> None:
    # CSS zoom is deterministic at exactly 130%, unlike browser Ctrl+Plus,
    # whose discrete levels typically jump from 125% to 150%.
    page.add_style_tag(content=f"""
        html {{ zoom: {zoom}; }}
        .global-navigation, .fandom-sticky-header, .top-ads-container,
        .bottom-ads-container, .ad-slot-placeholder, .rail-module,
        #WikiaBar, .global-footer {{ display: none !important; }}
    """)


def capture_page(page, title: str, output: Path, zoom: float,
                 timeout_ms: int, min_image_size: int) -> dict:
    slug = safe_name(title)
    directory = output / "pages" / slug
    images_directory = directory / "images"
    directory.mkdir(parents=True, exist_ok=True)
    images_directory.mkdir(parents=True, exist_ok=True)

    encoded_title = quote(title.replace(" ", "_"), safe="()_',-!")
    url = f"{BASE_URL}/wiki/{encoded_title}"
    navigate(page, url, timeout_ms)
    apply_capture_style(page, zoom)
    page.wait_for_timeout(750)

    content = page.locator(".mw-parser-output").first
    if not content.is_visible(timeout=5_000):
        content = page.locator("#mw-content-text").first
    try:
        content.screenshot(path=str(directory / "page.png"), timeout=timeout_ms)
    except Exception:
        page.screenshot(path=str(directory / "page.png"), full_page=True,
                        timeout=timeout_ms)

    captured_images: list[dict] = []
    image_locators = content.locator("img")
    count = image_locators.count()
    for index in range(count):
        image = image_locators.nth(index)
        try:
            image.scroll_into_view_if_needed(timeout=3_000)
            info = image.evaluate("""element => ({
                alt: element.alt || '',
                src: element.currentSrc || element.src || '',
                width: element.naturalWidth || element.width || 0,
                height: element.naturalHeight || element.height || 0
            })""")
            if min(info["width"], info["height"]) < min_image_size:
                continue
            name = safe_name(info["alt"] or f"image_{index:04d}")
            relative = f"images/{index:04d}_{name}.png"
            image.screenshot(path=str(directory / relative), timeout=8_000)
            captured_images.append({**info, "file": relative})
        except Exception as error:
            captured_images.append({"index": index, "error": str(error)[:300]})

    record = {
        "title": title,
        "url": page.url,
        "zoom": zoom,
        "page_screenshot": "page.png",
        "images": captured_images,
        "captured_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    save_json(directory / "metadata.json", record)
    return record


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("assets/wiki_reference"))
    parser.add_argument("--browser", choices=("opera", "chromium"), default="opera",
                        help="browser to launch (default: installed Opera/Opera GX)")
    parser.add_argument("--opera-path", type=Path,
                        help="path to opera.exe when automatic detection fails")
    parser.add_argument("--cdp-url",
                        help="attach to Opera started with --remote-debugging-port, "
                             "for example http://127.0.0.1:9222")
    parser.add_argument("--category", action="append", default=[],
                        help="MediaWiki category; repeat for several")
    parser.add_argument("--category-depth", type=int, default=1)
    parser.add_argument("--zoom", type=float, default=1.30)
    parser.add_argument("--delay", type=float, default=2.0,
                        help="minimum seconds between wiki pages")
    parser.add_argument("--max-pages", type=int, default=750)
    parser.add_argument("--min-image-size", type=int, default=40)
    parser.add_argument("--timeout", type=int, default=45,
                        help="navigation timeout in seconds")
    parser.add_argument("--headless", action="store_true",
                        help="not recommended; manual verification is unavailable")
    parser.add_argument("--refresh", action="store_true",
                        help="capture pages again even if already complete")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not 1.0 <= args.zoom <= 2.0:
        raise SystemExit("--zoom must be between 1.0 and 2.0")
    if args.delay < 1.0:
        raise SystemExit("--delay must be at least 1 second")
    if args.category_depth not in range(0, 4):
        raise SystemExit("--category-depth must be 0, 1, 2, or 3")

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("Playwright is not installed.", file=sys.stderr)
        print("Run: python -m pip install -e .[wiki-capture]", file=sys.stderr)
        print("Chromium only: python -m playwright install chromium", file=sys.stderr)
        return 2

    opera_path = args.opera_path.resolve() if args.opera_path else find_opera()
    if args.browser == "opera" and not args.cdp_url:
        if opera_path is None or not opera_path.is_file():
            raise SystemExit(
                "Opera was not found. Pass --opera-path C:\\path\\to\\opera.exe, "
                "or use --browser chromium."
            )
        print(f"Using Opera: {opera_path}")

    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    manifest_path = output / "manifest.json"
    manifest = load_json(manifest_path, {
        "schema_version": 1,
        "source": BASE_URL,
        "zoom": args.zoom,
        "browser": args.browser,
        "pages": {},
    })
    categories = args.category or list(DEFAULT_CATEGORIES)

    with sync_playwright() as playwright:
        attached_browser = None
        if args.cdp_url:
            print(f"Attaching to Opera at {args.cdp_url}")
            attached_browser = playwright.chromium.connect_over_cdp(args.cdp_url)
            if not attached_browser.contexts:
                raise RuntimeError("The attached Opera instance has no browser context")
            context = attached_browser.contexts[0]
        else:
            executable_path = str(opera_path) if args.browser == "opera" else None
            profile_name = ".opera-profile" if args.browser == "opera" else ".browser-profile"
            context = playwright.chromium.launch_persistent_context(
                user_data_dir=str(output / profile_name),
                executable_path=executable_path,
                headless=args.headless,
                viewport={"width": 1600, "height": 1000},
                device_scale_factor=2,
                args=["--disable-blink-features=AutomationControlled"],
            )

        # Always use tabs created by this script. In attach mode this ensures
        # personal tabs and their navigation state remain untouched.
        controller = context.new_page()
        controller.set_default_timeout(args.timeout * 1_000)
        try:
            navigate(
                controller,
                f"{BASE_URL}/wiki/Clash_of_Clans_Wiki",
                args.timeout * 1_000,
            )
            titles = discover_titles(
                controller, categories, args.category_depth, args.max_pages,
                args.timeout * 1_000, args.delay,
            )
            save_json(output / "discovered_pages.json", {
                "categories": categories,
                "titles": titles,
            })
            total = len(titles)
            for number, title in enumerate(titles, start=1):
                if title in manifest["pages"] and not args.refresh:
                    print(f"[{number}/{total}] skip {title}")
                    continue
                print(f"[{number}/{total}] capture {title}")
                capture_tab = context.new_page()
                capture_tab.set_default_timeout(args.timeout * 1_000)
                try:
                    record = capture_page(
                        capture_tab, title, output, args.zoom,
                        args.timeout * 1_000,
                        args.min_image_size,
                    )
                    manifest["pages"][title] = record
                    save_json(manifest_path, manifest)
                except KeyboardInterrupt:
                    raise
                except Exception as error:
                    print(f"  failed: {error}", file=sys.stderr)
                    manifest.setdefault("errors", {})[title] = str(error)[:500]
                    save_json(manifest_path, manifest)
                finally:
                    capture_tab.close()
                time.sleep(args.delay)
        finally:
            controller.close()
            if attached_browser is None:
                context.close()

    print(f"Captured {len(manifest['pages'])} page(s) under {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
