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
[`docs/a0-ironclad-coverage.md`](docs/a0-ironclad-coverage.md); evaluation
protocol and fixed-seed results are in [`docs/evaluation.md`](docs/evaluation.md).
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
  policy.py                strategy entry points for every run screen + eval summary
  card_train.py            REINFORCE card-selection training
  selfplay.py              root-PUCT self-play training (C++ search, network priors)
deployment/
  train_local.py           CLI: card | selfplay | benchmark
  benchmark_speed.py       throughput numbers (completed runs/simulations only)
  evaluate.py              fixed-seed evaluation: heuristic vs network vs search
  selfplay_compare.py      evaluate two checkpoints against the heuristic baseline
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
python -m deployment.train_local armg     # unified non-combat REINFORCE
python -m deployment.train_local combat-dagger --out-dir runs/combat-dagger
python -m deployment.train_local benchmark
pytest tests -q
python -m deployment.evaluate --split test --seeds 1000 \
    --combat-checkpoint runs/v3/selfplay/combat.pt \
    --card-checkpoint runs/v3/card/card.pt \
    --strategies heuristic,network,network_combat,network_cards,search_resampled
python -m deployment.selfplay_compare --kind combat --split val --seeds 500 \
    --a runs/v3/selfplay/combat.pt --simulations 16 --resample
simulator/bench.exe run 2000             # full-run throughput, greedy policy
simulator/bench.exe map 500              # map-generation throughput
simulator/bench.exe 10000                # combat throughput (Shrinker Beetle)
simulator/bench.exe 10000 72             # combat throughput (Cultists)
python simulator/tools/gen_coverage.py   # regenerate docs/a0-ironclad-coverage.md
```

The ArmG trainer scores each legal non-combat candidate with one shared MLP and
uses final floor / 50 with an exponential moving baseline for REINFORCE. Its
default fixed combat controller is native multi-level `mcts-oracle`: it uses the
complete simulator battle state and future RNG, like the STS1 reference, so
results are not directly player-usable. `mcts-resampled` resamples hidden state
and uses only the first action of a searched path. The old root-only `search`
controller remains available. Run `python -m deployment.train_local armg --help`
for the training options. It saves resumable `latest.pt`, the best checkpoint
on the validation seeds as `best.pt`, and `metrics.jsonl` in the output
directory. Truncated and errored episodes are reported and excluded from
updates. To compare the trained policy with the existing non-combat heuristic
on independent, paired test seeds, use:

```bash
python -m deployment.evaluate_armg --checkpoint runs/armg/best.pt --split test \
    --start 100 --seeds 100 --combat mcts-oracle --simulations 64 --out runs/armg/test.json
```

The ArmG policy uses only public run observations. To prevent a deterministic
policy from cycling indefinitely on reversible choices, repeated public states
can trigger a different legal action; these interventions are counted in the
training and evaluation reports.

Optional non-combat overlays can be enabled with `--need-rules` (deck-need
scoring on normal card rewards) and `--relic-rules` (shop relic and Ancient
energy-relic priorities). Both default to off, preserving the original model
and old checkpoint behavior. They are STS2-specific hypotheses, not a copy of
the STS1 card and relic pool. Compare the four combinations on the same seeds:

```bash
python -m deployment.evaluate_armg_rules --checkpoint runs/armg/best.pt \
    --out-dir runs/armg/rule_ablation --split val --start 100 --seeds 100 \
    --combat mcts-oracle --simulations 2000 --workers 8
```

The evaluator records per-run results, rule-source hashes, and the paired
floor differences. `mcts-oracle` has access to future battle state; its results
do not establish real-client performance.

The combat DAgger trainer uses the frozen original ArmG for non-combat choices.
It first bootstraps STS2-specific policy and value weights with MCTS-controlled
episodes, then trains on student-visited states labelled by native MCTS. The
default oracle teacher can see hidden future state; select
`--teacher-mode resampled` to study a hidden-state-resampled teacher. Policy and value targets
from completed battles are stored in disk shards, and aborted runs contribute
no training samples. Checkpoints include optimizers, RNG state and the active
replay manifest. Restart with the same settings and `--resume <output>/latest.pt`.
Training stores historical shards even after they leave the replay window, so
the output directory can grow. Each round chooses `best.pt` using separate
validation seeds; test seeds should only be used for final evaluation:

```bash
python -m deployment.evaluate_combat_dagger \
    --policy-checkpoint runs/combat-dagger/best.pt \
    --armg-checkpoint runs/armg_a0_mcts_20261029/eval_mcts10000_20261029_215142/model.pt \
    --out-dir runs/combat-dagger/test-eval --split test --seeds 100 \
    --simulations 512 --workers 8
```

To change battle controllers, start a separate run with `--init-checkpoint`
and a disjoint `--train-seed-offset`; only model weights are loaded and the
optimizer, baseline, and RNG are reset. The source checkpoint hash and settings
are recorded. `--resume` instead requires the same settings and restores the
optimizer, baseline, and RNG. In the MCTS oracle mode the controller caches up
to 15 actions from a victory path, or five from a non-victory path, checks each
action against the current legal set, and searches again if it is invalid. Boss
combats use three times the configured simulation budget.

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
scripts accept `--resume` and `--out-dir`. Current models:

- `runs/v3/card/card.pt` — card reward model (comparable to the heuristic card
  policy on validation seeds).
- `runs/v4/selfplay/combat.pt` — visit-target combat self-play.
- `runs/v4b/selfplay/combat.pt` — value-target combat self-play
  (`--target value`); used with root search in the final evaluation.

Older checkpoints are left in place. See `docs/evaluation.md` for the fixed-seed
comparison.

Seed splits are disjoint and fixed in `agent/policy.py`: train `10,000,000+`,
val `20,000,000+`, test `30,000,000+`. `search` is oracle root search over the
true draw order; `search_resampled` re-draws hidden draw/discard zones and the
future RNG stream per simulation and is the only search variant quoted as
player-usable. Search visits each root action once in descending-prior order
before PUCT, so a peaked network prior cannot collapse the budget onto one
action. `network_combat` (network combat + heuristic cards) and `network_cards`
(heuristic combat + network cards) separate the two learned heads.

## Full-run model

- `RunContext` holds HP/gold/act/floor/map position, deck card instances,
  relics with counters, potions/slots, all RNG streams and counters, room odds,
  encounter/event bags, shop/reward/event state, and the embedded combat state.
  It is fully copyable, snapshot/restorable (in-build binary blob) and hashed
  for replay checks.
- 12 run RNG streams plus 3 player streams, all named-seeded and independent;
  map generation uses a per-act seed; events derive their own seed from
  run seed + player id + event-name hash. No global RNG.

  The standalone `sim.generate_map(seed, act, ascension=0)` accepts the raw RNG seed;
  `RunContext.init(seed)` first hashes the decimal representation of the
  user-facing run seed before deriving its per-act map stream.
- Map generation is a port of `StandardActMap`: 7 columns, 15/14/13 rooms,
  seven starting paths, DAG edges, crossover prevention, redundant-path
  pruning, centering/spreading/straightening, forced monster/treasure/rest
  rows, and elite/shop/rest/unknown count assignment.
- Rooms: opening Ancient (Neow), Monster/Elite/Boss combats, Unknown resolution
  with growth/reset odds and shop blacklist, regular events, Rest
  (heal/smith/Dig/Lift), Shop (7 cards, 3 relics, 3 potions, one removal,
  sale/price variance), Treasure, selectable combat rewards and act transitions.
- A combat reaching the 200-turn safety limit ends the episode as truncated;
  it is not recorded as a game loss or used as a terminal training label.
- Events have their own engine, including event combats that return to the
  event page; the coverage manifest filters unsupported events out of the bag.

## Measured throughput

This machine, MinGW -O3, single thread:

| Path | Result |
| --- | --- |
| C++ native greedy full runs | 102.3 runs/s, 3535 combats, mean floor 12.4 |
| C++ map generation | 9.08 ms/run init inside the full-run benchmark |
| Python `RunEnv` + heuristic policy | 19.9 completed runs/s, 6310 env steps/s, 270 combats/s |
| Root search, oracle, 32 sims/decision | 90,479 completed sims/s (2827 decisions/s) |
| Root search, resampled hidden zones, 32 sims/decision | 55,280 completed sims/s (1728 decisions/s) |
| Resampled search, 64 sims/decision, 1 / 2 / 4 threads | 136,665 / 240,766 / 330,999 sims/s |
| Network + search self-play | 3917 sims/s, 490 valid samples/s, 633 env steps/s |
| C++ native greedy combats (Shrinker Beetle, 2.9 turns) | ~240,000 combats/s |
| C++ native greedy combats (Cultists, 6.2 turns) | ~130,000 combats/s |

Numbers come from `python -m deployment.benchmark_speed --runs 500
--simulations 8 --mcts-sims 32 --mcts-decisions 300` (single thread) and only
count completed runs/simulations. Batch worker scaling is GIL-bound in the
Python policy loop; native search releases the GIL.

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
| `RUN_OBS_DIM` | 237 | HP/gold/floor/deck stats, screen one-hot, deck card histogram |
| `PUBLIC_OBS_DIM` | 37305 | schema v10 public run + combat observation, rewards and selection grids |
| `PUBLIC_COMBAT_OBS_DIM` | 21330 | visible combat state, piles, stolen cards, enchantments, power instances and choice candidates |
| `CARD_FEAT_DIM` | 250 | card one-hot, cost, type, rarity, upgrade, price, enchantments, replay and combat state |
| `COMBAT_OBS_DIM` | 61 | player status block + 4 monster slots |
| `ACTION_FEAT_DIM` | 340 | action schema v9: card/potion identity, instance state, target and choice op/pile |

`observe_public()` exposes only player-visible information (deck, resources,
visible map, in-combat hand/piles/intents, combat relics/counters, potions and
the full pending-choice candidate set); draw order, future intents, RNG state
and hidden event outcomes are not included.  Observation schema v9 and action
schema v8 invalidate older checkpoints; `load_checkpoint` rejects mismatches.

## Content

Generated from the reference engine by `simulator/tools/dump_*.py` and
`gen_*.py` (cards, monsters, potions, relics):

- **221 cards**: 87 Ironclad, 64 colorless, 11 status, 14 tokens, 18 curses,
  27 event cards. All single-player cards are playable; multiplayer-only cards
  are present but inert and marked UNSUPPORTED. Curses are real cards: Decay,
  Regret, Bad Luck, Doubt, Shame and Debt apply their end-of-turn effects, and
  Normality blocks playing more than three cards in a turn.
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
- **54 events**: 3 fully executable, 22 approximate (deterministic substitutes
  for card/enchantment UIs and curated event-relic effects), 29 unsupported and
  excluded from event bags. All seven Ancients (Neow, Orobas, Pael,
  Tezcatara, Nonupeipe, Tanx, Vakuu) and shared Darv generate their C# offer
  pools and grant the chosen relic.
- **Map**: standard 7-column act maps with 15/14/13 rooms; the generated map and
  its room counts are covered by golden tests.

Known approximations (full list in the coverage manifest): event
card/enchantment selection uses RNG substitutes, enchantments remain
approximated by upgrades, some event relics needing enchantments/pets/map
manipulation are no-ops or substitutes, and the exact tagged GrabBag ordering
is approximated. Act 4 is out of
scope. Card text is never parsed; semantics follow the reference effect code.

## Verification

`pytest tests -q` (84 tests) checks observation/action dimensions, the full
event manifest gating, every card/potion/implemented relic, map golden hashes
and structural invariants, deterministic replay and snapshot/restore equality,
room/economy transitions, boss reward/act changes, JSONL output, Ancient offer
pools and grants, curse mechanics, search resampling/completed-simulation
accounting, and automated A0 Ironclad wins from the opening Ancient to the
act-3 boss (seeds 24 and 32).
Differential traces against a live headless client are not available in this
environment; unverified behavior is marked APPROXIMATE/UNSUPPORTED rather than
claimed exact.

Current fixed-seed status (1000 test seeds, 16-simulation search) is in
[`docs/evaluation.md`](docs/evaluation.md): the heuristic wins 10.2%, the card
model with heuristic combat wins 10.9%, the v4b combat network wins 1.5%, and
the same network with resampled root search wins 4.8%. The combat model is still
below the heuristic baseline; the card model is comparable, not proven better.

The Python package `sts2_env` was removed per the pure-C++ requirement; the
reference engine remains at
`D:\project\sts2_compactformer\sts2-rl-agent\sts2_env`.
