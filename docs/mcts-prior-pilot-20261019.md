# Native MCTS policy-prior pilot — 2026-10-19

## Scope and implementation

This is an opt-in benchmark integration, not a general in-game prior switch.
`ReplayMcts` accepts an optional policy callback in legal-action order. Without it,
the existing UCT path is retained. With it, selection uses
`Q + 1.5 * P * sqrt(1 + parentVisits) / (1 + childVisits)` and caches normalized
priors once per tree node. Invalid sizes, negative/nonfinite values and zero sums
fail explicitly. Final action selection remains maximum visit count.

All transitions, draw order, RNG and rollouts still use the full-information C#
Combat Solver environment. The Python process only encodes native observations
and runs the frozen policy network; it does not reconstruct or simulate worlds.
The value head is unused. The existing terminal/cutoff reward is unchanged.
The resident CPU service uses one Torch thread; no training or model update runs.

`NativeMctsPriorObservation` reads the current prediction state. The adapter is
deliberately restricted to unmodified Strike/Defend/Bash, no relics, potions,
player powers, stars, exhaust or pending selections, and `BYRDONIS` only.
Its alternating public move history is reconstructed deterministically. Other
monsters fail rather than pretending their histories are known. Extending this
to arbitrary encounters requires native history/features and card-state codecs.
The frozen Python registry says swoop damage 16, while native v0.111.0 uses 17;
the adapter checks intent shape and supplies native damage instead.

## Frozen model and reproduction

Source project: `sts2_compactformer/sts2-rl-agent` (external dependency, unmodified).
Checkpoint: `output/search_learned_vs_heuristic256_20261018_215108/frozen_model.pt`.
SHA256: `20bbfad0a319cf2910dbf0f30f9f554b60c56e3b69ce1a835aeb080f29c7de60`.
Architecture XS, ALL content contract, V7 checkpoint reward metadata. The old
checkpoint reward metadata describes training, not a replacement of C# rewards.
Native game contract: Windows v0.111.0. Pre-change source: `cda7972`.

From the repository root, with the external project's `.venv-az` installed:

```powershell
./scripts/benchmark-prior.ps1 -GameDir '<Steam game directory>' `
  -Source '<sts2-rl-agent directory>' -Checkpoint '<frozen_model.pt>'
```

The launcher builds once, runs hidden workers with a 120-second per-case timeout,
then saves each case to a fresh artifacts directory. Seeds default to 1,2,3 and
initial HP to 80,40. Each case contains UCT, uniform-prior PUCT and learned-prior
PUCT. Arm order reverses for even seeds. Each arm warms for 500 ms, measures three
fresh-root 250 ms searches, then plays a full native fight with 100 ms per decision.
The prior service is prewarmed before timed searches. Searches can slightly exceed
the soft deadline while draining a matching inference reply. Reported speed uses
actual elapsed time. Native nonterminal successor continuation keys are checked
against simulation after every executed action, outside the search timer.

## Measured pilot results

Six paired starting states, 18 full fights, 54 fixed-root searches. Each arm won
all three HP=80 fights and lost all three HP=40 fights; all fights terminated.

| Method | Fixed-root median simulations/s (18 samples) | Full-fight simulations/s (total/total search time) | Wins | Mean HP among wins |
| --- | ---: | ---: | ---: | ---: |
| Original UCT | 287.8 | 838.2 | 3/6 | 10.0 |
| Uniform-prior PUCT | 1103.3 | 1646.4 | 3/6 | 20.7 |
| Learned-prior PUCT | 182.4 | 387.7 | 3/6 | 10.0 |

| Initial HP | Seed | UCT final HP | Uniform final HP | Learned final HP |
| ---: | ---: | ---: | ---: | ---: |
| 80 | 1 | 13 | 19 | 8 |
| 80 | 2 | 3 | 24 | 3 |
| 80 | 3 | 14 | 19 | 19 |
| 40 | 1 | 0 | 0 | 0 |
| 40 | 2 | 0 | 0 | 0 |
| 40 | 3 | 0 | 0 | 0 |

Learned priors reduce the pooled fixed-root median throughput by 36.6% relative
to UCT; full-fight throughput falls 53.7%, though that comparison also includes
different chosen routes, states and rollout lengths. Uniform PUCT is included to
separate a change in tree policy from the contribution of learned probabilities.
These are simulation counts, not equal-work operations.

Across learned full fights: 1271 inference calls; 5067 ms service wall time out
of 9402 ms search time (53.9%). Per call: 3.99 ms service wall, 0.48 ms Python
entity construction, 3.23 ms `model.predict` (including its tensor encoding),
and about 0.27 ms remaining serialization/IPC. C# observation extraction is outside
the service timer but inside search time. Therefore these numbers do not isolate
pure neural forward-pass cost. Per-node synchronous inference is expensive here.

Machine-readable compact measurements: [benchmark JSON](benchmarks/mcts-prior-pilot-20261019.json).
Detailed actions, visits, priors and raw measurements remain in local
`artifacts/prior-pilot/seed-*-hp-*.json`. Root visit rows include visited actions;
PUCT priors additionally include every legal action (unlisted visits are zero).

## Interpretation and remaining work

The frozen policy can drive native MCTS without Python simulation, but this pilot
does not show a quality gain. It should not replace the default in-game search.
The uniform arm's better HP is a promising observation, not proof of general
superiority: only one encounter, three seeds, no relics and very short budgets were
tested. Arms share a process and receive only short warmup; order, JIT, GC and
deadline noise remain possible confounders. Headless results do not establish
visible-game throughput, FPS, boss performance or statistical win-rate improvement.

Next candidates are root-only or shallower prior use, a smaller/distilled in-process
policy, and measured batching. First compare at equal wall time on a broader native
scenario set. Do not increase simulation budgets to hide inference overhead.
General card/monster support, production enabling, training-data integration and
self-evolution remain outside this first step.

Validation: Release worker publish and ReplaySearch smoke passed; smoke covers
prior normalization, influence at equal reward, caching and invalid-prior rejection,
alongside existing UCT/reward checks. All 18 native pilot fights completed with
nonterminal successor checks. This is not exhaustive state-feature equivalence.
