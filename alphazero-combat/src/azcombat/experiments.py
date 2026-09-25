"""Run isolated candidate bootstrap, paired evaluation or champion self-play."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import shutil

from .samples import read_jsonl
from .training import ACTION_DIM, ENTITY_DIM, GLOBAL_DIM
from .versions import FEATURE_ABI, OBSERVATION_SCHEMA_VERSION, ONNX_MANIFEST_FORMAT

REGISTERED_ENCOUNTERS = frozenset({
    "FUZZY_WURM_CRAWLER_WEAK", "CULTISTS_NORMAL", "LIVING_FOG_NORMAL",
    "PHROG_PARASITE_ELITE", "KAISER_CRAB_BOSS",
})
STARTS = ("full_combat", "mid_combat_verified")
BASELINE_SEARCH_MODE = "pure-mcts"
CANDIDATE_SEARCH_MODE = "policy-value-tree-v1"
RESEARCH_ENCOUNTERS = ("CULTISTS_NORMAL", "LIVING_FOG_NORMAL")
RESEARCH_SPLIT_FORMAT = "azcombat.seed-split.v1"
RESEARCH_WAVE_FORMAT = "azcombat.research-wave.v1"
DECK_PLAN_FORMAT = "azcombat.deck-plan.v1"
IRONCLAD_STARTER_IDS = frozenset({"STRIKE_IRONCLAD", "DEFEND_IRONCLAD", "BASH"})
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


def _assembly_build_identity(assemblies: dict) -> dict[str, tuple[str, str]]:
    required = {"nativeWorker", "search", "combatSolver"}
    if not isinstance(assemblies, dict) or set(assemblies) != required:
        raise ValueError("loaded assembly build identities are incomplete")
    return {label: (identity["mvid"].lower(), identity["sha256"].lower())
            for label, identity in assemblies.items()}


def checked_model(model: Path) -> str:
    manifest = json.loads(model.with_suffix(".manifest.json").read_text(encoding="utf-8"))
    digest = sha256(model)
    if manifest.get("format") != ONNX_MANIFEST_FORMAT \
            or manifest.get("featureAbi") != FEATURE_ABI \
            or manifest.get("observationSchemaVersion", OBSERVATION_SCHEMA_VERSION) != OBSERVATION_SCHEMA_VERSION \
            or manifest.get("inputs") != {"entities": ["N", ENTITY_DIM], "globals": [GLOBAL_DIM],
                                          "actions": ["A", ACTION_DIM]} \
            or manifest.get("outputs") != {"logits": ["A"], "value": []}:
        raise ValueError("unsupported ONNX manifest")
    if digest.lower() != manifest.get("onnxSha256", "").lower():
        raise ValueError("candidate model/manifest hash mismatch")
    return digest


def run_wave(*, mode: str, output: Path, game_dir: Path, ritsu_root: Path,
             model: Path, seeds: list[str], encounters: list[str], budget_ms: int = 1000,
             max_decisions: int = 256, max_simulations: int = 50,
             candidate_search_mode: str = CANDIDATE_SEARCH_MODE,
             champion: Path | None = None,
             scenarios: list[str] | None = None) -> dict:
    """Never overwrite a previous run; retain every command's stdout/stderr."""
    if mode not in {"bootstrap", "evaluate", "selfplay"}:
        raise ValueError("mode must be bootstrap, evaluate or selfplay")
    if len(set(seeds)) != len(seeds) or len(seeds) < 2 or not all(seeds):
        raise ValueError("require at least two distinct nonempty seeds")
    if not encounters or any(encounter not in REGISTERED_ENCOUNTERS for encounter in encounters):
        raise ValueError("encounter is not in the admitted NativeWorker fixture catalog")
    scenarios = (["ordinary"] if mode == "bootstrap" else list(SCENARIOS)) if scenarios is None else scenarios
    if not scenarios or len(scenarios) != len(set(scenarios)) or any(s not in SCENARIOS for s in scenarios):
        raise ValueError("unknown or duplicate scenario")
    if budget_ms < 1000 or max_decisions < 1 or type(max_simulations) is not int or max_simulations < 1:
        raise ValueError("live decisions require at least 1000 ms, a positive simulation cap and trajectory cap")
    if candidate_search_mode != CANDIDATE_SEARCH_MODE:
        raise ValueError(f"candidate search mode must be {CANDIDATE_SEARCH_MODE}")
    if mode == "selfplay" and champion is None:
        raise ValueError("self-play requires a promoted champion alias")
    if mode != "selfplay" and champion is not None:
        raise ValueError("only promoted champion self-play accepts a champion alias")
    model = model.resolve(strict=True)
    # Read the training lineage before the strict manifest check so a bootstrap
    # seed collision is still reported as such, while every usable candidate is
    # subsequently required to carry the current v4/v4/schema-3 contract.
    model_manifest = json.loads(model.with_suffix(".manifest.json").read_text(encoding="utf-8"))
    source_seeds = set(model_manifest.get("training", {}).get("trainSeeds", [])) \
        | set(model_manifest.get("training", {}).get("validationSeeds", []))
    if mode in {"bootstrap", "evaluate"} and (not source_seeds or set(seeds) & source_seeds):
        raise ValueError(f"{mode} requires new seeds distinct from source training/validation")
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
                "sourceCheckpointSha256": model_manifest.get("checkpointSha256"),
                "encounters": encounters, "scenarios": scenarios, "startTypes": list(STARTS),
                "baselineSearchMode": BASELINE_SEARCH_MODE, "candidateSearchMode": candidate_search_mode,
                "budgetMilliseconds": budget_ms, "decisionBudgetMilliseconds": budget_ms,
                "maxSimulations": max_simulations,
                "maxDecisions": max_decisions, "runs": [], "status": "incomplete"}
    manifest_path = output / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    for seed_index, seed in enumerate(seeds):
        for encounter in encounters:
          for scenario in scenarios:
            spec = SCENARIOS[scenario]
            for start in spec["starts"]:
                for policy in (("baseline", "candidate") if mode == "evaluate" else
                               ("candidate",) if mode == "bootstrap" else ("champion",)):
                    stem = f"{seed_index:03d}-{encounter}-{scenario}-{start}-{policy}"
                    jsonl = output / (stem + ".jsonl")
                    stage = (output / (stem + ".stage")).resolve()
                    env = os.environ.copy()
                    for name in tuple(env):
                        if name.startswith("STS2_MCTS_EXPORT_") or name.startswith("STS2_ALPHAZERO_"):
                            env.pop(name)
                    requested_search_mode = BASELINE_SEARCH_MODE if policy == "baseline" else candidate_search_mode
                    env.update({"STS2_MCTS_EXPORT_OUT": str(jsonl.resolve()),
                                "STS2_MCTS_EXPORT_SEED": seed,
                                "STS2_MCTS_EXPORT_ENCOUNTER": encounter,
                                "STS2_MCTS_EXPORT_MID_START_TURNS": "1" if start == "mid_combat_verified" else "0",
                                "STS2_MCTS_EXPORT_MAX_DECISIONS": str(max_decisions),
                                "STS2_MCTS_EXPORT_BUDGET_MS": str(budget_ms),
                                "STS2_MCTS_EXPORT_MAX_SIMULATIONS": str(max_simulations),
                                "STS2_ALPHAZERO_SEARCH_MODE": requested_search_mode})
                    if spec["choiceFixture"]:
                        env["STS2_MCTS_EXPORT_CHOICE_FIXTURE"] = "1"
                        env["STS2_MCTS_EXPORT_FIXTURE_CARDS"] = ",".join(spec["fixtureCards"])
                    if spec["initialHp"] is not None:
                        env["STS2_MCTS_EXPORT_INITIAL_HP"] = str(spec["initialHp"])
                    command = [shell, "-NoProfile", "-File", str(script), "-GameDir", str(game_dir),
                               "-RitsuLibRoot", str(ritsu_root), "-Mode", "solver-mcts-export",
                               "-StageRoot", str(stage),
                               "-TimeoutSeconds", "1800", "-SearchMode", requested_search_mode,
                               "-MaxSimulations", str(max_simulations), "-BudgetMilliseconds", str(budget_ms)]
                    if policy != "baseline":
                        command.extend(["-OnnxModel", str(model)])
                    result = subprocess.run(command, cwd=repo, env=env, capture_output=True, text=True,
                                            encoding="utf-8", errors="replace", timeout=1900, check=False)
                    stdout = output / (stem + ".stdout.txt")
                    stderr = output / (stem + ".stderr.txt")
                    stdout.write_text(result.stdout, encoding="utf-8")
                    stderr.write_text(result.stderr, encoding="utf-8")
                    # Keep the complete Godot streams beside this run's independent stage.
                    worker_stdout = output / (stem + ".worker.stdout.txt")
                    worker_stderr = output / (stem + ".worker.stderr.txt")
                    entry = {"seed": seed, "encounter": encounter, "scenario": scenario,
                             "fixture": {"choiceFixture": spec["choiceFixture"],
                                         "fixtureCards": spec["fixtureCards"], "initialHp": spec["initialHp"]},
                             "startType": start, "policy": policy,
                             "jsonl": jsonl.name, "stdout": stdout.name, "stderr": stderr.name,
                             "workerStdout": worker_stdout.name, "workerStderr": worker_stderr.name,
                             "stageRoot": str(stage), "exitCode": result.returncode,
                             "status": "failed" if result.returncode != 0 else "auditing"}
                    manifest["runs"].append(entry)
                    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
                    for source, destination in ((stage / "stdout.txt", worker_stdout),
                                                (stage / "stderr.txt", worker_stderr)):
                        if not source.is_file():
                            if result.returncode != 0:
                                continue
                            raise FileNotFoundError(f"worker log missing for {stem}: {source}")
                        shutil.copyfile(source, destination)
                    if worker_stdout.is_file():
                        entry["workerStdoutSha256"] = sha256(worker_stdout)
                    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
                    if result.returncode != 0:
                        raise RuntimeError(f"NativeWorker failed for {stem}; artifacts preserved at {output}")
                    samples = read_jsonl(jsonl)
                    if not samples or any(sample.seed != seed or sample.start_type != start for sample in samples):
                        raise ValueError(f"empty or mislabeled samples for {stem}")
                    raw_lines = jsonl.read_text(encoding="utf-8").splitlines()
                    if any(not line.strip() for line in raw_lines):
                        raise ValueError(f"blank JSONL record for {stem}")
                    raw = [json.loads(line) for line in raw_lines]
                    if len(raw) != len(samples) or not raw or any(line.get("provenance") != raw[0].get("provenance") for line in raw):
                        raise ValueError(f"trajectory provenance changed or missing for {stem}")
                    provenance = raw[0].get("provenance")
                    if not isinstance(provenance, dict) \
                            or provenance.get("searchMode") != requested_search_mode \
                            or provenance.get("requestedSearchMode") != requested_search_mode \
                            or provenance.get("budgetMilliseconds") != budget_ms \
                            or provenance.get("maxSimulations") != max_simulations:
                        raise ValueError(f"native provenance does not match requested mode/budget for {stem}")
                    stage_provenance_path = stage / "stage_provenance.json"
                    stage_provenance = json.loads(stage_provenance_path.read_text(encoding="utf-8"))
                    expected_assemblies = {"NativeWorker": "nativeWorker", "Search": "search",
                                           "CombatSolver": "combatSolver"}
                    if Path(stage_provenance.get("stageRoot", "")).resolve() != stage \
                            or Path(stage_provenance.get("publishOutput", "")).resolve() != stage / "data_NativeWorker_windows_x86_64" \
                            or len(stage_provenance.get("assemblies", [])) != 3 \
                            or {item.get("label") for item in stage_provenance["assemblies"]} != set(expected_assemblies):
                        raise ValueError(f"isolated stage provenance differs from request for {stem}")
                    for item in stage_provenance["assemblies"]:
                        loaded = provenance["assemblies"][expected_assemblies[item["label"]]]
                        if Path(item["path"]).resolve() != Path(loaded["path"]).resolve() \
                                or item["mvid"].lower() != loaded["mvid"].lower() \
                                or item["sha256"].lower() != loaded["sha256"].lower() \
                                or sha256(Path(item["path"])).lower() != item["sha256"].lower():
                            raise ValueError(f"loaded assembly differs from isolated stage for {stem}")
                    metrics = provenance.get("decisionMetrics")
                    if not isinstance(metrics, list) or len(metrics) != len(samples):
                        raise ValueError(f"native decision metrics are not aligned with samples for {stem}")
                    for line, metric in zip(raw, metrics, strict=True):
                        if type(metric.get("simulations")) is not int or not 0 < metric["simulations"] <= max_simulations \
                                or type(metric.get("elapsedMilliseconds")) not in (int, float) \
                                or metric["elapsedMilliseconds"] < budget_ms \
                                or line.get("simulations") != metric["simulations"] \
                                or line.get("stateKey") != metric.get("stateKey") \
                                or metric.get("searchMode") != requested_search_mode \
                                or metric.get("maxSimulations") != max_simulations \
                                or metric.get("budgetMilliseconds") != budget_ms \
                                or type(metric.get("networkPriorCalls")) is not int \
                                or type(metric.get("networkValueCalls")) is not int \
                                or type(metric.get("networkFallbacks")) is not int \
                                or metric["networkFallbacks"] != 0:
                            raise ValueError(f"native decision mode, budget, simulations or fallback differs for {stem}")
                    if provenance.get("modelScored") != sum(item["networkPriorCalls"] for item in metrics) \
                            or provenance.get("modelUsed") != sum(item["networkValueCalls"] for item in metrics) \
                            or provenance.get("modelFallbacks") != sum(item["networkFallbacks"] for item in metrics):
                        raise ValueError(f"native network counters disagree for {stem}")
                    if policy == "baseline":
                        if provenance.get("modelLoadStatus") != "pure-mcts:no-model-configured" \
                                or provenance.get("modelUsed") != 0 \
                                or provenance.get("modelScored") != 0 \
                                or provenance.get("modelFallbacks") != 0 \
                                or any(item["networkPriorCalls"] != 0 or item["networkValueCalls"] != 0
                                       for item in metrics):
                            raise ValueError(f"baseline native provenance is not pure MCTS for {stem}")
                    elif not (str(provenance.get("modelLoadStatus", "")).startswith("model-ready")
                               and model_hash.lower() in str(provenance.get("modelLoadStatus", "")).lower()
                               and provenance.get("modelShadow") is False
                               and provenance.get("modelFallbacks") == 0
                               and all(item["networkPriorCalls"] > 0 and item["networkValueCalls"] > 0
                                       for item in metrics)):
                        raise ValueError(f"candidate native provenance does not show active tree guidance for {stem}")
                    entry.update({"sha256": sha256(jsonl), "samples": len(samples),
                                  "stageProvenanceSha256": sha256(stage_provenance_path),
                                  "status": "complete",
                                  "outcome": samples[0].outcome, "value": samples[0].value_target,
                                  "searchMode": provenance["searchMode"],
                                  "maxSimulations": provenance["maxSimulations"],
                                  "budgetMilliseconds": provenance["budgetMilliseconds"]})
                    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    manifest["status"] = "complete"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def _read_research_split(path: Path) -> dict:
    split = json.loads(path.read_text(encoding="utf-8"))
    if split.get("format") != RESEARCH_SPLIT_FORMAT:
        raise ValueError("unsupported research seed split")
    sizes = {"trainSeeds": 20, "validationSeeds": 5, "evaluationSeeds": 10}
    all_seeds = []
    for field, size in sizes.items():
        seeds = split.get(field)
        if not isinstance(seeds, list) or len(seeds) != size \
                or any(type(seed) is not str or not seed.strip() for seed in seeds):
            raise ValueError(f"research split requires {size} nonempty {field}")
        all_seeds.extend(seeds)
    if len(set(all_seeds)) != len(all_seeds):
        raise ValueError("research train/validation/evaluation seeds overlap")
    return split


def _model_lineage(model: Path) -> set[str]:
    metadata = json.loads(model.with_suffix(".manifest.json").read_text(encoding="utf-8")).get("training")
    if not isinstance(metadata, dict):
        raise ValueError(f"ONNX manifest lacks training lineage: {model}")
    seeds = []
    for field in ("trainSeeds", "validationSeeds"):
        values = metadata.get(field)
        if not isinstance(values, list) or not values or any(type(seed) is not str or not seed for seed in values):
            raise ValueError(f"ONNX manifest lacks valid {field}: {model}")
        seeds.extend(values)
    if len(seeds) != len(set(seeds)):
        raise ValueError(f"ONNX training/validation lineage overlaps: {model}")
    return set(seeds)


def _model_source_hashes(model: Path | None) -> tuple[str | None, str | None]:
    if model is None:
        return None, None
    manifest_path = model.with_suffix(".manifest.json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    checkpoint_hash = manifest.get("checkpointSha256")
    if not isinstance(checkpoint_hash, str) or re.fullmatch(r"[0-9a-fA-F]{64}", checkpoint_hash) is None:
        raise ValueError(f"ONNX manifest lacks a source checkpoint SHA256: {manifest_path}")
    return sha256(manifest_path), checkpoint_hash.lower()


def _read_deck_plan(path: Path, split: dict, split_hash: str) -> dict:
    plan = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(plan, dict) or set(plan) != {"format", "seedSplitSha256", "templates", "assignments"} \
            or plan["format"] != DECK_PLAN_FORMAT \
            or not isinstance(plan["seedSplitSha256"], str) \
            or plan["seedSplitSha256"].lower() != split_hash.lower():
        raise ValueError("deck plan format or frozen seed split SHA256 differs")
    templates = plan["templates"]
    assignments = plan["assignments"]
    all_seeds = set(split["trainSeeds"] + split["validationSeeds"] + split["evaluationSeeds"])
    if not isinstance(templates, dict) or len(templates) != 5 \
            or not isinstance(assignments, dict) or set(assignments) != all_seeds:
        raise ValueError("deck plan must define five templates and assign every frozen seed exactly once")
    for name, template in templates.items():
        if not isinstance(name, str) or not name \
                or not isinstance(template, dict) or set(template) != {"characterCards"}:
            raise ValueError("deck template name or fields are invalid")
        cards = template["characterCards"]
        if not isinstance(cards, list) or not 1 <= len(cards) <= 100 \
                or any(type(card) is not str or re.fullmatch(r"[A-Z0-9_]+", card) is None for card in cards) \
                or not set(cards) - IRONCLAD_STARTER_IDS:
            raise ValueError(f"deck template {name} needs explicit character cards including a nonstarter")
    if any(type(name) is not str or name not in templates for name in assignments.values()):
        raise ValueError("deck assignment references an unknown template")
    return plan


def _generated_scenario_bytes(seed: str, encounter: str, cards: list[str]) -> bytes:
    selection = {"count": len(cards), "ids": cards, "upgradeLevels": 0}
    empty = {"count": 0, "ids": [], "upgradeLevels": 0}
    spec = {"schemaVersion": 1, "mode": "Setup", "seed": seed,
            "characterId": "IRONCLAD", "encounterId": encounter,
            "encounterKind": "Monster", "ascension": 0,
            "includeStartingDeck": False, "includeStartingRelics": True,
            "includeAscendersBane": False, "characterCards": selection,
            "colorlessCards": empty, "relics": empty, "potions": empty}
    return (json.dumps(spec, sort_keys=True, indent=2) + "\n").encode("utf-8")


def _save_research_manifest(path: Path, manifest: dict) -> None:
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def run_research_wave(*, phase: str, split_path: Path, output: Path,
                      game_dir: Path, ritsu_root: Path, old_model: Path | None = None,
                      new_model: Path | None = None, budget_ms: int = 1000,
                      max_decisions: int = 256, timeout_seconds: int = 1800,
                      resume: bool = False, continue_after_error: bool = False,
                      deck_plan: Path | None = None) -> dict:
    """Run a fixed, serial full-combat research grid with immutable per-run artifacts.

    The M4 wave entry above remains unchanged. Research runs have no simulation
    cap and use the strict one-trajectory Native probe audit for every job.
    """
    if phase not in {"teacher", "evaluation"}:
        raise ValueError("research phase must be teacher or evaluation")
    if budget_ms < 1000 or max_decisions < 1 or timeout_seconds < 1:
        raise ValueError("research requires at least 1000 ms and positive decision/timeout limits")
    split_path = split_path.resolve(strict=True)
    split = _read_research_split(split_path)
    split_hash = sha256(split_path)
    if deck_plan is not None:
        deck_plan = deck_plan.resolve(strict=True)
        plan = _read_deck_plan(deck_plan, split, split_hash)
        plan_hash = sha256(deck_plan)
    else:
        plan = None
        plan_hash = None
    game_dir = game_dir.resolve(strict=True)
    ritsu_root = ritsu_root.resolve(strict=True)
    repo = Path(__file__).resolve().parents[3]
    catalog = repo / "combat" / "coverage" / "combat-hooks.json"
    if json.loads(catalog.read_text(encoding="utf-8")).get("gameVersion") != "0.111.0":
        raise ValueError("Combat Solver coverage catalog is not pinned to v0.111.0")
    old_hash = new_hash = None
    if old_model is not None:
        old_model = old_model.resolve(strict=True)
        old_hash = checked_model(old_model)
        if _model_lineage(old_model) & set().union(
                split["trainSeeds"], split["validationSeeds"], split["evaluationSeeds"]):
            raise ValueError("research seeds overlap old model training/validation lineage")
    if phase == "evaluation":
        if new_model is None:
            raise ValueError("evaluation requires a frozen new model")
        new_model = new_model.resolve(strict=True)
        new_hash = checked_model(new_model)
        if old_hash is not None and new_hash.lower() == old_hash.lower():
            raise ValueError("old and new evaluation models have identical ONNX hashes")
        new_lineage = _model_lineage(new_model)
        if new_lineage & set(split["evaluationSeeds"]):
            raise ValueError("evaluation seeds overlap new model training/validation lineage")
        if not new_lineage <= set(split["trainSeeds"] + split["validationSeeds"]):
            raise ValueError("new model training lineage is outside the frozen research split")
    elif new_model is not None:
        raise ValueError("teacher collection does not load a model")
    if plan is not None:
        old_manifest_hash, old_checkpoint_hash = _model_source_hashes(old_model)
        new_manifest_hash, new_checkpoint_hash = _model_source_hashes(new_model)

    seeds = ([("train", seed) for seed in split["trainSeeds"]]
             + [("validation", seed) for seed in split["validationSeeds"]]) if phase == "teacher" \
        else [("evaluation", seed) for seed in split["evaluationSeeds"]]
    policies = ("teacher",) if phase == "teacher" else ("pure-mcts", "old-tree", "new-tree")
    request = {"phase": phase, "splitPath": str(split_path), "splitSha256": split_hash,
               "gameDir": str(game_dir), "ritsuRoot": str(ritsu_root),
               "oldOnnx": str(old_model) if old_model else None, "oldOnnxSha256": old_hash,
               "newOnnx": str(new_model) if new_model else None, "newOnnxSha256": new_hash,
               "coverageCatalogSha256": sha256(catalog), "gameVersion": "v0.111.0",
               "encounters": list(RESEARCH_ENCOUNTERS), "startType": "full_combat",
               "baselineSearchMode": BASELINE_SEARCH_MODE,
               "candidateSearchMode": CANDIDATE_SEARCH_MODE,
               "budgetMilliseconds": budget_ms, "maxDecisions": max_decisions,
               "maxSimulations": None, "timeoutSeconds": timeout_seconds,
               "trainSeeds": split["trainSeeds"], "validationSeeds": split["validationSeeds"],
               "evaluationSeeds": split["evaluationSeeds"]}
    if plan is not None:
        request.update({"deckPlanPath": str(deck_plan), "deckPlanSha256": plan_hash,
                        "oldOnnxManifestSha256": old_manifest_hash,
                        "newOnnxManifestSha256": new_manifest_hash,
                        "oldCheckpointSha256": old_checkpoint_hash,
                        "newCheckpointSha256": new_checkpoint_hash})
    output = output.resolve()
    manifest_path = output / "manifest.json"
    if resume:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("format") != RESEARCH_WAVE_FORMAT or manifest.get("request") != request:
            raise ValueError("resume request differs from frozen research manifest")
        for run in manifest["runs"]:
            if run["status"] == "running":
                run["status"] = "interrupted"
                run["error"] = "previous process stopped before the job was audited; artifacts retained"
        _save_research_manifest(manifest_path, manifest)
    else:
        output.mkdir(parents=True, exist_ok=False)
        (output / "runs").mkdir()
        if plan is not None:
            (output / "inputs").mkdir()
        runs = []
        for seed_index, (partition, seed) in enumerate(seeds):
            for encounter in RESEARCH_ENCOUNTERS:
                template_name = plan["assignments"][seed] if plan is not None else None
                scenario_name = f"inputs/{seed_index:03d}-{encounter}.json" if plan is not None else None
                scenario_hash = hashlib.sha256(_generated_scenario_bytes(
                    seed, encounter, plan["templates"][template_name]["characterCards"])).hexdigest() \
                    if plan is not None else None
                for policy in policies:
                    stem = f"{seed_index:03d}-{encounter}-{policy}"
                    runs.append({"seed": seed, "partition": partition,
                                 "encounter": encounter, "policy": policy,
                                 "startType": "full_combat", "scenario": "ordinary",
                                 "requestedSearchMode": BASELINE_SEARCH_MODE if policy in {"teacher", "pure-mcts"}
                                                        else CANDIDATE_SEARCH_MODE,
                                 "requestedModelSha256": old_hash if policy == "old-tree" else
                                                         new_hash if policy == "new-tree" else None,
                                 "budgetMilliseconds": budget_ms, "maxDecisions": max_decisions,
                                 "maxSimulations": None,
                                 **({"deckTemplate": template_name,
                                     "generatedScenario": scenario_name,
                                     "generatedScenarioSha256": scenario_hash}
                                    if plan is not None else {}),
                                 "jsonl": f"runs/{stem}.jsonl",
                                 "probeReport": f"runs/{stem}.probe.json",
                                 "status": "unavailable" if policy == "old-tree" and old_model is None else "pending",
                                 **({"error": "no valid old ABI model was supplied"}
                                    if policy == "old-tree" and old_model is None else {})})
        manifest = {"format": RESEARCH_WAVE_FORMAT, "request": request,
                    "status": "pending", "runs": runs}
        _save_research_manifest(manifest_path, manifest)

    if plan is not None:
        for run in manifest["runs"]:
            spec_path = output / run["generatedScenario"]
            spec_bytes = _generated_scenario_bytes(
                run["seed"], run["encounter"], plan["templates"][run["deckTemplate"]]["characterCards"])
            digest = hashlib.sha256(spec_bytes).hexdigest()
            if digest != run["generatedScenarioSha256"]:
                raise ValueError(f"frozen scenario specification differs for {spec_path}")
            if not spec_path.is_file():
                if any(item["generatedScenario"] == run["generatedScenario"]
                       and item["status"] not in {"pending", "unavailable"}
                       for item in manifest["runs"]):
                    raise FileNotFoundError(f"completed/interrupted scenario specification missing: {spec_path}")
                spec_path.parent.mkdir(parents=True, exist_ok=True)
                with spec_path.open("xb") as handle:
                    handle.write(spec_bytes)
            if sha256(spec_path) != digest:
                raise ValueError(f"scenario specification SHA256 changed: {spec_path}")

    # Import here to avoid the native_probe -> experiments module import cycle.
    from .native_probe import run_probe

    reference_assemblies = next((run.get("assemblies") for run in manifest["runs"]
                                 if run.get("status") == "complete"), None)
    for run in manifest["runs"]:
        if run["status"] != "pending":
            continue
        model = old_model if run["policy"] == "old-tree" else new_model if run["policy"] == "new-tree" else None
        search_mode = BASELINE_SEARCH_MODE if model is None else CANDIDATE_SEARCH_MODE
        path = output / run["jsonl"]
        scenario = output / run["generatedScenario"] if plan is not None else None
        if scenario is not None and sha256(scenario) != run["generatedScenarioSha256"]:
            raise ValueError(f"scenario specification changed before Native launch: {scenario}")
        run["status"] = "running"
        run["startedAtUtc"] = datetime.now(timezone.utc).isoformat()
        manifest["status"] = "running"
        _save_research_manifest(manifest_path, manifest)
        try:
            audit = run_probe(output=path, seed=run["seed"], encounter=run["encounter"],
                              search_mode=search_mode, game_dir=game_dir, ritsu_root=ritsu_root,
                              model=model, max_decisions=max_decisions, budget_ms=budget_ms,
                              max_simulations=None, timeout_seconds=timeout_seconds,
                              generated_scenario=scenario)
            if reference_assemblies is None:
                reference_assemblies = audit["assemblies"]
            elif _assembly_build_identity(audit["assemblies"]) != _assembly_build_identity(reference_assemblies):
                raise ValueError("loaded assembly MVID/SHA256 differs from this research wave")
            run.update({"status": "complete", "audit": {
                key: audit[key] for key in ("samples", "outcome", "valueTarget", "terminal",
                                       "entryHp", "playerHp", "initialEnemyEffectiveHp",
                                       "enemyDamageLost", "simulations",
                                       "elapsedMilliseconds", "priorCalls", "valueCalls",
                                       "fallbacks", "jsonlSha256", "workerStdoutSha256")},
                        "assemblies": audit["assemblies"]})
            run["audit"]["choiceSamples"] = len(audit["choiceRows"])
        except Exception as error:
            run.update({"status": "error", "error": f"{type(error).__name__}: {error}"})
            manifest["status"] = "halted"
            _save_research_manifest(manifest_path, manifest)
            if not continue_after_error:
                raise
        finally:
            run["finishedAtUtc"] = datetime.now(timezone.utc).isoformat()
            _save_research_manifest(manifest_path, manifest)
    statuses = {run["status"] for run in manifest["runs"]}
    manifest["status"] = "complete" if statuses == {"complete"} else \
        "complete-with-missing" if statuses <= {"complete", "unavailable"} else \
        "complete-with-errors" if not statuses & {"pending", "running"} else "incomplete"
    _save_research_manifest(manifest_path, manifest)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("bootstrap", "evaluate", "selfplay", "teacher", "research-evaluate"))
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--game-dir", required=True, type=Path)
    parser.add_argument("--ritsu-root", required=True, type=Path)
    parser.add_argument("--model", type=Path)
    parser.add_argument("--old-model", type=Path)
    parser.add_argument("--new-model", type=Path)
    parser.add_argument("--split", type=Path)
    parser.add_argument("--deck-plan", type=Path)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--continue-after-error", action="store_true")
    parser.add_argument("--timeout-seconds", type=int, default=1800)
    parser.add_argument("--champion", type=Path)
    parser.add_argument("--seed", action="append")
    parser.add_argument("--encounter", action="append")
    parser.add_argument("--scenario", action="append", choices=tuple(SCENARIOS))
    parser.add_argument("--budget-ms", type=int, default=1000)
    parser.add_argument("--candidate-search-mode", choices=(CANDIDATE_SEARCH_MODE,), default=CANDIDATE_SEARCH_MODE)
    parser.add_argument("--max-simulations", type=int)
    parser.add_argument("--max-decisions", type=int, default=256)
    args = parser.parse_args()
    if args.mode in {"teacher", "research-evaluate"}:
        if args.deck_plan is None and not args.resume:
            parser.error("a new research wave requires the frozen --deck-plan")
        if args.split is None or args.model is not None or args.champion is not None \
                or args.seed is not None or args.encounter is not None or args.scenario is not None \
                or args.max_simulations is not None:
            parser.error("research waves require --split, fixed encounters and no simulation cap/fixture/M4 model")
        result = run_research_wave(
            phase="teacher" if args.mode == "teacher" else "evaluation",
            split_path=args.split, output=args.output, game_dir=args.game_dir,
            ritsu_root=args.ritsu_root, old_model=args.old_model, new_model=args.new_model,
            budget_ms=args.budget_ms, max_decisions=args.max_decisions,
            timeout_seconds=args.timeout_seconds, resume=args.resume,
            continue_after_error=args.continue_after_error, deck_plan=args.deck_plan)
        print(json.dumps({"status": result["status"], "runs": len(result["runs"]),
                          "complete": sum(run["status"] == "complete" for run in result["runs"])}, indent=2))
        return 0 if result["status"] == "complete" else 1
    if args.model is None or not args.seed or not args.encounter:
        parser.error("M4 waves require --model, --seed and --encounter")
    if args.split is not None or args.deck_plan is not None or args.old_model is not None \
            or args.new_model is not None or args.resume:
        parser.error("research-only arguments are not accepted by M4 waves")
    result = run_wave(mode=args.mode, output=args.output, game_dir=args.game_dir,
                      ritsu_root=args.ritsu_root, model=args.model, seeds=args.seed,
                      encounters=args.encounter, budget_ms=args.budget_ms,
                      max_decisions=args.max_decisions,
                      max_simulations=50 if args.max_simulations is None else args.max_simulations,
                      candidate_search_mode=args.candidate_search_mode,
                      champion=args.champion, scenarios=args.scenario)
    print(json.dumps({"status": result["status"], "runs": len(result["runs"])}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
