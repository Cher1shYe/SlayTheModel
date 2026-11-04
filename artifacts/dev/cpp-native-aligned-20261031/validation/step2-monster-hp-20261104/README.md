# Monster initial HP: decompile extraction and Niche-stream uniqueness

Date: 2026-11-04. Source tree: this workspace (`simulator/`). No commit/push.

## Why

`content/monsters.json` HP ranges came from the reference Python engine
(`simulator/tools/dump_monsters.py`, `hp_source: sampled_only`), not from the
native game code. Native `Creature.SetUniqueMonsterHpValue`:

```csharp
int minInitialHp = Monster.MinInitialHp;
int num = Monster.MaxInitialHp + 1;
HashSet<int> hashSet = Enumerable.Range(minInitialHp, num - minInitialHp).ToHashSet();
hashSet.ExceptWith(creaturesOnSide.Except(new <>z__ReadOnlySingleElementList<Creature>(this))
    .Select(e => e.MaxHp));
MonsterMaxHpBeforeModification = (_currentHp = (_maxHp = hashSet.Count <= 0
    ? rng.NextInt(minInitialHp, num) : rng.NextItem(hashSet)));
```

(`_decomp_local_0861bfa1/sts2.decompiled.cs:180539`, called from
`CombatState.CreateCreature` at :201715 with `RunState.Rng.Niche`.)

So initial HP is drawn from the run's **Niche** stream, uniformly over the
ascending set of values in `[MinInitialHp, MaxInitialHp+1)` that are not the
MaxHp of another creature on the same side; if the set is empty, a plain
uniform draw is used. `NextItem` enumerates a `HashSet<int>` built by
`Enumerable.Range(...).ToHashSet()`, i.e. ascending insertion order.

## Extraction

`extract_hp.py` parses every `class X : MonsterModel` block in the local
decompile, evaluates `MinInitialHp` / `MaxInitialHp` for A0 and A8
(`ToughEnemies = 8`), resolves inherited properties through the base class,
and handles Axebot's default `StockAmount = 2` (`RespawnMaxHpBonus = 0` on the
initial spawn). Run:

```
python -I validation/step2-monster-hp-20261104/extract_hp.py \
  D:/sts2_datacollection/_decomp_local_0861bfa1/sts2.decompiled.cs \
  simulator/content/monsters.json [--write]
```

Result: **106 / 109** JSON entries matched; **23 HP ranges differed** from the
stale reference-engine values (full list in `hp-diff.txt`). Examples:

| monster | old A0 / A8 | decompiled A0 / A8 |
| --- | --- | --- |
| CRUSHER | 199/199, 209/209 | 209/209, 219/219 |
| EXOSKELETON | 24..28, 25..29 | 24..28, 26..30 |
| BYRDONIS | 91..94, 99/99 | 81..84, 90/90 |
| PUNCH_CONSTRUCT | 46..55, 46..60 | 55/55, 60/60 |
| WATERFALL_GIANT | 250/250, 260/260 | 240/240, 250/250 |
| DECIMILLIPEDE_SEGMENT | 42..48, 48..56 | 40..46, 46..52 |
| MYSTERIOUS_KNIGHT | 101/101, 101/101 | 101/101, 108/108 (inherits FlailKnight) |
| AXEBOT | 40..44, 40..44 | 70..78, 76..86 (StockAmount 2 -> no respawn bonus) |

`hp-diff.txt` is the before/after report; `monsters.before.json` preserves the
pre-change content for inspection. The generator
(`simulator/tools/gen_monsters.py`) was rerun; only HP arrays and `hp_source`
changed in the tables.

Unmatched (3): `DOOR`, `DOORMAKER`, `ROYAL_GUARD` — no corresponding
`MonsterModel` class exists in this decompile (`Door` was deleted in the
Doormaker rework; the entries are retained for enum stability and remain
`sampled_only`).

## Engine change

`simulator/src/monsters.cpp`:

- `roll_monster_hp` implements the native two-pass selection: count unused
  values, one `NextInt(0, count)` draw, then pick the k-th ascending unused
  value. Empty set falls back to one uniform draw over the full range.
- `spawn_at` now draws initial HP from `bc.nicheRng` (was `bc.monsterAiRng`).
- `monster_hp_taken` excludes `MaxHp` of other same-side, non-INVALID, alive
  monsters, matching `creaturesOnSide` semantics at creature-creation time.

Native creation order is preserved: `CombatRoom.StartCombat` creates every
creature (HP draws, uniqueness against already-created creatures), then
`AfterCreatureAdded` runs room hooks. This matches the engine's existing
"draw all spawn HP, then apply encounter post-processing" order
(PunchOff reduction, Decimillipede even/unique normalization).

## Encounter RNG (same batch)

`EncounterModel.GenerateMonstersWithSlots` seeds a throwaway RNG with
`(ulong)(seed + TotalFloor) + hash(Id.Entry)` (`:75806`), where `Id.Entry` is
`StringHelper.Slugify(class name)` (`ModelDb.GetId`). It drives roster rolls
and correlated starting moves; `MonsterModel.RollMove` separately uses
`RunRng.MonsterAi` (`:77934`), and `Creature.SetUniqueMonsterHpValue` uses
`RunRng.Niche`.

Implemented:

- `EncounterDef.nativeEntry` is emitted by `gen_monsters.py` from the setup
  name (uppercased). All 89 non-null entries were checked against the
  `EncounterModel` subclass slugs extracted into `encounter_classes.txt`;
  none are missing. Explicit entries are used for the event encounters
  (`*_EVENT_ENCOUNTER`, `BATTLEWORN_DUMMY_EVENT_V*_ENCOUNTER`) and `nullptr`
  for the two non-native legacy entries (`SETUP_DOORMAKER_BOSS`,
  `SETUP_TOADPOLES_NORMAL` — the latter was renamed to `SeapunkNormal` in this
  build and is already excluded from the Underdocks bag).
- `RunContext::begin_combat` builds `Rng(seed + floor + hash(nativeEntry))`
  after resolving the encounter; `floor` was already incremented, matching
  native `TotalFloor` (MapPointHistory sum including the current point).
- `setup_encounter` consumes that RNG for the roster pick, Decimillipede /
  ScrollsOfBiting / TwoTailedRats / CorpseSlugs correlated starts, and
  PunchOff's two `StartingHpReduction` rolls. A single observed roster does
  not consume a draw (native GenerateMonsters is deterministic there).
- Decimillipede `StarterMoveIdx` 0/1/2 maps to WRITHE/BULK/CONSTRICT; the port
  stores WRITHE/CONSTRICT/BULK, so the forced indices use `{0,2,1}`.
- CorpseSlugs now uses the native one-draw rotation
  (`WHIP_SLAP/GLOMP/GOOP`) instead of three independent MonsterAi draws.

Remaining approximation: roster-variant selection uses the sampled
`ENC_PATTERNS` weights rather than replaying each native `NextItem(items)`
call; the distribution can differ even though the encounter RNG stream and
draw count for the covered encounters match. `random_encounter_for_act`'s
bag-exhaustion fallback still draws from MonsterAi (native uses the
map-generation UpFront RNG); it is unreachable while bags are non-empty.

## Encounter roster re-inventory (decompile)

`extract_encounters.py` extracts every `GenerateMonsters` roster and compares
it with all sampled rosters (`encounter-roster-audit.txt` before,
`encounter-roster-audit-after.txt` after). It found six deterministic roster
mismatches inherited from the reference engine, now corrected in
`content/monsters.json`:

| encounter | sampled before | native / now |
| --- | --- | --- |
| AXEBOTS_NORMAL | 2 Axebots | 1 Axebot |
| EXOSKELETONS_NORMAL | 3 | 4 Exoskeletons |
| EXOSKELETONS_WEAK | 2 | 3 Exoskeletons |
| SLUMBERING_BEETLE_NORMAL | Beetle only | Rock, Silk, Beetle |
| TUNNELER_NORMAL | Bowlbug + Tunneler (2 variants) | Chomper (ScreamFirst) + Tunneler |
| GREMLIN_MERC_NORMAL | Merc + Sneaky + Fat at start | Merc only |

DenseVegetation's audit line is a parser false positive: native iterates
`Slots` (four Wrigglers), which the sampled four-Wriggler roster already
matches.

The six encounters with genuinely randomised rosters now replay the native
draws in `native_random_roster` (`monsters.cpp`) instead of using sampled
weights:

- FlyconidNormal: `NextItem([LeafM, TwigM])` + Flyconid.
- SlimesNormal: `NextBool` selects which small slime is third.
- SlimesWeak: two distinct small slimes without replacement, then a medium;
  native list order is small1, medium, small2.
- SlitheringStranglerNormal: `NextItem` over
  `{SnappingJaxfruit, MediumSlime, SmallSlimes}`, then the secondary draw(s)
  and the Strangler.
- BowlbugsNormal/Weak: Rock plus workers/bugs from the native dictionaries
  (Normal draws two distinct workers in Egg/Silk/Nectar order).
- RubyRaidersNormal: three distinct raiders in
  Axe/Assassin/Brute/Crossbow/Tracker order.

`GREMLIN_MERC_NORMAL` now starts with one merc; `SurprisePower.AfterDeath`
appends SneakyGremlin then FatGremlin to the enemy list and transfers the
stolen gold to the Fat Gremlin (`battle_damage.cpp`), instead of spawning them
as initial roster members.

Regression coverage (`monster_audit_regression.cpp`): deterministic roster
sizes/order, Tunneler Chomper's first move, exact encounter-RNG draw counts
and composition for all six randomised encounters, and the Surprise death
spawn/gold transfer. Results: CTest 33/33, rules 833/0, monster audit 0
failures, pytest 363 passed/16 skipped, 1000-run smoke 0 anomalies
(`*-final-20261104j.txt`).

## Tests

- `simulator/tests/monster_audit_regression.cpp`:
  - ToughEgg now asserts the egg's initial HP is the first Niche draw and
    re-snapshots the stream before the hatch draw. This is not a weakened
    assertion: native `CreateCreature` consumes Niche before the hatch roll.
  - New check: two Chompers in one side draw HP from Niche, the second
    excludes the first MaxHp, and the stream advances exactly once per monster.
  - New check: PunchOff's two HP reductions come from the supplied encounter
    RNG (exactly two draws) and MonsterAi is untouched.
  - New check: Decimillipede consumes one encounter draw and applies the
    WRITHE/BULK/CONSTRICT starter mapping.
- Clean full rebuild (`build-clean-20261104h.txt`, exit 0, no errors);
  CTest **33/33** (`ctest-final-20261104i.txt`).
- `rules_test.exe` **833 checks / 0 failures**
  (`rules-regression-final-20261104i.txt`).
- `pytest tests` **363 passed / 16 skipped**
  (`pytest-final-20261104i.txt`).
- `bench.exe run 1000`: 1000 completed, 0 truncated, 0 errors, 52.5 runs/s,
  5.7 us/combat step (`benchmark-runs-1000-final-20261104i.txt`). Throughput
  on this host is extremely load-sensitive (observed 51-108 runs/s across
  runs of the same build); no rules were traded for speed.

Final batch-9/10 verification (relic pulls + four event re-verifications,
clean rebuild of current source): `build-clean-20261104q.txt` exit 0 / 0
errors (an incremental `build-final-20261104q2.txt` rebuild follows the
last test-string rename); CTest **33/33** (`ctest-final-20261104q.txt`);
`rules_test.exe` **840 checks / 0 failures**
(`rules-regression-final-20261104q.txt`, +7 Wongos/shop checks);
`sts2_monster_audit_test.exe` 0 failures
(`monster-audit-final-20261104q.txt`); `sts2_map_event_audit_test.exe` 0
failures (`map-event-audit-final-20261104q.txt`, adds TabletOfTruth,
LostWisp and Wellspring branch checks); pytest **363 passed / 16 skipped**
(`pytest-final-20261104q.txt`); `bench.exe run 1000` 1000 completed / 0
truncated / 0 errors, 77.2 runs/s, 3.9 us/combat step
(`benchmark-runs-1000-final-20261104q.txt`).

## Evidence identity / limitations

- The decompile is the **local build `0861bfa1`**, not the target DLL
  `9cb4f1ad8c9f284aa8fec3122ffd6d780bbf543d875c817abdd12ff63fbf12b4` (absent
  on this machine). This evidence is labelled decompile-based; it is not a
  target-DLL differential.
- Initial-move selection uses `monsterAiRng`, which matches native
  `MonsterModel.RollMove -> RunRng.MonsterAi`. Monster-specific `base.Rng`
  uses are limited in this build to the PunchOff reduction (encounter RNG,
  covered above) and ToughEgg's cosmetic skin choice (not simulated), so no
  persistent per-monster RNG state was needed.
- The six randomised encounters above now replay native draws; the weighted
  `ENC_PATTERNS` fallback is only reached for single-roster encounters (no
  draw). The bag-exhaustion fallback in `random_encounter_for_act` still uses
  MonsterAi (native uses UpFront) and remains listed as a gap.
- `docs/MONSTERS_REFERENCE.md` still carries the old reference-engine HP
  values; it was not regenerated in this batch.

## Relic pull sources: shop filter and the Wongos FeaturedItem

A decompile audit of all 15 `RelicFactory.PullNextRelicFromFront` /
`PullNextRelicFromBack` call sites found two mistakes in the port:

1. `RelicModel.IsAllowedInShops` is overridden to `false` by five relics
   (`AmethystAubergine` :85270, `BowlerHat` :86427, `LuckyFysh` :90675,
   `OldCoin` :91661, `TheCourier` :95609). Shop `FillSlot` (:179906) and both
   Wongos purchases (:129531, :129587) filter on it. The port only excluded
   `THE_COURIER`/`OLD_COIN` from back pulls and had no shop filter at all on
   front pulls.
2. `WelcomeToWongos.GenerateInitialOptions` pulls the FeaturedItem when the
   event starts with explicit `RelicRarity.Rare` (so **no Rewards draw**),
   removing it from the player's rare deque and the shared bag. The port
   scanned `RelicId` order at event start, left the bag untouched, and did not
   consume the featured relic.

Changes:

- `relic_allowed_in_shops` (`relics.cpp`) encodes the five native overrides.
- `RunContext::pull_relic` gained `shopsOnly`. Shop back pulls pass
  `fromBack=true`; Wongos passes `shopsOnly=true` for front pulls. Native
  `PullFromFront` only removes the relic it returns, so a front pull that skips
  a filtered relic now leaves it in the deque; run-state-disallowed relics are
  still purged.
- `EV_WELCOME_TO_WONGOS` start stores the front shop-allowed rare in
  `eventData[0]`; `BuyFeaturedItem` obtains it and `BuyBargainBin` performs an
  explicit front Common shop pull. Neither consumes Rewards RNG for rarity.

The other 12 call sites match native (LargeCapsule 2 pulls, ToyBox 5 wax
rewards, PaelsWing every 2 skips, BattlewornDummy V3, LuminousChoir, Ranwid x3,
RelicTrader 3 rewards, RoundTeaParty, ThisOrThat, Trial x2, UnrestSite).

Legacy checkpoint note: mid-Wongos checkpoints written by the previous build
hold the old scanned relic id in `eventData[0]`; they still restore and grant
that relic. The snapshot layout is unchanged.

Regression coverage: `r7_wongo_featured_*`, `r7_wongo_bargain_*`
(`rules_regression.cpp`) and the shop/filter deque assertions in
`snapshot_validation.cpp`.

## Event status re-verification (same batch)

Four events that were still labelled APPROXIMATE were re-read against the
decompile, found to have no remaining divergence, and promoted to
IMPLEMENTED with branch-level regressions (`map_event_audit` unless noted):

- TabletOfTruth (:127354): costs 3/6/12/24/`MaxHp - 1`, fifth decipher
  upgrades all, lethal branch drops MaxHp to 1 then kills.
- LostWisp (:125187): gold = `60 + base.Rng.NextInt(-15, 16)`; Claim adds Decay
  and the LostWisp relic (Power cards deal 8 unpowered damage).
- SapphireSeed (:126713): Eat heals 9 and upgrades; Plant only offers
  Sown-enchantable cards (`enchantment_contract.cpp`).
- Wellspring (:129620): Bottle draws one potion from the native
  Ironclad+shared pool order through PlayerRng.Rewards; Bathe removes one card
  then adds Guilty.

The event manifest is now 47 IMPLEMENTED / 14 APPROXIMATE / 5 UNSUPPORTED;
AROMA_PLACEHOLDER (no native class) and WarHistorianRepy (unreachable) account
for two of the unsupported entries, leaving CrystalSphere, FakeMerchant and
TinkerTime as the real unsupported content. No assertions were removed or
relaxed.
