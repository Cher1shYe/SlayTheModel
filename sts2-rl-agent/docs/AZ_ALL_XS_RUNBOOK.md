# AZ All-Content XS Runbook

Everything here is ready but **not executed automatically**: the formal training run
needs explicit authorization. All commands run from `sts2-rl-agent/` with
`.venv-az\Scripts\python.exe`.

## 1. Preflight (safe, no training)

```
python -m sts2_env.az.all_runner --preflight-only --iterations 1 --episodes 1
```

Expected: `training 1/1`, `validation 64/64`, `test 64/64`, `ready=true`, and the
generator-manifest SHA matching the frozen protocol. A differing manifest or any
rejected recipe makes preflight raise/return not-ready.

## 2. Smoke (pipeline only, not a learning claim)

```
python -m sts2_env.az.all_runner --iterations 1 --episodes 2 --updates 1 --budget 2 --max-turns 4 --out output/az_all_xs_smoke
```

Runs collection, one update, baseline/candidate validation and the paired report.
This verifies plumbing; it cannot support a learning claim.

## 3. Formal run (authorized)

```
python -m sts2_env.az.all_runner --iterations 4 --episodes 8 --updates 4 --budget 8 --workers 2 --out output/az_all_xs_run
```

Measured throughput at budget 8, `max_turns` 6, 8 episodes: **58.5 s serial /
26.6 s with 2 workers** (2.2x). The 4x8 run therefore costs roughly 2-3 minutes of
collection plus 4 validation passes (~17 s each at 64 recipes) and four updates.

The frozen 8x48 budget (config `az-all-xs-v1`) would be roughly **47 min serial /
21 min with 2 workers** of collection, plus validation, i.e. about 25 min total on
this machine.

Outputs in `--out`:

- `report.json`: `provenance` (config/protocol SHA-256, generator SHA, content/reward/rules
  versions), `baseline`, `history[*]` with `updates` losses, `seconds{collect,update,evaluate,total}`,
  `paired_vs_baseline` (scenario-paired bootstrap mean, 95% CI, P(gain>0)),
  `validation_by_encounter`, `target_stats`, `rejected_recipes`, `checkpoint`.
- `baseline.json`: frozen initial-model rows for later re-checks.
- `iteration-NNN.json` / `iteration-NNN.pt`: per-iteration evidence and checkpoint.
- `errors/`: one JSON per contract rejection (scenario, actions, exception).
- `replay/`: typed entity replay (idempotent commits, safe on resume).

## 4. Resume

```
python -m sts2_env.az.all_runner --iterations 8 --episodes 8 --updates 4 --budget 8 --workers 2 --resume --out output/az_all_xs_run
```

Resume loads the last checkpoint, keeps history, reloads `baseline.json` so paired
comparisons continue, and only collects the new iterations. Replay commits by
`episode_id` are idempotent.

## 5. Test split

Test recipes open only when `--include-test` is passed **and** the last iteration's
paired validation gain is positive; otherwise the report records
`test_gate.passed=false` and no test summary. `--force-test` overrides the gate and
is recorded as `forced=true`.

## 6. Known search-side rejections (recorded, not hidden)

The MCTS collection path can still reject 4 of the 64 validation recipes:

- `setup_gremlin_merc_normal` (x2) and `setup_axebots_normal`: a primary enemy is
  removed from combat, which needs a separate removal/summon budget contract.
- `setup_knights_elite`: the particle path does not yet account for `hexed` card
  states created during a simulated turn.

Network-only evaluation has **zero** rejections on the frozen 64-recipe validation
split. Rejections are written to `errors/` and `rejected_recipes`.

## 7. How to read the results

- `paired_vs_baseline.mean_gain` and its 95% CI are descriptive; a CI including 0 is
  not evidence of improvement.
- `validation.mean_utility` compares different policies on the same recipes only
  after pairing; raw means across split sizes are not comparable.
- `target_stats.mean_entropy` near 0 means degenerate targets; `forced_fraction`
  reflects single legal actions.
- Any claim about learning requires the formal run's own numbers, the frozen
  protocol, and no test-split peeking before the gate.
