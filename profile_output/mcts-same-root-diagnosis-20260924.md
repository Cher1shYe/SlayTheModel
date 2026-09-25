# Pure MCTS same-root throughput attribution (2026-09-24)

Final measurement: `artifacts/alphazero/mcts-diagnosis-20260924-005/manifest.json`.
The earlier `m5-performance-20260924/wall-clock-report-per-decision-corrected.json`
now shows cascade-tree prior/value calls as 364, 217 and 161 on its three
individual decisions rather than repeating the trajectory total 742.
Its throughput figures are unchanged. Re-reading that archived run checks
worker-log versus sample provenance, while explicitly not comparing against
the subsequently replaced shared stage DLL; new collection still checks the
actual on-disk loaded SHA256 at run time.
Earlier `-001` through `-004` directories remain intact as instrumentation-development
evidence; rates from different builds are not pooled here. Six serial headless
NativeWorker runs each used the full `ExportRelease` path, not `-SkipBuild`.
The manifest verifies the same loaded NativeWorker, Search and CombatSolver
path/MVID/SHA256 for all six processes and checks each file against disk.
The root's profiled/control runs use the exact same saved native entry checkpoint;
their root key, legal-action hash and observation hash match. CASCADE's second
choice root retains two promoted actions and one completed selection. No pending
choice was independently captured as a fresh combat root.

## Fixed Order And Rate

Each process used `ReplayMcts` with the legacy benchmark's now-shared pure-root
search helper, identical root, search seed, rollout policy and `maxDepth=200`.
The order was A cold first 1 s; an explicit 1 s warmup with its tree discarded;
B warmed *new-tree* 1 s; C warmed *new-tree* 5 s; E new-tree exactly 16 completed
simulations (5 s deadline); then, on profiled runs, D warmed new-tree 1 s with
the exporter's real post-search observation/sibling validation. `retainedVisits`
was zero in every arm. Except E, there was no simulation count cap. Each cell is
`completed / decisionWallMs (simulations/s)`; the 100/s threshold uses the same
full wall-clock denominator, not `searchActiveMs`.

| Root | Deep phase timing | A: cold 1 s | Discarded warmup | B: hot 1 s | C: hot 5 s |
| --- | --- | --- | --- | --- | --- |
| Ordinary entry | on | 79 / 1005 (78.6) | 82 / 1000 (82.0) | 122 / 1001 (121.9) | 2282 / 5000 (456.4) |
| Ordinary entry | off | 82 / 1008 (81.4) | 82 / 1001 (81.9) | 163 / 1000 (162.9) | 2054 / 5000 (410.8) |
| PURITY choice | on | 83 / 1011 (82.1) | 78 / 1003 (77.8) | 70 / 1004 (69.8) | 1565 / 5002 (312.9) |
| PURITY choice | off | 80 / 1009 (79.3) | 87 / 1002 (86.8) | 148 / 1003 (147.6) | 1569 / 5002 (313.7) |
| CASCADE second choice | on | 39 / 1012 (38.6) | 32 / 1008 (31.7) | 35 / 1007 (34.8) | 765 / 5005 (152.8) |
| CASCADE second choice | off | 39 / 1011 (38.6) | 35 / 1003 (34.9) | 34 / 1006 (33.8) | 825 / 5004 (164.9) |

The first search follows process startup and real root setup; it is not a
no-work cold process. The 1 s warmup does not reliably remove the short-decision
deficit: CASCADE remains 34-35/s in B with timing both on and off. The later 5 s
average exceeds 100/s for all three roots in this batch, but cannot substitute
for the A/B 1 s decisions. A further fresh 1 s search *after* C/E measured
456.3/s ordinary, 385.2/s PURITY and 174.0/s CASCADE with export validation.
This 4.5-5.8x A-to-late-D association reflects process maturation at the same
root, but does not isolate JIT from GC, cache, clock/scheduler changes, or the
different 1 s versus 5 s observation windows. Historical ~1000/s numbers were
not reused as this run's baseline.

The existing `WorkerServer` response still fills its legacy `SimulatorForks`
field from an Apply delta and its `StateTransitions` omits promoted-prefix
replay. Neither field was used for this diagnosis. New Fork counts come from
the actual simulator-copy sites, and restored-prefix work is separate.

## Work Per Completed Simulation

The following are from the profiled B new-tree 1 s arm. `Apply` counts only
explicit tree/rollout calls; prefix actions are separate. `semanticTransitions`
also counts internal choice-branch replay work. `forkCopies` is the driver's
physical `_run.ForkCount`, not an alias for Apply. Root setup has one additional
real root Fork per process, separately recorded as `rootForkCount=1`.

| Root | Complete / started / cut off | Tree + rollout steps per complete | Max rollout | Explicit Apply / complete | Prefix actions / complete | Forks / complete | Resolved choice branches / complete |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |
| Ordinary | 122 / 123 / 1 | 3.1 + 25.0 | 35 | 28.2 | 0 | 55.4 | 0 |
| PURITY | 70 / 71 / 1 | 1.9 + 25.0 | 42 | 27.3 | 1.0 | 66.3 | 20.1 |
| CASCADE layer 2 | 35 / 36 / 1 | 2.6 + 46.2 | 52 | 48.8 | 2.1 | 114.1 | 46.4 |

All completed simulations reached true terminal states, not the depth-200
unresolved boundary. The cut-off attempts still consumed work and are retained
in attempted, tree-step and rollout-step totals: ordinary 4 tree + 3 rollout
steps, PURITY 3 + 27, CASCADE 0 + 0 (its attempt was stopped before a new
transition). The fixed-16 arm completed exactly 16 on all six processes, with
zero cut-off attempts. For the same root, timing-on/off fixed-16 runs had
identical selected action, complete root visit statistics, tree/rollout steps
and physical Fork counts. CASCADE needed 805 explicit Apply, 34 prefix actions,
1878 Forks and 776 resolved choice successors for just 16 completions.

This is both **more work** and **more expensive work**, not just a slow single
transition: B's measured inclusive Apply averaged 0.287 ms ordinary,
0.423 ms PURITY and 0.506 ms CASCADE. Each CASCADE simulation also took about
1.7x ordinary explicit steps and 2.1x Forks. Internal choice replay attempts
were 1410 for PURITY and 1839 for CASCADE in B, with zero branch-budget drops.

## Stage Time And Memory

All values below are milliseconds within the profiled B 1 s search. Driver
phases are **exclusive** unless marked inclusive. `prefixReplay` and
`Apply` are separate inclusive environment ranges; they overlap the driver
phases and must not be added to the phase columns. `choiceMaterialization`
includes its child Fork/snapshot/replay work. The sum of exclusive driver
phases was 984/976/981 ms for ordinary/PURITY/CASCADE, versus 1001/1001/1003 ms
search-active time. These are elapsed phase timings, not sampled on-CPU stacks.

| Phase | Ordinary | PURITY | CASCADE layer 2 |
| --- | ---: | ---: | ---: |
| Prefix replay, inclusive | 0 | 183.8 | 135.5 |
| Explicit Apply, inclusive | 988.5 | 808.8 | 864.7 |
| Choice materialization, **inclusive** | 270.8 | 414.1 | 552.4 |
| Choice materialization, exclusive | 22.3 | 43.2 | 99.4 |
| True Fork copying, exclusive | 116.4 | 111.6 | 139.1 |
| Snapshot, exclusive | 143.2 | 148.2 | 120.6 |
| Action description, exclusive | 108.0 | 74.3 | 48.1 |
| Observation projection + validation, exclusive | 0 | 24.3 | 41.4 |
| Choice JSON serialization, exclusive | 0 | 16.6 | 22.4 |
| State fingerprint + identity hash, exclusive | 41.8 | 47.3 | 43.7 |
| Threat projection, exclusive | 7.7 | 4.1 | 3.2 |

The largest actionable choice-specific range is eager successor
materialization: in CASCADE it occupied 552 ms inclusive, 55% of search-active
time, with 1625 resolved successors for 35 completed rollouts. `prefixReplay`
was 136 ms inclusive, 13.5%. **These ranges overlap** because prefix replay
can materialize its own choice successors. Observation plus JSON was 64 ms in
CASCADE (6.4%); action description 48 ms exclusive and threat projection 3 ms.
None of these latter items alone explains the 3.5x ordinary-to-CASCADE B rate
difference. No strict validation was disabled.
The measured JSON phase covers choice-path identity and pending-frame
comparison. JSONL writing occurs after the trajectory and outside the
search-decision wall clock.

Process allocation in B was 163.1/112.0/125.8 MiB (1.34/1.60/3.59 MiB per
complete simulation) for ordinary/PURITY/CASCADE. GC counts were 18/0/0,
12/0/0 and 14/1/0 across generations 0/1/2, with 20.3/15.1/14.3 ms added
total GC pause. Process CPU time includes Godot/background threads, so it is
not attributed to a search phase. `dotnet-trace`/`dotnet-counters` were absent;
no CPU or allocation call-stack sample was captured. These are phase timings
and process allocations, not a CPU hotspot trace.

The exporter-style D arm shared the same root and pure search helper as the
legacy benchmark-style arms. Actual post-search observation/sibling validation
took 2.32/2.10/4.21 ms; waiting took <0.5 ms. Whole D decision wall was
1003.68/1002.13/1005.64 ms. Extra export validation thus accounts for <0.5%
of a 1 s decision, not the tens-to-hundreds-per-second gap. Build took about
2.0 s per process (one 2.8 s), worker startup 1.2-1.3 s, native reset 0.11-0.12 s,
and root setup 0.19/0.38/0.43 s by root. These were recorded separately and
excluded from each decision wall clock.

Deep phase timing is opt-in via `STS2_MCTS_DIAG_PROFILE=1`; both sides retain
lightweight attempt/step/environment counters only in the diagnosis mode.
Fixed-16 work and root visits matched exactly, but phase-on/off wall differences
were not stable in sign (34.7 vs 24.8 ms ordinary, 31.8 vs 44.3 ms PURITY,
96.4 vs 93.9 ms CASCADE). Five-second rates also differed in both directions.
The observed overhead cannot be treated as a constant correction to the gate.

## Decision And Boundaries

**Single priority for a later optimization experiment:** replace eager
materialization of unselected sibling choice successors in
`CombatBeamSolver.NativeMctsExpand` / `WithCardChoiceCheckpoint` with a
current-layer, demand-driven continuation. This is a proposal only; no
algorithm, rollout, action identity or combat semantics were changed here.
An unrealistically favorable ceiling from B is deleting *all* 552 ms of
CASCADE choice-materialization time, which would raise 35/1.007 s to at most
about 77/s on that exact workload. Real improvement is lower because selected
branch work is mandatory. It cannot alone establish the 100/s target; the
remaining rollout/description/Fork cost must be measured after any one-factor
change. Prefix caching alone has a still smaller ceiling (135 ms, about 41/s).

Before accepting such a change, run same-checkpoint fixed-completion A/B and
compare each legal choice key/path, candidate identity and order, min/max,
`completedSelections`, RNG/continuation fingerprints, terminal utility,
selected action and root visit statistics. Test cancellation and sibling replay
without cross-branch contamination. Then rerun the 1 s gate denominator with
the unchanged 100/s threshold. This batch does not establish M4 eligibility,
model quality, or visible Steam responsiveness; no champion/training/self-play
was started.

## Instrumentation Changelog

| File | Lines | Change | Instrumentation |
| --- | --- | --- | --- |
| `alphazero-combat/src/azcombat/performance_report.py` | 12-52 | modified | Per-decision prior/value/fallback now read from matching `decisionMetrics`; archived logs/provenance are not compared with newer shared-stage DLLs. |
| `alphazero-combat/src/azcombat/native_probe.py` | 135, 256-269 | modified | Keeps new-run disk hash checks by default; permits explicit archived-log/sample re-audit after a later publish replaces the stage. |
| `alphazero-combat/tests/test_performance_report.py` | all | created | Checks metric alignment and per-decision values. |
| `alphazero-combat/src/azcombat/mcts_diagnosis.py` | 33-153 | created | Serial full-publish launcher; saves checkpoints, full streams and assembly provenance. |
| `src/SlayTheModel.Search/ReplayMcts.cs` | 21-34, 85-148 | modified | Optional attempted/completed/cut-off, tree/rollout steps and terminal counters. |
| `tools/Sts2.NativeWorker/CombatSolverReplayEnvironment.cs` | 6-24, 138-205 | modified | Optional restore, prefix replay, Apply and observation ranges. |
| `tools/Sts2.NativeWorker/MctsThroughputDiagnosis.cs` | 13-252 | created | Real-root A/B/C/D/E runs, allocation/GC/pause and root identity checks. |
| `tools/Sts2.NativeWorker/Worker.cs` | 50-90 | modified | Dedicated headless diagnosis mode and exact checkpoint save/restore. |
| `scripts/native-worker.ps1` | 7, 77-94, 135-153 | modified | Diagnosis mode and separate publish/process wall timers. |
| `tools/Sts2.NativeWorker/CombatSolverMctsBenchmark.cs` | 443, 576-594 | modified | Legacy benchmark/search helper shared with diagnosis; exporter validation callable on the same root. |
| `combat/src/Api/NativeMctsSimulationApi.cs` | 53-70, 118 | modified | Exposes native driver counters and phase snapshots. |
| `combat/src/Search/CombatBeamSolver.NativeMcts.cs` | 26-32, 70-141, 259-319 | modified | Counts real root Fork and generated/resolved choice branches; times expand/describe/serialization. |
| `combat/src/Search/CombatBeamSolver.NativePolicyObservation.cs` | 42-102 | modified | Times observation projection and validation. |
| `combat/src/Search/CombatBeamSolver.Expansion.Replay.cs` | 354-356 | modified | Times physical root `ForkSimulator()` instead of the whole root Replay. |
| `combat/src/Search/SearchPerformanceMetrics.cs` | 31-43, 54-151 | modified | Adds optional native phases and both inclusive/exclusive aggregates. |
| `tools/PolicyValueMctsChecks/Program.cs` | 38-55, 91-123 | modified | Confirms capped completions and cancelled incomplete rollout counting. |

All source changes remain uncommitted. Existing worktree edits and earlier
diagnostic artifacts were preserved.
