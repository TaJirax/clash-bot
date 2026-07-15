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

# camera control: every change is verified from recognized building scale
python -m clashbot zoom-in <serial>
python -m clashbot zoom-out <serial> --steps 2
python -m clashbot normalize-zoom <serial> --target 0.80

# verified camera movement
python -m clashbot pan-up <serial>
python -m clashbot pan-down <serial>
python -m clashbot pan-left <serial>
python -m clashbot pan-right <serial>

# normalize zoom, visit several views, and merge detections into one map
python -m clashbot map-base <serial> village_1

# search multiple views and optionally open the detected building menu
python -m clashbot find-building <serial> town_hall --tap

# safely keep the home village active (0 loops means until Ctrl+C)
python -m clashbot anti-afk <serial>
python -m clashbot anti-afk <serial> --loops 1 --dry-run

# open Attack, but do not start matchmaking
python -m clashbot open-attack <serial>

# stop safely at army confirmation (no search cost yet)
python -m clashbot find-match <serial>
# confirm one search, verify the opponent, then exit without deploying
python -m clashbot find-match <serial> --confirm

# verify upgrade hammer and green resource control without pressing confirm
python -m clashbot check-upgrade-ui <serial> --category gold_mine

# build a labeled menu demonstration (navigate the game manually)
python -m clashbot menu-capture <serial> th2_menus home --description "main village"
# after tapping the Army button yourself:
python -m clashbot menu-capture <serial> th2_menus army_overview --after home --action "tap Army button"

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

## Capturing menus for learning

Use `menu-capture` once before an action and again after the game finishes its
animation. Give every distinct screen a short stable state name. The command
saves lossless screenshots and a `manifest.json` state/action graph under
`captures/menus/<session>/`; captures are ignored by Git because they may
contain player information.

For useful demonstrations, capture the normal result, disabled/unavailable
result, confirmation dialog, success result, and the way back out of each
menu. Record a video at the same emulator resolution, with taps visible if the
emulator supports that option. Do not crop or resize the video. A future pass
can then turn the demonstrated state graph into recognition templates and
safe bot actions.

Building recognition now sweeps camera zoom factors from 0.35x through 1.35x,
configured by
`camera_scales` in `assets/buildings.json`. This is separate from emulator
resolution scaling and prevents a player pinch-zoom from invalidating every
building template, including MEmu's maximum zoom-out view.

By default, `zoom-in` and `zoom-out` inject a real two-pointer Android gesture,
which also works with headless MEmu Hyper-V. Use `--backend memu` for MEmu's
official control service (equivalent to Ctrl+wheel/F2/F3), `--backend windows`
to send literal Ctrl+wheel to a visible emulator window, or `--backend android`
for Android zoom key events. Every backend verifies the result by measuring
recognized building sizes. `normalize-zoom` moves one
verified step at a time toward a repeatable mapping scale (0.80 by default).
If the emulator does not forward these keys to the game, the command exits
with an error instead of pretending the camera moved. In that case the
emulator needs a specific multi-touch backend before automatic pinching can be
enabled; recognition still works across the configured zoom sweep.

## Learning the base and menus

`map-base` first normalizes the camera to 0.55x, then follows a closed route
through right, left, up, and down views. Every pan is checked using the actual
map-content translation. Detected buildings are converted from screen
coordinates into shared map coordinates, so the same building seen in two
views is stored only once. Screenshots and the learned `map.json` are written
under `captures/maps/<session>/`. Use `--route` to provide a longer comma-
separated route, or `--skip-zoom-normalize` to preserve the current zoom.

Building templates teach the bot what physical village objects look like.
`menu-capture` separately teaches named UI states and the actions connecting
them. Capture each menu before and after every button action, including
disabled, confirmation, success, and error states. Those state transitions can
then be converted into guarded click workflows like the existing upgrade flow.

The standalone `anti-afk` command verifies the home screen using the learned
Attack button, finds a uniformly colored grass patch away from controls and
buildings, and touches it every 35-65 seconds. If any menu is open, the home
screen is uncertain, or no safe patch exists, that cycle performs no input.

`open-attack` matches the learned orange Attack button, taps only its verified
centre, and then requires the learned Multiplayer tab to appear. It never
clicks `Find a Match`; matchmaking is a separate behavior that remains locked
until its screens and cancel/confirmation paths have been taught and tested.

`find-match` implements the learned sequence Attack menu -> orange Find a
Match -> My Army. This default mode stops before spending gold. `--confirm`
continues through the green Attack confirmation, verifies the opponent screen
using its End Battle control, and immediately returns home without deploying.
`--stay` is intentionally separate because it leaves the live deployment
countdown running for a future attack-strategy module.

`check-upgrade-ui` selects a recognized building, verifies the learned hammer,
opens its details, and verifies the green resource button without clicking it.
Transient MEmu screenshots containing black/unrendered tiles are now rejected
and retried before any upgrade recognition or input.

Upgrade order is Town Hall, gold mines, elixir collectors, dark-elixir drills,
gold/elixir/dark-elixir storages, then walls. The bot clicks an upgrade cost
only after matching the selected-building hammer and a green cost button. It
never follows insufficient-resource dialogs or gem offers.
