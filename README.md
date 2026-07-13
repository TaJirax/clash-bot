# clashbot

Clash of Clans automation bot, built from scratch. Reuses ideas (not code)
from two prior projects:

- [ClAsHbOt](https://github.com/CodeSlinger69/ClAsHbOt) — AutoIt/C++, abandoned 2016.
  Reference for farming strategy logic (barcher, gibarch, BAM, loonion, dead
  base detection, donation flow) — not reusable code, since it drives a
  Windows client via AutoIt, not an emulator via ADB.
- [clash-of-clans-bot](https://github.com/mimslarry0007-cpu/clash-of-clans-bot) —
  early pyautogui prototype with hardcoded screen coordinates. Superseded by
  the ADB approach here, which is resolution/window-position independent.

## Roadmap

1. **Interaction** — connect to an emulator over ADB, take screenshots, send
   taps/swipes (`clashbot devices|screenshot|tap|swipe`). Taps/swipes are
   human-like by default: jittered position, a real press duration with a few
   pixels of drift, and randomised think-time, so input registers like a
   finger rather than an instantaneous `input tap`. `--raw` gives exact input.
2. **Recognition** — find base elements in a screenshot with OpenCV template
   matching (`clashbot find`), so behaviour is driven by what's on screen, not
   hardcoded coordinates. Supports alpha-masked and multi-scale matching for
   the catalog troop/spell icons under `assets/icons/`.
3. **Behavior** — real loops built on 1 + 2. **Resource gathering is done**
   (`clashbot collect`): find every resource-collect bubble and human-tap it.
   **Building upgrades are also implemented** (`clashbot upgrade`): recognise
   buildings, try upgrades in priority order every ten minutes, and touch a
   visually verified empty grass patch every 30–60 seconds between scans.
   Army training and attacking come next.

## Assets

- `assets/templates/collect_*.png` — resource-collect bubbles cropped from
  real gameplay at MEmu's 1280x720. These drive `clashbot collect`; add a new
  bubble type by dropping in another `collect_*.png`.
- `assets/icons/troops`, `assets/icons/spells` — MIT-licensed troop/spell
  icons for recognising the army/training UI (used later for attacking). See
  `assets/icons/ATTRIBUTION.md`.
- `assets/buildings.json` — building and upgrade-hammer reference crops. The
  supplied live base (`base_now.png`) seeds Town Hall 2, Gold Mine 1, Elixir
  Collector 1, and Gold Storage 1. Add clean in-game references as new levels
  are reached. Wiki screenshots are useful references, but their white
  background and browser scaling make unsafe click templates.

## Requirements

- Python 3.10+
- `adb` on PATH (already installed on this machine)
- An Android emulator with ADB debugging enabled: BlueStacks, MEmu, or Nox

### Enabling ADB on each emulator

- **BlueStacks**: Settings (gear icon) → Advanced → toggle "Android Debug
  Bridge (ADB)" → note the port shown.
- **MEmu**: ADB is on by default on port 21503 for the first instance.
- **Nox**: Settings → General → toggle "Enable USB Debugging" and "Enable
  Root Access"; the app uses port 62001 for the first instance.

## Usage

```
python -m clashbot devices
python -m clashbot screenshot <serial> out.png
python -m clashbot tap <serial> 500 800
python -m clashbot swipe <serial> 500 800 500 400 300

# recognition
python -m clashbot find <serial> assets/templates/collect_elixir.png --all --save debug.png

# resource gathering (add --dry-run to report without tapping)
python -m clashbot collect <serial>
python -m clashbot collect <serial> --loops 20 --interval 30

# continuous upgrades: 10-minute scans, random 30-60 second anti-idle touches
python -m clashbot upgrade <serial>

# inspect recognition without touching the game
python -m clashbot upgrade <serial> --scans 1 --dry-run
```

Upgrade order is Town Hall, gold mines, elixir collectors, dark-elixir drills,
gold/elixir/dark-elixir storages, then walls. The bot clicks an upgrade cost
only after matching the selected-building hammer and a green cost button. It
never follows insufficient-resource dialogs or gem offers.
