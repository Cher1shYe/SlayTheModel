# Checkpoints for the native rules port

This workspace retains the fast C++ simulator. Its identity is
`native-41cef1ea-port-v1`, targeting game DLL SHA-256
`9cb4f1ad8c9f284aa8fec3122ffd6d780bbf543d875c817abdd12ff63fbf12b4`.
`NATIVE_PARITY_COMPLETE` remains **false**.

New checkpoints bind the loaded extension's SHA-256, C++ source/generated
content digest, explicit ID maps, schema dimensions/formulas, and Python/C++
feature implementation digests. The source declarations are checked against
binding dimensions and exported IDs/counts. This identifies the environment;
it does not establish every feature mapping or native rule as correct.
Rebuild the extension after changing C++ sources. Do not change sources during
a training run. A different binary, including a platform-specific rebuild,
requires explicit migration rather than ordinary continuation.

Normal ArmG load, evaluation, warm start and resume reject another environment,
even when tensor shapes match. The combat-prior loader also checks this identity.
The existing live worker's strict hashes are not bypassed by this change.

## Explicit ArmG weight transfer

Run from this workspace with its freshly built extension. Inspect its identity:

```sh
python -c 'import json; from agent.engine_identity import current_engine_contract; print(json.dumps(current_engine_contract(), indent=2))'
```

For a legacy ArmG v1 checkpoint, the accepted source tree is the immutable
`be401e8` reference. Supply all three SHA-256 values explicitly:

```sh
python -m deployment.migrate_armg_weights \
  --source /absolute/path/to/old/latest.pt \
  --source-sha256 CHECKPOINT_SHA256 \
  --old-engine-sha256 OLD_CHECKPOINT_SETTINGS_SIMULATOR_SHA256 \
  --new-engine-sha256 CURRENT_EXTENSION_SHA256 \
  --source-tree /absolute/path/to/alphazero-be401e8 \
  --output /absolute/path/to/new/armg-initialization.pt
```

The source is never overwritten. The output records the source checkpoint and
environment hashes, source settings/progress as provenance, and **0 training
games in the target environment**. Optimizer, RNG and active progress fields
are absent. The old engine hash is checked against checkpoint metadata; this
does not reproduce or validate the original training environment.

ArmG feature v2 adds card/enchantment features for deck-grid kinds 6, 7 and 8.
Existing dimensions, IDs and the `grid_kind / 5` scale stay unchanged. This
explicit v1-to-v2 transfer is allowed only with the recorded source layout;
the new decisions still need training. Other layout changes are rejected.
For these new grids, the public run observation also uses the previously empty
first grid-card row's first two features for pending damage divided by 16 and
curse ID divided by `CardId::COUNT`. Existing grid kinds keep their old layout.

The output can be evaluated with the current ArmG loader or passed to
`agent.armg_train --init-checkpoint` to start a **new** training run. It cannot
be passed to `--resume`. The separate PUCT/site-prior full-continuation trainer
still requires a complete compatible training checkpoint, combat-prior model
and website data; this migration does not fabricate those assets or states.
No training or migration of the user's uploaded checkpoint is performed by
adding these interfaces.

## Round 2: native port v2 (public schema 11 / action schema 10)

ArmG feature version 3 keeps the candidate dimension (1297) and adds deck-card
encoding for new grid kinds 9–12. Its state dimension is now 16372. The explicit
migration accepts only the audited be401e8 v1 source or the immutable native
port v1 source backup. It preserves the old run segments, inserts each appended
boss identity separately, zero-initializes the new native-context columns, and
moves the unchanged action block after the larger state block. Existing IDs
must remain exact; only the reviewed appended encounter and enchantment IDs
are allowed. This preserves old-feature logits, not performance in new rules.

Normal loading and resume never accept the old environment hash. Transfer
creates a new `weights_only_migration` artifact, records the entire provenance
chain, and has zero games in the target environment. It contains no active
optimizer/RNG/progress. Unknown mappings are rejected.

### Complete PUCT training without unavailable private dependencies

The complete training entry point now also supports a declared new run:

```sh
STS2_PRIOR_PYD=/absolute/path/to/sts2_sim.extension python -m deployment.train_armg_puct_prior_rl \
  --fresh-init --init-checkpoint /absolute/path/to/current-migrated-armg.pt \
  --combat-prior-mode random --site-prior-mode disabled --prior-weight 0 \
  --out-dir /absolute/path/to/new-run --games 2 --batch-size 2 --workers 1 \
  --simulations 8 --floor-increment 0 --eval-every 2 --eval-runs 1
```

Omit `--init-checkpoint` to initialize ArmG randomly. The random combat prior is
saved separately, frozen during ArmG training, and marked untrained (zero games).
The website prior is disabled explicitly. This configuration is **not** a
reproduction of the colleague's trained combat prior or website-prior run.
`--prepare-only` writes initialization files without starting any episode or
optimizer update. To continue a prepared/run checkpoint, use the same settings
and `--resume` with its latest checkpoint; fresh initialization only loads
weights, never source optimizer/RNG/progress. Evaluation games are recorded
separately and are not training games.

The isolated bridge and its remaining unsupported choices are documented in
`bridge/README.md`; compilation is not evidence of an executed native UI game.
