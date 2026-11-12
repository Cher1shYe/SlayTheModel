# C++ native rules port workspace

**Read the repository-root `../../../AGENTS.md` first.** It holds the current
state (updated 2026-11-10), remaining work, versions and commands, and supersedes
everything that used to be written here. Detailed per-step records:
`validation/round4-step2-resume-20261108/README.md` and
`validation/round4-step3-events-20261108/README.md`.

Current identity: ruleset `native-41cef1ea-port-v8` (2026-11-11 The Future of Potions fix, see `validation/future-potions-fix-20261111/README.md`; 2026-11-10 NoSL fix, see `validation/nosl-fix-20261110/README.md`; macro observation v2), public observation v15,
action schema v14, snapshot v10, ArmG feature 6. Full native parity is not
established; changes from step 3 onward are source ports without DLL runs.
This directory owns the native rule port and C++ interfaces used by the new
`model/spire_rl/` training package. The old ArmG / `agent/` network and
`scripts/armg_live_worker.py` remain out of scope; necessary new macro-observation
or combat-driver interfaces are allowed within a requested task, without
silently changing game rules. Python network work belongs in `model/spire_rl/`.

The current source branch is `v111_SF1` (`50d72a6` at the handoff). The user has
started an A0 run on Windows/WSL2 with Conda `slay`, Python 3.12.0. The only GPU
result received is the pre-training `[val @0]` baseline; no GPU update/throughput
report has been received. Do not restart or alter that run to inspect it.

The original game DLL still exists. A verified macOS installation snapshot is
preserved at repository-root `artifacts/preserved-game-versions/sts2-v0.111.0-41cef1ea-macos-20261110/`.
It is not a build cache and must survive cleanup. Rebuilding fixture hosts and
running new native differential tests remain outstanding; preservation alone
is not new rule-parity evidence. See root AGENTS for local and remote paths.

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
