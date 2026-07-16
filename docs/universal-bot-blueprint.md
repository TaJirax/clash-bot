# Universal Clash Bot: architecture, workflow, and game strategy

## 1. Objective

Build one bot engine that can operate across low- and high-level accounts,
different layouts, zoom levels, sceneries, resolutions, unit unlocks, and game
states. The engine must discover account state from the game. It must not encode
one account's coordinates, building counts, troop bar, or upgrade order.

Universal does **not** mean one strategy for every account. It means:

- one perception and control engine;
- one world-state schema;
- account state discovered at runtime;
- strategy selected from data and user policy;
- unknown evidence produces `WAIT`, `SKIP`, or camera recovery, never a guess.

The bot is complete only when a completely unseen account passes the held-out
acceptance tests in section 10.

## 2. Non-negotiable design rules

1. **Separate perception from decisions.** A detector reports evidence and
   confidence. A planner chooses an action. An executor performs it. A verifier
   confirms the result.
2. **No runtime learning from unverified clicks.** Attack logs may create
   training candidates, but a new model/policy is promoted only after offline
   validation and approval.
3. **Never infer numeric facts from appearance alone.** Loot, resource balance,
   capacity, cost, time, builder count, and troop count require dedicated
   readers and repeated agreement.
4. **No account screenshots in decision code.** Real screenshots belong in a
   versioned dataset with labels and train/validation/test splits.
5. **Coordinates expire after camera movement.** Every click uses a detection
   from the current frame or a camera-independent map transformed into the
   current view.
6. **All spending is transactional.** Verify the building/menu, verify the
   resource button, click once, then verify the resulting state. Gems are never
   spent by default.
7. **Every attack is closed loop.** Re-read the battle after each deployment
   group; stop deploying if the state, boundary, or troop bar is unverified.

## 3. Target architecture

### Layer A: device and session control

- Discover the emulator and resolution.
- Capture complete frames and reject corrupted frames.
- Recover connection/inactivity dialogs.
- Verify home, menu, scout, battle, result, and loading states.
- Provide verified tap, swipe, pan, zoom, back, and retry actions.

### Layer B: universal perception

Produce observations, never actions:

- menu and game-state classification;
- building boxes, category, village type, level/variant, and confidence;
- unit/spell/hero/siege/pet card identity, level, count, and enabled state;
- resources, storage capacities, costs, timers, builder count, and loot OCR;
- legal deployment region and red forbidden boundary;
- construction, boost, destroyed, full/empty, and selected-building states.

Use a detector for location/category and a second classifier for level/variant.
Template matching remains useful for stable UI anchors, but it cannot be the
primary universal building detector.

### Layer C: world model

Maintain a camera-independent snapshot:

```text
AccountState
  village: home | builder | capital
  town_hall_level
  resources/current/capacity
  builders: free, busy, finish_times
  laboratory: idle, active_research, finish_time
  army: capacity, trained units, spells, heroes, siege, pets
  buildings[]: id, category, level, position, state, confidence
  unlocks[]
  current_goals[]
```

Enemy bases use the same building schema plus available loot, destruction
state, defense coverage, legal deployment perimeter, and reachability scores.

### Layer D: planner

The planner receives a verified world model and a policy. It emits exactly one
intent, such as `COLLECT`, `UPGRADE`, `RESEARCH`, `TRAIN`, `SCOUT_NEXT`,
`ATTACK`, or `WAIT`. It must include evidence and a reason.

### Layer E: guarded executor

Convert one intent into a short state machine. Re-detect controls immediately
before every click. Do not execute a second intent until the first is verified
or rolled back.

### Layer F: telemetry and evaluation

For every decision, append:

- before/after screenshots;
- observations and confidence;
- policy inputs and selected intent;
- clicks/swipes and coordinates;
- verification result;
- attack composition, deployments, loot gained, stars, destruction, and time;
- model, dataset, and policy version.

## 4. Making the 17 GB asset library useful

The read-only acquisition and provenance layer is implemented and documented
in [asset-acquisition.md](asset-acquisition.md). It currently joins Fan Kit and
Statscell references with decoded installed-game SC/SCTX resources and patched
SC3D models through `AssetCatalog`. Roles remain explicit: labelled reference,
texture atlas, resource sprite, named vector composition, and model.

The Fan Kit is reference art, not a ready detector dataset. Some files contain
multiple angles or states, transparent padding, promotional poses, or artwork
that differs from the live game camera. Brute-force matching every file against
every screenshot is both slow and inaccurate.

Use this ingestion pipeline:

1. Parse the manifest into canonical category, village, level, variant, and
   asset identifiers.
2. Split multi-object/multi-angle sheets into components using alpha/connected
   regions; retain provenance to the original asset.
3. Remove transparent padding and normalize color space, scale, and orientation.
4. Generate synthetic training samples on several grass/scenery backgrounds
   with shadows, labels, boost auras, construction effects, troops, walls, and
   partial occlusion.
5. Combine synthetic data with labelled real gameplay frames. Synthetic data
   broadens coverage; real frames close the domain gap.
6. Split by **account and layout**, not random images. No frame from a test
   account may appear in training.
7. Export a compact detector and level classifier. Runtime loads the model and
   metadata index, not 17 GB of source art.

Required labelled real-data matrix:

- every Town Hall range and important building level family;
- low, normal, and high camera zoom;
- compact, spread, edge, and crowded layouts;
- default and seasonal sceneries;
- idle, boosted, upgrading, selected, full/empty, and partially hidden states;
- multiple emulator resolutions;
- friendly and enemy views;
- unit cards across roster, battle bar, disabled, empty, and active states.

## 5. Recognition workflow at runtime

1. Capture a frame and classify the screen state.
2. If blocked, recover and wait for a verified destination state.
3. Detect buildings/units once at the current scale.
4. Build a confidence and coverage report.
5. If coverage is weak, try in order:
   - reuse the last verified camera transform;
   - zoom toward the model's preferred object size;
   - pan through a bounded route;
   - merge detections into world coordinates;
   - zoom back to the starting scale.
6. Confirm questionable objects from at least two views or with a second model.
7. Mark unresolved objects as unknown. Unknown objects may be mapped and logged,
   but never clicked as a named building.

For speed, use a fast primary pass and targeted recovery only for missing or
low-confidence regions. Cache model tensors, asset metadata, camera scale, and
unchanged world-state objects within a session.

## 6. Universal base-management strategy

### Management cycle

Run this priority loop:

1. Recover dialogs and verify the Home Village.
2. Read resources/capacities, builders, lab, timers, army, and shields.
3. Collect verified resource bubbles when storage is not full.
4. If a builder is free, choose one affordable upgrade from the progression
   policy and verify it transactionally.
5. If the Laboratory is idle, choose one affordable research upgrade.
6. Fill the configured farming army and spells.
7. Use overflow resources on approved walls only when a builder is available
   and doing so will not block the next scheduled upgrade.
8. If management cannot make progress, scout for loot.
9. After an attack, rebuild the world state instead of assuming balances or
   army counts.

### Recommended balanced progression policy

Use prerequisites and account goals, not a fixed list of coordinates.

Priority A — keep the account operational:

- required storage capacity for the next priority upgrade;
- Laboratory and the primary farming army's training buildings;
- Army Camps and Clan Castle capacity;
- spell/siege capacity needed by the primary army;
- Builder Huts/builders when available under the user's gem policy.

Priority B — offensive progression:

- primary farming units and their supporting spell;
- heroes and hero equipment used by the chosen army;
- a second reliable war/general army after farming is healthy;
- remaining troop/spell unlock buildings.

Priority C — economy:

- collectors/mines when their payback is useful at the current stage;
- storage only when capacity is required or overflow is frequent.

Priority D — defenses:

- core air/splash defenses appropriate to the current Town Hall;
- high-impact defenses, then point defenses;
- traps and remaining defenses;
- walls using genuine overflow, not resources reserved for offense/research.

Town Hall upgrade gate for the recommended balanced profile:

- no required offensive building is missing;
- Laboratory is not severely behind for the primary/secondary armies;
- Army Camps and Clan Castle are at the chosen completion target;
- heroes meet the user's target band;
- enough builders/resources exist to use the new Town Hall unlocks;
- the user has not selected a strategic-rush profile.

### Research priority

1. Primary farming damage unit or tank.
2. Primary resource-targeting/support unit.
3. Primary spell(s).
4. Secondary army core units and spells.
5. Frequently used donated/war units.
6. Remaining units by usage and upgrade efficiency.

Research must be derived from unlocked units. The bot never searches for a
unit that the account has not unlocked.

## 7. Universal attack strategy

### Scout decision

Keep the user's minimum loot rule: attack only when at least one desired
resource is **20% or more of verified account capacity**. Add these gates:

- loot OCR agrees across two stable frames;
- enemy Town Hall and high-impact defenses are recognised;
- the enemy is no more than the configured Town Hall advantage;
- at least one resource cluster is reachable from a legal deployment edge;
- the available trained army has a supported plan;
- attack cost and expected gain meet the selected profit policy.

Do not use a fixed maximum number of defenses for every Town Hall. Replace it
with a normalized risk score:

```text
risk = defense_strength_by_level
     + coverage_on_target_resource_cluster
     + wall/path_cost
     + enemy_TH_difference
     - exposed_resource_bonus
     - available_counter_bonus
```

### Composition model

Store unit knowledge as data:

- target preference: any, defenses, resources, walls, heroes;
- range, movement, housing, damage type, splash, tankiness, and speed;
- deployment role: tank, funnel, resource hunter, ranged support, wall break,
  cleanup, spell support, hero, siege;
- valid Town Hall/unlock range and compatible compositions.

The planner selects from the units actually trained. Recommended loot plan for
the currently learned early-game cards:

1. Giants onto the smallest defense cluster covering the selected resources.
2. Barbarians/Archers on outer buildings to shape the path when necessary.
3. Goblins in fast batches toward exposed collectors/storages.
4. Archers behind tanks and on safe cleanup targets.
5. Preserve unneeded troops when the loot objective has been achieved.

For higher accounts, use versioned strategy profiles rather than improvising:
each composition defines prerequisites, target-base conditions, deployment
phases, spell/hero rules, and abort conditions.

### Deployment workflow

1. Map enemy buildings and legal exterior regions.
2. Select one resource cluster and entry side.
3. Simulate simple paths from legal deployment points to target buildings.
4. Deploy by role in short groups, not one unit at a time and not one blind
   mass click.
5. After each group, re-read troop counts, battle state, destroyed buildings,
   and target availability.
6. Retarget or stop deployment when the objective is complete or invalid.
7. Read the result screen and calculate actual profit.

Losing trophies or the battle may be acceptable in `loot_first` mode, but only
when the expected resource profit and deployment budget satisfy policy.

## 8. Learning from logs

Logs should improve estimates, not directly rewrite live behavior.

Offline job:

1. Convert attack logs into examples: base map, planned target, deployed units,
   timing, loot gained, destruction, and result.
2. Calculate outcome by strategy/profile and enemy features.
3. Train or tune target/risk scoring on training accounts.
4. Replay the candidate policy against stored battles and held-out accounts.
5. Promote only if safety gates do not regress and profit improves.
6. Keep rollback to the previous model/policy version.

## 9. Development workflow and milestones

### Phase 0 — safety and observability

- One versioned event schema for management and attack actions.
- Screen-state gate before every interaction.
- Transaction wrapper for spending.
- Deterministic replay of decisions from stored observations.

Exit gate: no click can occur without a named state, current-frame target, and
logged reason.

### Phase 1 — universal visual dataset

- Fan Kit, installed-game, and third-party reference metadata cache. **Done.**
- SC/SCTX/SC3D read-only extraction with provenance. **Done.**
- Component reconstruction/rendering into detector training samples.
- Annotation format and review tool.
- Account/layout-separated dataset splits.
- Coverage report by category, level, state, zoom, and resolution.

Exit gate: no category is called supported without real held-out examples.

### Phase 2 — buildings and base world model

- Building detector plus level/state classifier.
- Multi-view camera transform and deduplication.
- Exact-count and position evaluation on unseen accounts.

Exit gate: held-out category precision >= 98%, recall >= 95%, exact building
count on >= 95% of supported test bases, and zero wrong building clicks in the
interaction safety suite.

### Phase 3 — complete menus, OCR, and units

- Menu-state graph for Home, Laboratory, Barracks, Army, Shop, Attack, Scout,
  Battle, and Result.
- Numeric readers with stable-frame agreement.
- Full roster and battle-bar recognition with levels/counts/states.

Exit gate: menu state >= 99.5% accuracy; critical numeric fields >= 99% exact
agreement on held-out screens; zero automatic action on ambiguous readings.

### Phase 4 — base management in dry-run, then live

- Account discovery and progression dependency graph.
- Upgrade/research/training planners.
- Dry-run recommendations compared with human decisions.
- Transactional live execution on test accounts.

Exit gate: 100 consecutive management cycles without a wrong menu, gem spend,
locked action, or misidentified upgrade.

### Phase 5 — attack planner

- Enemy OCR/map/risk/reachability.
- Composition profiles and phase executor.
- Profit/result reader and replayable logs.

Exit gate: 100 test-account scouts with correct attack/skip evidence; then 50
guarded attacks with no red-zone deployment, no unverified troop selection,
and positive average resource profit for the selected profile.

### Phase 6 — universality release

- Test accounts excluded from all training.
- Low-, mid-, and high-level accounts; several resolutions and layouts.
- Long-run recovery, restart, network-loss, and unknown-content tests.

Exit gate: every supported account passes the same acceptance suite without
adding account-specific templates or coordinates.

## 10. User decisions before live autonomy

Recommended defaults are shown first.

1. **Progression:** balanced offense-first; alternatives are full-max or
   strategic rush.
2. **Attack objective:** loot-first; alternatives are hybrid loot/trophies or
   trophy-first.
3. **Loot threshold:** 20% of verified capacity.
4. **Enemy level:** at most player Town Hall +1 when the target resources are
   exposed; stricter option is equal/lower only.
5. **Gem policy:** never auto-spend gems. Optional policy: builder purchases
   only, still requiring manual approval.
6. **Town Hall gate:** upgrade after primary offense, camps/castle, and chosen
   hero/research targets; choose whether defenses must also be maxed.
7. **Wall policy:** overflow only; choose reserved-resource amounts.
8. **Attack troop budget:** deploy only what is needed for the loot objective;
   choose a maximum percentage of the trained army per raid.
9. **Learning promotion:** manual approval after offline evaluation; optional
   later policy is automatic promotion with a rollback gate.
10. **Supported villages:** Home Village first; Builder Base and Clan Capital
    should remain disabled until they pass separate datasets and policies.

## 11. Immediate implementation order for this repository

1. Reconstruct named SC compositions and render patched SC3D models into
   game-camera training candidates.
2. Add a labelled-data manifest and annotation/review command that joins those
   candidates with real screenshots.
3. Add `AccountState`, `BuildingObservation`, `ArmyState`, and confidence/
   provenance schemas.
4. Add resource/capacity/builder/lab/loot readers with two-frame agreement.
5. Expand unit metadata and recognise every unlocked card state.
6. Replace best-view counts with multi-view world-coordinate merging.
7. Implement a dependency-based progression planner and dry-run report.
8. Implement enemy risk/reachability and versioned composition profiles.
9. Run management dry-runs, then guarded test-account actions.
10. Release attack automation only after the phase gates above pass.

The current bot should be treated as a test harness and evidence collector
until these gates pass, not as a universal autonomous bot.
