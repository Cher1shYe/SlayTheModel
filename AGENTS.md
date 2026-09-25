# Repository Guidelines

## Project Structure

- `src/` contains the core C# protocol, search, and game-mod projects.
- `combat/` contains the CombatSolver simulation and search code; read its
  `AGENTS.md` before changing anything under that directory.
- `tools/` contains NativeWorker, ABI probes, and focused executable checks;
  `smoke/` contains lightweight protocol and search smoke projects.
- `alphazero-combat/` is the isolated Python/ONNX experiment package. Source is
  in `src/azcombat`, tests in `tests`, and configs/data/models/runs are local
  experiment inputs or outputs.
- `contracts/` and `docs/` hold versioned ABI contracts and design notes.
  Generated logs, binaries, `artifacts/`, `bin/`, and `obj/` are not source.

## Build, Test, and Development Commands

The repository uses the SDK selected by `global.json` (`9.0.306`, with feature
roll-forward). Common Windows commands from the repository root are:

```powershell
dotnet build CombatSolver.csproj -c Release
pwsh -NoProfile -File scripts\windows.ps1 -Action Test
python -m unittest discover -s alphazero-combat/tests -v
pwsh -NoProfile -File scripts\native-worker.ps1 -Mode verify -GameDir <game-dir>
```

Install Python extras only when needed: `python -m pip install -e
'./alphazero-combat[train]'` or `[export]`. NativeWorker runs must use the
matching STS2 v0.111.0 game and RitsuLib paths; keep each run's logs and
provenance in a new output directory.

## Coding Style and Testing

C# follows the repository defaults: four-space indentation, nullable reference
types, implicit usings, latest language version, and warnings treated as errors.
Use PascalCase for public C# APIs and descriptive camelCase locals. Python uses
PEP 8, `snake_case` functions, and type hints where practical. Unknown game
semantics must fail closed; do not return defaults, filter invalid samples, or
fake search statistics. Add focused tests beside the affected tool or Python
module, then run the smallest relevant check before broader suites. Headless
tests must clean up their instance (`-CleanupInstanceOnExit`).

## Commits and Pull Requests

Use short imperative subjects, preferably scoped (`feat(azcombat): ...`,
`fix(native-worker): ...`). Keep commits focused and describe behavior rather
than implementation trivia. Pull requests should summarize the change, list
commands and environments used for verification, link relevant issues or
reports, and call out untested paths. Do not commit game assemblies, secrets,
personal absolute paths, or generated `bin/`, `obj/`, `.godot/`, and artifact
outputs.

## Configuration and Safety

The supported game ABI is STS2 `v0.111.0`; verify local paths through script
parameters or environment variables such as `STS2_GAME_DIR`. Preserve existing
uncommitted work, and never use destructive Git commands to clean unrelated
changes.
