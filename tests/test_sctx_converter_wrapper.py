from pathlib import Path

import struct

from scripts.convert_sctx_textures import output_path, parse_sctx_header, three_byte_le


def test_sctx_output_preserves_asset_tree_and_changes_extension(tmp_path: Path) -> None:
    root = tmp_path / "package"
    source = root / "assets" / "image" / "skin_icons" / "builder.sctx"
    target = output_path(source, root, tmp_path / "png")

    assert target == tmp_path / "png" / "assets" / "image" / "skin_icons" / "builder.png"


def test_parse_sctx_header_tolerates_unknown_trailing_fields(tmp_path: Path) -> None:
    # Minimal FlatBuffer table with the SCTX identifier and fields 1-7.
    header = bytearray(64)
    struct.pack_into("<I", header, 0, 32)
    header[4:8] = b"SCTX"
    struct.pack_into("<HH", header, 12, 20, 28)
    offsets = (0, 4, 8, 10, 12, 0, 16, 20)
    for index, offset in enumerate(offsets):
        struct.pack_into("<H", header, 16 + index * 2, offset)
    struct.pack_into("<i", header, 32, 20)
    struct.pack_into("<IHHB", header, 36, 204, 128, 64, 1)
    struct.pack_into("<I", header, 48, 8)
    struct.pack_into("<i", header, 52, 4096)
    path = tmp_path / "test.sctx"
    path.write_bytes(struct.pack("<I", len(header)) + header)

    result = parse_sctx_header(path)

    assert result["pixel_type"] == 204
    assert result["width"] == 128
    assert result["height"] == 64
    assert result["texture_length"] == 4096


def test_astc_24bit_dimensions_are_little_endian() -> None:
    assert three_byte_le(4096) == b"\x00\x10\x00"
