# C++ native rules port workspace

**Read the repository-root `../../../AGENTS.md` first.** It holds the current
state (2026-11-09), remaining work, versions and commands, and supersedes
everything that used to be written here. Detailed per-step records:
`validation/round4-step2-resume-20261108/README.md` and
`validation/round4-step3-events-20261108/README.md`.

Current identity: ruleset `native-41cef1ea-port-v6`, public observation v15,
action schema v14, snapshot v10, ArmG feature 6. Full native parity is not
established; changes from step 3 onward are source ports without DLL runs.
Scope (user, 2026-11-09): native rule adaptation only. Torch and the training
network are out of scope.

Rules that still apply here:

- Base `be401e8ba09ac58c9f3b01cf77e195f7122c8d0c` (`origin/alphazero`). Target
  is the local native game `v0.111.0` / `41cef1ea`, game DLL SHA-256
  `9cb4f1ad8c9f284aa8fec3122ffd6d780bbf543d875c817abdd12ff63fbf12b4`.
- The decompiled source is at `../../native-source/v0.111.0`. Prefer actual
  DLL execution when evidence differs. External decompiles of other game
  versions have different rules.
- Preserve player decisions. Never substitute random choices for player input,
  skip rules, or discard legitimate actions for speed.
- Do not commit, push, install mods, or overwrite the immutable reference
  snapshot, the user's checkpoint, or native fixture results.
- Append new IDs at the end; Grapple stays a reserved, excluded slot. Change
  generators (`simulator/tools/gen_*.py`) together with generated files.
- Keep regression assertions on. Tests locate fixtures through
  `simulator/tests/port_root.h` (`$STS2_PORT_ROOT`, else the working
  directory and its parents), so run them from this directory.
- Put new validation logs in new directories; keep older evidence intact.
