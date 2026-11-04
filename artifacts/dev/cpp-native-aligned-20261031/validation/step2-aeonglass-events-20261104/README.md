# Step-2 rule pass: Aeonglass, ByrdonisNest, Splash, potion holes, native ordering

2026-11-04. Scope: Ironclad single-player, target `v0.111.0 / 41cef1ea`.

## Identity

| field | value |
| --- | --- |
| ruleset | `native-41cef1ea-port-v6` |
| public observation | v15, dim 67784 (run 23519 + combat 44265) |
| action schema | v13, feature dim 717 |
| ArmG feature | v6 (state width 23519) |
| snapshot | v10 |
| target DLL | `9cb4f1ad...` (absent, see BLOCKERS.md) |
| local DLL | `0861bfa1...` (same-source reading evidence only) |

## Changes covered here

- Physical potion belt slots (`Player.PotionSlots` null holes): first-empty-slot
  add, hole-preserving removal, max-slot shrink, legal actions, snapshot
  validation, public observation, Python bindings, ArmG encoding.
- Splash: all unlocked character pools minus the owner pool (only when more
  than one pool exists), combat-generatable Attacks, `GetDistinctForCombat` 3,
  upgrade candidates, skippable choice, chosen card free this turn + to hand.
- Aeonglass boss: 512/535 HP, Ebb 22/26 + 33 block, Eye Lasers 11x2/12x2,
  Increasing Intensity (Wither creation and fake upgrade levels, accumulating
  Strength), WitheringPresence 6-card counter, Artifact 3.
- Wither: unplayable status, end-of-turn in-hand damage with fake upgrade.
- ByrdonisNest: TAKE (Byrdonis Egg) / EAT (+7 max HP), `IsAllowed` pet rule,
  first-run Overgrowth tutorial placement at event-bag slot 0.
- Native event declaration order for all four act types (AllEvents then the 18
  shared events), plus registration of WhisperingHollow/WoodCarvings/ZenWeaver
  as unsupported (inventory completeness; they stay out of bags).
- Native Hive encounter declaration order, removing the non-native
  `SETUP_TUNNELER_NORMAL` from Hive bags. Overgrowth/Glory/Underdocks content
  order was already the native declaration order (verified against the
  decompile); Underdocks keeps its explicit list.
- Boss `AllBossEncounters` and `BossDiscoveryOrder` now follow native
  declaration order (Glory: Aeonglass/Queen/TestSubject; discovery
  Queen/TestSubject/Aeonglass).

## Follow-up event batch (same date)

Twelve events were implemented from the decompiled v0.111.0 classes and added
to the native event bags: TeaMaster, RoundTeaParty, TrashHeap, ColossalFlower,
WhisperingHollow, TheLegendsWereTrue, JungleMazeAdventure, InfestedAutomaton,
DollRoom, SlipperyBridge, TheFutureOfPotions, ZenWeaver, Amalgamator.  The
manifest is now 22 IMPLEMENTED / 23 APPROXIMATE / 21 UNSUPPORTED out of 66.  C++ regression
checks for these rules live in `simulator/tests/rules_regression.cpp`
(549 checks, 0 failures).  Two documented implementation ceilings:
SlipperyBridge records skipped cards only for the first 62 deck positions, and
TheFutureOfPotions' uniform three-card selection order is an approximation.

This batch also fixed two latent engine bugs exposed by the new bag
trajectories: nondeterministic `RunCardGrid` padding in raw snapshots (restore
replay divergence) and a 160-entry finished-card overflow abort in
`necrobinder_after_card_played` during long rollouts.  See `FAILURES.md` 7-9.

## Verification

| check | result |
| --- | --- |
| full rebuild (MSVC 19.51, Ninja, Release + /UNDEBUG) | successful |
| CTest | 33/33 passed (`ctest.txt`) |
| artifact pytest | 363 passed, 16 skipped, 0 failed (`pytest.txt`) |
| step-2 new regressions | 11 tests in `tests/test_step2_rules_20261104.py` |
| multi-seed whole-run smoke (`bench.exe run 1000`) | 1000/1000 completed, 0 abnormal, 0 truncated, 0 errors |
| throughput same-machine before/after | medians 68.2 -> 65.3 runs/s (`benchmark-before-after.txt`) |

Skip reasons are in `pytest.txt` (`-rs`).  The workspace-root `tests/` tree in
`D:\sts2_datacollection\sts2` is not applicable to this build: it imports a
different `deployment` package layout and its local `sts2_sim` extension is
older than its sources (e.g. missing `mcts_priors`).  The artifact's own test
tree, which uses the rebuilt extension, is the suite reported above.

## Native evidence level

There is no target-DLL differential for this batch.  Rule values and ordering
come from the v0.111.0 decompilation of the locally installed same-commit
Windows build (`_decomp_local_0861bfa1/sts2.decompiled.cs`), with source
locations:

- `ActModel.GenerateRooms` (line 71570): AllEvents + AllSharedEvents,
  `UnstableShuffle`, GrabBag refill.
- `RoomSet` (line 47109): `NextEvent`/`NextNormalEncounter` modulo cycling.
- `Glory/Hive/Overgrowth/Underdocks.AllEvents` and `GenerateAllEncounters`
  (lines 154411-154830).
- `HungryForMushrooms`/`Reflections`/`SunkenStatue` act placement.

These are labelled as decompilation evidence, not as target-DLL replay.

## Still not done

- Target-DLL same-seed whole-run differential (blocked, see BLOCKERS.md).
- 21 events remain registered as unsupported and are omitted from event bags
  (bag RNG therefore diverges from native whenever an omitted event would have
  been drawn); 23 more events are APPROXIMATE.  Reasons: CrystalSphere is an
  interactive minigame; FakeMerchant is a custom shop UI; Trial/TinkerTime/
  BattlewornDummy/PunchOff and TheLanternKey need event-combat orchestration;
  EndlessConveyor is a multi-round weighted-dish loop; ColorfulPhilosophers/
  LuminousChoir/MorphicGrove/RanwidTheElder/RelicTrader/Bugslyer
  need multi-card/relic selection or unmodelled pool interactions;
  WoodCarvings/Symbiote/SelfHelpBook/GraveOfTheForgotten/FieldOfManSizedHoles
  need unmodelled enchantments (Corrupted/Sharp/SoulsPower/PerfectFit).
  WarHistorianRepy's native `IsAllowed` is always false, so it is not a real
  playable gap.
- SlipperyBridge skipped-card bitmap covers 62 deck positions; beyond that a
  skipped high-index card can be offered again.
- TheFutureOfPotions uniform three-card selection order is approximated.
- Wither fake upgrade level is visible in the game UI but is not encoded in the
  public observation (under-encoding, no hidden-info leak).
- Combat step throughput regressed ~1.9x (2.3 -> 4.3 us/step) while whole-run
  throughput stayed within spread; to profile separately.

## Second follow-up batch (2026-11-04, final for this pass)

Nine more events are implemented from the v0.111.0 decompilation and are now
part of the native event bags:

- **MorphicGrove**: gold >= 100 with two transformable cards; Group spends all
  gold and transforms two cards, Loner gains 5 max HP.
- **Bugslayer**: adds Exterminate or Squash to the deck.
- **EndlessConveyor**: gold >= 120, weighted dish rotation (Caviar, Spicy
  Snappy, Jelly Liver, Fried Eel, Suspicious Condiment, Clam Roll, Golden
  Fysh), every fifth dish Seapunk Salad, 40-gold gate, leave/observe options.
- **Trial**: Accept rolls merchant/noble/nondescript; guilt/innocence rewards
  (curses, relics, gold, heal, two 3-card rewards, two upgrades/transforms);
  Reject page including the abandon-run DoubleDown.
- **PunchOff**: floor >= 6, Nab (Injury + relic), Fight (SETUP_PUNCH_OFF) with
  the relic and potion reward populated at the post-combat reward screen
  (eventData deferral, so combat-end RNG ordering matches native).
- **RanwidTheElder**: act > 0, gold >= 100, potion + tradable relic; trades a
  potion, 100 gold, or the relic for front-pulled relics.
- **RelicTrader**: act > 0, >= 5 tradable relics; StableShuffle (relic key
  ordinal) then UnstableShuffle picks three trades; replacements pulled up
  front.
- **SelfHelpBook**: Sharp/Nimble/Swift (amount 2) target filtering and
  single SkipBook option when nothing is enchantable.
- **WoodCarvings**: transform a Basic card to Peck/ToricToughness, or enchant
  one card with Slither.

Supporting engine work:

- `RelicModel.IsTradable` equivalent (`relic_is_tradable`): excludes melted,
  Starter/Event/Ancient rarities and the 46 relics whose decompiled models set
  `HasUponPickupEffect`/`SpawnsPets` (list generated by an offline audit of
  the same-commit decompile, embedded with its provenance comment).
- `RunContext::remove_relic` shifts relic id/aux/wax/melted slot state.
- Enchantments `SHARP` (+2 powered attack damage) and `SLITHER` (playable
  non-X cards; cost re-rolled 0..3 from `Rng.CombatEnergyCosts` on every draw)
  with `card_can_enchant` rules and snapshot validation bounds.
- New event card-selection kinds 7-10 and the Basic-only transform filter for
  WoodCarvings.

Manifest is now **33 IMPLEMENTED / 23 APPROXIMATE / 10 UNSUPPORTED** out of 66.
Of the 10 unsupported, AROMA_PLACEHOLDER has no class in the native decompile
and WarHistorianRepy's native `IsAllowed` is always false, so 8 are real
playable gaps: CrystalSphere and FakeMerchant (interactive minigame/custom shop
UI), TinkerTime (MadScience card), BattlewornDummy/TheLanternKey (event
monsters BattleFriend/MysteriousKnight), and FieldOfManSizedHoles/
GraveOfTheForgotten/Symbiote (PerfectFit/SoulsPower/Corrupted enchantments).

Verification for this batch: full rebuild; CTest 33/33
(`ctest-final-20261104b.txt`); C++ rules_regression 686 checks, 0 failures
(`rules-regression-final-20261104b.txt`); artifact pytest 363 passed / 16
skipped / 0 failed (`pytest-final-20261104b.txt`); `bench.exe run 1000` gave
1000/1000 normal terminations, 0 truncation, 0 errors, 70.1 runs/s, 4.0 us per
combat step (`benchmark-runs-1000-final-20261104b.txt`).  Seed 32 of the
snapshot replay test now dies before the snapshot point under the expanded
event rules, so that fixture uses seed 4 (verified non-terminal at 250 steps);
the skip branch and reason are unchanged.  Failures 10-15 in `FAILURES.md`
record the intermediate failures.

Still blocked: target DLL `9cb4f1ad...` is absent, so no same-seed target
differential exists.  RelicTrader's StableShuffle uses the relic key as the
ModelId ordinal proxy; the target build would be needed to confirm the native
ordinal directly.

## Third follow-up batch (same date)

Four previously unsupported events were implemented from the same v0.111.0
decompile and one approximate event was promoted:

- **FieldOfManSizedHoles**: RESIST removes two cards then adds Normality;
  ENTER_YOUR_HOLE applies PerfectFit (shuffled card moves to the top).
- **GraveOfTheForgotten**: CONFRONT adds Decay + SoulsPower (removes Exhaust,
  keeps the card); ACCEPT grants ForgottenSoul.
- **Symbiote**: APPROACH applies Corrupted (powered attack damage x1.5, 2 HP
  self-damage on play); ABSORB transforms two cards.
- **BattlewornDummy**: three settings enter BattleFriendV1/V2/V3 (75/150/300
  HP). `BattlewornDummyTimeLimitPower` decrements at each enemy side turn end
  and escapes the dummy on the third, setting RanOutOfTime; combat then ends
  as a victory with no standard rewards and the event resolves to its DEFEAT
  page. A real kill offers one uniform character+shared potion (V1), two
  upgradable cards after StableShuffle (V2), or the front relic (V3).
- **TheLanternKey**: RETURN_THE_KEY grants 100 gold; KEEP_THE_KEY offers FIGHT,
  which enters `SETUP_MYSTERIOUS_KNIGHT` (MysteriousKnight: FlailKnight AI —
  RAM/FLAIL/WAR_CHANT random branch, Strength 6, Plating 6) and after victory
  offers the fixed `LANTERN_KEY` card as a one-card reward.
- **ThisOrThat** promoted from APPROXIMATE: PLAIN loses 6 HP then gains the
  41-68 rolled gold; ORNATE pulls the front relic (same rewards-RNG rarity
  roll as `RelicFactory.PullNextRelicFromFront`) and adds Clumsy.

Engine work added in this batch:

- Enemy-side-turn-end handling for `BATTLEWORN_DUMMY_TIME_LIMIT`; escape is
  recorded as `alive=false` with hp intact, which is how the event
  distinguishes RanOutOfTime from a kill.
- Event-combat resume now supports custom post-combat reward construction
  (potion/relic/card) without a separate action kind; the LanternKey card is
  a normal one-card reward slot, so take/skip remains a real player choice.
- `MysteriousKnight` is driven by the existing generated state machine; the
  generated row lacks the inherited A8 HP (108) and A9 deadly damage overrides
  (Flail 10, Ram 17), so `setup_encounter`/`roll_intent`/`monster_act` apply
  them explicitly. This is a generator-data gap, recorded in `FAILURES.md`
  and `results.json`, not a behavior substitution.

Manifest is now **39 IMPLEMENTED / 22 APPROXIMATE / 5 UNSUPPORTED** out of 66.
Of the 5 unsupported, AromaPlaceholder has no native class, WarHistorianRepy
is unreachable (`IsAllowed` returns false), and CrystalSphere declares
`IsDeterministic=false` (interactive minigame). The two remaining real gaps
are FakeMerchant (custom merchant inventory UI) and TinkerTime (MadScience
dynamic card type/rider state).

Verification for this batch: full rebuild of the simulator and Python
extension; CTest 33/33 (`ctest-final-20261104c.txt`); C++ rules_regression
**775 checks, 0 failures** (`rules-regression-final-20261104c.txt`); artifact
pytest 363 passed / 16 skipped / 0 failed (`pytest-final-20261104c.txt`);
`bench.exe run 1000` gave 1000/1000 normal terminations, 0 truncation, 0
errors (`benchmark-runs-1000-final-20261104c.txt`). Throughput remains noisy
on this machine: three back-to-back runs after the batch measured
66.7 / 67.2 / 66.5 runs/s (4.4 us per combat step); the saved single run
measured 67.6 runs/s (4.2 us per combat step). The earlier 70.1 runs/s / 4.0 us sample and the ~2.3 us
baseline gap are still not profiled; no speed-for-rules trade was made.

Still blocked: target DLL `9cb4f1ad...` is absent, so no same-seed target
differential exists.

## Fourth follow-up batch (same date)

A decompile audit of `EncounterModel.ShouldGiveRewards` / `RewardsCmd` corrected
the post-combat reward flow for event fights:

- `ShouldGiveRewards` defaults to true; only the three
  `BattlewornDummyEventEncounter` variants override it to false. Therefore
  DenseVegetation, PunchOff, TheLanternKey (MysteriousKnight) and FakeMerchant
  keep the room's normal monster rewards (gold, potion roll, 3-card reward),
  and `CombatRoom.ExtraRewards` are appended after them in list order
  (`RewardsSet.WithRewardsFromRoom`). The simulator previously suppressed the
  normal rewards for every event fight.
- PunchOff now yields standard monster rewards followed by its RelicReward and
  PotionReward extras, using the rewards RNG in native populate order.
- TheLanternKey now yields standard monster rewards plus the fixed LanternKey
  card in the next free reward-card slot; take/skip remains a real choice and
  the standard 3-card reward is no longer overwritten.
- DenseVegetation (no extras) and FakeMerchant (unsupported) follow the same
  rule. Events passing `shouldResumeAfterCombat=false` clear event state when
  the reward list is built, so leaving the rewards screen ends the room.
- BattlewornDummy remains `ShouldGiveRewards=false` (no standard rewards,
  event resumes, variant reward only after a real kill).

Tests added/updated in `rules_regression.cpp`: PunchOff standard gold/cards +
extra relic/potion + event flags cleared; DenseVegetation standard rewards and
event completion; LanternKey standard 3-card slot 0 plus special card in slot 1.
`tests/test_smoke.py` snapshot replay moved from seed 4 to seed 5 because seed 4
now dies before step 250 under the corrected reward rules (verified seed 5 is
non-terminal at 250 steps; the conditional skip remains as a safety net).

Verification: full rebuild; CTest 33/33 (`ctest-final-20261104d.txt`);
rules_regression **795 checks, 0 failures**
(`rules-regression-final-20261104d.txt`); artifact pytest 363 passed / 16
skipped / 0 failed (`pytest-final-20261104d.txt`); `bench.exe run 1000`
1000/1000 normal terminations, 0 truncation, 0 errors, 70.4 runs/s, 4.2 us per
combat step (`benchmark-runs-1000-final-20261104d.txt`). The 16 skips are the
same optional-artifact skips as before.

Target DLL `9cb4f1ad...` is still absent; the same-seed native long-path
differential remains blocked and no substitute DLL was used.

## Fifth follow-up batch (same date)

Decompile audit of every two-bound `Rng.NextInt(min, max)` call (native upper
bound is exclusive) found four off-by-one translations in implemented content:

- PunchOff CalculateVars `NextInt(91, 99)` had been ported as inclusive 91..99;
  corrected to 91..98.
- LuminousChoir `149 - NextInt(0, 50)` had allowed 99; corrected to 100..149.
- WhisperingHollow `35 + NextInt(-9, 10)` had allowed 45; corrected to 26..44.
- PunchOffEventEncounter StartingHpReduction `NextInt(2, 10)` had allowed 10;
  corrected to 2..9.

StoneOfAllTime Lift now maps its stored index over `Player.Potions` (non-null
physical slots in order) and calls `potion_remove_at`, so discarding the chosen
potion leaves an empty physical slot instead of compacting the belt. Other
DenseVegetation/SunkenStatue/ThisOrThat/LostWisp/JungleMaze rolls were verified
against the decompile and already matched.

Four APPROXIMATE events were audited against the v0.111.0 decompile, covered by
new regression checks, and promoted to IMPLEMENTED:

- **DenseVegetation**: gold 61..99, TRUDGE_ON 8 unblockable damage + gold, Rest
  mimics rest-site heal (30% max HP plus rest relics) and offers the fight,
  which now gives standard monster rewards.
- **BrainLeech**: ShareKnowledge offers 5 noncombat Ironclad cards (choose 1);
  Rip loses 5 HP and offers a 3-card colorless base-odds reward.
- **PotionCourier**: GrabPotions offers three fixed FoulPotions; Ransack picks
  one random uncommon character+shared potion with the rewards RNG.
- **SpiritGrafter**: LetItIn heals 25 and adds Metamorphosis; Rejection upgrades
  one deck card then takes 10 unblockable/unpowered damage.

Manifest is now **43 IMPLEMENTED / 18 APPROXIMATE / 5 UNSUPPORTED** out of 66.

Verification: full rebuild; CTest 33/33 (`ctest-final-20261104e.txt`);
rules_regression **829 checks, 0 failures**
(`rules-regression-final-20261104e.txt`); artifact pytest 363 passed / 16
skipped / 0 failed (`pytest-final-20261104e.txt`); `bench.exe run 1000`
1000/1000 normal terminations, 0 truncation, 0 errors; this sample measured
65.1 runs/s and 4.7 us per combat step under concurrent test load
(`benchmark-runs-1000-final-20261104e.txt`).

Known remaining RNG gap: monster HP sampling and initial-state weighted rolls
currently use `RunRngType.MonsterAi`, while native
`Creature.SetUniqueMonsterHpValue` draws from `RunState.Rng.Niche` (with the
ascending unused-HP set when duplicates are excluded) and 108/109 generated
monster HP ranges are probe-sampled rather than decompiled. Fixing this needs a
full monster HP-range regeneration plus a controlled target-build differential;
it is recorded in `results.json` `not_done` and not claimed as aligned.

Target DLL `9cb4f1ad...` is still absent; same-seed native differential remains
blocked.

## Sixth follow-up (same date): Orobas locked option

Orobas' third pool is a native `EventOption` with a null onChosen when neither
`TouchOfOrobas` (requires a Starter-rarity relic) nor `ArchaicTooth` (requires
Bash/Neutralize/Unleash/FallingStar/Dualcast in deck) sets up; it is disabled,
not a selectable no-op. The port now marks an INVALID ancient relic slot as
unavailable and still consumes the single `NextItem` draw for the locked entry.
The ArchaicTooth condition was also corrected to the native starter-card set
(BREAK is not one of its keys).

Verification: full rebuild; CTest 33/33 (`ctest-final-20261104f.txt`);
rules_regression **833 checks, 0 failures**
(`rules-regression-final-20261104f.txt`); artifact pytest 363 passed / 16
skipped (`pytest-final-20261104f.txt`); `bench.exe run 1000` 1000/1000 normal
terminations, 0 truncation, 0 errors, 70.5 runs/s, 4.2 us per combat step
(`benchmark-runs-1000-final-20261104f.txt`).
