# Round 4, step 1: independent self-damage state

Original target `v0.111.0 / 41cef1ea` DLL controlled fixtures. See `validation.json` for exact game/harness/host/results digests. The harness runs original card OnPlay/replay, then original `Hook.AfterPlayerTurnStart`; it clears existing block before that hook to reproduce the ordinary turn boundary without taking an enemy turn.

56 fixtures cover base/upgraded and replayed Crimson Mantle / Inferno; unchanged per-turn self-damage counters; raw power Apply without a card play; removal/recreation; relative acquisition order; Rupture; Tungsten Rod, Buffer, Intangible; lethal damage and Lizard Tail revival; enemy-side, direct-HP and blocked-damage negative cases. C++ tests load the final `results.json` and compare live state and per-enemy outcomes.

This does not establish general hook-order or whole-run equivalence. Native final death removes every power; C++ already retains final power values. The C++ effect test compares HP/block/damage/outcome for those terminal cases and explicitly excludes that preexisting global teardown difference.

`first-*` records the initial 42-fixture run. `failed-duplicate-source-build.log` records an intermediate harness compilation failure; `stale-build-*` records the accidentally repeated old host. Only the successful final 56-fixture `results.json`, matching compiled/copied host and `validation.json`, is used by tests.

Local rebuild: `dotnet build SimulatorAudit.csproj --no-restore -c ExportRelease -o .godot/mono/temp/bin/ExportRelease -p:NuGetAudit=false`. Check success, copy `SimulatorAudit.dll` from that output into `SimulatorAudit.app/Contents/Resources/data_SimulatorAudit_macos_arm64/`, and sign the local host with the included entitlements. Then `python3 run_native.py` and `python3 validate.py`. The copied host/game assemblies are local dependencies, not portable deliverables. The project uses an isolated custom Godot user directory.
