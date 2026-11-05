# Native RNG alignment — 2026-10-31

## Target and scope

Reference is the actual local game DLL: release `v0.111.0 / 41cef1ea`, SHA-256
`9cb4f1ad8c9f284aa8fec3122ffd6d780bbf543d875c817abdd12ff63fbf12b4`.
The historical C++ snapshot used different RNG/hash behavior despite the same
release label. This change intentionally invalidates its old seeded trajectories.
Targeted mathematical equivalence does not establish full native game parity.

## API contract

- `RunContext.init(uint64, ascension)` / Python `init` and `reset` now take an
  **already derived raw 64-bit RNG seed**. Numeric 22 does not mean game string
  `"22"`. This differs from the previous decimal-string hashing behavior.
- `RunContext.init_seed(string, ascension)` / Python `init_seed` accepts an ASCII
  game seed, trims ASCII whitespace, uppercases it, replaces O/I with 0/1, then
  applies native UTF-8 xxHash64. Generated game seeds are ASCII. Non-ASCII seed
  canonicalization is explicitly rejected; Unicode .NET case folding is not
  approximated. The hash primitive itself supports arbitrary UTF-8, including
  embedded NUL when supplied as string_view.
- Standalone `generate_map` and `BattleContext.init` now accept raw 64-bit seeds.
  Run and player stream name hashes are 64-bit; the single-player slot is zero.
  Event RNG derives from the same slot zero, including non-shared events.
- Current native MegaRandom uses SplitMix64 initialization and xoshiro256**.
  Integer ranges, double/float conversion, Boolean calls, Gaussian retry draws,
  and counter increments follow the measured native wrapper. C++'s inclusive
  `next_int(lo, hi)` remains an explicit adapter for existing rule call sites.
- Search, rollout and hidden resampling still use the shared RNG implementation.
  Their public search seed may remain uint32, but their stochastic decisions now
  change as well. Previous MCTS action sequences and policy evaluation outcomes
  must not be attributed only to game rule changes.

## State and draw handling

Snapshot header version is now **5**, rejecting version 4 before reading its
object image. Each RNG stores four uint64 state words and an int32 counter;
explicit reserved bytes avoid indeterminate tail padding in RNG state hashes.
State restore preserves native counter wrap; an impossible seeded all-zero state
is rejected. Native snapshot export serializes full state, not only a seed and
counter. Simulator snapshots remain compiler/build-specific POD snapshots.

Discard reshuffle now combines remaining draw cards with discard, sorts using
native model entry / upgrade comparison, then Fisher–Yates shuffles. Initial
shuffle remains unsorted. Both convert native index-zero-top order to the C++
stack representation whose last element is the top. `native_card_less` is shared
for rule sites needing native card comparison. Equal-model/upgrade identities,
shuffle hooks and complex altered card piles still require broader native replay
coverage; a comparator match alone is not a complete proof of identity ordering.

Map point-count rolls now match the current three native act methods: rest then
unknown, without the historical extra Gaussian roll or cloned RNG lookahead.
The entire map generator and upstream room/content pools still require native
map/long-run differential checks.

## Oracle and regression

`tools/native-rng-vectors/Program.cs` calls the native DLL using reflection; it
starts no scene or RunManager. Its output is checked in as
`simulator/tests/fixtures/native_rng_41cef1ea.json`. The fixture binds the exact
DLL SHA and contains UTF-8 hash vectors, ASCII canonicalization, eight seed cases
(including high bits and UINT64_MAX), 424 mixed RNG operations with every output,
float/double bit pattern, counter and four-word state, plus a 155,216-draw case.
`simulator/tests/native_rng_contract.cpp` checks these native vectors, restore
continuation, invalid-bound behavior, counter wrap and shuffle output.

Regenerate from the repository root (substitute the actual oracle DLL path):

```sh
dotnet run --project tools/native-rng-vectors/NativeRngVectors.csproj -- /absolute/path/sts2.dll
```

The host assembly may print a Sentry initialization line before the JSON; retain
the JSON object and verify its oracle hash before replacing any fixture.

The primitive test can run independently of a full simulator build:

```sh
clang++ -std=c++17 -O3 -I simulator/include -I simulator/json/include simulator/tests/native_rng_contract.cpp -o /tmp/sts2-native-rng-contract
/tmp/sts2-native-rng-contract
```

Historical fixed RNG/map hashes and winning heuristic seeds are not native
proofs. Update expected mathematical vectors only from the native oracle and
separate intentional environment changes from genuine rule regressions.
