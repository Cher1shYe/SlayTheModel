# STS2 v0.111.0 simulator ABI findings

Pinned assembly SHA-256:
`9cb4f1ad8c9f284aa8fec3122ffd6d780bbf543d875c817abdd12ff63fbf12b4`.

These findings come from read-only ECMA-335 metadata inspection of the locally installed game assembly. The probe does not load or execute game code.

## State that is already serializable

- `SerializableRun` plus `RunState.FromSerializable` cover the persistent whole-run state.
- `RunRngSet.ToSerializable` and `LoadFromSerializable` preserve the independent future-determining RNG streams, including shuffle, monster AI, combat targets, card generation, map, rewards, potions, and relics.
- `SerializableRng` stores its counter and four internal state words.
- `CombatReplay` stores the serialized run at combat entry, the deterministic input event stream, player-choice results, action/hook/checksum counters, and checksum checkpoints.

## Full combat snapshot available for validation

`NetFullCombatState.FromRun` creates a public, packet-serializable description of the current combat. It includes:

- all combat creatures, HP, block, powers, monster IDs, and player IDs;
- every player, combat phase, turn number, energy, stars, gold, relics, potions, orbs, and player RNG;
- every ordered combat pile and card, including serialized card state, current energy cost, affliction, and keywords;
- the complete run RNG set and deterministic action, hook, choice, and reward counters.

`ChecksumTracker.GenerateChecksum(NetFullCombatState)` hashes this representation. We will use the native checksum as a differential oracle: replay the same action in the live game and in a cloned worker, then require identical snapshots/checksums.

## Legal action and transition hooks

- A card is playable when `CardModel.CanPlay()` succeeds; legal targets are given by `CanPlayTargeting(Creature)`.
- Stable in-combat card references are provided by `NetCombatCard.CombatCardIndex`.
- Card, potion, and end-turn inputs have public `PlayCardAction`, `UsePotionAction`, and `EndPlayerTurnAction` constructors.
- `ActionQueueSet.EnqueueWithoutSynchronizing` and `ActionExecutor.FinishedExecutingActions` provide the deterministic action execution boundary.
- `CombatState` exposes ordered players/creatures and mutable combat side/round, but has no public whole-object clone or restore method.

## Clone strategy

There is no public `CombatState.Clone()` or `NetFullCombatState.ToRun()` in this build. The implementation therefore uses two layers:

1. Reconstruct a worker from the serialized run and combat-entry replay prefix, which is the canonical correctness path.
2. Add a faster in-memory clone only after differential tests prove that its native `NetFullCombatState` checksum matches replay reconstruction over a large action corpus.

This keeps correctness independent of a fragile hand-copied list of private fields while leaving room for a high-throughput fast path.

Run the compatibility gate with:

```bash
dotnet run --project tools/Sts2.AbiProbe -- \
  --contract contracts/sts2-v0.111.0.json \
  --out artifacts/abi/sts2-current.json
```
