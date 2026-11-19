# Step 1 native relic replacement fixtures

This isolated host executes 11 controlled cases against the target game DLL,
`v0.111.0 / 41cef1ea`, SHA-256
`9cb4f1ad8c9f284aa8fec3122ffd6d780bbf543d875c817abdd12ff63fbf12b4`.
The global game scene is not loaded. No installed game or mod is modified.

Eight cases record the complete ordered relic inventory before and after Touch
of Orobas: Burning Blood at the first, middle and last positions; Black Blood's
Circlet fallback; and the other four original starter mappings. They check fresh
replacement state, unchanged sibling objects/counters, obtain/remove event order
and zero Niche RNG draws. The remaining three cover first-Starter priority,
`AfterObtained` execution using native `SetupForTests` with Strawberry, and the
missing-Starter boundary. These are targeted fixtures, not natural-run or complete
other-character parity evidence. Native wax/floor metadata is recorded; the C++
port does not thereby gain support for those fields.

## Reproduce locally

From this directory, using the existing local native probe dependencies and
copied host runtime:

```sh
python3 build_native.py
python3 run_native.py
python3 validate.py
```

`build_native.py` compiles the harness with `dotnet build --no-restore`, copies its
DLL/PDB into this directory's app runtime, and signs only that copied app. The
local `SimulatorAudit.app` and `.godot` build scaffolding were copied from
`../native-round3-relic-fixtures/` before building this harness. A fresh source-only
copy requires those local prerequisites (or an equivalent prepared host and
restored Godot .NET build). `SimulatorAudit.csproj` identifies the native probe
assembly paths; `run_native.py` identifies the installed game pack.

`results.json` is the actual DLL output. `validation.json` records verification
and its hash; `replacement_cases.inc` is regenerated from that output for the C++
regression in `simulator/tests/native_step1_relic_replace.cpp`. Build/invocation
commands and hashes are retained in `build.json` and `invocation.json`. Game DLLs,
native probe dependencies, copied app/runtime binaries and build caches are local
validation dependencies and must not be published with source artifacts.

## Scope boundaries

Without a Starter relic, native `SetupForPlayer` returns false and normal Orobas
option generation omits Touch. Forcing native `RelicCmd.Obtain` anyway inserts
Touch and then throws `InvalidOperationException`; this invalid-call behavior is
recorded rather than presented as a valid game action. C++ rejects that acquisition
atomically before mutation or queueing, consistent with making it unavailable.

The accompanying Toy Box change only keeps relic IDs and their auxiliary counters
together when the existing deletion path shifts slots, then clears the vacated
slot. Its five wax relics, ordered melting and fifteen-combat lifetime remain
unimplemented; none of these 11 native fixtures certifies Toy Box behavior.
