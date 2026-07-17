# Fast universal mapping and loot strategy

## Perception loop

1. Capture a home-village frame and verify the HUD.
2. Recognize at the current scale using semantic references ordered by role,
   then by level.  The catalog checks labelled references and rendered
   composites before raw package resources.
3. If confidence or category coverage is weak, zoom one step in, rescan, and
   pan only the missing quadrant.  Do not repeat a verified view.
4. Merge detections into map coordinates and keep the highest-confidence
   observation for each building.  This is faster than rescanning the entire
   route after every miss.

## Target evaluation

The attack planner will only approve a target when all of these are verified:

- available gold/elixir/dark elixir is at least 20% of the player storage
  capacity (the largest verified resource fraction);
- reachable and exposed resource buildings exist;
- Town Hall advantage is no more than one level;
- defensive count is within the loot policy; and
- when defense power is available, it is no more than 115% of the verified
  army power. Unknown values cause a skip.

## Deployment phases

The generated plan is ordered: scout a legal edge, deploy tanks, send loot
troops after defenses retarget, add ranged support, clean up, and stop once
the loot objective is reached. The executor must keep the battle HUD and legal
deployment boundary verified before every wave; a failed verification aborts
without clicking.

This is a conservative loot policy, not a guarantee of a win. Actual power
and reachability must come from the live opponent screen rather than asset art.
