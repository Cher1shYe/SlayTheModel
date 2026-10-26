# Training lessons

## Capacity sweep, not a scaling law

The project compared `[128,128]` and `[256,256]` MLPs. The smaller model reached a
held-out peak of 39.52 floors in its 8k-game run. The larger model finished at train
39.49 / eval 37.56. Bigger was not automatically better for this task and data loop.

Two model sizes are not enough to establish a scaling law. This is a capacity sweep and
pilot scaling experiment. A proper scaling study would vary model size, data volume,
compute, and random initialization over a much wider range and fit uncertainty-aware
held-out trends.

## Training longer is not the same as improving

In the 15k-game `[128,128]` run:

- game 9,504: held-out evaluation peaked at 41.34;
- game 13,504: train was 39.08 while eval fell to 36.78;
- game 15,000: eval recovered to 39.24 but did not exceed the earlier peak.

The train rollouts sampled actions while evaluation used a greedy policy, so their raw
gap is not a textbook generalization gap. The robust signal is that continued training
stopped producing durable held-out improvements. This motivates frequent evaluation,
checkpointing, and early stopping.

## Learning and planning are different computation modes

The non-combat scorer is a model-free reactive policy: training amortizes experience
into weights, then one forward pass ranks the legal actions.

Combat uses model-based online planning: MCTS spends compute at decision time to
expand future card draws, enemy actions, and turn sequences. AlphaZero-style systems
combine these modes with a policy/value network, MCTS, and self-play. The negative
combat experiments in this repository did not complete that full loop.
