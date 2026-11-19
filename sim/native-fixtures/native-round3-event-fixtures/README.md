# Third-round native event/rest fixtures

The 57 fixtures execute the installed target game DLL (`v0.111.0 / 41cef1ea`, SHA-256 recorded in `validation.json`) inside a copied isolated host. No game/mod deployment is performed. The global game scene is not loaded. This is controlled differential evidence, not full-run parity.

`AuditWorker.cs` calls native event methods, native rest-entry hooks, and the native rest-heal routine. Player card choices use `CardSelectCmd.PushSelector`. Full-belt reward tests use the game's `RewardsSet.testSelector` to record offered potions then explicitly skip them, preserving the offered-reward evidence without replacing game generation logic. Dense rest runs its UI-free branch through a temporary nonlocal context. Compatibility initialization is inherited from the existing isolated native host.

The six-card decks, seeds, starting HP/relics/potions and chosen card index are in the fixture source. `results.json` records raw outcomes; `invocation.json` records the launched command and source hash. `simulator/tests/native_event_round3_alignment.cpp` checks the C++ outcomes and additionally restores pending player choices, rejects taking potions with a full belt, discards one potion, and then takes an offered reward.

To rebuild locally with the installed cached Godot SDK, run `dotnet build SimulatorAudit.csproj --no-restore -c ExportRelease -o .godot/mono/temp/bin/ExportRelease` with the existing NuGet package cache. Copy the resulting `SimulatorAudit.dll` into `SimulatorAudit.app/Contents/Resources/data_SimulatorAudit_macos_arm64/`, sign the copied local host using the included entitlements, and run `python3 run_native.py`. The host binary and game DLL are local validation dependencies, not portable deliverables.

Known event gaps and source-review coverage are listed in `../validation/round3/events-audit.json`.
