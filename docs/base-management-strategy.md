# Base-management game plan

The manager runs this priority loop before considering an attack:

1. **Recover**: dismiss a verified inactivity/connection dialog and confirm the
   home HUD again.
2. **Collect**: sweep visible gold, elixir, and dark-elixir bubbles. Pan only
   when the current view has been processed.
3. **Research**: open the learned Laboratory/research menu and start the best
   affordable research upgrade. Never infer an idle laboratory from artwork.
4. **Build**: if a builder is free, inspect upgrade menus, compare cost and
   duration, and start the highest-priority affordable upgrade. Prefer
   offense/storage capacity, then resource production, then defenses/traps.
5. **Train**: keep a valid farming composition queued; do not attack with an
   unverified or empty army.
6. **Attack**: hand off to the loot planner only when collection, research,
   builders, upgrade affordability, and army readiness are all verified clear.

The scheduler is fail-closed: an unknown value produces `inspect`, never an
automatic attack. Boost auras are recorded as informational decoration and are
not click targets. Each action should be logged with the source screenshot,
menu state, selected building/research, cost, and verification result so a
failed action can be replayed without guessing.

Use `python -m clashbot manage-status <serial>` to inspect the current evidence
and the selected next action. The planner is deliberately separate from input
execution so future menu readers can be added without weakening these guards.
