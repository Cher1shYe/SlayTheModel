# STS2 native simulator + training

A Slay the Spire 2 simulator written in C++ (modeled on
[gamerpuppy/sts_lightspeed](https://github.com/gamerpuppy/sts_lightspeed)) with
Python only for the neural heads and training loops.

Everything that advances game state lives in `simulator/`: card effects are
switch tables, `BattleContext`/`RunContext` are plain copyable structs, and
search is done in C++. The Python layer builds observations with the extension
itself (`sts2_sim`), then trains small PyTorch scorers.

The fixed target is **Slay the Spire 2 v0.111.0, standard single-player,
all content unlocked, Ironclad, Ascension 0**: one complete climb from the
opening Ancient through acts 1-3 to victory or death. The rules contract and the
per-item coverage manifest are in
[`docs/a0-ironclad-contract.md`](docs/a0-ironclad-contract.md) and
[`docs/a0-ironclad-coverage.md`](docs/a0-ironclad-coverage.md).
Decompiled game code was consulted locally as a behavior reference; no game
assemblies or assets are committed here.

## Layout

```
simulator/                 C++ engine + pybind11 module
  include/sts2/            common.h battle.h map.h monsters.h potions relics run.h search.h observe.h
  src/                     cards, battle, map, monsters, potions, relics, events, run, search, observe
  content/                 generated JSON tables from the reference dump
  tools/                   dump/gen scripts + gen_coverage.py
  bindings/bindings.cpp    sts2_sim Python module
  apps/bench.cpp           standalone throughput benchmark
agent/
  common.py                binding import, observation helpers, legacy run loop
  run_env.py               training-facing full-run env, JSONL, thread-pool batch
  heuristics.py            baseline run/combat policies used by the tests
  nets.py                  CardScorer (run-level), CombatNet (combat policy/value)
  card_train.py            REINFORCE card-selection training
  selfplay.py              PUCT self-play training (C++ search, network priors)
deployment/
  train_local.py           CLI: card | selfplay | benchmark
  benchmark_speed.py       throughput numbers
  selfplay_compare.py      evaluate two checkpoints
docs/                      rules contract + generated coverage manifest
tests/test_smoke.py        engine, run, determinism, coverage and training checks
```

## Build

MSVC (preferred):

```powershell
cd simulator
cmake -S . -B build -G "Visual Studio 18 2026" -A x64
cmake --build build --config Release --target sts2_sim sts2_bench
copy build\Release\sts2_sim.*.pyd .
copy build\Release\bench.exe .
```

MinGW fallback (`pip install cmake ninja` first; used to validate this tree):

```bash
TC=/path/to/mingw/bin; PY=.venv/Scripts
export PATH="$TC:$PY:$PATH"
$PY/cmake.exe -S . -B build-mingw -G Ninja -DCMAKE_BUILD_TYPE=Release \
    -DCMAKE_CXX_COMPILER="$TC/x86_64-w64-mingw32-g++.exe" \
    -DPYTHON_EXECUTABLE="$PY/python.exe"
$PY/cmake.exe --build build-mingw -j 8
```

Both generators drop `sts2_sim.*.pyd` and `bench.exe` next to `CMakeLists.txt`,
so `agent/common.py` imports the simulator without extra `sys.path` setup.

## Usage

```bash
python -m deployment.train_local card     # card-selection REINFORCE
python -m deployment.train_local selfplay # combat self-play
python -m deployment.train_local benchmark
pytest tests -q
simulator/bench.exe run 2000             # full-run throughput, greedy policy
simulator/bench.exe map 500              # map-generation throughput
simulator/bench.exe 10000                # combat throughput (Shrinker Beetle)
simulator/bench.exe 10000 72             # combat throughput (Cultists)
python simulator/tools/gen_coverage.py   # regenerate docs/a0-ironclad-coverage.md
```

Full-run training API:

```python
from agent.common import SCREEN
from agent.run_env import RunEnv, run_batch, play_and_log
from agent.heuristics import run_policy, combat_policy

env = RunEnv(seed=26)
obs = env.reset(26)                # public observation, np.float32[RUN_OBS_DIM]
legal = env.legal_actions()        # [(action_type, index), ...]
mask = env.action_mask()
while not env.is_terminal():
    action = combat_policy(env) if env.screen == SCREEN.COMBAT else run_policy(env)
    assert env.step(action)
blob = env.snapshot()              # binary; restore(blob) rewinds exactly

results = run_batch(range(1, 41), run_policy, combat_policy, workers=8)
play_and_log(26, run_policy, combat_policy, "runs/traj.jsonl")
```

Checkpoints go to `runs/card/card.pt` and `runs/selfplay/combat.pt`; both
scripts accept `--resume` and `--out-dir`.

## Full-run model

- `RunContext` holds HP/gold/act/floor/map position, deck card instances,
  relics with counters, potions/slots, all RNG streams and counters, room odds,
  encounter/event bags, shop/reward/event state, and the embedded combat state.
  It is fully copyable, snapshot/restorable (in-build binary blob) and hashed
  for replay checks.
- 12 run RNG streams plus 3 player streams, all named-seeded and independent;
  map generation uses a per-act seed; events derive their own seed from
  run seed + player id + event-name hash. No global RNG.
- Map generation is a port of `StandardActMap`: 7 columns, 15/14/13 rooms,
  seven starting paths, DAG edges, crossover prevention, redundant-path
  pruning, centering/spreading/straightening, forced monster/treasure/rest
  rows, and elite/shop/rest/unknown count assignment.
- Rooms: opening Ancient (Neow), Monster/Elite/Boss combats, Unknown resolution
  with growth/reset odds and shop blacklist, regular events, Rest
  (heal/smith/Dig/Lift), Shop (7 cards, 3 relics, 3 potions, one removal,
  sale/price variance), Treasure, boss rewards and act transitions.
- Events have their own engine, including event combats that return to the
  event page; the coverage manifest filters unsupported events out of the bag.

## Measured throughput

This machine, MinGW -O3, single thread:

| Path | Result |
| --- | --- |
| C++ native greedy full runs | ~64 runs/s (~470 combat rooms/s) |
| C++ map generation | ~180 maps/s; ~5–12 ms per act map |
| Python `RunEnv` + heuristic 1-ply policy | ~41 runs/s (1 worker) |
| Python `RunEnv` batch, 2 / 4 / 8 workers | ~44 / 34 / 30 runs/s (policy loop is GIL-bound; native calls release the GIL) |
| C++ native greedy combats (Shrinker Beetle, 2.9 turns) | ~240,000 combats/s |
| C++ native greedy combats (Cultists, 6.2 turns) | ~130,000 combats/s |
| C++ MCTS | measured separately via `bench.exe <n> <encounter> <sims>` |

A full run spends almost all of its native time generating the act map
(~90% of `init`); combat itself is ~1.5 µs per action. Map generation is
dominated by `StandardActMap` redundant-path pruning, which re-enumerates all
start-to-boss paths and their segments each iteration. The pruning scan now
uses a compact allocation-free segment key and first-occurrence bucket order;
the remaining cost is inherent to the reference algorithm.

Native state copies (`clone`) and `rollout` release the GIL, so C++-only
self-play/search threads scale; Python-side policy bookkeeping does not.

## Observations (built in C++)

| Constant | Size | Contents |
| --- | --- | --- |
| `RUN_OBS_DIM` | 192 | HP/gold/floor/deck stats, screen one-hot, deck card histogram |
| `CARD_FEAT_DIM` | 191 | card one-hot, cost, type, rarity, upgrade, price |
| `COMBAT_OBS_DIM` | 61 | player status block + 4 monster slots |
| `ACTION_FEAT_DIM` | 188 | action type, card one-hot, cost, target, damage/block |

`observe_public()` exposes only player-visible information (deck, resources,
visible map, in-combat hand/piles/intents); draw order, future intents, RNG
state and hidden event outcomes are not included.

## Content

Generated from the reference engine by `simulator/tools/dump_*.py` and
`gen_*.py` (cards, monsters, potions, relics):

- **176 cards**: 87 Ironclad, 64 colorless, 11 status, 14 tokens. All 163
  single-player cards are playable; the 13 multiplayer-only cards are present
  but inert and marked UNSUPPORTED.
- **108 monsters / 89 A0 encounters** with reference AI state machines, intents,
  random/conditional branches, repeats, summons and recorded move effects. 62
  encounters are in the acts 1-3 climb plus the Dense Vegetation event fight;
  act-4 and unsupported-event setups are out of scope.
- **64 potions**: 52 drop for Ironclad (49 shared + 3 Ironclad-pool); the 12
  other-character potions never drop in this contract.
  Combat potions are legal `USE_POTION` actions; `ANY_TIME` potions work on run
  screens. Slots default to 3 (+2 with Potion Belt); Entropic Brew refills them.
- **289 relics, 241 implemented**: all 132 event/ancient relics, all 8
  Ironclad-pool relics and 101 of 116 shared relics. Only implemented relics
  enter random drop pools. Rest sites expose Shovel Dig and Girya Lift.
- **47 events**: 3 implemented, 15 approximate (deterministic substitutes for
  card/enchantment/curse UIs), 29 unsupported and excluded from event bags.
  Neow (opening Ancient) is approximate because curse card effects are not
  modeled.
- **Map**: standard 7-column act maps with 15/14/13 rooms; the generated map and
  its room counts are covered by golden tests.

Known approximations (full list in the coverage manifest): event
card/enchantment selection uses RNG substitutes, curses are absent outside
combat, some event relics needing enchantments/pets/map manipulation are no-ops
or substitutes, potion rewards auto-add when slots are free, and the exact
tagged GrabBag ordering is approximated. Acts 2/3 Ancient rooms and act 4 are
unsupported. Card text is never parsed; semantics follow the reference effect
code.

## Verification

`pytest tests -q` (22 tests) checks observation/action dimensions, the full
event manifest gating, every card/potion/implemented relic, map golden hashes
and structural invariants, deterministic replay and snapshot/restore equality,
room/economy transitions, boss reward/act changes, JSONL output, and automated
A0 Ironclad wins from the opening Ancient to the act-3 boss (seeds 26 and 32).
Differential traces against a live headless client are not available in this
environment; unverified behavior is marked APPROXIMATE/UNSUPPORTED rather than
claimed exact.

The Python package `sts2_env` was removed per the pure-C++ requirement; the
reference engine remains at
`D:\project\sts2_compactformer\sts2-rl-agent\sts2_env`.
