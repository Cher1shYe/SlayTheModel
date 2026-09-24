"""Run isolated NativeWorker candidate/baseline evaluation or champion self-play."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import shutil

from .samples import read_jsonl

REGISTERED_ENCOUNTERS = frozenset({
    "FUZZY_WURM_CRAWLER_WEAK", "CULTISTS_NORMAL", "LIVING_FOG_NORMAL",
    "PHROG_PARASITE_ELITE", "KAISER_CRAB_BOSS",
})
STARTS = ("full_combat", "mid_combat_verified")
SCENARIOS = {
    "ordinary": {"starts": STARTS, "choiceFixture": False, "fixtureCards": None, "initialHp": None},
    "purity_choice": {"starts": ("full_combat",), "choiceFixture": True,
                      "fixtureCards": ["PURITY", "ARMAMENTS", "HEADBUTT", "STRIKE_IRONCLAD", "DEFEND_IRONCLAD"],
                      "initialHp": None},
    "cascade_nested": {"starts": ("full_combat",), "choiceFixture": True,
                       "fixtureCards": ["CASCADE", "CASCADE", "CASCADE", "PREPARED", "PREPARED", "PREPARED",
                                        "PREPARED", "PREPARED", "STRIKE_IRONCLAD", "DEFEND_IRONCLAD"],
                       "initialHp": None},
    "native_death": {"starts": ("full_combat",), "choiceFixture": True,
                     "fixtureCards": ["STRIKE_IRONCLAD"], "initialHp": 1},
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def checked_model(model: Path) -> str:
    manifest = json.loads(model.with_suffix(".manifest.json").read_text(encoding="utf-8"))
    digest = sha256(model)
    if manifest.get("format") != "azcombat.onnx.v1" or digest.lower() != manifest.get("onnxSha256", "").lower():
        raise ValueError("candidate model/manifest hash mismatch")
    return digest


def run_wave(*, mode: str, output: Path, game_dir: Path, ritsu_root: Path,
             model: Path, seeds: list[str], encounters: list[str], budget_ms: int = 1000,
             max_decisions: int = 256, champion: Path | None = None,
             scenarios: list[str] | None = None) -> dict:
    """Never overwrite a previous run; retain every command's stdout/stderr."""
    if mode not in {"evaluate", "selfplay"}:
        raise ValueError("mode must be evaluate or selfplay")
    if len(set(seeds)) != len(seeds) or len(seeds) < 2 or not all(seeds):
        raise ValueError("require at least two distinct nonempty seeds")
    if not encounters or any(encounter not in REGISTERED_ENCOUNTERS for encounter in encounters):
        raise ValueError("encounter is not in the admitted NativeWorker fixture catalog")
    scenarios = list(SCENARIOS) if scenarios is None else scenarios
    if not scenarios or len(scenarios) != len(set(scenarios)) or any(s not in SCENARIOS for s in scenarios):
        raise ValueError("unknown or duplicate scenario")
    if budget_ms < 1000 or max_decisions < 1:
        raise ValueError("live decisions require at least 1000 ms and a positive trajectory cap")
    if mode == "selfplay" and champion is None:
        raise ValueError("self-play requires a promoted champion alias")
    model = model.resolve(strict=True)
    model_hash = checked_model(model)
    if mode == "selfplay":
        assert champion is not None
        alias = json.loads(champion.read_text(encoding="utf-8"))
        if alias.get("format") != "azcombat.champion.v1" or alias.get("onnxSha256", "").lower() != model_hash.lower():
            raise ValueError("self-play model does not match the promoted champion")
        gate_path = Path(alias.get("gateReport", ""))
        if not gate_path.is_file() or sha256(gate_path).lower() != alias.get("gateReportSha256", "").lower() \
                or json.loads(gate_path.read_text(encoding="utf-8")).get("approved") is not True:
            raise ValueError("champion gate report is missing, altered or denied")
        if set(seeds) & set(alias.get("usedSeeds", [])):
            raise ValueError("self-play seed overlaps champion training/evaluation seeds")
    repo = Path(__file__).resolve().parents[3]
    script = repo / "scripts" / "native-worker.ps1"
    catalog = repo / "combat" / "coverage" / "combat-hooks.json"
    if json.loads(catalog.read_text(encoding="utf-8")).get("gameVersion") != "0.111.0":
        raise ValueError("Combat Solver coverage catalog is not pinned to v0.111.0")
    shell = shutil.which("pwsh.exe") or shutil.which("pwsh")
    if shell is None:
        raise FileNotFoundError("PowerShell 7 is required for the verified native-worker script")
    if not script.is_file() or not game_dir.is_dir() or not ritsu_root.is_dir():
        raise FileNotFoundError("NativeWorker script/game/RitsuLib prerequisite missing")
    output.mkdir(parents=True, exist_ok=False)
    manifest = {"format": "azcombat.wave.v2", "mode": mode, "gameVersion": "v0.111.0",
                "coverageCatalogSha256": sha256(catalog),
                "candidateOnnx": str(model), "candidateSha256": model_hash, "seeds": seeds,
                "encounters": encounters, "scenarios": scenarios, "startTypes": list(STARTS), "budgetMilliseconds": budget_ms,
                "maxDecisions": max_decisions, "runs": [], "status": "incomplete"}
    manifest_path = output / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    for seed_index, seed in enumerate(seeds):
        for encounter in encounters:
          for scenario in scenarios:
            spec = SCENARIOS[scenario]
            for start in spec["starts"]:
                for policy in (("baseline", "candidate") if mode == "evaluate" else ("champion",)):
                    stem = f"{seed_index:03d}-{encounter}-{scenario}-{start}-{policy}"
                    jsonl = output / (stem + ".jsonl")
                    env = os.environ.copy()
                    for name in tuple(env):
                        if name.startswith("STS2_MCTS_EXPORT_") or name.startswith("STS2_ALPHAZERO_"):
                            env.pop(name)
                    env.update({"STS2_MCTS_EXPORT_OUT": str(jsonl.resolve()),
                                "STS2_MCTS_EXPORT_SEED": seed,
                                "STS2_MCTS_EXPORT_ENCOUNTER": encounter,
                                "STS2_MCTS_EXPORT_MID_START_TURNS": "1" if start == "mid_combat_verified" else "0",
                                "STS2_MCTS_EXPORT_MAX_DECISIONS": str(max_decisions),
                                "STS2_MCTS_EXPORT_BUDGET_MS": str(budget_ms)})
                    if spec["choiceFixture"]:
                        env["STS2_MCTS_EXPORT_CHOICE_FIXTURE"] = "1"
                        env["STS2_MCTS_EXPORT_FIXTURE_CARDS"] = ",".join(spec["fixtureCards"])
                    if spec["initialHp"] is not None:
                        env["STS2_MCTS_EXPORT_INITIAL_HP"] = str(spec["initialHp"])
                    if policy != "baseline":
                        env["STS2_ALPHAZERO_ONNX_MODEL"] = str(model)
                    command = [shell, "-NoProfile", "-File", str(script), "-GameDir", str(game_dir),
                               "-RitsuLibRoot", str(ritsu_root), "-Mode", "solver-mcts-export",
                               "-TimeoutSeconds", "1800"]
                    result = subprocess.run(command, cwd=repo, env=env, capture_output=True, text=True,
                                            encoding="utf-8", errors="replace", timeout=1900, check=False)
                    stdout = output / (stem + ".stdout.txt")
                    stderr = output / (stem + ".stderr.txt")
                    stdout.write_text(result.stdout, encoding="utf-8")
                    stderr.write_text(result.stderr, encoding="utf-8")
                    # The script echoes only the last 12/20 worker log lines. Preserve the
                    # full redirected Godot streams before the next release overwrites them.
                    stage = repo / "artifacts" / "native-host"
                    worker_stdout = output / (stem + ".worker.stdout.txt")
                    worker_stderr = output / (stem + ".worker.stderr.txt")
                    for source, destination in ((stage / "stdout.txt", worker_stdout),
                                                (stage / "stderr.txt", worker_stderr)):
                        if not source.is_file():
                            raise FileNotFoundError(f"worker log missing for {stem}: {source}")
                        shutil.copyfile(source, destination)
                    entry = {"seed": seed, "encounter": encounter, "scenario": scenario,
                             "fixture": {"choiceFixture": spec["choiceFixture"],
                                         "fixtureCards": spec["fixtureCards"], "initialHp": spec["initialHp"]},
                             "startType": start, "policy": policy,
                             "jsonl": jsonl.name, "stdout": stdout.name, "stderr": stderr.name,
                             "workerStdout": worker_stdout.name, "workerStderr": worker_stderr.name,
                             "workerStdoutSha256": sha256(worker_stdout),
                             "exitCode": result.returncode}
                    manifest["runs"].append(entry)
                    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
                    if result.returncode != 0:
                        raise RuntimeError(f"NativeWorker failed for {stem}; artifacts preserved at {output}")
                    samples = read_jsonl(jsonl)
                    if not samples or any(sample.seed != seed or sample.start_type != start for sample in samples):
                        raise ValueError(f"empty or mislabeled samples for {stem}")
                    entry.update({"sha256": sha256(jsonl), "samples": len(samples),
                                  "outcome": samples[0].outcome, "value": samples[0].value_target})
                    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    manifest["status"] = "complete"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("evaluate", "selfplay"))
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--game-dir", required=True, type=Path)
    parser.add_argument("--ritsu-root", required=True, type=Path)
    parser.add_argument("--model", required=True, type=Path)
    parser.add_argument("--champion", type=Path)
    parser.add_argument("--seed", action="append", required=True)
    parser.add_argument("--encounter", action="append", required=True)
    parser.add_argument("--scenario", action="append", choices=tuple(SCENARIOS))
    parser.add_argument("--budget-ms", type=int, default=1000)
    parser.add_argument("--max-decisions", type=int, default=256)
    args = parser.parse_args()
    result = run_wave(mode=args.mode, output=args.output, game_dir=args.game_dir,
                      ritsu_root=args.ritsu_root, model=args.model, seeds=args.seed,
                      encounters=args.encounter, budget_ms=args.budget_ms,
                      max_decisions=args.max_decisions, champion=args.champion, scenarios=args.scenario)
    print(json.dumps({"status": result["status"], "runs": len(result["runs"])}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
