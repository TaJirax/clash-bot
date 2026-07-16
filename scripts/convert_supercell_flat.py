"""Decode extracted Supercell Flat/Odin GLBs with provenance.

The third-party converter stays in the ignored source cache. Inputs are staged
under collision-proof names and decoded outputs are copied to derived cache.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path


def hash_file(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def clear_files(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for path in directory.iterdir():
        if path.is_file():
            path.unlink()
        else:
            raise RuntimeError(f"unexpected directory in converter staging area: {path}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path, help="file or directory containing optimized GLBs")
    parser.add_argument("--tool-root", type=Path,
                        default=Path("assets/source_cache/github/supercell_flat_converter"))
    parser.add_argument("--python", type=Path,
                        default=Path(".tools/flat-converter-venv/Scripts/python.exe"))
    parser.add_argument("--output", type=Path,
                        default=Path("assets/derived_cache/flat_gltf"))
    parser.add_argument("--mode", choices=("decode", "decodeRaw"), default="decode")
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()

    source_root = args.input if args.input.is_dir() else args.input.parent
    inputs = sorted(args.input.rglob("*.glb")) if args.input.is_dir() else [args.input]
    if args.limit is not None:
        inputs = inputs[:args.limit]
    if not inputs:
        raise SystemExit("no GLB inputs found")
    tool_root = args.tool_root.resolve()
    python = args.python.resolve()
    if not (tool_root / "main.py").is_file() or not python.is_file():
        raise SystemExit("converter or isolated Python environment is missing")

    staged_input = tool_root / "In-SC-glTF"
    staged_output = tool_root / "Out-glTF"
    clear_files(staged_input)
    clear_files(staged_output)
    mapping = {}
    for source in inputs:
        relative = source.relative_to(source_root)
        staged_name = hashlib.sha256(relative.as_posix().encode()).hexdigest()[:16] + ".glb"
        shutil.copy2(source, staged_input / staged_name)
        mapping[staged_name] = (source, relative)

    result = subprocess.run(
        [str(python), "main.py", args.mode], cwd=tool_root,
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    print(result.stdout, end="")
    if result.stderr:
        print(result.stderr, end="")
    args.output.mkdir(parents=True, exist_ok=True)
    records = []
    for staged_name, (source, relative) in mapping.items():
        converted = staged_output / staged_name
        record = {
            "source": source.as_posix(),
            "relative_source": relative.as_posix(),
            "source_sha256": hash_file(source),
            "mode": args.mode,
        }
        if converted.is_file():
            target = args.output / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(converted, target)
            record.update({
                "output": target.relative_to(args.output).as_posix(),
                "bytes": target.stat().st_size,
                "output_sha256": hash_file(target),
            })
        else:
            record["error"] = "converter_produced_no_output"
        records.append(record)

    manifest = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "tool_commit": subprocess.run(
            ["git", "-c", f"safe.directory={tool_root}", "rev-parse", "HEAD"],
            cwd=tool_root, capture_output=True, text=True, check=True,
        ).stdout.strip(),
        "converter_exit_code": result.returncode,
        "converted": sum("output" in record for record in records),
        "failed": sum("output" not in record for record in records),
        "records": records,
    }
    manifest_path = args.output / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"converted {manifest['converted']}/{len(records)} GLBs -> {args.output}")
    if result.returncode and not manifest["converted"]:
        raise SystemExit(result.returncode)


if __name__ == "__main__":
    main()
