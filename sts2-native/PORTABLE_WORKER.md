# Vendored native worker

This directory contains buildable source from the audited
`az_candidate500_20261020_120022/native` snapshot, including CombatSolver,
the full-node policy/pure-value search and the Reattach, Iron Wave, Volley and
Hand of Greed corrections. The upstream CombatSolver base is recorded in
`combat/.source-commit`; the snapshot includes subsequent local corrections.
Do not treat that base SHA as the complete snapshot's identity.

Game assemblies, resource packs, RitsuLib binaries, build outputs and decompiled
game source are not distributed here. Preserve `LICENSE`,
`combat/LICENSE` and `combat/THIRD_PARTY_NOTICES.md` when redistributing source.
The CombatSolver docs record its own earlier mod development history; the
current training deployment instructions are in the repository root README.

The new portable preparation script is
`../sts2-rl-agent/scripts/prepare_native_az_self_evolution.py`. It copies source
into a new output directory, then invokes `build_native_runtime.py` with explicit
game and RitsuLib paths and `CopyModOnBuild=false`. Windows uses `win-x64`;
Linux uses `linux-x64` and `data_NativeWorker_linuxbsd_x86_64`.

The generic collector takes `STS2_PYTHON_EXECUTABLE` from its Python parent,
so it does not assume a Windows virtual environment. The older native scripts
remain historical Windows-specific entry points.

ABI admission remains pinned to the recorded v0.111.0 `sts2.dll` SHA256. A Linux
assembly that differs is rejected and needs an independent ABI and semantic
audit. Linux host execution is not yet empirically verified; the build,
process-group cleanup, file lock and interpreter paths have platform branches.
Run the 16-fight strict startup check on the destination before full training.
