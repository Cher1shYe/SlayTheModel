# Native policy/value experiments, 2026-10-20

This is a source/evidence archive of completed isolated experiments, not a new training launch. No checkpoints, fight caches, DLLs, or logs are included.

- `native-isolated.patch`: all-node joint policy/value search, pending-selector projection repairs, per-hit death processing, Minion Fatal and IronWave fixes, and branch-owned Reattach Fatal handling/tests.
- `native-patch-manifest.json`: exact before/after file hashes. The baseline is the frozen **four-arm** native snapshot at `output/mcts_three_arm_250ms_20261019_2250/native`, not an arbitrary Git checkout. Verify every baseline hash before applying; do not overwrite a newer native repository with this patch.
- `regression-evidence.json`: 12 successful strict replays, including the original IronWave/HandOfGreed/Volley failures and nine additional regressions. Final full continuation matched in every case. The Reattach test also passed branch-alive/dead, live HP divergence after capture, and parent/sibling/descendant isolation.
- `run_alphazero_comparison.py`: archived as `run_comparison.py` at the root of an isolated experiment with `python/`, `native/`, `models/`, config/protocol and verification evidence.
- `run_policy_comparison.py`: archived as `policy_only/run_comparison.py` within that experiment; reuses its frozen DLL/source without compiling.
- `verify_native_regressions.py`: archived diagnostic runner; expects the prior epoch experiment's retained fixtures at the documented sibling path. It builds only the new isolated runtime before testing.
- `results.json`: compact original result records without the per-update loss history.

These experiment drivers intentionally retain the original local directory layout and checksum guards. They are not portable one-command entry points; provision the named artifacts before use. The normal Python repository now supports explicit admission of bounded search validation and the joint policy/value inference operation. Strict endpoint, feature, action, reward, model and provenance validation remains enabled.

The source snapshot mixes Windows and Unix line endings. After verifying the baseline file hashes, use `git apply --check --ignore-space-change` followed by `git apply --ignore-space-change` from the native snapshot root. The patch applicability check passed against that exact baseline. The after hashes describe the tested original snapshot bytes; applying with different line endings may change byte hashes without changing source text.

## Results (296 paired frozen recipes)

| Decision method | Champion wins / V7 | Candidate wins / V7 |
|---|---|---|
| Pure policy argmax, no search | 193 (65.20%) / 0.277223 | 196 (66.22%) / 0.296511 |
| Root policy + mixed value, 500ms | 225 (76.01%) / 0.489178 | 238 (80.41%) / 0.575847 |
| All-node policy + pure model value, 500ms | 194 (65.54%) / 0.278235 | 236 (79.73%) / 0.559549 |

Candidate training: champion weight initialization, fresh optimizer, 1024 fights, 18,327 rows, three complete shuffled epochs, 861 updates, batch64 with final partial batches, learning rate **0.0003**. The earlier “0.003” task note was erroneous. No champion promotion.

Pure-policy paired V7 gain: +0.019289, bootstrap 95% CI [-0.041203, 0.080359]; 13 gained wins and 10 lost wins. No clear evidence of improved standalone policy performance. All-node search paired gain: +0.281314, CI [0.196170, 0.368321]; 45 gained wins and 3 lost wins. This supports improved search guidance, but does not isolate policy versus value causally. Shared representations and changes to the whole policy distribution can matter even with unchanged argmax.

Training caches spanned four audited simulator stages (399/39/367/219 fights). Preserved real trajectories passing strict checks do not certify every hypothetical old search branch. The before/after 500ms comparisons hold evaluation budget fixed; comparisons against older 250ms results also vary budget/runtime. Depth means meanBackupDepth, and simulation totals include terminal revisits.

Model SHA256:

- Champion: `b95195162750e188ecfad53d9eadcf730b18c097f60c6bc438ba5331a119d034`
- Candidate: `9603642088b8a926abc61ab95de1080c69e15cd4194f7fab8866aa1b9ff98b13`
