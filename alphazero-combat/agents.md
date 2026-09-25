# AlphaZero Combat Contributor Guide

## Scope and Layout

This directory contains the isolated single-player combat learning pipeline.
Python package code is in `src/azcombat`; unit tests are in `tests`; experiment
configs, inputs, models, and run records live in `configs/`, `data/`, `models/`,
and `runs/`. Keep generated JSONL, logs, checkpoints, ONNX files, and reports
in a new run directory or under the repository's ignored `artifacts/` tree.
Changes to the C# bridge or NativeWorker also follow the repository root guide
and `combat/AGENTS.md` when they touch `combat/`.

## Environment and Commands

Use Python 3.10 or newer and the SDK pinned by the repository `global.json` for
NativeWorker builds. From the repository root:

```powershell
python -m pip install -e './alphazero-combat[train]'
python -m unittest discover -s alphazero-combat/tests -v
python -m pip install -e './alphazero-combat[export]'
```

Run experiment and export CLIs only with explicit, unique output paths. Native
data collection must use `scripts/native-worker.ps1` and the complete
`ExportRelease` flow; never use an old published worker or `-SkipBuild` to hide
a build mismatch. Preserve stdout, stderr, manifest, provenance, and failure
diagnostics for every run.

## Contracts and Data Discipline

The active contracts are observation schema 3, `azcombat.features.v4`,
`azcombat.onnx.v4`, `azcombat.checkpoint.v3`, and the `azcombat.search.v2`
sample semantics. Keep the 1,970-parameter network unchanged unless a task
explicitly changes the experiment contract. Strict readers must reject unknown
actions, zero visit totals, bad hashes, invalid masks, and incompatible ABI
versions. Do not filter bad samples, invent visits, default unknown semantics,
or treat `regressionOnly` fixtures as training data. Preserve win, loss, and
unresolved evidence separately; unresolved or error runs are not wins.

## Implementation and Verification

Use `snake_case`, type hints, small pure helpers, and deterministic seeds in
Python. Keep observation encoding limited to player-visible combat state; never
add RNG, future draws, future intent, state keys, or provenance as model
features. Validate Python, ONNX, and Native numerics before evaluating a model.
Select checkpoints only from fixed training/validation splits, never from final
evaluation results. Report the exact model hash, search mode, budgets, fallback
counts, and actual outcomes. Do not create a champion or start self-play from
this directory without an explicit promotion decision.

## Changes and Reviews

Use focused imperative commits such as `fix(azcombat): reject stale samples`.
Pull requests should identify the contract or CLI changed, list exact test and
run commands, link preserved diagnostics, and state untested scenarios. Never
commit personal game paths, secrets, or generated `bin/`, `obj/`, and run
outputs.
