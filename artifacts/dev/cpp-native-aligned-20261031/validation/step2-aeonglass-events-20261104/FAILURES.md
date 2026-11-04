# Failure record for this batch

Every failure encountered while integrating this batch is listed with the
resolution and the independent evidence used.  No failing assertion was deleted
or loosened without a stated reason.

## 1. Schema tests expected the pre-content layout

`tests/test_audit_regressions.py::test_observation_schema_versions_are_bumped`
and `tests/test_binding_schema_contract.py::test_field_limits_and_public_schema`
failed with `PUBLIC_OBS_DIM=67782` vs expected `67775` and version 14 vs 15.

Resolution: `PUBLIC_OBS_VERSION` bumped 14 -> 15 and expectations set to the
derived values.  Evidence is arithmetic from the layout formulas in
`simulator/include/sts2/observe.h`: `MonsterId.COUNT + 1` adds one one-hot to
each of `MAX_MONSTERS=4` slots (+4 combat), `Encounter.COUNT + 1` adds
`2*COUNT` + 1 extension entry (+3 run).  A second change (registering three
native unsupported events) grew `PUB_EVENT_N` 64 -> 66 (+2 run), final
67784 / 44265 / 23519.  The binding length is asserted against the live
`observe_public()` output, so this is not a golden re-record.

## 2. Snapshot version test expected v9

`tests/test_native_step1_state.py::test_previous_snapshot_version_is_rejected`
expected header bytes `09 00`; the batch moved the raw `Card` layout (potion
slots and `fakeUpgradeLevel`), so the snapshot format changed earlier in this
uncommitted batch to v10.  The test now expects `0a 00` and still proves the
previous v9 blob is rejected atomically.

## 3. ArmG gradient contract failed on float32 accumulation

`test_rules_batched_gradient_matches_exact_per_decision_transform` failed at
`atol=2e-5`.  Measured on the same seeds: max absolute gradient difference
`1.3e-3` (embedding layer), but the *relative Frobenius* difference was
`4.6e-5` for every non-degenerate parameter, and changing only `chunk_size`
(2 vs 4, same math) moved the same gradients by the same order.  That is
float32 summation-order noise over a 23517-wide state, not a transform bug.

Resolution: the contract test now runs the same transform in float64 (the
production call site keeps float32; `backward_weighted` now takes the input
dtype from the observation batch) and asserts loss/gradients at
`rtol=1e-12, atol=1e-12` / `rtol=1e-9, atol=1e-10`.  This is tighter than the
old assertion, not looser, and it keeps the structural comparison exact.

## 4. ArmG gate hardcoded the observation version

`agent/armg_train.py` refused any public observation version other than 14
because slots 8/9/10 carry in-combat/elite/boss classification.  Those offsets
are unchanged in v15, so the gate was updated to 15.  No layout assumption was
removed.

## 5. Live worker hardcoded the event-id space

`test_armg_native_bridge.py::test_native_new_fields_encode_at_real_schema_boundaries`
raised `wrong state feature count: 23517` because the live encoder wrote a
64-wide event block and rejected event ids `>= 64`.  Added a `PUB_EVENT_N`
binding and made `scripts/armg_live_worker.py` / `armg_live_events.py` use it
instead of the literal.  The test now passes at the real schema boundary.

## 6. Snapshot validation asserted more than native guarantees

`sts2_snapshot_validation_test` aborted at
`assert(bag.normalBag[i] != bag.normalBag[j])` after the Hive encounter list was
corrected.  Root cause: native `ActModel.GenerateRooms` fills normal encounters
from a `GrabBag` and refills it when empty, so a duplicate is possible after a
refill; Hive has 10 regular encounters for 11 regular rooms.  The old assertion
only passed because the content table contained the non-native
`SETUP_TUNNELER_NORMAL` (11 entries).

Resolution: the test now asserts uniqueness within one grab-bag cycle, using
the native declaration-list pool sizes (weak/normal/elite = 4/4/3, 12/10/3,
9/3/3 for Overgrowth/Hive/Glory).  Evidence: decompiled
`ActModel.GenerateRooms` (line 71570) and `RoomSet.NextNormalEncounter`
(line 47143, modulo cycling).  The assertion was not deleted; it is now the
invariant the native code actually provides.

## 7. Snapshot restore replay diverged inside a card grid

`tests/test_smoke.py::test_snapshot_restore_replays_identically` failed after
the event-bag changes moved seed 32 onto BrainLeech: the restored run produced
a different `state_hash` on the first step after restore, with exactly one
differing byte.  The byte was inside `RunCardGrid` (grid padding after
`preview`).  `RunContext` snapshots hash the raw object image, and MSVC copies
trivially-copyable `RunCardGrid` assignments as a whole-object copy, so
uninitialized stack padding from a local `RunCardGrid` reached the run state.

Resolution: `RunCardGrid` now has a constructor that clears the object image
and restores the `-1` defaults (`orderSlots`, `freeNext`, `freeHead`), the same
pattern already used by `Card`.  This removes the nondeterminism instead of
masking the hash; the replay test then passes.  The first attempt cleared
`freeHead` to 0 by omission, which snapshot validation correctly rejected
(`fresh restore == false`); it was fixed to `-1`.

## 8. Event-status assertions became stale as events were implemented

`tests/test_step2_rules_20261104.py::test_event_bags_follow_native_declaration_order`
asserted that WhisperingHollow/WoodCarvings/ZenWeaver were UNSUPPORTED.  After
implementing WhisperingHollow and ZenWeaver the assertion was false, not the
engine.  It now asserts those two are IMPLEMENTED and WoodCarvings remains
UNSUPPORTED; the bag-order loop still derives the expected pool from live
statuses.  The replacement is backed by new C++ checks in
`simulator/tests/rules_regression.cpp`, not by deleting the assertion.

## 9. Necrobinder finished-card set overflowed a fixed image

`tests/test_smoke.py::test_room_transitions_and_economy` raised
`OverflowError: Finished card identity capacity` during a heuristic combat
rollout.  `necrobinder_after_card_played` appended every distinct played uid to
a 160-entry fixed image and threw at capacity; native keeps an unbounded
`HashSet`.  The new event bag moved the seed onto a combat where a generated
card loop finishes more than 160 distinct cards in one turn.

Resolution: when the image is full, the oldest uid is dropped and the newest
appended (most-recent-160 semantics).  This is deterministic, removes the
abort, and differs from native only for >160-distinct-card turns; the comment
in `simulator/src/necrobinder.cpp` records the ceiling.  The smoke test passes.

## 10. MorphicGrove used a helper declared after `event_allowed_now`

The first rebuild after adding MorphicGrove failed with C3861
(`transformable_deck_count` not found) because the helper lives later in the
anonymous namespace.  A forward declaration was added before the status/table
section; the build then succeeded and the new Grove checks passed.

## 11. Initial Trial checks reused a finished event context

The first Trial regression block called `event_choose` again after an earlier
option had already called `finish_event`, so the follow-up choices were
rejected (`screen != EVENT`) and seven checks failed.  The test was wrong, not
the engine: each trial branch now gets a fresh `RunContext` with
`event_begin`, and all checks pass.  No engine assertion was loosened.

## 12. Duplicate `EV_PUNCH_OFF` case in `event_allowed_now`

`event_allowed_now` already had a PunchOff floor gate further down; adding the
new case produced C2196 (duplicate case).  The duplicate was removed and the
original rule kept.

## 13. Snapshot validation rejected the new card-selection kinds

`simulator/tests/snapshot_validation.cpp` (CTest 8) rejected a valid event
snapshot with `valid snapshot rejected: seed=11 step=31 screen=5`: the event
bag now reaches SelfHelpBook/WoodCarvings, whose card-selection kinds 7-10 were
outside the snapshot validator's `eventCardSelection <= 6` bound.  The bound
was raised to 10; the per-kind legality check in
`event_card_selection_valid` was extended at the same time.  The snapshot
layout and version did not change (the field is still one byte).

## 14. `test_snapshot_restore_replays_identically` seed ended early

With the expanded event bags, seed 32 died before 250 steps, so the test
skipped ("seed finished before the snapshot point").  This was a fixture
sensitivity, not a restore bug: seed 4 was verified to reach a non-terminal
snapshot point and the test now uses it.  The skip branch remains for future
rule changes; the [skip] reason is still reported.

## 15. Event-status assertion updated again

`test_event_bags_follow_native_declaration_order` asserted WoodCarvings stayed
UNSUPPORTED.  WoodCarvings and SelfHelpBook are now implemented (Sharp/Slither
enchantments plus their selection rules), so the assertion now checks all four
previously-missing act events are IMPLEMENTED.  The bag-order expectation is
still derived from live statuses and backed by new C++ checks.

## 16. BattlewornDummy regression read Strength from the power array

The first Battleworn/TheLantern checks read
`mk.power[PowerId::STRENGTH]`, which is always zero in this engine: Strength
is stored in `Monster::strength`, while `power_ref` only redirects writes.
The engine applied the correct 6 Strength; the test was wrong and was changed
to read `mk.strength`.  No game-code change.

## 17. Generated MysteriousKnight data lost inherited ascension values

`monsters_generated.inc` gives `MYSTERIOUS_KNIGHT` HP `{101,101}` and no A9
`deadlyDamage` on its Flail/Ram intents, but the decompiled class inherits
`FlailKnight`: HP 101/108 and Flail 9/10, Ram 15/17.  The generator row is
incomplete, not the native behavior.  `setup_encounter` applies the A8+ 108 HP
and `roll_intent`/`monster_act` apply the A9 damage overrides explicitly, with
a comment.  Regenerating `monsters_generated.inc` remains the proper fix and
is recorded in `results.json` `not_done`.

## 18. BattlewornDummy reward path needed an event-combat resume hook

`finish_combat` only opened the reward screen when a relic/gold/stolen reward
existed, so the V1 potion-only reward would have been dropped and the event
would have resumed with no reward.  `event_resume_after_combat` now handles
BattlewornDummy (potion / StableShuffle upgrades / front relic, and the
RanOutOfTime defeat page) and TheLanternKey (fixed special card) before the
generic `eventReturnPage` branch.  The new checks cover both the escape and
the kill path.

## 19. Event combats wrongly suppressed the room's standard rewards

The simulator's `finish_combat` treated every `eventCombat` fight as
no-standard-rewards.  The decompile shows `EncounterModel.ShouldGiveRewards`
defaults to true and only `BattlewornDummyEventEncounter` overrides it to
false; `RewardsSet.WithRewardsFromRoom` appends `CombatRoom.ExtraRewards` after
the normal gold/potion/card list.  So DenseVegetation, PunchOff and
TheLanternKey were each missing a gold reward, a potion roll and a 3-card
reward (FakeMerchant has the same rule but is still unsupported).

Fixed in `events.cpp` (`event_combat_gives_standard_rewards`,
`event_combat_extra_rewards`) and `run.cpp`: standard-reward event fights now
fall through the normal reward block, append extras afterwards using the
rewards RNG in native populate order, and clear the event state because these
events pass `shouldResumeAfterCombat=false`.  TheLanternKey's special card is
placed in the next free card-reward slot instead of overwriting slot 0;
BattlewornDummy keeps the no-standard path.  Regression checks were added for
PunchOff, DenseVegetation and TheLanternKey.  `test_smoke.py`'s snapshot replay
moved from seed 4 to seed 5 because seed 4 now dies before step 250 under the
corrected rewards (seed 5 verified non-terminal at 250 steps).

## 20. Four event RNG ranges were inclusive where native is exclusive

Native `Rng.NextInt(min, max)` treats `max` as exclusive. The port had four
inclusive translations in implemented content: PunchOff gold (91..99 instead of
91..98), LuminousChoir cost (99..149 instead of 100..149), WhisperingHollow gold
cost (26..45 instead of 26..44), and PunchOffConstruct StartingHpReduction
(2..10 instead of 2..9). Each was corrected and given a range regression check.
DenseVegetation, SunkenStatue, ThisOrThat, LostWisp and JungleMazeAdventure
rolls were re-verified against the decompile and already matched.

## 21. StoneOfAllTime compacted the potion belt

`Lift` stored a `NextItem(Player.Potions)` index (non-null slots in physical
order) but removed the potion by shifting the array and decrementing
potionCount, which both removed the wrong slot when the belt had holes and
broke the physical-slot model. It now maps the index to the actual slot and
uses `potion_remove_at`, leaving an empty slot. A regression check starts with
slots `[empty, FoulPotion, empty]` and verifies the potion disappears from slot
1 while max HP increases by 10.

## 22. Monster HP stream remains approximate (not fixed)

`Creature.SetUniqueMonsterHpValue` draws from `RunState.Rng.Niche` over the
ascending set of unused HP values on the enemy side, and the encounter RNG
(`seed + TotalFloor + hash(encounter Id.Entry)`) drives encounter-specific
rolls such as PunchOff's StartingHpReduction. The C++ engine currently samples
HP and those encounter rolls from `monsterAiRng`, and 108 of 109 monster HP
ranges in `content/monsters.json` are 512-sample probe estimates rather than
decompile-extracted MinInitialHp/MaxInitialHp. This is recorded in
`results.json` `not_done`; no rule was changed for it in this batch.

## 23. Orobas locked third option was selectable

`OptionPool3` returns a locked `EventOption` (null onChosen) when neither
TouchOfOrobas nor ArchaicTooth can set up. The port stored relic id 0 and left
option 2 available, so a player could spend the choice on a no-op. Ancient
INVALID relic slots are now unavailable; the locked case still consumes the
single `NextItem` draw that native performs over the one-entry locked list.
ArchaicTooth's deck condition was corrected to Bash/Neutralize/Unleash/
FallingStar/Dualcast (it previously also accepted BREAK).

## 22 update (2026-11-04, monster HP batch)

The HP half of item 22 is fixed; the encounter-RNG half remains.

- All 106 monsters that exist as `MonsterModel` classes in the local
  decompile now get decompile-extracted `MinInitialHp`/`MaxInitialHp`
  (`hp_source: decompiled_local_0861bfa1`); 23 ranges changed versus the
  stale reference-engine samples. `DOOR`, `DOORMAKER`, `ROYAL_GUARD` have no
  class in this decompile and stay `sampled_only`.
- `spawn_at` draws HP from `bc.nicheRng` using the native unique-value
  algorithm (`Creature.SetUniqueMonsterHpValue`): exclude same-side MaxHp
  values, one `NextInt(0,count)` / `NextItem`, fallback uniform draw.
- Regression coverage added in `monster_audit_regression.cpp` (ToughEgg
  initial draw + two-Chomper uniqueness/stream consumption). Full rebuild;
  CTest 33/33; rules 833/0; pytest 363 passed / 16 skipped; 1000-run smoke
  0 anomalies / 0 truncation. See `validation/step2-monster-hp-20261104/`.
- Still open: encounter-specific rolls use `EncounterModel.Rng =
  new Rng(seed + TotalFloor + hash(encounter Id.Entry))` in native but
  `monsterAiRng` here; per-monster `MonsterModel.Rng` initial-move rolls
  likewise remain on `monsterAiRng`. These are the next RNG-alignment items,
  not silently accepted as equivalent.

## 22 update 2 (2026-11-04, encounter RNG batch)

The encounter-RNG half of item 22 is implemented:

- `EncounterDef` now carries the native `ModelId.Entry`
  (`StringHelper.Slugify(class name)`), generated from the setup name with
  explicit event-encounter entries. `RunContext::begin_combat` builds
  `Rng(seed + floor + hash(entry))` after `++floor` (native TotalFloor includes
  the current point) and passes it into `battle.init -> setup_encounter`.
- Roster picks, Decimillipede/Scrolls/TwoTailedRats/CorpseSlugs correlated
  starts and PunchOff's two StartingHpReduction rolls now consume that
  throwaway RNG instead of `monsterAiRng`; single-roster encounters consume
  no draw. Decimillipede starter indices corrected to WRITHE/BULK/CONSTRICT
  order; CorpseSlugs uses one-draw rotation.
- MonsterAi remains the stream for `RollMove`/random branches, matching
  native `RunRng.MonsterAi`; no per-monster RNG state is needed for this
  build beyond PunchOff.
- Still approximate: roster variant weights are sampled `ENC_PATTERNS`
  probabilities, not a replay of native `NextItem(items)` lists; the
  bag-exhaustion fallback in `random_encounter_for_act` still uses MonsterAi.
- Verification: full rebuild; CTest 33/33; rules 833/0; pytest 363 passed /
  16 skipped; 1000-run smoke 0 anomalies / 0 truncation. Evidence:
  `validation/step2-monster-hp-20261104/` (final logs `*-20261104h.txt`).

## 24. Encounter rosters inherited from the reference engine were stale

`extract_encounters.py` compared every decompiled `GenerateMonsters` roster
with the sampled rosters in `content/monsters.json`. Six deterministic
rosters were wrong: AxebotsNormal had two Axebots (native one);
ExoskeletonsNormal/Weak had 3/2 (native 4/3); SlumberingBeetleNormal was a
single Beetle (native Rock, Silk, Beetle); TunnelerNormal was Bowlbug +
Tunneler (native Chomper with ScreamFirst + Tunneler); GremlinMercNormal
started with Merc + Sneaky + Fat (native Merc only). The content table now
matches the decompile, Tunneler's Chomper gets its native SCREECH first move,
and GremlinMerc's helpers are spawned by SurprisePower on the merc's death
(SneakyGremlin then FatGremlin appended at the end of the enemy list, stolen
gold transferred to Fat).

The six randomised encounters (Flyconid, Slimes normal/weak, Slithering
Strangler, Bowlbugs normal/weak, Ruby Raiders) now replay the native
`NextItem`/`NextBool` draws in `native_random_roster` instead of weighted
sampled patterns, including the SlimesWeak list order small1, medium, small2.
DenseVegetation's audit mismatch is a parser false positive (native loops over
four slots; the sampled four Wrigglers are correct).

Evidence: `validation/step2-monster-hp-20261104/encounter-roster-audit*.txt`,
`extract_encounters.py`; regression checks in `monster_audit_regression.cpp`.
Verification: CTest 33/33, rules 833/0, monster audit 0 failures, pytest
363 passed / 16 skipped, 1000-run smoke 0 anomalies (`*-final-20261104j.txt`).

## 25. Shop relic filtering and the Wongos FeaturedItem pull were both wrong

A decompile pass over every `RelicFactory.PullNextRelicFromFront` /
`PullNextRelicFromBack` call site found two divergences:

- `RelicModel.IsAllowedInShops` is overridden to `false` by five relics
  (`AmethystAubergine` :85270, `BowlerHat` :86427, `LuckyFysh` :90675,
  `OldCoin` :91661, `TheCourier` :95609). Shops pull from the back with
  `(blacklist == null || !blacklist.Contains(r)) && r.IsAllowedInShops`
  (`MerchantRelicEntry.FillSlot` :179906), and `WelcomeToWongos` pulls the
  FeaturedItem (*Rare*) and Bargain Bin (*Common*) from the front with the same
  filter (:129531, :129587). The port only excluded OldCoin/TheCourier from
  back pulls and had no shop filter for front pulls, so the other three could
  appear in shops and the Wongos pulls could return them.
- `WelcomeToWongos.GenerateInitialOptions` pulls the FeaturedItem when the
  event starts with an explicit rarity (no `RollRarity`, so no Rewards draw),
  removing it from the player's rare deque and the shared bag. The port instead
  scanned `RelicId` order at event start, left the relic in the bag, and
  consumed nothing. `BuyFeaturedItem` now obtains the stored pull; the
  Bargain Bin uses an explicit Common front pull with the shop filter.

`RunContext::pull_relic` gained a `shopsOnly` flag. Native `PullFromFront`
only removes the relic it returns, so a caller-filtered front pull now skips a
filtered-out relic without consuming it; run-state-disallowed relics are still
purged. Back pulls (shops) already skipped filtered relics.

Audit of the other 12 call sites found no divergence: LargeCapsule (2 relics),
ToyBox (5 wax relic rewards), PaelsWing (every 2 skips), BattlewornDummy V3,
LuminousChoir, Ranwid (potion/gold/relic), RelicTrader (3 rewards), RoundTeaParty,
ThisOrThat, Trial, UnrestSite, and both Wongos purchases all match the native
pull-rarity/pull-front order; UnrestSite's `add_random_shared_relic` is the same
RollRarity(0.5/0.83) + front pull.

Legacy checkpoint caveat: checkpoints captured mid-Wongos by the previous build
store the old scanned relic in `eventData[0]`; restore grants that relic. The
snapshot layout is unchanged, so they still load.

Evidence: decompile lines above; regression checks
`r7_wongo_featured_*`, `r7_wongo_bargain_*` (rules_test) and the shop/filter
deque checks in `snapshot_validation.cpp`.

Verification (batch 9): clean full rebuild of current sources
(`build-clean-20261104q.txt`, exit 0, 0 errors); CTest 33/33
(`ctest-final-20261104q.txt`); rules 840/0 with the seven new Wongos/shop
checks (`rules-regression-final-20261104q.txt`); monster audit 0 failures;
pytest 363 passed / 16 skipped (`pytest-final-20261104q.txt`); 1000-run smoke
1000 completed / 0 truncated / 0 errors (`benchmark-runs-1000-final-20261104q.txt`).

## 26. Four events labelled APPROXIMATE had no remaining divergence

Re-read the local decompile (`_decomp_local_0861bfa1`) for four events whose
port logic already matched, then added branch-level regressions and promoted
them from APPROXIMATE to IMPLEMENTED:

- **TabletOfTruth** (:127354): per-page costs 3/6/12/24/`MaxHp - 1`; the fifth
  decipher upgrades every upgradable card and finishes; a cost not below
  current MaxHp first drops MaxHp to 1 and then kills (Fairy-style prevention
  still applies). Port matched; `map_event_audit` now asserts the full cost
  sequence, the all-upgrade page and the lethal branch.
- **LostWisp** (:125187): `CalculateVars` sets Gold = `60 + base.Rng.NextInt(-15, 16)`.
  Claim adds Decay plus the LostWisp relic; Search grants the rolled gold. The
  relic (Power cards deal 8 unpowered damage, :90656) was already implemented.
- **SapphireSeed** (:126713): Eat heals 9 then upgrades one selected card; Plant
  offers only Sown-enchantable cards. Already covered by
  `enchantment_contract.cpp`; no code change.
- **Wellspring** (:129620): Bottle draws `PlayerRng.Rewards.NextItem` over the
  concatenated Ironclad + shared potion pools and offers a potion reward;
  Bathe removes one card then adds Guilty. `map_event_audit` now asserts the
  native pool order, the single Rewards draw and the remove-then-Guilty order.

Status table is now 47 IMPLEMENTED / 14 APPROXIMATE / 5 UNSUPPORTED
(AROMA_PLACEHOLDER has no native class, WarHistorianRepy is unreachable, and
CrystalSphere/FakeMerchant/TinkerTime remain the three real unsupported
events). No assertions were relaxed or removed.

Verification (same batch): clean rebuild `build-clean-20261104q.txt` (exit 0,
0 errors) plus an incremental `build-final-20261104q2.txt` after the last
test-name edit; CTest 33/33 (`ctest-final-20261104q.txt`);
`sts2_map_event_audit_test.exe` 0 failures
(`map-event-audit-final-20261104q.txt`); rules 840/0; pytest 363 passed / 16
skipped; 1000-run smoke 1000 completed / 0 truncated / 0 errors
(`*-final-20261104q.txt`).
