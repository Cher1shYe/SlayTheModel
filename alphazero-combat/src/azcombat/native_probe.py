"""Run one isolated headless NativeWorker regression and audit its actual trajectory."""
from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess

from .experiments import REGISTERED_ENCOUNTERS, checked_model, sha256
from .promotion import ASSEMBLY, EXPORT_OUT
from .reward import Outcome, TerminalResult, score_result
from .samples import read_jsonl


def _write_new(path: Path, content: str) -> None:
    with path.open("x", encoding="utf-8") as handle:
        handle.write(content)


def _selected_candidate_indices(choice: dict, payload: dict) -> list[int]:
    selected = payload.get("SelectedCards")
    if not isinstance(selected, list):
        raise ValueError("choice action lacks selected-card identities")
    indices = []
    for item in selected:
        if not isinstance(item, dict) or not isinstance(item.get("CardId"), str) \
                or type(item.get("UpgradeLevel")) is not int \
                or type(item.get("OptionOccurrence")) is not int:
            raise ValueError("selected-card identity is malformed")
        candidates = [candidate for candidate in choice["candidates"]
                      if candidate["modelId"] == "CARD." + item["CardId"]
                      and candidate["upgradeLevel"] == item["UpgradeLevel"]]
        occurrence = item["OptionOccurrence"]
        if occurrence < 0 or occurrence >= len(candidates):
            raise ValueError("selected-card occurrence is not in the choice candidates")
        indices.append(candidates[occurrence]["combatCardIndex"])
    if len(indices) != len(set(indices)):
        raise ValueError("choice selected the same card instance twice")
    return indices


def _audit_generated_deck(provenance: dict, expected: dict) -> None:
    spec_path = expected.get("generatedScenarioPath")
    actual = provenance.get("generatedDeck")
    if spec_path is None:
        if actual is not None:
            raise ValueError("Native used an unrequested generated deck")
        return
    path = Path(spec_path).resolve(strict=True)
    digest = expected.get("generatedScenarioSha256")
    if sha256(path).lower() != str(digest).lower():
        raise ValueError("generated scenario file changed after launch")
    spec = json.loads(path.read_text(encoding="utf-8"))
    cards = spec["characterCards"]["ids"]
    empty = {"count": 0, "ids": [], "upgradeLevels": 0}
    if spec.get("schemaVersion") != 1 or spec.get("mode") != "Setup" \
            or spec.get("seed") != expected["seed"] or spec.get("encounterId") != expected["encounter"] \
            or spec.get("characterId") != "IRONCLAD" or spec.get("ascension") != 0 \
            or spec.get("includeStartingDeck") is not False \
            or spec.get("includeStartingRelics") is not True \
            or spec.get("includeAscendersBane") is not False \
            or type(cards) is not list or any(type(card) is not str for card in cards) \
            or spec["characterCards"].get("count") != len(cards) \
            or spec["characterCards"].get("upgradeLevels") != 0 \
            or any(spec.get(name) != empty for name in ("colorlessCards", "relics", "potions")):
        raise ValueError("generated deck specification is not the frozen A0 character-only setup")
    if not isinstance(actual, dict) or actual.get("specSha256", "").lower() != str(digest).lower() \
            or Path(str(actual.get("specPath", ""))).resolve() != path \
            or actual.get("characterId") != "IRONCLAD" \
            or actual.get("encounterId") != expected["encounter"] \
            or not isinstance(actual.get("resolverEncounterId"), str) \
            or not actual["resolverEncounterId"] \
            or actual.get("ascension") != 0 or actual.get("includeStartingDeck") is not False \
            or actual.get("requestedCards") != cards or actual.get("resolvedCards") != cards \
            or actual.get("actualDeck") != [{"id": card, "upgradeLevel": 0} for card in cards] \
            or not isinstance(actual.get("catalogFingerprint"), str) \
            or re.fullmatch(r"[0-9a-fA-F]{64}", actual["catalogFingerprint"]) is None:
        raise ValueError("Native generated deck provenance or actual card order differs from request")


def run_probe(*, output: Path, seed: str, encounter: str, search_mode: str,
              game_dir: Path, ritsu_root: Path, model: Path | None = None,
              fixture_cards: list[str] | None = None, force_card: str | None = None,
              initial_hp: int | None = None, max_decisions: int = 32,
              budget_ms: int = 1000, max_simulations: int | None = None,
              timeout_seconds: int = 700, root_parity_output: Path | None = None,
              generated_scenario: Path | None = None,
              regression_only: bool = False) -> dict:
    if output.suffix != ".jsonl" or output.exists() or output.with_suffix(".probe.json").exists():
        raise FileExistsError("probe requires a new .jsonl output and report path")
    if not seed or encounter not in REGISTERED_ENCOUNTERS:
        raise ValueError("probe requires a seed and a registered encounter")
    if search_mode not in {"pure-mcts", "policy-value-tree-v1"}:
        raise ValueError("unsupported probe search mode")
    if (search_mode == "pure-mcts") != (model is None):
        raise ValueError("pure MCTS cannot load a model; tree mode requires one")
    if root_parity_output is not None and search_mode != "policy-value-tree-v1":
        raise ValueError("root numerical parity requires a tree model")
    if force_card is not None and (not fixture_cards or force_card not in fixture_cards):
        raise ValueError("forced-card regression requires that card in a choice fixture")
    if fixture_cards is not None and not fixture_cards:
        raise ValueError("choice fixture card list is empty")
    if initial_hp is not None and (initial_hp < 1 or fixture_cards is None):
        raise ValueError("low-HP fixture requires a positive HP and a fixture deck")
    if generated_scenario is not None and (fixture_cards is not None or force_card is not None
                                           or initial_hp is not None):
        raise ValueError("generated deck cannot be combined with a regression fixture")
    if max_decisions < 1 or budget_ms < 1000 or max_simulations is not None and max_simulations < 1 \
            or timeout_seconds < 1:
        raise ValueError("probe requires positive decisions/simulations and at least 1000 ms")
    if not game_dir.is_dir() or not ritsu_root.is_dir():
        raise FileNotFoundError("game or RitsuLib directory is missing")
    model_hash = None
    if model is not None:
        model = model.resolve(strict=True)
        model_hash = checked_model(model)
    if generated_scenario is not None:
        generated_scenario = generated_scenario.resolve(strict=True)
        spec = json.loads(generated_scenario.read_text(encoding="utf-8"))
        if not isinstance(spec, dict) or spec.get("seed") != seed or spec.get("encounterId") != encounter \
                or spec.get("characterId") != "IRONCLAD" or spec.get("ascension") != 0 \
                or spec.get("includeStartingDeck") is not False or spec.get("includeAscendersBane") is not False \
                or spec.get("mode") != "Setup":
            raise ValueError("generated scenario does not match this A0 deck-only Native request")
        scenario_hash = sha256(generated_scenario)
    else:
        scenario_hash = None
    shell = shutil.which("pwsh.exe") or shutil.which("pwsh")
    if shell is None:
        raise FileNotFoundError("PowerShell 7 is required")
    repo = Path(__file__).resolve().parents[3]
    script = repo / "scripts" / "native-worker.ps1"
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    stage = output.with_suffix(".stage")
    if stage.exists():
        raise FileExistsError(f"probe requires a new isolated stage: {stage}")
    if root_parity_output is not None:
        root_parity_output = root_parity_output.resolve()
        if root_parity_output == output or root_parity_output.exists():
            raise FileExistsError("root parity requires a new output separate from JSONL")
        root_parity_output.parent.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    for name in tuple(env):
        if name.startswith("STS2_MCTS_EXPORT_") or name.startswith("STS2_ALPHAZERO_"):
            env.pop(name)
    env.update({"STS2_MCTS_EXPORT_OUT": str(output), "STS2_MCTS_EXPORT_SEED": seed,
                "STS2_MCTS_EXPORT_ENCOUNTER": encounter,
                "STS2_MCTS_EXPORT_MAX_DECISIONS": str(max_decisions)})
    if generated_scenario is not None:
        env["STS2_MCTS_EXPORT_GENERATED_SCENARIO"] = str(generated_scenario)
    if root_parity_output is not None:
        env["STS2_ALPHAZERO_ROOT_PARITY_OUT"] = str(root_parity_output)
    if fixture_cards is not None:
        env["STS2_MCTS_EXPORT_CHOICE_FIXTURE"] = "1"
        env["STS2_MCTS_EXPORT_FIXTURE_CARDS"] = ",".join(fixture_cards)
    if force_card is not None:
        env["STS2_MCTS_EXPORT_FORCE_CARD"] = force_card
    if initial_hp is not None:
        env["STS2_MCTS_EXPORT_INITIAL_HP"] = str(initial_hp)
    if regression_only:
        env["STS2_MCTS_EXPORT_REGRESSION_ONLY"] = "1"
    command = [shell, "-NoProfile", "-File", str(script), "-GameDir", str(game_dir.resolve()),
               "-RitsuLibRoot", str(ritsu_root.resolve()), "-Mode", "solver-mcts-export",
               "-StageRoot", str(stage),
               "-TimeoutSeconds", str(timeout_seconds), "-SearchMode", search_mode,
               "-BudgetMilliseconds", str(budget_ms)]
    if model is not None:
        command.extend(["-OnnxModel", str(model)])
    if max_simulations is not None:
        command.extend(["-MaxSimulations", str(max_simulations)])
    report_path = output.with_suffix(".probe.json")
    report = {"format": "azcombat.native-probe.v1", "output": str(output), "seed": seed,
              "encounter": encounter, "requestedSearchMode": search_mode,
              "modelSha256": model_hash, "fixtureCards": fixture_cards, "forceCard": force_card,
              "initialHp": initial_hp, "maxDecisions": max_decisions,
              "budgetMilliseconds": budget_ms, "maxSimulations": max_simulations,
              "timeoutSeconds": timeout_seconds,
              "rootParityOutput": str(root_parity_output) if root_parity_output else None,
              "generatedScenarioPath": str(generated_scenario) if generated_scenario else None,
              "generatedScenarioSha256": scenario_hash,
              "stageRoot": str(stage),
              "regressionOnly": regression_only or force_card is not None, "status": "started"}
    _write_new(report_path, json.dumps(report, indent=2) + "\n")
    try:
        try:
            result = subprocess.run(command, cwd=repo, env=env, capture_output=True, text=True,
                                    encoding="utf-8", errors="replace", timeout=timeout_seconds + 300,
                                    check=False)
        except subprocess.TimeoutExpired as error:
            for suffix, content in ((".launcher.stdout.txt", error.stdout),
                                    (".launcher.stderr.txt", error.stderr)):
                if isinstance(content, bytes):
                    content = content.decode("utf-8", errors="replace")
                _write_new(output.with_suffix(suffix), content or "")
            for suffix, source in ((".worker.stdout.txt", stage / "stdout.txt"),
                                   (".worker.stderr.txt", stage / "stderr.txt")):
                if source.is_file():
                    with source.open("rb") as reader, output.with_suffix(suffix).open("xb") as writer:
                        shutil.copyfileobj(reader, writer)
            raise
        report["exitCode"] = result.returncode
        for suffix, content in ((".launcher.stdout.txt", result.stdout),
                                (".launcher.stderr.txt", result.stderr)):
            _write_new(output.with_suffix(suffix), content)
        for suffix, source in ((".worker.stdout.txt", stage / "stdout.txt"),
                               (".worker.stderr.txt", stage / "stderr.txt")):
            destination = output.with_suffix(suffix)
            if not source.is_file():
                if result.returncode != 0:
                    continue
                raise FileNotFoundError(f"worker log missing from isolated stage: {source}")
            with source.open("rb") as reader, destination.open("xb") as writer:
                shutil.copyfileobj(reader, writer)
        if result.returncode != 0:
            raise RuntimeError(f"NativeWorker failed; see {output.with_suffix('.worker.stderr.txt')}")
        report.update(audit_probe(output, expected=report))
        report["status"] = "complete"
        return report
    except Exception as error:
        report["status"] = "failed"
        report["error"] = str(error)
        raise
    finally:
        stage_provenance = stage / "stage_provenance.json"
        report["stageProvenanceSha256"] = sha256(stage_provenance) if stage_provenance.is_file() else None
        report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


def audit_probe(path: Path, *, expected: dict, verify_current_assembly: bool = True) -> dict:
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines or any(not line.strip() for line in lines):
        raise ValueError("probe JSONL is empty or contains blank lines")
    raw = [json.loads(line) for line in lines]
    samples = read_jsonl(path, allow_regression=bool(expected["regressionOnly"]))
    if len(samples) != len(raw):
        raise ValueError("strict/raw sample counts differ")
    provenance = raw[0]["provenance"]
    if any(line.get("provenance") != provenance for line in raw):
        raise ValueError("trajectory provenance differs across samples")
    if provenance.get("regressionOnly") is not expected["regressionOnly"] \
            or provenance.get("forcedFixtureCard") != expected["forceCard"] \
            or provenance.get("requestedSearchMode") != expected["requestedSearchMode"] \
            or provenance.get("searchMode") != expected["requestedSearchMode"] \
            or provenance.get("maxSimulations") != expected["maxSimulations"] \
            or provenance.get("budgetMilliseconds") != expected["budgetMilliseconds"] \
            or provenance.get("maxDecisions") != expected["maxDecisions"] \
            or provenance.get("seed") != expected["seed"] \
            or provenance.get("encounter") != expected["encounter"]:
        raise ValueError("native provenance differs from probe request")
    _audit_generated_deck(provenance, expected)
    metrics = provenance.get("decisionMetrics")
    if not isinstance(metrics, list) or len(metrics) != len(samples):
        raise ValueError("decision metrics are not aligned with samples")
    choice_rows = []
    rates = []
    for index, (sample, line, metric) in enumerate(zip(samples, raw, metrics, strict=True)):
        if sample.seed != expected["seed"] or sample.start_type != "full_combat":
            raise ValueError("sample seed/start differs from request")
        legal_ids = {action.action_id for action in sample.legal_actions}
        if metric.get("selectedActionId") not in legal_ids \
                or metric.get("stateKey") != line.get("stateKey") \
                or metric.get("simulations") != line.get("simulations"):
            raise ValueError("selected action or root metrics are misaligned")
        simulations = metric.get("simulations")
        elapsed = metric.get("elapsedMilliseconds")
        if type(simulations) is not int or simulations <= 0 \
                or type(elapsed) not in (int, float) or not math.isfinite(elapsed) \
                or elapsed < expected["budgetMilliseconds"] \
                or expected["maxSimulations"] is not None and simulations > expected["maxSimulations"] \
                or metric.get("maxSimulations") != expected["maxSimulations"] \
                or metric.get("budgetMilliseconds") != expected["budgetMilliseconds"] \
                or metric.get("searchMode") != expected["requestedSearchMode"] \
                or metric.get("networkFallbacks") != 0 \
                or metric.get("networkFallbackReason") is not None:
            raise ValueError(f"invalid simulation, budget, mode or fallback at decision {index}")
        prior, value = metric.get("networkPriorCalls"), metric.get("networkValueCalls")
        if expected["requestedSearchMode"] == "pure-mcts":
            if prior != 0 or value != 0:
                raise ValueError("pure MCTS made network calls")
        elif type(prior) is not int or type(value) is not int or prior <= 0 or value <= 0:
            raise ValueError("tree decision did not use prior and value")
        rates.append(simulations / (elapsed / 1000))
        if sample.observation["choice"] is not None:
            if not sample.legal_actions or any(action.kind != "NestedChoice" for action in sample.legal_actions) \
                    or metric.get("choiceLayer", 0) < 1:
                raise ValueError("choice observation is not an actual choice root")
            choice = sample.observation["choice"]
            layer = metric["choiceLayer"]
            if layer == 1:
                if choice["completedSelections"]:
                    raise ValueError("first choice layer contains a future selection")
            else:
                previous = samples[index - 1] if index else None
                previous_metric = metrics[index - 1] if index else None
                previous_choice = previous.observation["choice"] if previous is not None else None
                if previous_choice is None or previous_metric.get("choiceLayer") != layer - 1 \
                        or previous_metric.get("parentDecision") != metric.get("parentDecision") \
                        or previous_metric.get("parentActionId") != metric.get("parentActionId"):
                    raise ValueError("nested choice is not adjacent to its parent layer")
                selected = next((action for action in previous.legal_actions
                                 if action.action_id == previous_metric["selectedActionId"]), None)
                if selected is None or not isinstance(selected.payload, dict):
                    raise ValueError("previous choice selected action cannot be mapped")
                expected_completed = [*previous_choice["completedSelections"],
                                      {"effect": previous_choice["effect"],
                                       "combatCardIndices": _selected_candidate_indices(
                                           previous_choice, selected.payload)}]
                if choice["completedSelections"] != expected_completed:
                    raise ValueError("completedSelections differs from the committed prior choice")
            choice_rows.append({"index": index, "choiceLayer": metric["choiceLayer"],
                                "choice": choice,
                                "simulations": simulations, "elapsedMilliseconds": elapsed,
                                "simulationsPerSecond": rates[-1],
                                "networkPriorCalls": prior, "networkValueCalls": value})
    if provenance.get("modelScored") != sum(item["networkPriorCalls"] for item in metrics) \
            or provenance.get("modelUsed") != sum(item["networkValueCalls"] for item in metrics) \
            or provenance.get("modelFallbacks") != 0:
        raise ValueError("network totals differ from actual per-decision calls")
    status = provenance.get("modelLoadStatus", "")
    if expected["modelSha256"] is None:
        if status != "pure-mcts:no-model-configured":
            raise ValueError("pure baseline attempted to load a model")
    elif not status.startswith("model-ready") or expected["modelSha256"].lower() not in status.lower():
        raise ValueError("Native loaded a different model")
    transitions = provenance.get("enemyHpTransitions")
    if not isinstance(transitions, list) or any(
            type(item.get("before")) is not int or type(item.get("after")) is not int
            or type(item.get("damage")) is not int
            or item["damage"] != max(0, item["before"] - item["after"])
            for item in transitions):
        raise ValueError("native enemy HP transition evidence is invalid")
    if not transitions or transitions[0]["before"] != provenance.get("initialEnemyEffectiveHp") \
            or sum(item["damage"] for item in transitions) != provenance.get("enemyDamageLost"):
        raise ValueError("cumulative actual enemy damage differs from native transitions")
    if len(transitions) != len(samples) or any(
            previous["after"] != following["before"]
            for previous, following in zip(transitions, transitions[1:])):
        raise ValueError("native enemy HP transitions are missing or discontinuous")
    outcome = Outcome(samples[0].outcome)
    if any(sample.outcome != outcome.value or sample.value_target != samples[0].value_target
           for sample in samples):
        raise ValueError("outcome/value was not uniformly backfilled")
    if provenance.get("terminal") is not (outcome is not Outcome.UNRESOLVED):
        raise ValueError("native settlement disagrees with outcome")
    value_target = score_result(TerminalResult(
        outcome, provenance["entryHp"], provenance["playerHp"],
        provenance["enemyDamageLost"], provenance["initialEnemyEffectiveHp"]))
    if abs(value_target - samples[0].value_target) > 1e-6:
        raise ValueError("value target differs from native HP and reward definition")
    worker_log = path.with_suffix(".worker.stdout.txt").read_text(encoding="utf-8")
    worker_err = path.with_suffix(".worker.stderr.txt").read_text(encoding="utf-8")
    if "SLAY_WORKER_FAILED" in worker_log + worker_err or "pure-mcts-fallback" in worker_log + worker_err:
        raise ValueError("worker failure/fallback diagnostic is present")
    loaded = ASSEMBLY.findall(worker_log)
    if len(loaded) != 3 or {item[0] for item in loaded} != {"NativeWorker", "Search", "CombatSolver"}:
        raise ValueError("actual loaded assembly identities are incomplete")
    stage_root = expected.get("stageRoot")
    if stage_root is not None:
        stage = Path(stage_root).resolve(strict=True)
        stage_provenance_path = stage / "stage_provenance.json"
        stage_provenance = json.loads(stage_provenance_path.read_text(encoding="utf-8"))
        staged = stage_provenance.get("assemblies")
        if Path(stage_provenance.get("stageRoot", "")).resolve() != stage \
                or not isinstance(staged, list) or len(staged) != 3 \
                or {item.get("label") for item in staged if isinstance(item, dict)} \
                != {"NativeWorker", "Search", "CombatSolver"}:
            raise ValueError("isolated stage provenance is incomplete or mismatched")
        staged_by_label = {item["label"]: item for item in staged}
    fields = {"NativeWorker": "nativeWorker", "Search": "search", "CombatSolver": "combatSolver"}
    for label, assembly_path, mvid, digest in loaded:
        identity = provenance["assemblies"][fields[label]]
        if Path(identity["path"]).resolve() != Path(assembly_path).resolve() \
                or identity["mvid"].lower() != mvid.lower() \
                or identity["sha256"].lower() != digest.lower() \
                or verify_current_assembly and sha256(Path(assembly_path)).lower() != digest.lower():
            raise ValueError(f"loaded {label} assembly path/MVID/SHA256 differs")
        if stage_root is not None:
            staged_identity = staged_by_label[label]
            if not Path(assembly_path).resolve().is_relative_to(stage / "data_NativeWorker_windows_x86_64") \
                    or Path(staged_identity["path"]).resolve() != Path(assembly_path).resolve() \
                    or staged_identity["mvid"].lower() != mvid.lower() \
                    or staged_identity["sha256"].lower() != digest.lower():
                raise ValueError(f"loaded {label} assembly differs from isolated stage")
    if EXPORT_OUT.findall(worker_log) != [str(path.resolve())]:
        raise ValueError("Native export path differs from requested output")
    diagnostic_files = [str(file) for file in path.parent.glob(path.name + ".*diagnostic.json")]
    if diagnostic_files:
        raise ValueError(f"native diagnostics exist: {diagnostic_files}")
    return {"samples": len(samples), "outcome": outcome.value, "valueTarget": samples[0].value_target,
            "terminal": provenance["terminal"], "entryHp": provenance["entryHp"],
            "playerHp": provenance["playerHp"],
            "initialEnemyEffectiveHp": provenance["initialEnemyEffectiveHp"],
            "enemyDamageLost": provenance["enemyDamageLost"],
            "enemyHpTransitions": len(transitions), "choiceRows": choice_rows,
            "simulations": [item["simulations"] for item in metrics],
            "elapsedMilliseconds": [item["elapsedMilliseconds"] for item in metrics],
            "simulationsPerSecond": rates,
            "priorCalls": provenance["modelScored"], "valueCalls": provenance["modelUsed"],
            "fallbacks": provenance["modelFallbacks"],
            "assemblies": provenance["assemblies"], "jsonlSha256": sha256(path),
            "workerStdoutSha256": sha256(path.with_suffix(".worker.stdout.txt"))}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--seed", required=True)
    parser.add_argument("--encounter", default="CULTISTS_NORMAL")
    parser.add_argument("--search-mode", choices=("pure-mcts", "policy-value-tree-v1"), required=True)
    parser.add_argument("--model", type=Path)
    parser.add_argument("--fixture-cards", help="Comma-separated registered card IDs")
    parser.add_argument("--force-card")
    parser.add_argument("--initial-hp", type=int)
    parser.add_argument("--max-decisions", type=int, default=32)
    parser.add_argument("--budget-ms", type=int, default=1000)
    parser.add_argument("--max-simulations", type=int, help="Omit for an uncapped time-budgeted search")
    parser.add_argument("--root-parity-output", type=Path,
                        help="Opt-in extra Native root inference sidecar for numeric parity")
    parser.add_argument("--generated-scenario", type=Path,
                        help="Frozen GeneratedCombatScenarioOptions JSON for a natural full combat")
    parser.add_argument("--regression-only", action="store_true",
                        help="Mark a diagnostic fixture as ineligible for training or promotion")
    parser.add_argument("--game-dir", required=True, type=Path)
    parser.add_argument("--ritsu-root", required=True, type=Path)
    args = parser.parse_args()
    report = run_probe(output=args.output, seed=args.seed, encounter=args.encounter,
                       search_mode=args.search_mode, model=args.model,
                       fixture_cards=args.fixture_cards.split(",") if args.fixture_cards else None,
                       force_card=args.force_card, initial_hp=args.initial_hp,
                       max_decisions=args.max_decisions, budget_ms=args.budget_ms,
                       max_simulations=args.max_simulations,
                       root_parity_output=args.root_parity_output,
                       generated_scenario=args.generated_scenario,
                       regression_only=args.regression_only,
                       game_dir=args.game_dir, ritsu_root=args.ritsu_root)
    print(json.dumps({key: report[key] for key in ("status", "output", "samples", "outcome",
                                                   "choiceRows", "priorCalls", "valueCalls",
                                                   "fallbacks")}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
