# A10 ArmG PPO

PPO replaces the REINFORCE optimizer in a **new training entry point**:
`deployment.train_armg_a10_ppo`. The old REINFORCE run is stopped and its
checkpoints/results remain unchanged. Implementing PPO does not launch a new
10,000-game experiment.

## Environment and reward

- A10, public non-combat observations only.
- Pure oracle MCTS, no combat policy network or PUCT prior.
- Per combat decision: `5000 + 500*(max(floor,1)-1)`, elite `+5000`, boss `+10000`.
- Terminal total: `floor/20 + n*(n+1)/2 + 0.1*defeated_elites`, where `n` is
  the number of actual boss victories (0–4). Elite bonus is independent of act.
- Cumulative-reward differences between non-combat decisions become transition
  rewards. Intervening forced choices/combat outcomes remain in the trajectory.
  The final transition includes the terminal remainder. The collector checks
  that transition rewards sum to the exact episode total.
- Completed episodes only. Errors and truncations abort the batch rather than
  treating an incomplete rollout as a terminal loss.

## PPO

| Setting | Default |
|---|---:|
| Actor | Existing ArmG candidate scorer, 128×128 |
| Critic | Separate state-only MLP, 128×128 |
| Actor / critic learning rates | 0.0003 / 0.001 |
| Games per rollout | 32 |
| Epochs / minibatch decisions | 4 / 128 |
| Probability-ratio clip | 0.2 |
| Target KL | 0.02 (stop further updates above 1.5× threshold) |
| Gamma / GAE lambda | 1.0 / 0.95 |
| Value coefficient / entropy coefficient | 0.5 / 0.01 |
| Maximum global gradient norm | 0.5 |
| Training games / CPU workers | 10000 / 8 |
| Validation | 50 greedy games every 640 training games and at completion |

Each trajectory stores the sampled action's old log probability, full old
legal-action distribution, old state value, chosen action and legal candidates.
GAE is computed independently per complete episode with terminal bootstrap zero.
Advantages are normalized across actor-eligible decisions in the current rollout.
Single-action and safety-forced decisions train only the critic, not the actor
or website regularizer. Padding never participates in the action distribution.
Old-rollout probabilities/advantages/targets remain frozen throughout PPO epochs.

PPO checks that the actor matches the behavior policy before updating. Exact
categorical KL is checked on each minibatch before an update and on the complete
rollout after each epoch. This is an early-stop guard, not a hard guarantee that
the final KL cannot overshoot the threshold.

Website prior weight remains `0.2*max(0,1-N/10000)`, with `N` the completed
training games before the rollout update. Policy loss is now a mean over
actor-eligible decisions; website KL is a mean over eligible card decisions.
The coefficient therefore does not imply the same gradient ratio as the old
per-game-summed REINFORCE objective. The prior participates in the same clipped
gradient update and KL monitoring; it does not run as an unchecked extra step.

Metrics include raw reward components, policy/value losses, exact KL,
clip fraction, entropy, explained variance, gradient norm, early stopping and
the actual prior weight. `progress.json` and Chinese `progress.md` update from
the trainer while sampling (five-second polling), with no separate watcher
required. Best-model selection remains mean validation floor for continuity.

## Launch when requested

The active run was paused at 2560 saved games to add action rewards. Its
`latest.pt` and `config.json` now use `floor20-boss-elite01-actions`:
`floor/20 + bosses*(bosses+1)/2 + 0.1*elite_wins + 0.05*campfire_upgrades + 0.02*shop_removals`.
Only successfully executed campfire upgrades and shop removals count. These
bonuses enter the PPO transition rewards as well as episode summaries.
Actor, critic, optimizer and training game count are retained. Earlier metrics
remain under the old formula; backups are named `pre_action_rewards.*`.
The prepared resume arguments are in the run's `resume_action_rewards.json`;
they include `--reward-mode floor20-boss-elite01-actions --resume .../latest.pt`.
Training remains stopped until requested. The example below describes the
original fresh-run defaults, not the modified run's resume command.

From `D:\sts2_datacollection\sts2` in PowerShell:

```powershell
$env:STS2_PRIOR_PYD='D:\sts2_datacollection\sts2\.scratch\potion-module\sts2_sim.cp312-win_amd64.pyd'
$env:OMP_NUM_THREADS='1'
$env:MKL_NUM_THREADS='1'
$env:PYTHONUTF8='1'
.venv/Scripts/python.exe -u -m deployment.train_armg_a10_ppo --out-dir runs/armg_a10_ppo_floor20_elite01_20261031 --data-dir runs/armg_spire_wr50_prior_20261030/data
```

New runs initialize actor and critic randomly with a fresh optimizer. Resume
requires `--resume <same-output-directory>/latest.pt` and identical settings.
PPO checkpoints contain actor, critic, both Adam parameter groups, RNG states
and game count. REINFORCE checkpoints are intentionally rejected as incompatible;
their optimizer states must not be passed off as PPO state. Existing actor-only
evaluation loaders also cannot directly load this combined checkpoint; the new
trainer's validation uses its actor directly.

Tests: `tests/test_armg_ppo.py`, plus existing ArmG collection/reward/progress
tests. Real simulator smoke-test outputs are isolated under
`.scratch/ppo-smoke-20261031` (4 training games and 2 validation games), not used
as evidence of learning improvement.

## Fixed-seed fresh PPO pilot (2026-10-31)

`--fixed-game-seed 10600000` repeats the same A10 game seed for both training
and evaluation. Actor, critic and optimizer initialize from scratch; the existing
website prior remains enabled. Policy sampling and combat search RNG are independent
between training episodes. Evaluation reuses a fixed panel of search RNG seeds,
including an initial random-policy baseline. These evaluations measure single-seed
learning, not generalization.

Active pilot: `runs/armg_a10_ppo_fixed10600000_fresh_20261031`, 512 games,
16 games per PPO rollout, 4 CPU workers, 8 greedy evaluation episodes before
training and every 64 games. Reward is `floor20-boss-elite01-actions-elo`:
`floor/20 + bosses*(bosses+1)/2 + 0.1*elites + 0.05*upgrades + 0.02*removals + terminal_deck_mean_elo/5000`.
MCTS budgets and website-prior schedule retain existing defaults.
Launch arguments/PID: `runs/fixed10600000_20261031.launch.json`.
Live status: run directory `progress.json`; baseline and PPO statistics:
`metrics.jsonl`. Existing multi-seed training continues independently.
