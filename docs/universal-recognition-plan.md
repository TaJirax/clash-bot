# Universal attack and base recognition plan

## Data paths

- `assets/supercell_fankit/`: downloaded reference art. It is categorised by
  asset type, unit/building, and level. It is never matched directly against a
  live base.
- `assets/templates/`: small crops from actual game screens: buttons, menu
  anchors, troop cards, and battle controls.
- `assets/buildings.json`: live-building template catalogue. Every entry names
  a building, its level/variant, source image, crop, confidence threshold, and
  maximum count.
- `captures/`: ignored training evidence. Each account and zoom level gets its
  own labelled captures; no account-specific screenshots are committed.

All runtime defaults resolve from the repository path, not the current shell
directory.

## Build order

1. Capture a reference matrix at normalised zoom for every Town Hall/Builder
   Hall range. Crop each in-game building level into a catalogue entry.
2. Add held-out base screenshots for every range. A detector is accepted only
   if it reports correct position/category on the held-out image and never
   returns a low-confidence false click.
3. Capture each Army roster page and battle bar. Add templates per unit card,
   level skin, spell, hero, siege machine, and pet. Keep unavailable/locked
   cards distinct from deployable cards.
4. Add battle OCR for own resources/capacity and enemy available loot. Verify
   each number twice before passing it to `LootPlanner`.
5. Map enemy resource buildings, defenses, and Town Hall; score exposed
   collectors/storages and paths from a legal deployment edge.
6. The planner may approve a loot attack only when all evidence is verified:
   loot >= 20% capacity, enemy level within policy, exposed reachable resource
   target, acceptable defense risk, and a recognised deployable army.
7. Deploy one recognised troop group at a time, re-check the battle HUD after
   every action, then verify the result/loot screen. Unknown state means stop.

## Current gate

Navigation and the four current battle-bar troop cards are verified. Universal
attack automation is intentionally gated until level-specific live building
templates and live numeric OCR have passed the held-out tests.
