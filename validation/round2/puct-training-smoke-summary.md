# Native port v2: bounded PUCT training smoke

- Engine SHA: `212402640efd753944306ece0bad85913d07cb3be33f448bb17651a2636cda1a`.
- Public schema 11, combat action schema 10, ArmG feature version 3.
- Explicitly migrated old ArmG weights to `validation/weights/armg-native-port-v2-init.pt`.
  The source is unchanged; migration starts at zero target-environment games.
- Configuration: 8 simulations per non-forced combat root, no floor increment,
  one worker, frozen random **untrained** combat policy prior, no website prior,
  oracle simulator information. This does not reproduce the original private
  combat checkpoint or website-prior configuration.

## Actual result

| Split | Games | Completed | Mean floor | Search roots | Simulations | Errors / cutoffs |
|---|---:|---:|---:|---:|---:|---:|
| Training | 2 | 2 | 13.5 | 155 | 1240 | 0 / 0 |
| Validation | 1 | 1 | 17 | 133 | 1064 | 0 / 0 |

All three games ended in death. There were no cycle recoveries. The two training
games produced one optimizer update; the six parameter tensors changed, with a
maximum absolute difference of approximately 0.0003. Every Adam state records
step 1. The final checkpoint records exactly two target-environment training
games; the validation game is not counted as training.

Strict loading of the final ArmG checkpoint and the frozen combat-prior
checkpoint passed against the exact current engine contract. The inherited
source migration chain is preserved. Evidence is in
`puct-training-smoke-audit.json`; `audit_training_smoke.py` can rerun the artifact
checks without playing or training.

The first attempt (`puct-training-smoke`) stopped before training because an
old classification guard required observation version 10. The corrected
collector uses the checked v11 public native combat flags, validates boss
consistency and elite/boss exclusivity, and retains the original failure log.
The successful run is in `puct-training-smoke-fixed`.

This is a pipeline test, not evidence of model strength or complete native-rule
parity. No additional training or deployment was performed.
