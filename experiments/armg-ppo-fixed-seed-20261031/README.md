# Fixed-seed A10 PPO experiment

This is a source overlay for the `alphazero` simulator at commit
`be401e8ba09ac58c9f3b01cf77e195f7122c8d0c`. It is kept separate from the
native-alignment WIP in this branch: their observation schemas and engine
identities differ. This overlay has not been ported to that engine.

## Apply

Create a separate clone at the pinned base, then copy the contents of `overlay/`
into its root (preserving subdirectories). Do not overlay the native-aligned
working copy or immutable reference directory. Install the base requirements,
build its simulator, and set `STS2_PRIOR_PYD` to the resulting extension.
The frozen website-prior data directory is also required; it contains
`cards.json`, `relics.json`, `potions.json`, `community.json`, and `manifest.json`.
Those data, local environments, binaries, logs and checkpoints are not included.
See `overlay/docs/armg-a10-ppo.md` for implementation and local run details.

From the prepared clone root:

```sh
python -u -m deployment.train_armg_a10_ppo --out-dir runs/fixed10600000 --data-dir /path/to/frozen-prior-data --games 512 --batch-size 16 --workers 4 --eval-every 64 --eval-runs 8 --fixed-game-seed 10600000 --seed 20261031 --reward-mode floor20-boss-elite01-actions-elo
```

Actor and critic start randomly, with a fresh optimizer. The website prior
remains enabled. Game seed is fixed; training policy/search RNGs vary, while
baseline and evaluation use the same fixed search RNG panel. Only noncombat
policy decisions are trained; combat uses existing pure oracle MCTS.

Reward: `floor/20 + bosses*(bosses+1)/2 + 0.1*elites + 0.05*upgrades + 0.02*removals + terminal_deck_mean_elo/5000`.

## Validation

On the original Windows simulator environment, the PPO and A10 reward suites
passed **37 tests**, including fixed-seed collection and interrupted/resumed
training equivalence. Eight initial greedy evaluation episodes completed
without errors/truncations: mean floor 11.75, reward 0.92106, win rate 0%.
The first 16 training games and PPO update completed successfully. These are
launch checks, not evidence of learning improvement or cross-seed generalization.

`manifest.json` records SHA-256 hashes of all ten uploaded source files.
