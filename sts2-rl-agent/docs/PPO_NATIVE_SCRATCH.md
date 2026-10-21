# Native scratch PPO

This is an independent PPO-Clip experiment using the existing native-property XS
Transformer, initialized randomly with a fresh AdamW optimizer. It does not load
an AlphaZero checkpoint or train on MCTS labels. The original self-evolution
experiment remains paused.

`prepare_native_ppo.py --tier S` selects the versioned S architecture. The native
inference service reads the checkpoint tier and still validates its full
configuration/schema; PPO initialization and recovery use the configured tier.
XS has 4 layers, width128, 4 heads and 3,023,106 parameters; S has 6 layers,
width256, 8 heads and 9,460,738 parameters. They cannot share weight tensors.
`--reuse-runtime` copies an audited native runtime into the new experiment after
checking dependencies and worker-source compatibility, without rebuilding shared
DLLs. The S trial in `output/ppo_s_2048_20261021` uses 16 rollouts (2048 battles),
permanent checkpoints every512 battles, then evaluates the final model on the
same296 validation recipes. Original XS training remains paused.

## Collection and objective

- Eight native workers, two fights per worker invocation, 128 complete bounded
  episodes per on-policy rollout. Freeze the behavior checkpoint for the entire
  rollout; finish collection before updating. Collect new episodes after updating.
- Categorical sampling from legal network probabilities, independent RNG derived
  from recipe seed and decision number. No MCTS, Dirichlet noise or greedy action
  substitution. The legacy `budget_ms=500` transport field remains for ABI and
  cache validation; **there are zero simulations and no 500ms search wait**.
- Preserve all existing live/projected features, root, continuation, selector and
  endpoint checks. Any contract error stops collection; no skipped trajectories.
- Record normalized behavior probabilities, chosen-action log probability, value,
  random uniform, exact action keys and model SHA. Recompute every probability
  and value with the frozen model before training, including after resume.
- V7 payoff appears only at the final transition. The 40-turn/100-decision limit
  defines the same scored finite horizon as earlier experiments. Keep
  `terminationReason=time_limit`, `complete=false` and the cutoff data. The payoff
  replaces, rather than adds to, a continuation bootstrap.
- GAE gamma=1, lambda=.95; normalize advantages over nonforced choices. Forced
  decisions remain in trajectories and value training, but not policy/entropy
  averages.
- Up to three epochs per rollout, shuffled once per epoch, batch64/microbatch16,
  no dropped tail. Clip=.2, value-MSE weight=.5, entropy weight=.01,
  learning rate=.0003, AdamW weight decay=0, gradient norm limit=.5.
- Stop further updates on this rollout when a minibatch's approximate KL exceeds
  .03 before its optimizer step. Log both planned and actual updates through
  per-batch metrics; this is not an equal-update-count AlphaZero ablation.

Implementation follows [PPO-Clip](https://spinningup.openai.com/en/latest/algorithms/ppo.html),
with a shared actor/critic trunk and the existing finite-horizon V7 objective.
Scratch initialization differs from the pretrained AlphaZero experiments, so
their final scores alone cannot isolate the effect of algorithm choice.

## Recovery and artifacts

- `progress.json`: five-second updates with battles completed/trained, cycle,
  phase, gradient updates, worker count and latest batch wins/V7.
- `latest.pt`: full optimizer, Torch RNG, batch cursor and dataset identity after
  every optimizer boundary; overwritten atomically. Recovery revalidates cached
  trajectories and their behavior model before consuming them.
- `initial.pt`: untouched random initialization.
- `behavior/NNNNNN.pt`: immutable behavior weights for every rollout.
- `checkpoints/battles-000000512.pt`, etc.: permanent post-update recovery
  checkpoints every **512 trained battles**. No checkpoint/cache pruning.
- `cache/`: every original native trajectory, job and log retained.
- `batches/`: full PPO metrics and collection outcomes for each rollout.
- Create `STOP` in the experiment directory to pause at a safe boundary. Active
  collection completes its rollout before pausing the update loop. Remove STOP
  and add `--resume` to restart; never start a second runner in the same directory.

Prepare with `scripts/prepare_native_ppo.py`, providing a fresh `--out`, audited
`--native-template`, frozen `--protocol`, game/RitsuLib locations and dotnet.
It copies audited simulation sources into the new directory and compiles there,
then freezes Python sources. It does not rebuild a shared active runtime.

Run the frozen entry:

```powershell
.\.venv-az\Scripts\python.exe -u <experiment>\python\scripts\run_native_ppo.py `
  --experiment <experiment>
# Recovery:
.\.venv-az\Scripts\python.exe -u <experiment>\python\scripts\run_native_ppo.py `
  --experiment <experiment> --resume
```

No total episode limit is imposed by default. `--max-cycles` is available for
bounded engineering checks. No scheduled monitor or automatic model promotion.

## Verification

`tests/test_native_ppo.py` checks advantage boundaries, signed clipping, variable
action masks, behavior/model mismatch rejection, high-KL no-op, every-row epoch
coverage, native sampled-record corruption and exact optimizer-resume equivalence.
The real smoke under `output/ppo_scratch_20261021/smoke` runs collect/update cycles
and then resumes in a fresh process; it is separate from the formal random model.


### S full-rollout KL comparison (2026-10-21)

`kl_scope=rollout` evaluates the existing sampled-action k3 KL estimator over every non-forced decision in the current rollout before each optimizer step. Evaluation is microbatched, weighted by decision count, uses no gradients, and restores model mode. The threshold remains 0.03; minibatch KL is logged but does not gate this mode. Missing full-rollout rows and nonfinite KL fail explicitly. Default `minibatch` preserves the original algorithm. Resume recomputes KL from the restored model and the same strictly validated rollout; optimizer/RNG checkpoints remain intact.

The independent S comparison uses learning rate 1e-4, random initialization with seed 20261021, 8 collection workers, 128 battles per rollout, and up to 3 epochs. `scripts/run_native_ppo_milestones.py --experiment PATH` runs to 2048 battles, retaining permanent checkpoints and performing strict greedy evaluation on the same 296 recipes after 512/1024/1536/2048 battles. Evaluation directories must be prepared with their own config/protocol/expected and run.py. `milestone-progress.json` combines training and evaluation status; restarting the same command resumes retained checkpoints/caches. Full-rollout scans increase CPU work. This is a joint learning-rate/KL-scope intervention, not an attribution to either change individually.

Validation: 51 targeted PPO/cache/generic tests passed, including full-rollout weighting, forced-row exclusion, outlier-vs-global stopping and exact resumed updates for XS/S. Independent native S smoke uses the copied Surprise-fixed runtime; no shared DLL rebuild.


KL interval change (2026-10-21): after 189 updates / 256 trained battles, resume the retained third rollout using post-update full-rollout KL every 16 applied updates and at every epoch end (coincident boundaries check once). The counter is per rollout and does not reset at epoch boundaries. An over-threshold check keeps the completed update and stops remaining rollout updates. Metrics and cursor are checkpointed together after the check; a crash before persistence replays from the previous saved optimizer/RNG state. The first 256 battles used per-update pre-checks, so this is a continued mixed-schedule experiment, not a fresh interval-16 run. Migration audit and complete original caches/Python/recovery state are in before-kl-interval16/. 28 targeted tests passed, including update-16 resume equivalence and epoch-boundary scheduling.


## V7 potential control (2026-10-21)

# S PPO: V7 potential reward, coefficient 0.1

Independent random S initialization (seed 20261021); 2048 sampled-policy battles, 8 collection workers. Each 128-battle rollout receives up to 3 PPO epochs. Learning rate 0.0001; full-rollout sampled-action k3 KL checked every 16 applied updates and each epoch end; threshold 0.03. Permanent checkpoints and greedy frozen-296 evaluation at 512, 1024, 1536, 2048 battles. Evaluation uses 4 workers as in the baseline. Pipeline stops after the 2048 evaluation.

Phi(s) is the existing V7 time-limit utility at the checked decision state, with original battle entry HP, the existing finite primary enemy progress ledger and current incoming risk. Pending choice uses canonical cutoff risk=1. Raw trajectories carry pre/post facts; Python recomputes the score and requires endpoint/HP/adjacent-state consistency. Native continuation, behavior model, source provenance and cache checks remain strict.

Nonfinal reward = 0.1 * (Phi(next)-Phi(current)). Final reward = unchanged V7 win/death/time_limit reward - 0.1*Phi(current). Terminal potential is zero, including the finite time_limit endpoint. Gamma=1, so episode reward telescopes to original V7 - 0.1*Phi(initial); cycles cannot create net shaping return. Do not add absolute V7 scores each step. Validation reports only original V7 and wins.

Architecture and tanh value head are unchanged. The critic is trained on shaped GAE targets, not analytically shifted predictions (which would cancel the intervention in TD errors). Targets are NOT clipped; values outside [-1,1] are counted in batch reports. This small range mismatch is an explicit limitation, not a reason to change architecture in this control.

57 regression tests passed. Four real sampled native battles (51 decisions, one win and three deaths) passed all parity, potential recomputation and telescoping checks. Actual shaped PPO update passed and checkpoint/optimizer/RNG restoration reproduced the next update bit for bit. Smoke random initialization matched the prior S baseline weights; smoke data and weights are isolated and are NOT reused by formal training. Synthetic tests cover time_limit payoff and terminal cancellation. No claim that all old trajectories were rerun.

Runtime: native/artifacts/native-host; frozen Python: python/. All previous caches/checkpoints remain untouched. Formal training starts from fresh random weights and optimizer. Keep latest.pt, behavior checkpoints, milestone checkpoints and all battle caches.

Concise progress: milestone-progress.json (updates every 5 seconds). Detailed progress: progress.json; full pipeline errors: pipeline-detail.json and timestamped stderr logs.


## 2026-10-21: pending selector maximum-HP evidence repair

Seed 8001450 / SCROLLS_OF_BITING_NORMAL, EndTurn followed by STRATAGEM: actual maximum HP was 64 at decision 25, while NativeMctsState pending description intentionally retained the pre-action snapshot (74). GenericCollection potential evidence incorrectly read this stale maximum HP, although native policy observation correctly projected the selector state. Fix: capture HP and maximum HP from the live checked endpoint; also use live maximum HP for the finite cutoff outcome metadata. No simulation continuation or PPO objective change. Strict potential validation remains enabled.

Fresh isolated native-potential-maxhp runtime reproduced all 33 decisions with the same behavior checkpoint. Actions, observations, probabilities, values and rewards match; only potentialAfter at 24 and potentialBefore at 25 changed maxHp 74 -> 64. Regression fixture native_ppo_pending_maxhp_v1.json.gz rejects the original stale metadata. 58 relevant tests passed. before-potential-maxhp/migration.json records full cache backup, 1456 training records and 592 validation records revalidated, only the failed battle reexecuted. Model weights, optimizer, RNG, counters, permanent checkpoints and completed evaluation files preserved. Old runtime retained; no shared DLL rebuilt.
