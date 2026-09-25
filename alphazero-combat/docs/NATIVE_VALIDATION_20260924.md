# Native selection, terminal and wall-clock validation (2026-09-24)

All runs used headless NativeWorker via `scripts/native-worker.ps1` with full
`ExportRelease` publishing and the pinned v0.111.0 game/RitsuLib. Each probe
has a distinct JSONL, launcher stdout/stderr, full worker stdout/stderr and a
strict `.probe.json` report. The report checks loaded assembly path, MVID and
SHA256 against the JSONL provenance; no old artifact was overwritten.

## Real choice boundaries

Source: `artifacts/alphazero/m5-choice-20260924/`. Forced parent cards are
regression fixtures only. Every file has `regressionOnly=true`; the normal
training loader rejects them. The six files pass strict schema validation with
the regression-only validation flag, and all selected action IDs belong to
their frozen choice root. NativeSession validates live/predicted option identity,
order, cardinality and legal action mapping before applying each layer.

| Fixture | Pure MCTS choice layers | Tree choice layers | Candidate prior/value per choice root | Fallback |
| --- | ---: | ---: | --- | ---: |
| PURITY | 1 | 1 | 50 / 50 | 0 |
| BURNING_PACT | 1 | 1 | 50 / 50 | 0 |
| CASCADE/PREPARED | 2 | 2 | 50 / 50 on each layer | 0 |

All choice roots completed exactly 50 simulations under the cap and received
at least 1000 ms. PURITY exposes `Exhaust`, `Hand`, min/max 0/3, ordered=false;
BURNING_PACT exposes 1/1; CASCADE exposes 1/1 on both layers. Candidate card
identities/order match the live options. On the second CASCADE layer,
`completedSelections` was checked against the previous layer's *selected*
action payload using card identity, upgrade and duplicate occurrence, not only
against the presence of a context field. The regression trajectories are
unresolved because the cap is one parent decision; they are not win/loss data.

## Actual terminal results

Source: `artifacts/alphazero/m5-terminal-20260924/`. The exporter's enemy HP
counter formerly read its `before` value after enqueueing the action, so a
genuine win with enemy HP falling 91 to zero recorded zero damage. The
NativeSession test host now snapshots before submission and persists every
native before/after/damage transition. The utility formula itself is unchanged.

| Run | Outcome | Decisions | Player HP | Enemy actual damage | Backfilled value |
| --- | --- | ---: | --- | --- | ---: |
| ordinary pure MCTS | win | 16 | 80 -> 68 | 91 / 91 | 0.327979 |
| ordinary tree | loss | 18 | 80 -> 0 | 60 / 91 | -0.835165 |
| native low-HP pure MCTS | loss | 4 | 1 -> 0 | 12 / 89 | -0.966292 |
| native low-HP tree | loss | 4 | 1 -> 0 | 12 / 89 | -0.966292 |

Every sample passed strict readback. In each trajectory, all samples share the
actual terminal outcome and utility computed from native HP evidence. All
prior/value calls on tree runs are real, and no fallback occurred. The ordinary
seed was selected because an earlier pure-MCTS artifact had won; the current
tree loss is not evidence of model quality from a paired holdout evaluation.

## Independent performance

Source: `artifacts/alphazero/m5-performance-20260924/wall-clock-report.json`.
No `MaxSimulations` cap was set. The denominator is the full per-decision
`elapsedMilliseconds` used by the existing gate, including any waiting needed
to meet the >=1000 ms live-decision floor. The threshold remains 100/s.

| Mode / root | Decisions | Min | Median | Max | Every decision >=100/s |
| --- | ---: | ---: | ---: | ---: | --- |
| Pure MCTS / ordinary | 3 | 42.56 | 84.95 | 101.04 | No |
| Pure MCTS / choice | 3 | 33.48 | 42.81 | 93.61 | No |
| Tree / ordinary | 3 | 361.26 | 537.00 | 553.96 | Yes |
| Tree / choice | 3 | 159.65 | 216.21 | 320.26 | Yes |

Tree prior/value calls are positive at each tested root, with zero fallback.
Pure MCTS has no network calls. Its complex choice roots miss the 100/s
threshold, so the current pipeline does **not** pass an across-modes 100/s
claim. `ReplayMcts` continues a depth-limited rollout after expansion, whereas
`PolicyValueMcts` evaluates a new leaf and backs up; this is a plausible cost
source, not a completed performance optimization. These small headless fixtures
do not establish sustained throughput, visible-game responsiveness, model
effectiveness, or M4 promotion eligibility.

Profiling instrumentation changelog:

| File | Lines | Change | Purpose |
| --- | --- | --- | --- |
| `tools/Sts2.NativeWorker/NativeSession.cs` | 54-66, 321-354 | modified | Native enemy HP before/after transitions for reward audit. |
| `tools/Sts2.NativeWorker/CombatSolverMctsBenchmark.cs` | 112-115, 394 | modified | Persist HP evidence and allow regression-only forced tree fixtures. |
| `alphazero-combat/src/azcombat/native_probe.py` | 14-303 | created | Isolated run, full logs and strict trajectory audit. |
| `alphazero-combat/src/azcombat/performance_report.py` | 12-62 | created | Read-only decision-wall-clock throughput distribution. |
| `alphazero-combat/tests/test_native_probe.py` | 25-92 | created | Probe contract and duplicate-card choice mapping tests. |

No formal self-play, full M4 matrix, champion creation or push was performed.
