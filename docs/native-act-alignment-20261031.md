# Native act routing and Golden Compass

Target: local `v0.111.0`, release commit `41cef1ea`, DLL SHA-256
`9cb4f1ad8c9f284aa8fec3122ffd6d780bbf543d875c817abdd12ff63fbf12b4`.

## Implemented slice

- `RunContext.act` is still the run position `0..2`. `actTypes` records the
  content identities independently: Overgrowth=0, Hive=1, Glory=2, Underdocks=3.
  Underdocks occupies position zero; it is not a fourth act.
- `init`/`init_seed` retain fixed Overgrowth/Hive/Glory. New
  `init_with_context(raw_seed, ascension, first_act, progress)` and
  `init_seed_with_context(text_seed, ascension, first_act, progress)` support
  fixed Overgrowth (`first_act=0`), fixed unlocked Underdocks (`3`), or native
  normal-single-player selection (`-1`). The latter prioritizes newly unlocked,
  undiscovered Underdocks, otherwise uses the `act_selection` stream and the
  native ordered alternatives. This is not the native TestMode override.
- Underdocks uses first-act map counts, Neow, its own native encounter pool, and
  its own event pool followed by shared events. The native pool contains
  `SeapunkNormal`, added at the end of the historical encounter IDs with the
  roster `[CalcifiedCultist, Seapunk]`. The obsolete `ToadpolesNormal` is retained
  as a historical table entry but excluded from this act's room generation.
- Golden Compass regenerates a linear map at obtain time, retains visited
  coordinates still present, and records the act to which its effect belongs.
  The native single-player route has sixteen rooms, an Ancient and a Boss.
  Coordinate capacity is eighteen rows; network node capacity stays 119.
  Its unknown rooms use the native Event-only allowed set: one float roll is
  consumed, no non-event odds grow. Subsequent acts use their standard maps.
  The native Golden Path has no second-boss map node.
- Unknown-room odds reset between acts. For a supplied zero prior-run count,
  the first two unknown rooms are Events and the third is a Monster, without
  consuming the unknown-room RNG; this check precedes relic hooks in native.

## Supported progress inputs and explicit boundaries

`NativeProgressContext` accepts `apply_discovery_order`, `number_of_runs`,
`seen_encounters`, and explicit Neow/Orobas/Darv/Underdocks unlock flags plus
`underdocks_discovered`. Defaults preserve the old fixed-act environment, with
represented encounters treated as seen. This is a limited context, **not an
importer for the complete native progress save**. It does not implement all
card, potion, relic, or event epoch filters.

When discovery overrides are enabled, the first unseen supported Boss in the
native discovery order is selected after the random draw. A native Aeonglass
Boss has no corresponding historical simulator entry. `aeonglass_seen` is an
explicit separate flag, default true. A context requiring Aeonglass as the next
discovery is rejected rather than substituted with Doormaker.

First-run Overgrowth discovery requires the unported ByrdonisNest event; that
initialization is explicitly rejected. The deterministic tutorial room ordering
is present, but its public first-run entry stays closed until that required event
has an implementation. Disabling discovery is an explicit test configuration,
not a claim to reproduce an ordinary first-ever run.

Underdocks remains a **partial-content environment**. Unimplemented events are
still excluded by the existing content policy, including PunchOff,
EndlessConveyor and TrashHeap, and unported shared events. These omissions alter
event-pool size and RNG consumption, so selecting Underdocks does not establish
native whole-act or whole-run same-seed parity. PunchOff in particular needs
event-specific monster initial state and generation timing, not merely two
ordinary PunchConstructs. The original three acts' full event/relic pools and
Glory's old Boss pool also remain separate parity work.

Rooms are still generated on act entry rather than all at run creation. The
current simulator has no intermediate UpFront consumers beyond those setup
sites, but no full-run comparison has established general equivalence of this
timing. Map geometry, equal-card identity ordering and cross-rule RNG consumption
still require native replay differential testing.

## Verification and compatibility

`tools/generate_native_act_fixtures.py` extracts route, encounter and discovery
order fixtures from the target native sources and records their SHA-256 hashes
in `simulator/tests/fixtures/native_act_41cef1ea.json`. This is source-exact
evidence, not a dynamic full-run oracle. `native_act_alignment.cpp` checks the
route/edges, RNG count and unchanged odds, state boundaries, native encounter
membership/roster, Boss history, unlock controls, and snapshot behavior.
`tests/test_native_act_context.py` checks the Python initialization contract.

POD snapshots are now version 6. Version 5 and earlier are rejected, including
same-size images with an old header. New context, act identity, Golden Path
state and map shape are validated on restore. This version change covers the
other agents' new run selection/relic fields in the same implementation round.
