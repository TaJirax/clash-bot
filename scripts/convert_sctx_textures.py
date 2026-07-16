"""Decode current Supercell SCTX containers to PNG with provenance."""

from __future__ import annotations

import argparse
import hashlib
import json
import struct
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path


def hash_file(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def output_path(source: Path, source_root: Path, output_root: Path) -> Path:
    return (output_root / source.relative_to(source_root)).with_suffix(".png")


def parse_sctx_header(path: Path) -> dict:
    """Read stable scalar fields without rejecting unknown union extensions."""
    data = path.read_bytes()
    header_length = struct.unpack_from("<I", data, 0)[0]
    header = memoryview(data)[4:4 + header_length]
    if len(header) != header_length or bytes(header[4:8]) != b"SCTX":
        raise ValueError("invalid SCTX header")
    table = struct.unpack_from("<I", header, 0)[0]
    vtable = table - struct.unpack_from("<i", header, table)[0]
    vtable_length = struct.unpack_from("<H", header, vtable)[0]

    def scalar(field: int, fmt: str, default: int = 0) -> int:
        entry = vtable + 4 + field * 2
        if entry + 2 > vtable + vtable_length:
            return default
        offset = struct.unpack_from("<H", header, entry)[0]
        return default if offset == 0 else struct.unpack_from(fmt, header, table + offset)[0]

    return {
        "header_length": header_length,
        "unknown_1": scalar(0, "<H"),
        "pixel_type": scalar(1, "<I"),
        "width": scalar(2, "<H"),
        "height": scalar(3, "<H"),
        "levels_count": scalar(4, "<B", 1),
        "unknown_3": scalar(5, "<B"),
        "flags": scalar(6, "<I"),
        "texture_length": scalar(7, "<i"),
        "unknown_5": scalar(8, "<B"),
        "unknown_6": scalar(9, "<B"),
        "vtable_fields": max(0, (vtable_length - 4) // 2),
    }


ASTC_BLOCKS = {
    186: (4, 4), 187: (5, 4), 188: (5, 5), 189: (6, 5), 190: (6, 6),
    192: (8, 5), 193: (8, 6), 194: (8, 8), 195: (10, 5), 196: (10, 6),
    197: (10, 8), 198: (10, 10), 199: (12, 10), 200: (12, 12),
    204: (4, 4), 205: (5, 4), 206: (5, 5), 207: (6, 5), 208: (6, 6),
    210: (8, 5), 211: (8, 6), 212: (8, 8), 213: (10, 5), 214: (10, 6),
    215: (10, 8), 216: (10, 10), 217: (12, 10), 218: (12, 12),
}


def three_byte_le(value: int) -> bytes:
    return value.to_bytes(3, "little")


def extract_astc(path: Path) -> tuple[bytes, dict]:
    info = parse_sctx_header(path)
    block = ASTC_BLOCKS.get(info["pixel_type"])
    if block is None or info["levels_count"] != 1:
        raise ValueError("SCTX is not a supported single-level ASTC texture")
    data = path.read_bytes()
    position = 4 + info["header_length"]
    mip_metadata_length = struct.unpack_from("<I", data, position)[0]
    position += 4 + mip_metadata_length
    if info["flags"] & 8:
        position = (position + 15) & ~15
    if info["flags"] & 1:
        try:
            import zstandard
        except ImportError as error:
            raise ValueError("compressed SCTX requires the SC2FLA tool environment") from error
        payload = zstandard.ZstdDecompressor().decompress(
            data[position:], max_output_size=info["texture_length"]
        )
    else:
        end = position + info["texture_length"]
        payload = data[position:end]
    expected = (
        ((info["width"] + block[0] - 1) // block[0])
        * ((info["height"] + block[1] - 1) // block[1]) * 16
    )
    if len(payload) != info["texture_length"] or len(payload) != expected:
        raise ValueError("ASTC payload length does not match dimensions")
    astc_header = (
        b"\x13\xab\xa1\x5c" + bytes((block[0], block[1], 1))
        + three_byte_le(info["width"]) + three_byte_le(info["height"])
        + three_byte_le(1)
    )
    return astc_header + payload, info


def decode_one(executable: Path, pvr_tool: Path, source: Path,
               source_root: Path, output_root: Path) -> dict:
    target = output_path(source, source_root, output_root)
    target.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [str(executable), "decode", "-t", str(source.resolve()), str(target.resolve())],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    record = {
        "source": source.as_posix(),
        "relative_source": source.relative_to(source_root).as_posix(),
        "source_sha256": hash_file(source),
        "exit_code": result.returncode,
    }
    decoder = "sctx_converter"
    fallback_error = ""
    if result.returncode != 0 or not target.is_file():
        try:
            astc, header = extract_astc(source)
            with tempfile.TemporaryDirectory(prefix="clashbot-sctx-") as temporary:
                astc_path = Path(temporary) / "texture.astc"
                astc_path.write_bytes(astc)
                fallback = subprocess.run(
                    [str(pvr_tool), "-i", str(astc_path), "-d", str(target.resolve()),
                     "-ics", "sRGB", "-noout"],
                    capture_output=True, text=True, encoding="utf-8", errors="replace",
                )
            if fallback.returncode == 0 and target.is_file():
                result = fallback
                decoder = "pvrtextool_astc_fallback"
                record["parsed_header"] = header
            else:
                fallback_error = (fallback.stderr or fallback.stdout)[-2000:]
        except (ValueError, OSError, struct.error) as error:
            fallback_error = str(error)

    if result.returncode == 0 and target.is_file():
        record.update({
            "output": target.relative_to(output_root).as_posix(),
            "bytes": target.stat().st_size,
            "output_sha256": hash_file(target),
            "decoder": decoder,
        })
    else:
        record.update({
            "error": "decode_failed",
            "stderr": result.stderr[-2000:],
            "stdout": result.stdout[-2000:],
            "fallback_error": fallback_error,
        })
    return record


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("--executable", type=Path,
                        default=Path(".tools/sc2-decoder/bin/SctxConverter.exe"))
    parser.add_argument("--output", type=Path,
                        default=Path("assets/derived_cache/sctx_png"))
    parser.add_argument("--pvr-tool", type=Path,
                        default=Path("assets/source_cache/github/sc2fla_foss/lib/PVRTexToolCLI.exe"))
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    source_root = args.input if args.input.is_dir() else args.input.parent
    sources = sorted(args.input.rglob("*.sctx")) if args.input.is_dir() else [args.input]
    if args.limit is not None:
        sources = sources[:args.limit]
    executable = args.executable.resolve()
    pvr_tool = args.pvr_tool.resolve()
    if not executable.is_file() or not pvr_tool.is_file():
        raise SystemExit("SCTX converter or PVR texture decoder is missing")
    args.output.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as executor:
        records = list(executor.map(
            lambda source: decode_one(executable, pvr_tool, source, source_root, args.output),
            sources,
        ))
    version = subprocess.run(
        [str(executable), "--version"], capture_output=True, text=True,
        encoding="utf-8", errors="replace",
    ).stdout.strip()
    manifest = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "tool": str(args.executable),
        "tool_sha256": hash_file(executable),
        "tool_version": version,
        "pvr_tool": str(args.pvr_tool),
        "pvr_tool_sha256": hash_file(pvr_tool),
        "converted": sum("output" in record for record in records),
        "failed": sum("output" not in record for record in records),
        "records": records,
    }
    (args.output / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    print(f"converted {manifest['converted']}/{len(records)} SCTX textures -> {args.output}")
    if manifest["failed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
