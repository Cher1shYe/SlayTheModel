# Native relic lifecycle fixtures, step 2

This isolated host runs the actual target DLL `v0.111.0 / 41cef1ea` (SHA-256
`9cb4f1ad8c9f284aa8fec3122ffd6d780bbf543d875c817abdd12ff63fbf12b4`).
It records 24 cases: nine Toy Box combinations of three seeds and take-all,
skip-all or reverse-order partial selection; six Small Capsule take/skip cases;
six Large Capsule cases with/without Molten Egg and Bing Bong; two exhausted-bag
Circlet fallbacks; and one controlled nested-reward suspension. The Toy Box cases
each record 18 combat-end transitions, including its stop at 15, preserved
inventory positions/counters and exclusion of melted relics from hook listeners.

Relic bags are explicitly controlled in each case. Their initial identities and
order are included in the results. This verifies source-specific rarity draws,
front-of-bucket pulls, rewards and acquisition timing; it does not certify native
initial bag population. Large Capsule **does** roll rarity once per relic in the
target DLL, using `PlayerRng.Rewards`; its former use of `RNG_NICHE` was incorrect.

The nested case uses native `TestRngInjector` to make the first Large Capsule relic
Small Capsule and suspends its selector before proceeding. That override isolates
await/continuation behavior; it does not claim Ancient relics belong to ordinary
random bags. The C++ test inserts the same controlled override in the first rolled
bucket, preserving the later random stream.

Run from this directory with local host/build prerequisites prepared:

```sh
python3 build_native.py
python3 run_native.py
python3 validate.py
```

The app runtime and `.godot` scaffolding were copied from
`../native-round4-step1-relic-fixtures/`; the build replaces the new harness
DLL/PDB and signs only the copied app. The project references the existing native
probe assemblies, and the runner uses the installed game pack. These game and
runtime binaries and build caches are local validation dependencies, not files
to publish with source artifacts. Earlier evidence is not overwritten.

`results.json` contains raw DLL observations. `validation.json` pins their hash,
the harness hash and target DLL identity. The C++ differential regression is
`simulator/tests/native_step2_relic_lifecycle.cpp`. No relic rules are patched in
the native host, the game scene is not loaded, and these controlled cases do not
establish full-run equivalence.
