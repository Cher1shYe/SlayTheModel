# Blockers for target-build differentials (2026-11-04)

## Target DLL absent

Required reference: `9cb4f1ad8c9f284aa8fec3122ffd6d780bbf543d875c817abdd12ff63fbf12b4`
(macOS build used by `native-run-fixtures/` and the earlier differential runs).

Disk search on this machine (`D:\sts2_datacollection`, filename `sts2.dll`):

| path | sha256 |
| --- | --- |
| `SlayTheModel/artifacts/native-host/data_NativeWorker_windows_x86_64/sts2.dll` | `0861bfa1df347538d932f22d580e75420f08082792eb914e53b4882764acdbe9` |
| `SlayTheModel/combat/.godot/mono/temp/obj/Release/PublicizedAssemblies/sts2.DA203708786AE9E5E8FAA42D95210CE1/sts2.dll` | `4419b074c44428d505582c1bd5f716af600a8345021b597eff294d14aac2efa3` |

`SlayTheModel/artifacts/native-host/release_info.json` says commit `41cef1ea`,
version `v0.111.0`, so `0861bfa1` is very likely the same source built for
Windows.  It is still a different binary hash and is **not** used as the target
reference; the decompiled C# of `0861bfa1` is used only as labelled reading
evidence (Aeonglass, Wither, event/encounter declaration order).

## No whole-run native oracle

`native-run-fixtures/results.json` records `"gameSceneLoaded": false`,
`"status": "completed"` and `"scope": "Controlled native fixtures, not natural
runs or full-run parity."`  `validation.json` likewise says the only native
execution target is controlled direct relic obtain.  There is therefore no
same-seed / same-progress / same-decision native whole-run trace to diff
against.  The native host worker (`NativeWorker.exe`) is the combat prior
worker, not a run driver.

Consequence: the long-path native vs C++ comparison required for final
acceptance remains blocked.  C++ multi-seed whole-run smoke and target-source
(declaration-order) checks are recorded, but they are not native differentials.

## Regent native samples

No native Regent sample set exists in the repository; the fixture DLL that
produced the existing samples is the absent `9cb4f1ad` macOS build.
