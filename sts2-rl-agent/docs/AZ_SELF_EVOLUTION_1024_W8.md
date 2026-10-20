# Candidate-initialized AlphaZero self-evolution

The dedicated entry point `scripts/run_native_az_self_evolution.py` uses the
published 1024-fight candidate as its initial learner and champion. Every
new nonterminal search leaf uses joint policy/value inference; backpropagation
uses pure model value. Terminal and approved 40-turn/100-decision cutoffs retain
native V7 utility. Strict endpoint, feature, successor and provenance checks
remain enabled; contract failures stop the run.

The frozen plan uses 500 ms per decision, eight workers with two fights per
worker, 1,024 fresh fights per round, three complete shuffled epochs, batch 64,
learning rate 0.0003 and value-loss weight 0.5. The default plan is ten rounds.
Training seeds start at 4,000,000 and advance by 10,000 per round. Each round
trains on that round's complete collection, with no dropped tail. Adam state and
RNG continue across rounds. The learner collects subsequent rounds even if it
does not become champion.

Champion selection uses the same 296 frozen validation recipes with the same
500 ms AlphaZero search. Promotion requires the paired V7 utility gain's
bootstrap 95% interval lower bound to exceed zero. This entry point does not
change the older `all_runner` CLI's four-worker admission limit; the generic
backend now supports up to eight workers for this dedicated entry point.

## Startup check performed on 2026-10-20

Run directory: `output/az_self_evolve1024_e3_500ms_w8_20261020`.

The runner was launched with `--verify-and-stop`, completed the first 16-fight
shard using eight workers, verified a real optimizer update and checkpoint
reload, then exited. The launcher and runner exited and no NativeWorker
process remained.

- 16/16 fights passed strict validation; zero contract rejections.
- 323 decision rows, including 54 forced rows.
- 10 wins, 5 deaths and 1 approved V7 time-limit truncation.
- Mean simulations per searched decision: 349.2602.
- Mean backup depth: 4.0619.
- One diagnostic update on 64 real collected rows; finite loss 1.27195.
- Parameters changed, and the reloaded checkpoint matched the updated model.
- **Formal updates: 0**. Initial learner and champion remain byte-identical to
  published candidate SHA256
  `9603642088b8a926abc61ab95de1080c69e15cd4194f7fab8866aa1b9ff98b13`.

The diagnostic update lives in `run/iteration-000/startup-check.pt` and is never
used for formal training. Collection is permanently divided into 16-fight
shards, so these 16 cached fights retain the same identity on resume; the
remaining collection is 1,008 fights. The full 1,024-fight training and validation
cycle has **not** been executed in this startup check. This small sample is not
a win-rate or scaling benchmark.

Evidence: [startup-check.json](../experiments/az_self_evolution1024_w8/startup-check.json).
Progress: `output/az_self_evolve1024_e3_500ms_w8_20261020/progress.json`.
The top-level progress is authoritative; `active_shard` is a periodic heartbeat
snapshot and can lag the final completed-fight count.

## Clean-checkout deployment verification

After adding the vendored native sources and portable setup, the staged Git
contents were exported to `output/portable_clean_checkout_20261020`. No unstaged
Python changes or existing native binaries were used. This exposed and fixed
legacy config paths, a working-directory-dependent card-reference read, and an
unnecessary Windows .NET Framework 4.8 MemoryCleaner build dependency.

The isolated ExportRelease build then succeeded in
`output/portable_buildcheck2_20261020`. Its new frozen entry point completed
another 16-fight, eight-worker startup check and exited automatically:
323 rows, 271 searched decisions, zero contract rejections, one approved
time-limit truncation, 342.7675 simulations/decision and 4.0534 mean backup depth.
The separate diagnostic update changed weights, produced finite loss 1.28471,
and reloaded exactly. Formal updates remain zero; no champion was promoted.
Both original and deployment-check caches remain on disk.

[Clean-checkout startup evidence](../experiments/az_self_evolution1024_w8/clean-checkout-startup.json)
is the evidence for the newly packaged build path. This is a **Windows**
execution; Linux source branches and deployment instructions are provided,
but Linux game ABI and native execution have not been empirically validated.
The updated runner also refreshes its final shard snapshot synchronously.

Across the six relevant test modules, 94 unique tests passed in the clean
checkout: 68 passed initially; 26 legacy-path failures passed after redirecting
the two example configs to the vendored native source. These are separate from
the initial startup check's earlier 90-test verification.

Regression verification covered 90 unique tests across the new runner helpers,
full-epoch optimizer/resume tests, native schema, cache, backend and leaf tests.
The initial run found four old assertions expecting a four-worker cap; after
updating the boundary to nine, all 18 affected cache/runner/epoch tests passed.

## Preparation and resume

Preparation now copies the vendored all-node native source from `sts2-native/`
and freezes Python sources into a new experiment directory, then builds the
isolated runtime against explicit game/RitsuLib paths. The runner itself never
builds a DLL and rejects runtime, source, model, dependency or configuration
identity changes on resume. The first startup check above used the existing
audited runtime before this portable preparation path was added; its frozen
runner remains unchanged. See the root README for Linux deployment limitations.

Run these commands from `sts2-rl-agent` to prepare a **new** directory:

```powershell
.\.venv-az\Scripts\python.exe scripts/prepare_native_az_self_evolution.py `
  --out output/NEW_RUN_NAME `
  --game 'D:/Steam/steamapps/common/Slay the Spire 2' `
  --ritsu 'D:/Steam/steamapps/workshop/content/2868840/3747602295' `
  --initial models/epoch1024_e3_500ms/candidate.pt
```

The existing run is deliberately stopped. To continue its formal plan:

```powershell
$runBase = (Resolve-Path output/az_self_evolve1024_e3_500ms_w8_20261020).Path
$stamp = Get-Date -Format yyyyMMdd_HHmmss
$env:PYTHONUTF8 = '1'
Start-Process -WindowStyle Hidden `
  -FilePath (Resolve-Path .venv-az/Scripts/python.exe).Path `
  -ArgumentList @('-u', "$runBase/python/scripts/run_native_az_self_evolution.py",
                  '--experiment', $runBase, '--resume') `
  -RedirectStandardOutput "$runBase/resume-$stamp.stdout.log" `
  -RedirectStandardError "$runBase/resume-$stamp.stderr.log"
```

Use the frozen runner under the experiment's `python/` directory. No periodic
monitoring task was created. Prior experiment caches, model checkpoints and
champion weights remain untouched.
