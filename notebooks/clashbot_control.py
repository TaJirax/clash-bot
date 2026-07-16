# %% [markdown]
# # ClashBot control notebook
#
# Open this file in VS Code and use **Run Cell** above each `# %%` block.
# Every game-changing command is kept in its own cell so you can inspect the
# screen and logs between actions.

# %% Setup
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path.cwd()
if not (ROOT / "src" / "clashbot").is_dir():
    ROOT = Path(__file__).resolve().parents[1]
if not (ROOT / "src" / "clashbot").is_dir():
    raise RuntimeError("Could not locate the clash-bot repository")

PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"
if not PYTHON.is_file():
    PYTHON = Path(sys.executable)

SERIAL = "127.0.0.1:21513"


def bot(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    """Run a ClashBot CLI command and show its complete output in this cell."""
    result = subprocess.run(
        [str(PYTHON), "-m", "clashbot", *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )
    if result.stdout:
        print(result.stdout, end="", flush=True)
    if result.stderr:
        print(result.stderr, end="", file=sys.stderr, flush=True)
    if check and result.returncode:
        raise RuntimeError(f"ClashBot exited with code {result.returncode}")
    return result


# %% Device connection
bot("devices")

# %% Capture the current game screen
capture = ROOT / "captures" / "notebook" / "current.png"
capture.parent.mkdir(parents=True, exist_ok=True)
bot("screenshot", SERIAL, str(capture))
print(capture)

# %% Read-only recognition: learned menu state, troop cards, and battle HUD
bot("check-state", SERIAL, check=False)
bot("recognize-army", SERIAL, check=False)
bot("check-battle", SERIAL, check=False)

# %% Base management: dry-run first (no taps)
bot("manage-status", SERIAL)
bot("upgrade", SERIAL, "--dry-run", "--scans", "1")

# %% Base management: perform one verified upgrade pass
# Uncomment only when the dry-run output is correct.
# bot("upgrade", SERIAL, "--scans", "1")

# %% Maintain an active home village without touching buildings
bot("anti-afk", SERIAL, "--loops", "1", "--dry-run")

# %% Attack navigation: open the menu and stop at My Army (no search cost)
bot("open-attack", SERIAL, check=False)
bot("find-match", SERIAL, check=False)

# %% Attack scouting: starts one search, verifies an opponent, but does not deploy
# bot("find-match", SERIAL, "--confirm", "--stay")

# %% Read-only check of a scouted opponent
# bot("check-battle", SERIAL)

# %% Logged attack: small verified wave
# Run only after the scouting cell reports a verified opponent screen.
# bot("loot-attack", SERIAL, "notebook_loot_001")

# %% Logged aggressive test-account attack
# bot("loot-attack", SERIAL, "notebook_win_001", "--aggressive")

# %% Show recorded attack logs
logs = ROOT / "captures" / "attacks"
if logs.exists():
    for path in sorted(logs.glob("*/events.jsonl")):
        print(path.relative_to(ROOT), f"({len(path.read_text(encoding='utf-8').splitlines())} events)")
