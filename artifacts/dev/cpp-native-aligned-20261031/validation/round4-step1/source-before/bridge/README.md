# Isolated native ArmG bridge review

This directory is a reviewable patch against immutable `workspace-82e5621`.
It is **not installed**, and no native UI playthrough has been performed.

`dotnet build bridge/NativeArmGBridge.Check.csproj` reads the other reference
sources without modifying them, and compiles the replacement files here.
The local game DLL is the v0.111.0 / 41cef1ea DLL with SHA-256
`9cb4f1ad8c9f284aa8fec3122ffd6d780bbf543d875c817abdd12ff63fbf12b4`.
The worker is `scripts/armg_live_worker.py` in the parent dev directory.

## What is genuinely projected

- Native deck energy cost, Guilty combat counter, enchantment identity/amount/
  disabled state; afflictions without an adapter are rejected.
- Frozen selected deck indices, without inferring the pending effect from its
  generic UI prompt.
- Native act identities, Golden Compass act, unknown-point visit count,
  discovery/unlock history, seen encounters, and current boss identities.
- Exact source checkpoint/engine contract through the ordinary strict loader.
- Returned selection subsets, if a future worker supports them, must satisfy
  the original frozen template and `ValidateSubmittedSetAction` before use.

## Explicit remaining limits

The worker still declares approximate features for simulator map allocation
order, some event/relic/run counters, pending rewards/shop state, and acquisition
queue. Those are carried over limitations, not evidence of native equivalence.
It rejects active card grids, selection templates, non-empty Pael stored-card
state, unknown IDs, and unsupported reward alternatives. It does not silently
mask an unsupported native candidate or identify Pael removal by its generic
remove prompt. A single concrete legal action can be returned without model
inference, but a single selection template cannot.

Completing grid/Pael support requires an explicit native acquisition-source
scope, the exact pending operation and after-selection effects, full stored
card state, and an integration test executing the selected subset in the UI.
The new protocol members are optional so unrelated existing policies remain
usable; missing required ArmG facts produce `unsupported`.
