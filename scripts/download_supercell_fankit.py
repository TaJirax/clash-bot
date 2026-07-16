"""Download original PNG assets from Supercell's public Clash of Clans fan kit.

The script uses the same public listing and original-file download endpoints as
the fan-kit page. It is resumable and stores source metadata plus SHA-256 hashes
in a manifest beside the downloaded files.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import http.client
import json
import os
import re
import shutil
import sys
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


BASE_URL = "https://fankit.supercell.com"
DOCUMENT_ID = 338
SOURCE_PAGE = f"{BASE_URL}/d/vkEdmkUCngKw/game-assets"
SEARCH_URL = f"{BASE_URL}/api/assets/search/{DOCUMENT_ID}"
DOWNLOAD_URL = f"{BASE_URL}/api/screen/download"
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
JPEG_SIGNATURE = b"\xff\xd8\xff"
USER_AGENT = "clash-bot-fankit-downloader/1.0"

# Every current Asset Type exposed by the public Clash of Clans fan kit.
DEFAULT_CATEGORIES = (
    "App Icons",
    "Banners",
    "Builder Base",
    "Buildings",
    "Characters",
    "Clan Capital",
    "Clan Shields",
    "Clash-A-Rama!",
    "Decorations",
    "Hero Equipment",
    "Hero Pets",
    "Hero Skins",
    "Home Village",
    "Icons",
    "League Icons",
    "Loading Screens",
    "Magic Items",
    "Mega Troops",
    "Music & SFX",
    "Obstacles",
    "Resources",
    "Sceneries",
    "Seasonal/Temporary Units",
    "Siege Machines",
    "Spells",
    "Super Troops",
    "Town Hall/Builder Hall/Capital Hall",
    "Guardian",
    "Memes",
    "Defences",
)


def safe_name(value: str, fallback: str = "asset") -> str:
    value = re.sub(r"[<>:\"/\\|?*\x00-\x1f]+", "_", value)
    value = re.sub(r"\s+", " ", value).strip(" ._")
    return (value or fallback)[:120]


def extract_level(title: str) -> int | None:
    explicit = re.search(r"(?:level|lvl)[ _-]*(\d+)(?:\D*)$", title, re.IGNORECASE)
    if explicit:
        return int(explicit.group(1))
    trailing = re.search(r"(?:_|-|\s)(\d+)$", title.strip())
    return int(trailing.group(1)) if trailing else None


def building_group(title: str) -> str:
    value = re.sub(
        r"^(?:Building|Defence|Defense)_(?:HV|BB|CC|CAT)?_?",
        "",
        title,
        flags=re.IGNORECASE,
    )
    value = re.sub(r"(?:_|-|\s)*(?:level|lvl)[ _-]*\d+(?:\D*)$", "", value,
                   flags=re.IGNORECASE)
    value = re.sub(r"(?:_|-|\s)\d+$", "", value)
    value = value.replace("_", " ").strip()
    return safe_name(value, "Unsorted Building")


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def save_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2, ensure_ascii=False, sort_keys=True)
        handle.write("\n")
    for attempt in range(20):
        try:
            temporary.replace(path)
            return
        except PermissionError:
            if attempt == 19:
                raise
            time.sleep(0.05 * (attempt + 1))


def request_bytes(url: str, timeout: int, retries: int) -> tuple[bytes, str]:
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            request = Request(url, headers={"User-Agent": USER_AGENT})
            with urlopen(request, timeout=timeout) as response:
                return response.read(), response.headers.get("Content-Type", "")
        except (
            HTTPError,
            URLError,
            TimeoutError,
            ConnectionError,
            http.client.HTTPException,
        ) as error:
            last_error = error
            if attempt >= retries:
                break
            time.sleep(min(2 ** attempt, 8))
    raise RuntimeError(f"request failed after {retries + 1} attempt(s): {url}") from last_error


def request_json(url: str, timeout: int, retries: int) -> dict[str, Any]:
    body, _ = request_bytes(url, timeout, retries)
    try:
        result = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RuntimeError(f"server did not return JSON: {url}") from error
    if not result.get("success"):
        raise RuntimeError(f"fan-kit API rejected request: {result}")
    return result


def search_url(category: str, page: int, page_size: int,
               facet_key: str = "asset-type97") -> str:
    query = urlencode({
        "limit": page_size,
        "page": page,
        "order": "NEWEST",
        facet_key: category,
    })
    return f"{SEARCH_URL}?{query}"


def asset_path(output: Path, category: str, asset: dict[str, Any],
               namespace: str | None = None) -> Path:
    folder = output
    if namespace:
        folder /= safe_name(namespace, "Groups")
    folder /= safe_name(category, "Uncategorized")
    title = safe_name(str(asset.get("title") or "asset"))
    level = extract_level(str(asset.get("title") or ""))
    if namespace == "Characters":
        folder /= f"Level {level}" if level is not None else "Unsorted"
    elif namespace == "Asset Types" and category.casefold() == "buildings":
        folder /= building_group(str(asset.get("title") or ""))
        folder /= f"Level {level}" if level is not None else "Unsorted"
    return folder / f"{title}__{int(asset['id'])}.png"


def discover_facets(timeout: int, retries: int) -> dict[str, list[str]]:
    payload = request_json(
        f"{SEARCH_URL}?{urlencode({'limit': 1, 'page': 1, 'order': 'NEWEST'})}",
        timeout,
        retries,
    )
    result: dict[str, list[str]] = {}
    for facet in payload.get("facettes", []):
        key = str(facet.get("key") or "")
        if not key:
            continue
        result[key] = [
            str(item.get("value") or item.get("name"))
            for item in facet.get("items", [])
            if item.get("display", True) and (item.get("value") or item.get("name"))
        ]
    return result


def ensure_png(body: bytes, content_type: str) -> tuple[bytes, str | None]:
    if body.startswith(PNG_SIGNATURE):
        return body, None
    import cv2
    import numpy as np

    if body.startswith(JPEG_SIGNATURE):
        source_format = "jpeg"
    elif body.startswith((b"GIF87a", b"GIF89a")):
        source_format = "gif"
    elif body.startswith(b"RIFF") and body[8:12] == b"WEBP":
        source_format = "webp"
    elif body.startswith((b"II*\x00", b"MM\x00*")):
        source_format = "tiff"
    elif body.startswith(b"BM"):
        source_format = "bmp"
    else:
        source_format = "unknown-image"

    image = cv2.imdecode(np.frombuffer(body, dtype=np.uint8), cv2.IMREAD_UNCHANGED)
    if image is None:
        raise RuntimeError(
            f"could not decode {source_format} bytes "
            f"(Content-Type: {content_type or 'unknown'})"
        )
    encoded, png = cv2.imencode(".png", image, [cv2.IMWRITE_PNG_COMPRESSION, 9])
    if not encoded:
        raise RuntimeError(f"could not convert {source_format} asset to PNG")
    return png.tobytes(), source_format


def download_asset(asset: dict[str, Any], destination: Path,
                   timeout: int, retries: int) -> tuple[int, str, str | None]:
    token = str(asset.get("token") or "")
    if not token:
        raise RuntimeError(f"asset {asset.get('id')} has no download token")
    body, content_type = request_bytes(f"{DOWNLOAD_URL}/{token}", timeout, retries)
    body, converted_from = ensure_png(body, content_type)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".part")
    temporary.write_bytes(body)
    temporary.replace(destination)
    return len(body), hashlib.sha256(body).hexdigest(), converted_from


def add_category_file(source: Path, destination: Path) -> None:
    """Expose an already-downloaded asset in another category without waste."""
    if destination.is_file() or source.resolve() == destination.resolve():
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.link(source, destination)
    except OSError:
        shutil.copy2(source, destination)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path,
                        default=Path("assets/supercell_fankit"))
    parser.add_argument("--category", action="append", default=[],
                        help="Asset Type value; repeat to override discovered types")
    parser.add_argument("--character", action="append", default=[],
                        help="Characters value; repeat to override discovered characters")
    parser.add_argument("--skip-asset-types", action="store_true")
    parser.add_argument("--skip-characters", action="store_true")
    parser.add_argument("--page-size", type=int, default=100)
    parser.add_argument("--delay", type=float, default=0.2,
                        help="seconds between original-file downloads")
    parser.add_argument("--timeout", type=int, default=60)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--workers", type=int, default=4,
                        help="parallel original-file downloads (1-8)")
    parser.add_argument("--max-assets", type=int, default=0,
                        help="stop after this many PNGs; 0 downloads all")
    parser.add_argument("--refresh", action="store_true",
                        help="download existing files again")
    parser.add_argument("--dry-run", action="store_true",
                        help="enumerate PNGs without downloading them")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not 1 <= args.page_size <= 100:
        raise SystemExit("--page-size must be between 1 and 100")
    if args.delay < 0:
        raise SystemExit("--delay cannot be negative")
    if args.max_assets < 0:
        raise SystemExit("--max-assets cannot be negative")
    if not 1 <= args.workers <= 8:
        raise SystemExit("--workers must be between 1 and 8")

    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    manifest_path = output / "manifest.json"
    manifest = load_json(manifest_path, {
        "schema_version": 1,
        "source": SOURCE_PAGE,
        "document_id": DOCUMENT_ID,
        "assets": {},
        "errors": {},
    })
    facets = discover_facets(args.timeout, args.retries)
    categories = args.category or facets.get("asset-type97") or list(DEFAULT_CATEGORIES)
    characters = args.character or facets.get("characters16", [])
    work: list[tuple[str, str, str]] = []
    if not args.skip_asset_types:
        work.extend(("Asset Types", "asset-type97", value) for value in categories)
    if not args.skip_characters:
        work.extend(("Characters", "characters16", value) for value in characters)
    if not work:
        raise SystemExit("both filter groups were skipped")
    handled = 0
    discovered = 0

    for group_number, (namespace, facet_key, category) in enumerate(work, start=1):
        print(f"[{group_number}/{len(work)}] {namespace} / {category}")
        page = 1
        while True:
            payload = request_json(
                search_url(category, page, args.page_size, facet_key),
                args.timeout,
                args.retries,
            )
            assets = payload.get("data", [])
            if not isinstance(assets, list):
                raise RuntimeError("fan-kit API returned an unexpected asset list")
            print(f"  page {page}: {len(assets)} records (category total {payload.get('total')})")

            pending: list[tuple[dict[str, Any], Path, dict[str, Any] | None]] = []
            for asset in assets:
                if str(asset.get("ext", "")).casefold() != "png":
                    continue
                asset_id = str(asset["id"])
                discovered += 1
                destination = asset_path(output, category, asset, namespace)
                existing = manifest["assets"].get(asset_id)
                if existing:
                    existing_file = existing.get("file")
                    groups = existing.setdefault("groups", {})
                    group_values = groups.setdefault(namespace, [])
                    if category not in group_values:
                        group_values.append(category)
                    if namespace == "Asset Types":
                        known_categories = existing.setdefault("categories", [])
                        if category not in known_categories:
                            known_categories.append(category)
                    primary = output / str(existing_file) if existing_file else None
                    if primary and primary.is_file() and not args.refresh:
                        manifest["errors"].pop(asset_id, None)
                        add_category_file(primary, destination)
                        files = existing.setdefault("files", [str(existing_file)])
                        relative = destination.relative_to(output).as_posix()
                        if relative not in files:
                            files.append(relative)
                        save_json(manifest_path, manifest)

                if args.dry_run:
                    print(f"    PNG {asset_id}: {asset.get('title')}")
                    handled += 1
                elif existing and destination.is_file() and not args.refresh:
                    print(f"    skip {destination.name}")
                    handled += 1
                else:
                    print(f"    download {destination.name}")
                    pending.append((asset, destination, existing))

                if args.max_assets and handled >= args.max_assets:
                    save_json(manifest_path, manifest)
                    print(f"Stopped at --max-assets {args.max_assets}")
                    return 0

            if args.max_assets:
                pending = pending[:max(0, args.max_assets - handled)]

            with ThreadPoolExecutor(max_workers=args.workers) as executor:
                futures = {
                    executor.submit(
                        download_asset, asset, destination, args.timeout, args.retries,
                    ): (asset, destination, existing)
                    for asset, destination, existing in pending
                }
                for future in as_completed(futures):
                    asset, destination, existing = futures[future]
                    asset_id = str(asset["id"])
                    try:
                        size, digest, converted_from = future.result()
                        record = {
                            key: value for key, value in asset.items()
                            if key != "token"
                        }
                        record.update({
                            "categories": sorted(set(
                                (existing or {}).get("categories", [])
                                + ([category] if namespace == "Asset Types" else [])
                            )),
                            "groups": {
                                **(existing or {}).get("groups", {}),
                                namespace: sorted(set(
                                    (existing or {}).get("groups", {}).get(namespace, [])
                                    + [category]
                                )),
                            },
                            "file": destination.relative_to(output).as_posix(),
                            "files": [destination.relative_to(output).as_posix()],
                            "bytes": size,
                            "sha256": digest,
                            "converted_from": converted_from,
                            "downloaded_at": time.strftime(
                                "%Y-%m-%dT%H:%M:%SZ", time.gmtime()
                            ),
                        })
                        manifest["assets"][asset_id] = record
                        manifest["errors"].pop(asset_id, None)
                        save_json(manifest_path, manifest)
                        handled += 1
                    except Exception as error:
                        print(f"      failed: {error}", file=sys.stderr)
                        manifest["errors"][asset_id] = {
                            "title": asset.get("title"),
                            "filter_group": namespace,
                            "filter_value": category,
                            "error": str(error),
                        }
                        save_json(manifest_path, manifest)
                    time.sleep(args.delay)

            if args.max_assets and handled >= args.max_assets:
                save_json(manifest_path, manifest)
                print(f"Stopped at --max-assets {args.max_assets}")
                return 0

            if not payload.get("hasMore") or not assets:
                break
            page += 1

    save_json(manifest_path, manifest)
    print(
        f"Finished: encountered {discovered} PNG record(s); "
        f"manifest contains {len(manifest['assets'])} unique asset(s) in {output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
