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
   taps/swipes. Done in this commit (`clashbot devices|screenshot|tap|swipe`).
2. **Recognition** — detect base elements (buildings, resources, troops, UI
   icons) in a screenshot using OpenCV template matching, so the bot can find
   things instead of relying on hardcoded coordinates.
3. **Behavior** — combine 1 + 2 into actual farming loops (collect, upgrade,
   attack, donate) driven by what's recognized on screen, not fixed
   coordinates.

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
```
