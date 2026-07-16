"""Create extraction-only SCTX copies without unknown extension unions.

Only the FlatBuffer header is rebuilt. Mip metadata and the pixel payload are
copied byte-for-byte, allowing older SC tools to verify current texture banks.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import struct
from datetime import datetime, timezone
from pathlib import Path

import flatbuffers

try:
    from scripts.convert_sctx_textures import parse_sctx_header
except ModuleNotFoundError:  # direct execution: python scripts/sanitize_sctx_headers.py
    from convert_sctx_textures import parse_sctx_header


def hash_file(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def stable_header(info: dict) -> bytes:
    builder = flatbuffers.Builder(64)
    # The installed July-2025 decoder schema has eight fields. Newer game
    # builds append three fields/unions; omitting them is sufficient for a
    # read-only extraction copy and preserves the actual texture payload.
    builder.StartObject(8)
    builder.PrependUint16Slot(0, info["unknown_1"], 0)
    builder.PrependUint32Slot(1, info["pixel_type"], 0)
    builder.PrependUint16Slot(2, info["width"], 0)
    builder.PrependUint16Slot(3, info["height"], 0)
    builder.PrependUint8Slot(4, info["levels_count"], 1)
    builder.PrependUint8Slot(5, info["unknown_3"], 0)
    builder.PrependUint32Slot(6, info["flags"], 0)
    builder.PrependInt32Slot(7, info["texture_length"], 0)
    header = builder.EndObject()
    builder.Finish(header, file_identifier=b"SCTX")
    return bytes(builder.Output())


def sanitize(source: Path, target: Path) -> dict:
    info = parse_sctx_header(source)
    original = source.read_bytes()
    header = stable_header(info)
    tail = original[4 + info["header_length"]:]
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(struct.pack("<I", len(header)) + header + tail)
    return info


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", type=Path,
                        default=Path("assets/derived_cache/sctx_sanitized"))
    args = parser.parse_args()
    root = args.input if args.input.is_dir() else args.input.parent
    sources = sorted(args.input.rglob("*.sctx")) if args.input.is_dir() else [args.input]
    records = []
    for source in sources:
        relative = source.relative_to(root)
        target = args.output / relative
        info = sanitize(source, target)
        records.append({
            "source": source.as_posix(),
            "relative_source": relative.as_posix(),
            "source_sha256": hash_file(source),
            "output": target.relative_to(args.output).as_posix(),
            "output_sha256": hash_file(target),
            "removed_extension_header_bytes": max(0, info["header_length"] - len(stable_header(info))),
            "parsed_header": info,
        })
    manifest = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "files": len(records),
        "records": records,
    }
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    print(f"sanitized {len(records)} SCTX headers -> {args.output}")


if __name__ == "__main__":
    main()
