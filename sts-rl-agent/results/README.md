# Reproducible result artifacts

This directory keeps only small, auditable experiment summaries. Raw trajectories,
videos, TensorBoard runs, and intermediate checkpoints are intentionally excluded.

## Metrics

- `armG_track_G128x128*.jsonl`: model-free non-combat policy learning curves.
- `armG_track_G256x256.jsonl`: larger-capacity comparison.
- `armB_track_*.jsonl`: negative combat-distillation experiments.
- `mcts_budget.csv`: fixed 50-seed search-budget comparison.

## Figures

Regenerate the Arm G curves with:

```bash
python eval/plot_armG.py G128x128
python eval/plot_armG.py G128x128_15k
python eval/plot_armG.py G256x256
```

The repeatedly inspected 50-seed set is a validation/evaluation set, not a pristine
one-shot final test set. See `docs/evaluation.md` for the evidence boundary.
