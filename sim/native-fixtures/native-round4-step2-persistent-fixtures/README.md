# Round 4 step 2: persistent relic fixtures

18 controlled fixtures run the original target DLL (`v0.111.0 / 41cef1ea`). `validation.json` records the exact game, source harness, compiled/copied host and results digests.

Coverage: Bone Tea's opening hand and one-combat consumption (including original non-upgradable Wound/Byrdonis Egg, no permanent deck upgrade); Fake Venerable Tea Set's rest-entry boolean and once-only energy reset; Byrdpip's private seeded skin RNG, all egg transforms in the deck/draw/discard/exhaust piles, fresh replacement identities, Molten Egg/Bing Bong/Lucky Fysh/Book of Five Rings/Fresnel Lens acquisition interactions, summoned pet, and base/upgraded Byrd Swoop with/without a pet.

Native Byrdpip is a passive pet with no combat moves. Byrd Swoop's `WithAttackerAnim` changes the visual attacker; its `FromCard` damage and hooks still belong to the player. The C++ representation stores pet presence, not a fake enemy. `HATCH` is a real rest-site action when an egg is held, wired by the run layer.

The native fixtures do not establish all turn-start hook ordering. In particular, relative acquisition order between Bone Tea and other hand-modifying relics (Choices Paradox, Toolbox, etc.) remains bounded by the simulator's existing turn-start scheduling. The C++ pending-choice regression verifies Bone Tea is not consumed before a paused initial selection completes; it is not a full native combined-relic order fixture.

Rebuild with `dotnet build SimulatorAudit.csproj --no-restore -c ExportRelease -o .godot/mono/temp/bin/ExportRelease -p:NuGetAudit=false`, check success, copy the output SimulatorAudit.dll into the local exported app's managed assembly folder, and sign with the included entitlements. Run `python3 run_native.py`, then `python3 validate.py`. The host and game binaries are local dependencies and not source deliverables. A separate custom Godot user directory is used.
