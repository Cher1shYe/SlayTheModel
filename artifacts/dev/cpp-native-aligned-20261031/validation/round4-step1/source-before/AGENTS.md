# C++ native rules port workspace

## Current handoff (2026-10-31)

Read the repository-root `../../../AGENTS.md` for the current round3 state,
confirmed gap inventory, evidence locations, and next-step order. It supersedes
the historical agent ownership below. This directory remains the editable port.
Current ruleset is `native-41cef1ea-port-v3`, observation/action schemas 12/11,
ArmG feature4, snapshot7. Full native parity is still false.

Important audit correction: LostCoffer is already using the Ironclad reward pool
with `useBaseOdds=true`; the round3 relic report's "fixed common colorless" claim
is wrong. Its complete reward hooks remain unverified. Grapple is absent from
the target native version and intentionally excluded; do not restore it to pools.

User authorized retaining the fast C++ engine and aligning its rules to the
native game used by our headless probe. Do not commit, push, install mods, or
overwrite the immutable reference snapshot or user's uploaded checkpoint.

Base: `be401e8ba09ac58c9f3b01cf77e195f7122c8d0c` (`origin/alphazero`).
Target: local native game `v0.111.0`, release commit `41cef1ea`, game DLL SHA-256
`9cb4f1ad8c9f284aa8fec3122ffd6d780bbf543d875c817abdd12ff63fbf12b4`.
The release label alone is not a compatibility guarantee.

Native execution oracle and prior audit:
`../../reference/alphazero-be401e8-review/`. Native source at
`../../../artifacts/native-source/v0.111.0` matches the local DLL for tested rules;
prefer actual DLL execution when evidence differs. External repository decompiles
are secondary references and contain different game rules.

Preserve game decisions; do not substitute random choices for player input.
Do not skip rules, discard legitimate actions or fabricate parity to improve speed.
Snapshots/weights must retain explicit compatibility and migration provenance.
Keep assertions enabled in regression tests. State partial coverage explicitly;
passing targeted tests does not establish complete native equivalence.

Previous agent assignments have ended. Establish fresh ownership before parallel
edits; coordinate shared headers, generated IDs, observations, bindings and
snapshot/checkpoint identities. Freeze source before an integrated build.
Preserve original reports and put future validation in new round directories.
