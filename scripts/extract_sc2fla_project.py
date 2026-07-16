"""Stage and reconstruct one SC family without modifying package originals."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path


def hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def find_family(input_root: Path, family: str) -> tuple[Path, list[Path]]:
    matches = sorted(input_root.rglob(f"{family}.sc"))
    if len(matches) != 1:
        raise ValueError(f"expected one {family}.sc below {input_root}, found {len(matches)}")
    source = matches[0]
    def belongs_to_family(path: Path) -> bool:
        # `chr_bat` and `chr_battle_blimp` are distinct families. Only the
        # primary SC/meta pair and underscore-qualified companion resources
        # belong to a family; a textual prefix alone is unsafe.
        name = path.name
        return (
            name in {f"{family}.sc", f"{family}.sc.meta"}
            or name.startswith(f"{family}_")
        )

    related = sorted(
        path for path in source.parent.iterdir()
        if path.is_file()
        and path.suffix.lower() in {".sc", ".sctx", ".meta"}
        and belongs_to_family(path)
    )
    return source, related


def stage_family(
    input_root: Path,
    family: str,
    sanitized_root: Path,
    destination: Path,
) -> list[dict]:
    source, related = find_family(input_root, family)
    source_parent = source.parent
    records = []
    destination.mkdir(parents=True, exist_ok=False)
    for original in related:
        chosen = original
        if original.suffix.lower() == ".sctx":
            relative = original.relative_to(input_root)
            sanitized = sanitized_root / relative
            if sanitized.is_file():
                chosen = sanitized
        target = destination / original.name
        shutil.copy2(chosen, target)
        records.append({
            "name": original.name,
            "package_source": original.as_posix(),
            "staged_source": chosen.as_posix(),
            "sanitized_header": chosen != original,
            "sha256": hash_file(target),
        })
    if not (destination / f"{family}.sc").is_file():
        raise RuntimeError("family staging did not include its primary SC file")
    return records


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("family", help="SC basename, for example buildings or chr_balloon")
    parser.add_argument("--input", type=Path,
                        default=Path("assets/derived_cache/game_package"))
    parser.add_argument("--sanitized", type=Path,
                        default=Path("assets/derived_cache/sctx_sanitized"))
    parser.add_argument("--output", type=Path,
                        default=Path("assets/derived_cache/sc2fla_staging"))
    parser.add_argument("--tool-root", type=Path,
                        default=Path("assets/source_cache/github/sc2fla_foss"))
    parser.add_argument("--python", type=Path,
                        default=Path(".tools/sc2fla-venv/Scripts/python.exe"))
    args = parser.parse_args()

    tool = (args.tool_root / "main.py").resolve()
    python = args.python.resolve()
    if not tool.is_file() or not python.is_file():
        raise SystemExit("SC2FLA checkout or isolated Python environment is missing")
    destination = args.output / args.family
    if destination.exists():
        raise SystemExit(f"staging destination already exists: {destination}")

    records = stage_family(args.input, args.family, args.sanitized, destination)
    command = [str(python), "main.py", "--process", str((destination / f"{args.family}.sc").resolve()),
               "--dump-raw"]
    result = subprocess.run(
        command, cwd=args.tool_root.resolve(), capture_output=True, text=True,
        encoding="utf-8", errors="replace",
    )
    print(result.stdout, end="")
    if result.stderr:
        print(result.stderr, end="")
    manifest = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "family": args.family,
        "command": command,
        "exit_code": result.returncode,
        "files": records,
    }
    (destination / "extraction_manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    if result.returncode:
        raise SystemExit(result.returncode)


if __name__ == "__main__":
    main()
