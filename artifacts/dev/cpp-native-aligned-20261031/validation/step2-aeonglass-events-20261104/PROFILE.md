# Throughput profile (2026-11-04)

Question: the whole-run benchmark dropped from ~70 runs/s / 4.0 us per combat
step to ~65-67 runs/s / 4.2-4.4 us per combat step.  Where does the time go?

## Method

- Sampling via Visual Studio DiagnosticsHub (user-mode, no kernel logger):
  `VSDiagnostics.exe start <id> /launch:<bench.exe> /launchArgs:"<args>"
  /loadConfig:...\CpuUsageBase.json`, stop to a `.diagsession`, then
  `expandDiagSession` + `xperf -i <etl> -symbols -a stack -butterfly 2`.
- A separate `RelWithDebInfo` build (same `/O2`, `/Zi` symbols) was configured
  in `simulator/build-profile`; the Release `bench.exe` was restored
  afterwards (`build-win/_b.bat`, no PDB, re-verified 65.0 runs/s).
- Traces kept: `profiling/run-1000.diagsession` (`bench.exe run 1000`) and
  `profiling/combat-200000.diagsession` (`bench.exe 200000`, combat only).

## Whole-run trace (1000 runs)

| symbol | exclusive | inclusive |
| --- | ---: | ---: |
| `find_matching_segments` (map.cpp, anon) | **29.8%** | **76.4%** |
| `find_all_paths` | 1.5% | 28.5% |
| `prune_duplicate_segments` | - | 76.6% |
| `RunContext::init` / `start_act` / `generate_act_map` | - | 77.3-77.3% |
| `std::_Uhash_compare::operator()` | 2.0% | 2.0% |

`bench.exe` attributes 14-15 ms per run to `init` out of ~15 s total for 1000
runs.  In other words, whole-run throughput is dominated by act-map segment
pruning at run initialization, not by combat.  `BattleContext::step` itself
does not appear near the top of this trace.

## Combat-only trace (200,000 combats, 16,785 samples)

| symbol | exclusive |
| --- | ---: |
| `BattleContext::BattleContext` (one-time zeroing per bench combat) | 13.5% |
| `ActivePlay::ActivePlay` | 2.9% |
| `BattleContext::player_power` | 1.2% |
| `BattleContext::start_player_turn` | 1.2% |
| `BattleContext::legal_actions` | 1.0% |
| `greedy_action` | 0.8% |
| `regent_before_card_played` | 0.8% |
| `card_has` | 0.7% |
| `run_active_play` | 0.6% |
| `silent_before_card_played` | 0.6% |
| `card_def` | 0.6% |
| `calc_player_damage` | 0.6% |

No single combat-step function dominates.  The remaining cost is spread across
per-card/per-power hook scans (`player_power`, `card_has`, `card_def`,
`regent_before_card_played`, `silent_before_card_played`) and pile/choice
bookkeeping.  The constructor cost is paid once per `bench_combat` iteration and
is not representative of the whole-run loop, which reuses `RunContext::battle`.

## Conclusion

- The whole-run rate is limited by map generation (`find_matching_segments`
  enumerates every path segment and hashes/copies each candidate, re-run after
  every prune iteration).  This is deterministic rule code; optimizing it
  requires preserving the `.NET Dictionary` first-occurrence order and the
  exact prune-loop iteration count.
- The 2.3 -> 4.2-4.4 us combat-step delta is not attributable to one hot
  function in this sampling profile.  It is consistent with accumulated
  per-card/per-power hook scans added over the rule batches.  No rule or real
  choice was removed to recover speed, and no optimization is claimed yet.
- Next candidates, in order: (1) reduce segment-key hashing/allocations and
  cache `find_all_paths` during one prune iteration without changing candidate
  order; (2) fast-path `player_power`/`card_has` lookups used in every damage
  calculation; (3) only then micro-optimize `BattleContext` construction if a
  real run loop shows it again.

## Reproduce

```
# build symbols
cmake -S simulator -B simulator/build-profile -G Ninja \
  -DCMAKE_BUILD_TYPE=RelWithDebInfo -DBUILD_TESTING=OFF \
  -DSTS2_MODULE_OUTPUT_DIR=<abs build-profile>
cmake --build simulator/build-profile --target sts2_bench
# collect
VSDiagnostics.exe start 2 /launch:<abs>/bench.exe /launchArgs:"200000" \
  /loadConfig:"...\AgentConfigs\CpuUsageBase.json"
VSDiagnostics.exe stop 2 /output:<abs>/combat.diagsession
VSDiagnostics.exe expandDiagSession combat.diagsession
xperf -i <expanded sc.user_aux.etl> -symbols -a stack -butterfly 2 -o stacks.html
```
