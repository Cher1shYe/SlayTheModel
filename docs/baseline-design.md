# Omniscient global MCTS baseline

## Scope

The baseline is allowed to observe the complete future-determining state: ordered card piles, RNG streams, generated map and reward data when present, and all other state available to the game runtime. The baseline must not use the user's proposed new decision framework.

"Global" means that every player decision in a solo run is owned by the search system. It does not mean putting every card play from floor one through the final boss into one flat tree. That tree has an unusable horizon. The implementation is hierarchical:

- **Combat tree:** card instance + target, potion + target, card selections, and end turn.
- **Run tree:** path, reward, shop, rest, event, treasure, deck mutation, and other screen decisions.
- **Nested transition:** when a run-level rollout reaches combat, a bounded combat search resolves that encounter and returns the resulting HP, deck, potions, relic state, rewards, and terminal status.

## Required environment contract

```text
Clone(state) -> independent state
LegalActions(state) -> stable action list
Apply(state, action) -> mutates only that clone
IsTerminal(state) -> bool
Evaluate(state) -> scalar utility
StateHash(state) -> deterministic hash
```

The policy-facing observation is separate from the world state:

- `CombatSnapshot` is the complete simulator-owned state and retains RNG, native payloads, checksums, and persistent fields required for exact transitions.
- `CombatObservation` is the combat-policy input. It contains combat resources, piles, creatures, powers, relic IDs, potion slots, and orbs, but excludes gold, RNG, checksums, build metadata, and opaque native JSON.
- `RunObservation` is the run-policy input. Its first bridge contains persistent HP, gold, relics, and potions; the canonical deck, map, floor, rewards, and shops are added with the M5 run-state bridge rather than guessed from transient combat piles.

The omniscient searcher may use the full simulator state to follow known future RNG, but a leaf policy or external baseline receives only the observation type appropriate to its decision level.

## Baseline search

The first searcher is classic UCT:

1. Clone the root state.
2. Select edges with mean value plus an exploration bonus.
3. Expand one unvisited legal action.
4. Roll out to a terminal state or depth cap.
5. Back-propagate the terminal/leaf value.
6. Play the most visited root action.

Later baseline additions may include transposition tables, progressive widening, policy priors, batched leaf evaluation, parallel roots, virtual loss, and tree reuse. Each addition must be separately switchable so its effect can be measured.

## Reproducible comparison protocol

Every reported comparison records:

- exact game version and assembly hash;
- character, ascension, seed set, and enabled content;
- oracle information made available;
- simulations, state transitions, wall time, threads, CPU, and GPU;
- win rate, floor reached, HP loss, decision latency, and simulator divergence count;
- search configuration and evaluator version.

The primary comparison uses fixed held-out seeds. Training seeds and evaluation seeds must not overlap.

## Milestones

- **M0 — Search kernel (complete):** generic deterministic UCT and smoke tests.
- **M1 — ABI probe (complete for v0.111.0):** inventory and automatically verify the minimum run/combat/action APIs for the pinned build.
- **M2 — State/action bridge (code complete; live fixture deferred):** serialize full combat state, enumerate legal card/target/end-turn actions, reject stale commands, convert protocol actions back to native game actions, and wait for the native action queue to settle. Per the current development boundary, in-game fixture validation is deferred; headless integration can use the same public bridge methods.
- **M3 — Exact transition:** clone and step without presentation; verify state hashes against the live game.
- **M4 — Combat MCTS:** resolve complete fights with known future RNG and report throughput/quality curves.
- **M5 — Run MCTS:** add rewards, map, shops, rest sites, events, and nested combat resolution.
- **M6 — Benchmark:** fixed-seed comparison against random, greedy, and heuristic baselines.

## Current platform note

Development is currently on macOS arm64 with .NET 9 and STS2 public-beta v0.111.0. GPU inference is a later backend concern; state transition throughput and correctness come first.
