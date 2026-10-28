# Fixed-seed evaluation

Evaluation is run only through `deployment/evaluate.py` (or
`deployment/selfplay_compare.py`), never through ad-hoc smoke loops. All
strategies in one invocation see the same seed list.

## Protocol

- **Splits.** Disjoint fixed ranges in `agent/policy.py`: train
  `10,000,000+`, validation `20,000,000+`, test `30,000,000+`. Test seeds are
  used only for the final report; model selection uses validation seeds.
- **Termination.** A run ends at `RUN_OVER` (victory or death). A step cap
  produces `truncated`; a rejected action produces `error`. Both count as
  abnormal and are never trained on. Terminal reward is the run result, not a
  progress proxy.
- **Metrics.** Win rate with Wilson 95% CI, number of runs reaching acts 1/2/3,
  mean final floor, mean HP loss (`max_hp - hp`), abnormal rate.
- **Strategies.**
  - `heuristic`: deterministic 1-ply combat policy plus heuristic map, shop,
    event, rest, treasure and card-reward choices.
  - `network`: combat policy-head argmax plus card-model choices.
  - `network_combat` / `network_cards`: one learned head at a time, the other
    screen policy heuristic, to attribute any difference.
  - `search`: root PUCT with network priors and greedy rollouts over the true
    state (**oracle**, not player-usable).
  - `search_resampled`: the same search with draw/discard order and the future
    RNG stream re-drawn per simulation (**player-usable**).
- Search visits each root action once in descending-prior order before PUCT;
  without that pass a peaked network prior collapses a small simulation budget
  onto one action. The value head is not used inside search.
- Checkpoints record observation/action schema versions and parameter shapes;
  mismatched files are rejected rather than loaded.

## Results: validation split, 300 seeds (v3 models)

Command:

```bash
python -m deployment.evaluate --split val --seeds 300 \
    --strategies heuristic,network,network_combat,network_cards,search_resampled \
    --simulations 16 --tag attrib \
    --combat-checkpoint runs/v3/selfplay/combat.pt \
    --card-checkpoint runs/v3/card/card.pt
```

| Strategy | Win rate | 95% CI | Act 1/2/3 | Mean floor | HP loss | Abnormal |
| --- | --- | --- | --- | --- | --- | --- |
| heuristic | 11.33% | 8.22–15.42% | 300/190/79 | 25.81 | 79.78 | 0 |
| network (both heads) | 0.33% | 0.06–1.86% | 300/65/6 | 15.71 | 83.08 | 0 |
| network combat only | 0.00% | 0.00–1.26% | 300/39/2 | 13.83 | 83.10 | 0 |
| network cards only | 9.67% | 6.81–13.54% | 300/213/83 | 28.01 | 81.42 | 0 |
| search, resampled, 16 sims | 0.33% | 0.06–1.86% | 300/66/7 | 15.82 | 83.00 | 0 |

Interpretation: the card model is statistically comparable to the heuristic
card policy (overlapping CIs; higher mean floor and act-3 reach, slightly lower
win rate). The v3 combat network is clearly worse than the heuristic combat
policy, and 16-simulation search shares that weakness. This is a negative
result for the v3 combat model, not evidence of learned combat skill. The v4
and v4b combat models below are trained with the corrected exploration pass.

## Combat-network retrain (v4)

The v3 self-play targets came from search runs whose prior-driven exploration
had collapsed: at 16 simulations the visit target was effectively one-hot on
the network's own argmax, so self-play could not improve on it. After the
initialising-visit fix, a from-scratch 120-iteration run (16 episodes/iteration,
16 simulations, visit targets) produced `runs/v4/selfplay/combat.pt`.

Validation, 100 seeds, v3 card model, 16 simulations:

| Strategy | Win rate | 95% CI | Act 1/2/3 | Mean floor | HP loss |
| --- | --- | --- | --- | --- | --- |
| network (v4 combat) | 1.00% | 0.18–5.45% | 100/55/6 | 21.4 | 84.27 |
| search, visits, resampled | 0.00% | 0.00–3.70% | 100/62/8 | 22.6 | 85.62 |
| search, mean-value, resampled | 2.00% | 0.55–7.00% | 100/49/9 | 21.21 | 83.76 |

The retrain is a large improvement over v3 (mean floor 15.7 → 21.4, act-2 reach
21.7% → 55%) but still below the heuristic (11.33% over 300 seeds). Root search
at 16 simulations does not reliably improve on the pure policy head; the CI on
100 seeds is too wide to separate the variants. This remains a negative result
for learned combat strength, not evidence of parity with the baseline.

## Value-target retrain (v4b)

Visit targets at 16 simulations are nearly uniform over ~12 actions, so a
second run used the mean rollout value per root action as a soft target
(temperature 0.5, 32 simulations, 50 completed iterations before its final
evaluation). This is policy improvement from one-step lookahead: the target
prefers actions whose greedy rollout actually won with more HP.

Validation, 100 seeds, v3 card model, 16 simulations:

| Strategy | Win rate | 95% CI | Act 1/2/3 | Mean floor | HP loss |
| --- | --- | --- | --- | --- | --- |
| network (v4b combat) | 1.00% | 0.18–5.45% | 100/54/5 | 20.86 | 84.14 |
| search, visits, resampled | 5.00% | 2.15–11.18% | 100/61/16 | 23.95 | 82.71 |
| search, mean-value, resampled | 2.00% | 0.55–7.00% | 100/58/16 | 23.76 | 84.89 |

For the same v4b checkpoint, search raises win rate and floor over the pure
policy head; the CIs overlap, so this is a direction, not a proven effect.
v4b search also beats v4 search on the same seeds (5% vs 0%, floor 23.95 vs
22.60). The 1000-seed test report uses v4b for both `network` and
`search_resampled`, with the v3 card model, so the network-versus-search
comparison holds the checkpoint fixed.

## Final test split, 1000 seeds

Command:

```bash
python -m deployment.evaluate --split test --seeds 1000 \
    --strategies heuristic,network,network_cards,search_resampled \
    --simulations 16 --tag final-test \
    --combat-checkpoint runs/v4b/selfplay/combat.pt \
    --card-checkpoint runs/v3/card/card.pt
```

Test seeds are `30,000,000..30,000,999`; none were used for training or model
selection. `network` and `search_resampled` share the v4b combat checkpoint and
the v3 card checkpoint; `network_cards` uses the heuristic combat policy with
the v3 card model.

| Strategy | Win rate | 95% CI | Act 1/2/3 | Mean floor | HP loss | Abnormal | Runs/s |
| --- | --- | --- | --- | --- | --- | --- | --- |
| heuristic | 10.20% | 8.47–12.23% | 1000/640/296 | 26.25 | 81.17 | 0 | 34.75 |
| network (v4b combat + v3 cards) | 1.50% | 0.91–2.46% | 1000/504/90 | 20.88 | 84.77 | 0 | 6.89 |
| network cards only (heuristic combat) | 10.90% | 9.12–12.98% | 1000/716/326 | 28.45 | 82.04 | 0 | 10.38 |
| search, resampled, 16 sims (v4b combat) | 4.80% | 3.64–6.31% | 1000/618/181 | 24.42 | 84.38 | 0 | 2.22 |

Reading the result:

- The **card model is not worse than the heuristic card policy**: win CIs
  overlap and it reaches act 3 more often (326 vs 296) with a higher mean floor
  (28.45 vs 26.25). It is a usable component, not a demonstrated improvement.
- The **combat model is clearly weaker than the heuristic combat policy**:
  1.5% vs 10.2%, with non-overlapping CIs. More self-play data or a stronger
  search target is required before claiming learned combat skill.
- **Root search improves the same combat checkpoint** from 1.5% to 4.8%
  (non-overlapping CIs), so the search integration works, but it does not close
  the gap to the heuristic. Search uses 16 simulations and greedy rollouts, not
  a full MCTS with value-head leaves.
- All 4000 runs terminated normally (`abnormal_rate = 0`); no truncated or
  errored episodes were counted.
- These are negative results for the learned combat policy and are reported as
  such. They do not satisfy the stronger criterion “the current model stably
  beats the baseline” from the review; that remains open.
