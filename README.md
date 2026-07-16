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

The expanded local acquisition pipeline now inventories official Fan Kit art,
labelled Statscell references, decoded installed-game texture banks, named SC
compositions, and patched 3D models without committing third-party assets.
See [docs/asset-acquisition.md](docs/asset-acquisition.md) for the exact
read-only MEmu/APK workflow, provenance rules, current counts, and repeatable
commands. Run `python scripts/report_asset_coverage.py` to inspect what the bot
can query without loading image data.

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

### Interactive notebook cells

Open `notebooks/clashbot_control.py` in VS Code and choose **Run Cell** above
each `# %%` block. It provides separate cells for device checks, screenshots,
safe upgrade scans, attack navigation, battle inspection, and logged attacks.
Set the `SERIAL` value in its setup cell to your emulator.

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

## Capturing wiki references

For original official artwork, prefer the Supercell fan-kit downloader. It
enumerates both filter menus in the Clash of Clans fan kit: every Asset Type
and every Characters value,
downloads original PNG files (not browser thumbnails), organizes them by asset
group, and records metadata plus SHA-256 hashes in a resumable manifest. Asset
types are stored under `Asset Types/<type>/`; units, heroes, pets, and other
named characters are stored under `Characters/<name>/`:

```powershell
# Safe one-file test
python scripts/download_supercell_fankit.py --category Buildings --max-assets 1

# Download all PNGs in the selected fan-kit categories
python scripts/download_supercell_fankit.py

# Bot-reference scope: Buildings plus every Character filter, sorted by level
python scripts/download_supercell_fankit.py --category Buildings

# Preview matches without downloading files
python scripts/download_supercell_fankit.py --skip-asset-types --character Balloon --dry-run --max-assets 20
```


Output defaults to `assets/supercell_fankit/` and is ignored by Git because it
can be large. Re-running skips completed paths; use `--refresh` to replace
them. It uses Supercell's public fan-kit listing and the same original-file
endpoint as its Download button, so Opera tabs are not needed. Review the
linked Fan Content Policy before redistributing files.

If an asset is assigned to more than one group, it appears in every matching
category folder. On Windows these entries use hard links when possible, so the
PNG data consumes disk space only once.

Building and character titles containing `level`, `lvl`, or a trailing numeric
level are placed in `Level <n>/` subfolders. Artwork without a trustworthy
level marker is retained under `Unsorted/` for later review.

The optional `scripts/capture_coc_wiki.py` tool opens a visible Opera GX window
on your own network and captures permanent troop, hero, spell, siege, pet,
building, and trap pages from the Clash of Clans Wiki. Every discovered entry
opens in a visible tab, is recorded, and then closes before the next entry.
Pages and meaningful image elements are rendered at exactly 130% CSS zoom and
2x device scale.

```powershell
python -m pip install -e ".[wiki-capture]"
python scripts/capture_coc_wiki.py
```

The default mode detects Opera GX and starts a separate automation window with
its own profile under `assets/wiki_reference/.opera-profile`. It does not read,
close, or navigate the tabs in your normal Opera profile, so your already-open
browser can remain running. Pass `--opera-path "C:\path\to\opera.exe"` only if
automatic detection fails.

If Cloudflare displays a verification page, solve it in the visible browser
and press Enter in the terminal. The script does not bypass verification. It
uses a persistent browser profile, waits at least two seconds between pages,
records source URLs and metadata, and resumes completed pages after restart.
Output defaults to `assets/wiki_reference/` and is ignored by Git because the
screenshots are large, third-party reference material. Review the wiki's terms
and licenses before sharing or redistributing captures.

Useful scope controls:

```powershell
# Small test run
python scripts/capture_coc_wiki.py --category Troops --max-pages 5

# Add deeper/custom categories
python scripts/capture_coc_wiki.py --category Buildings --category "Siege Machines" --category-depth 2

# Re-capture existing pages
python scripts/capture_coc_wiki.py --refresh

# Optional: use Playwright's bundled Chromium instead of Opera
python -m playwright install chromium
python scripts/capture_coc_wiki.py --browser chromium
```

Advanced attach mode is available if you intentionally launch Opera with a
remote-debugging port. The collector still creates and closes only its own
tabs:

```powershell
& "C:\Users\you\AppData\Local\Programs\Opera GX\opera.exe" --remote-debugging-port=9222
python scripts/capture_coc_wiki.py --cdp-url http://127.0.0.1:9222
```

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
