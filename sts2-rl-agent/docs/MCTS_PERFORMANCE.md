# Combat MCTS performance

The implementation lives in `sts2_env/search/`. It is a deterministic,
perfect-information search baseline, not AlphaZero or information-set MCTS.
It uses uniform exploration priors and random rollouts with a simple HP leaf
evaluation. Full-game strength and hidden-information fairness are not claimed.

## Changes

- `clone_state` copies simulator objects including inherited slots, closure
  cells, captured defaults and bound methods. Unsupported types fail loudly.
  Python `deepcopy` shares closure functions; the old `fast_copy` also shared
  slots-only objects, so those are not valid correctness references.
- Replay mode copies only the root once per simulation and reconstructs the
  selected path. Nodes keep statistics, not large cyclic combat snapshots.
- Reference mode retains node snapshots for an independent equivalence check.
  It skips the rollout copy when rollout depth is zero.
- Auto mode uses reference mode for zero-depth leaf evaluation and replay mode
  for rollouts. Replay reduces copying, but can be slower for short searches or
  expensive replay paths; explicit modes remain available.
- Tree nodes have no parent pointer; backup uses a short path list. Exploration
  scale is calculated once per node selection. Random actions use an integer
  index rather than numpy.choice. Inner-loop timer calls were removed.
- The process-global card allocator is reset per simulated path and restored
  after search, including exceptions. Use processes, not concurrent threads.
- `SearchPool` keeps Windows-spawn workers alive across batches. Jobs describe
  reproducible starter-deck scenarios, avoiding pickling live state closures.
  This parallelizes independent battles, not one shared search tree. General
  deck/scenario serialization remains future work.

## Reproduce

From the sts2-rl-agent directory in PowerShell:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_search_mcts -v
.\.venv\Scripts\python.exe scripts/benchmark_mcts.py --sims 64 256 --seeds 3 --output output/mcts_benchmark.json
.\.venv\Scripts\python.exe scripts/benchmark_mcts_batch.py --sims 128 --seeds 6 --workers 4 8 --output output/mcts_batch_benchmark.json
```

The paired benchmark compares all node visit counts, cumulative values and
unexpanded actions. The batch benchmark compares full-tree digests between
serial and parallel execution. It measures total batch wall time, including
scenario reconstruction, serialization and GC; pool startup is reported
separately. Paired search timings exclude scene setup and pre-search GC.

## Measurements on 2026-10-08

Intel Core Ultra X7 358H, Python 3.14.4, current local workload. Short benchmarks
are noisy; these are measured samples, not throughput guarantees.

Six opening/mid-combat scenes, single process, identical trees:

| Rollout depth | Simulations/decision | Reference sims/s | Replay sims/s |
|---|---:|---:|---:|
| 40 | 64 | 339 | 338 |
| 40 | 256 | 339 | 357 |
| 0 | 64 | 2534 | 2045 |
| 0 | 256 | 2654 | 1880 |

Depth zero uses the HP heuristic, **not a neural network**. Its greater speed
changes the evaluation method; it does not establish equal playing strength.

Twelve independent scenes, 128 simulations/decision, depth 40, auto mode:

| Workers | Aggregate sims/s | Relative throughput | Pool startup |
|---|---:|---:|---:|
| Serial | 391 | 1.00x | — |
| 4 | 1479 | 3.78x | 0.34 s |
| 8 | 2198 | 5.63x | 0.45 s |

Parallel throughput does not imply equivalent single-decision latency. Raw
results are written to the output paths above. These new safe-copy measurements
are not directly comparable to old unsafe-copy results or different scene sets.

## Integration

```python
from sts2_env.search.mcts import search

result = search(combat, simulations=128, rollout_depth=40)
action = result.action
```

For a value network, use `rollout_depth=0, evaluator=your_value_function` and
measure inference overhead. Policy priors and batched neural inference are not
implemented. Always call pools inside a main guard on Windows:

```python
from sts2_env.search.batch import SearchJob, SearchPool

if __name__ == "__main__":
    with SearchPool(8) as pool:
        results = pool.run([SearchJob(scene_seed=i) for i in range(32)])
```

Tests cover isolation of player/card slots, RNG, pending choices, monster
callbacks, recursive/shared closure cells, exception cleanup, 22 Act 1
encounters, and serial/spawn equivalence. They do not prove all-card or real-game
parity. Module-level functions/globals stay shared: only the known card ID
allocator is explicitly isolated, so newly introduced global mutable simulation
state must be audited before extending this search.
