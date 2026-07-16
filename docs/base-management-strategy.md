# Base-management strategy

The scheduler operates in this order. A missing/unknown UI fact is a **wait**
state, never permission to attack.

1. Recover blocking dialogs and capture a complete home-village frame.
2. Collect verified resource bubbles.
3. Read builder availability from the home HUD. With an idle builder, inspect
   recognised buildings in configured priority order and upgrade only after the
   hammer and resource-cost controls are verified.
4. Read the Laboratory state. If it is idle and a verified affordable research
   item exists, research the configured priority unit/spell. Never spend gems
   or bypass a lock/insufficient-resource state.
5. Read Army capacity and troop training state. Train only the configured
   composition when capacity is free and its visible cards are recognised.
6. If no builder upgrade, laboratory research, collection, or training action
   is available, inspect enemy candidates. Attack only after verified loot is
   at least 20% of our verified capacity, enemy Town Hall/defense risk passes,
   an exposed resource target is found, and deployable troops are recognised.
7. Deploy tanks, resource-targeters, then support in short groups from a
   verified legal exterior point. Capture each group and the outcome. Feed
   victory/loot results back into the strategy dataset.

## Current learned checks

- Home/base building templates and upgrade hammer/resource controls.
- Laboratory and Barracks menu anchors.
- Four battle-bar troop cards: Barbarian, Goblin, Giant, Archer.
- Attack menu, My Army, opponent scouting, active battle, and attack logging.

## Required next readers

The bot is intentionally not allowed to claim these facts until trained with
live UI examples: builder count, resource capacity/current resources, lab idle
and research affordability, full troop training state, enemy loot digits, and
level-specific enemy buildings/defenses.
