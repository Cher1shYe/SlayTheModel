# Evaluation protocol and the seed-leakage lesson

## The early mistake

Early LLM-memory experiments used too few seeds and allowed experience accumulated on
evaluation seeds to influence later decisions on those same seeds. Results improved,
but the loop was learning the exam as well as the task. The local history called this
iteration `learn-on-test`.

Six archived runs averaged 11.83 floors in the naive version and 13.17 floors in the
learn-on-test version. That difference is historical debugging evidence, not a valid
generalization claim.

## The corrected policy-training loop

- Generate nearly unlimited random training seeds.
- Explicitly exclude the fixed 50 evaluation seeds from training.
- Evaluate greedily at fixed intervals.
- Save every evaluation checkpoint and track the best one.
- Compare against baselines at the same combat-search budget.

Because the fixed 50 seeds were repeatedly used for model and checkpoint selection,
they are best described as a held-out validation/evaluation set. A stricter future
protocol should add a third, untouched final-test seed set and repeat each configuration
across multiple random initializations.

## Public reporting boundary

- A single real-Steam run demonstrates integration and gives an interpretable case.
- The 50-seed simulator evaluation is the comparative performance evidence.
- Neither is a claim of statistical significance or state of the art.
