# A0 Ironclad full-run simulator contract

This document fixes the behavior target for `simulator/`. When the reference
game is ambiguous, the fixed-version decompiled behavior is the local reference;
when a behavior cannot be verified, it is marked APPROXIMATE or UNSUPPORTED in
[`a0-ironclad-coverage.md`](a0-ironclad-coverage.md) instead of being claimed
exact.

## Fixed contract

| Field | Value |
| --- | --- |
| Game version | Slay the Spire 2 v0.111.0 |
| Mode | Standard, single player |
| Unlocks | All content unlocked |
| Character | Ironclad |
| Ascension | 0 |
| Run | Opening Ancient -> act 1 -> act 2 -> act 3 -> final boss (victory or death) |
| Excluded | Tutorial corrections, daily challenge, mods, multiplayer, seeded custom modifiers |
| Deliverable | Logic and data only: no UI, animation, audio, localization, or game assets |

Decompiled/deobfuscated game code is used only as a local behavior reference.
No game assemblies, assets, or copied source are committed or redistributed.
Card text is never parsed; semantics follow the reference effect code.

## State contract

`RunContext` (see `simulator/include/sts2/run.h`) is a copyable POD-style value
containing everything that affects future behavior:

- HP/max HP, gold, act, per-act floor, total floor, win flag, map coordinates,
  visited-node bitset, last room type and room/screen state.
- Deck `Card` instances with upgraded flag, persistent UID, and run-level
  modifications; relics with per-relic auxiliary counters; potions and slots.
- All run/player RNG streams with their counters, plus card-rarity, potion,
  unknown-room and per-type unknown odds.
- Act encounter bags (normal/elite/event) and boss choice.
- Shop inventory/prices/sold flags/removal state, card reward offer, event page
  and data, and the embedded `BattleContext` for event combats.

The whole value can be copied (`RunContext b = a;`), snapshotted
(`snapshot()`), restored in place (`restore(blob)`), and hashed
(`state_hash()`); `serialize()` is an in-build binary blob guarded by a magic
header and `sizeof(RunContext)`. Snapshots are only valid within the same build.

## RNG contract

All randomness is owned by the run value; there is no global RNG.

Run streams (`RunRngType`, named seeds derived from the run seed plus the
deterministic name hash, matching `RunRngSet` order):

1. `UpFront`
2. `Shuffle`
3. `UnknownMapPoint`
4. `CombatCardGeneration`
5. `CombatPotionGeneration`
6. `CombatCardSelection`
7. `CombatEnergyCosts`
8. `CombatTargets`
9. `MonsterAi`
10. `Niche`
11. `CombatOrbs`
12. `TreasureRoomRelics`

Player streams: `Rewards`, `Shops`, `Transformations`, seeded from
`run seed + player id`.

Event RNG is derived per event from run seed + player id + deterministic hash
of the event name. Map generation uses a per-act named seed
(`act_<n>_map`), so map generation is reproducible and does not consume run
streams. `Rng` implements the reference `.NET System.Random` algorithm
(55-element seed array, `internal_sample`, inclusive `next_int`, float sample),
with stream counters that participate in snapshots and in the state hash.

## Run flow

1. `init` builds the 10-card Ironclad starter deck with Burning Blood, 80/80 HP,
   99 gold, generates the act-1 map, and enters the Ancient (Neow) room.
2. Map moves follow the generated DAG. Point types: Ancient, Monster, Elite,
   Event, Rest, Shop, Treasure, Boss.
3. Rooms:
   - Monster/Elite/Boss: encounter bag draw, native `BattleContext`, rewards.
   - Unknown: per-point odds resolved with growth/reset and shop blacklist.
   - Event: event engine; event combats return to the event (or finish it).
   - Rest: heal 30%, smith, Shovel Dig, or Girya Lift.
   - Shop: five character cards (Attack/Attack/Skill/Skill/Power), two
     colorless cards, three relics, three potions, one card removal, one sale,
     price variance.
   - Treasure: 42-52 gold and a rarity-rolled relic, respecting Silver Crucible.
4. Boss victory offers a boss card reward. After acts 1/2 the next act map is
   generated and entered; after act 3 the run is won. Combats can kill the run.
5. Every act starts at its Ancient node: act 1 rolls Neow, act 2 rolls one of
   Orobas/Pael/Tezcatara, act 3 rolls one of Nonupeipe/Tanx/Vakuu, and the shared
   Darv is assigned to at most one of acts 2/3. Offer pools follow the C#
   generators; each option grants its relic (secondary relic effects are listed
   in the coverage manifest).

## Economy and rewards

- Gold: monster 10-20, elite 35-45, boss 100 (Bowler Hat +20%); treasure 42-52.
- Card rarity: regular rare 3% / uncommon 37%; elite 10% / 40%; boss always
  rare; shop 9% / 37%, with the persistent rarity offset (-0.05 start, +0.01
  per non-rare, cap 0.4, reset on rare). Boss card rewards are always rare.
- Card upgrades in rewards roll `actIndex * 25%` for non-rares.
- Potion drop odds start at 40%, move +/-10% per roll, and elites add 12.5
  percentage points in the comparison.
- Relic rarity: 50% common, 33% uncommon, rest rare; shop stock uses two rolled
  rarities plus one shop-only relic. Merchant prices vary multiplicatively;
  removal costs 75 + 25 per prior use.
- Unsupported relics are never placed in drop, shop, treasure or event pools.

## Events

`simulator/src/events.cpp` holds the manifest. Reachable events are either
IMPLEMENTED or APPROXIMATE; UNSUPPORTED entries are excluded from the event bag
by `event_pool_for_act`. Coin-gated and potion-gated options are removed from
`legal_actions` and rejected by `event_choose`. Event combat uses the same
`BattleContext` and resumes the event when the reference does.

## Training API

`RunEnv` (`agent/run_env.py`) exposes:

- `reset(seed)` / `observe()` / `observe_public()`
- `legal_actions()` / `action_mask()` / `step(action)`
- `is_terminal()` / `terminal_reward()` / `state_hash()`
- `snapshot()` / `restore(blob)`
- `play_run`, `play_and_log` (JSONL), and `run_batch` (thread pool).

Each `RunEnv` owns its native `RunContext`; no module-level mutable state is
shared, so threads can run independent seeds. `observe_public()` exposes only
player-visible information: deck, resources, visible map, and in-combat hand,
pile counts and intents. It contains no RNG state, draw order, future intents or
hidden event outcomes.

## Acceptance tests

`tests/test_smoke.py` covers:

- observation/action dimensions and mask consistency;
- deterministic replay for the same seed + action sequence, and snapshot/
  restore hash equality;
- golden hashes and structural invariants for the generated map (per act);
- room transitions, treasure gold, shop stock/prices, rest upgrades, boss reward
  and act transition;
- event manifest gating (unsupported events never in a pool);
- every card playable, every potion usable, every implemented relic surviving a
  combat, every event relic obtainable;
- automated full A0 Ironclad wins from the opening Ancient to the act-3 boss
  (seeds 24 and 32 in the checked-in deterministic heuristic); and
- one training step for each Python head.

Run `python -m pytest tests -q`; build notes are in `README.md`.

## Non-goals and remaining gaps

- Other characters, act 4, and other game modes.
- UI-level card/enchantment/potion selection; events needing them use
  deterministic substitutes and are marked APPROXIMATE.
- Pets and map-manipulation event relics. Curses are modelled as cards,
  including their in-combat end-of-turn effects and Normality's play
  restriction.
- Byte-exact reproduction of every reference RNG-consumption call; behavior is
  golden-traced where possible and otherwise documented as approximate.
