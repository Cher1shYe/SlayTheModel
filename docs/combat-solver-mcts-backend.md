# Combat Solver MCTS Backend

The AI policy remains `ReplayMcts`/UCT. Combat Solver supplies only the forkable combat simulation used by each rollout. The native game executes only the selected root action.

## Dependency

The Combat Solver repository must exist at `combat` inside this repository and remain based on commit `8826a333a6d48e05f0e368ee2db5d4a15092382e`. `scripts/native-worker.ps1` verifies this commit before building. The local Combat Solver bridge changes intentionally remain uncommitted for now.

## Correctness Gates

- Native action execution and prediction produce the same `ContinuationStamp`.
- End turn, enemy actions, and the following player turn match native execution.
- Purity exposes 15 independent MCTS choice nodes; a three-card choice matches native execution.
- Repeated pondering and post-action search retain MCTS visits.
- Unsupported or dynamic prediction boundaries fail the search instead of receiving a rollout value.

## Performance

Windows headless, single-threaded MCTS, fixed seed, `maxDepth=200`, one warm-up plus five 5-second samples per encounter:

| Encounter | Median rollout/s | Minimum rollout/s |
|---|---:|---:|
| `FUZZY_WURM_CRAWLER_WEAK` | 1404.45 | 655.63 |
| `CULTISTS_NORMAL` | 914.89 | 882.40 |
| `LIVING_FOG_NORMAL` | 489.07 | 485.58 |
| `PHROG_PARASITE_ELITE` | 606.14 | 600.29 |
| `KAISER_CRAB_BOSS` | 1521.84 | 1512.79 |

All five scenarios exceed 100 completed full rollouts per second. Raw output is generated at `artifacts/native-host/benchmark.json`.

Run verification:

```powershell
& .\scripts\native-worker.ps1 -GameDir 'D:\Steam\steamapps\common\Slay the Spire 2' -Mode verify -TimeoutSeconds 240
```

Run the performance matrix:

```powershell
& .\scripts\native-worker.ps1 -GameDir 'D:\Steam\steamapps\common\Slay the Spire 2' -Mode solver-mcts-benchmark -TimeoutSeconds 360
```
