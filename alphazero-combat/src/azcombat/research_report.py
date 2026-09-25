"""Read-only audit and battle-level summary for the frozen teacher/tree study."""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
from statistics import mean

from .experiments import (RESEARCH_ENCOUNTERS, RESEARCH_WAVE_FORMAT, checked_model,
                          sha256)
from .native_probe import audit_probe
from .samples import read_jsonl
from .training import load_seed_split


# Fixed before collection. Missing or unresolved jobs are reported, not replaced.
MIN_TRAIN_SEEDS = 10
MIN_VALIDATION_SEEDS = 3
MIN_TERMINAL_DECISIONS = 100
MIN_TRAIN_DECK_TEMPLATES = 3
MIN_VALIDATION_DECK_TEMPLATES = 2


def _artifact(base: Path, name: str) -> Path:
    if not isinstance(name, str) or not name:
        raise ValueError("research artifact path is empty")
    path = (base / name).resolve()
    if not path.is_relative_to(base.resolve()) or not path.is_file():
        raise ValueError(f"missing or out-of-wave artifact: {name}")
    return path


def _expected_cells(request: dict) -> set[tuple[str, str, str, str]]:
    phase = request["phase"]
    if phase == "teacher":
        seeds = [("train", seed) for seed in request["trainSeeds"]] + [
            ("validation", seed) for seed in request["validationSeeds"]]
        policies = ("teacher",)
    elif phase == "evaluation":
        seeds = [("evaluation", seed) for seed in request["evaluationSeeds"]]
        policies = ("pure-mcts", "old-tree", "new-tree")
    else:
        raise ValueError("unknown research phase")
    return {(partition, seed, encounter, policy) for partition, seed in seeds
            for encounter in RESEARCH_ENCOUNTERS for policy in policies}


def _require_root_visit_accounting(sample: dict, metric: dict, index: int) -> None:
    visits = sample["visitPolicy"]
    # A fresh policy/value tree spends its first completed simulation
    # evaluating the root and initializing priors, without visiting an edge.
    expected_root_visits = sample["simulations"] - (
        1 if metric["searchMode"] == "policy-value-tree-v1" else 0)
    if sum(visits.values()) != expected_root_visits \
            or metric["selectedActionId"] not in visits:
        raise ValueError(f"root visit distribution does not account for simulation/selection at row {index}")


def _verify_request(base: Path, request: dict) -> None:
    split = Path(request["splitPath"]).resolve(strict=True)
    groups = load_seed_split(split)
    if sha256(split) != request["splitSha256"] or any(
            groups[name] != request[name] for name in ("trainSeeds", "validationSeeds", "evaluationSeeds")):
        raise ValueError("frozen seed split changed after research wave")
    if request["encounters"] != list(RESEARCH_ENCOUNTERS) or request["startType"] != "full_combat" \
            or request["budgetMilliseconds"] < 1000 or request["maxDecisions"] != 256 \
            or request["maxSimulations"] is not None:
        raise ValueError("research wave differs from frozen full-combat contract")
    for path_key, hash_key in (("oldOnnx", "oldOnnxSha256"), ("newOnnx", "newOnnxSha256")):
        if request[path_key] is not None and checked_model(Path(request[path_key])) != request[hash_key]:
            raise ValueError(f"{path_key} changed after research wave")
        if request[path_key] is not None:
            model = Path(request[path_key])
            stem = "old" if path_key == "oldOnnx" else "new"
            manifest = model.with_suffix(".manifest.json")
            if request.get(f"{stem}OnnxManifestSha256") is not None \
                    and sha256(manifest) != request[f"{stem}OnnxManifestSha256"]:
                raise ValueError(f"{path_key} manifest changed after research wave")
            checkpoint = model.with_suffix(".pt")
            if request.get(f"{stem}CheckpointSha256") is not None \
                    and (not checkpoint.is_file()
                         or sha256(checkpoint) != request[f"{stem}CheckpointSha256"]):
                raise ValueError(f"{path_key} checkpoint changed after research wave")
    if request.get("deckPlanPath") is not None:
        plan_path = Path(request["deckPlanPath"]).resolve(strict=True)
        if sha256(plan_path) != request.get("deckPlanSha256"):
            raise ValueError("frozen deck plan changed after research wave")
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        all_seeds = request["trainSeeds"] + request["validationSeeds"] + request["evaluationSeeds"]
        if plan.get("format") != "azcombat.deck-plan.v1" \
                or plan.get("seedSplitSha256", "").lower() != request["splitSha256"].lower() \
                or set(plan.get("assignments", {})) != set(all_seeds):
            raise ValueError("deck plan assignments differ from frozen seed split")


def _check_completed(base: Path, run: dict, request: dict) -> dict:
    jsonl = _artifact(base, run["jsonl"])
    probe = json.loads(_artifact(base, run["probeReport"]).read_text(encoding="utf-8"))
    model_hash = request["oldOnnxSha256"] if run["policy"] == "old-tree" else \
        request["newOnnxSha256"] if run["policy"] == "new-tree" else None
    mode = "pure-mcts" if model_hash is None else "policy-value-tree-v1"
    if probe.get("status") != "complete" or probe.get("seed") != run["seed"] \
            or probe.get("encounter") != run["encounter"] \
            or probe.get("requestedSearchMode") != mode \
            or probe.get("modelSha256") != model_hash \
            or probe.get("budgetMilliseconds") != request["budgetMilliseconds"] \
            or probe.get("maxDecisions") != request["maxDecisions"] \
            or probe.get("maxSimulations") is not None \
            or probe.get("regressionOnly") is not False \
            or probe.get("forceCard") is not None or probe.get("fixtureCards") is not None:
        raise ValueError("probe request differs from frozen research cell")
    if request.get("deckPlanPath") is not None:
        plan = json.loads(Path(request["deckPlanPath"]).read_text(encoding="utf-8"))
        template = plan["assignments"][run["seed"]]
        spec = _artifact(base, run["generatedScenario"])
        spec_hash = sha256(spec)
        source = json.loads(spec.read_text(encoding="utf-8"))
        if run.get("deckTemplate") != template \
                or spec_hash != run.get("generatedScenarioSha256") \
                or probe.get("generatedScenarioPath") != str(spec) \
                or probe.get("generatedScenarioSha256") != spec_hash \
                or source.get("characterCards", {}).get("ids") != plan["templates"][template]["characterCards"] \
                or source.get("seed") != run["seed"] or source.get("encounterId") != run["encounter"]:
            raise ValueError("run deck template/spec differs from frozen deck plan")
    elif probe.get("generatedScenarioPath") is not None:
        raise ValueError("unplanned generated deck was used")
    audited = audit_probe(jsonl, expected=probe, verify_current_assembly=False)
    raw_lines = jsonl.read_text(encoding="utf-8").splitlines()
    for index, line in enumerate(raw_lines):
        sample = json.loads(line)
        metric = sample["provenance"]["decisionMetrics"][index]
        _require_root_visit_accounting(sample, metric, index)
    recorded = run.get("audit", {})
    for key in ("samples", "outcome", "valueTarget", "terminal", "entryHp", "playerHp",
                "initialEnemyEffectiveHp", "enemyDamageLost", "simulations",
                "elapsedMilliseconds", "priorCalls", "valueCalls", "fallbacks",
                "jsonlSha256", "workerStdoutSha256"):
        if recorded.get(key) != audited[key]:
            raise ValueError(f"recorded {key} differs from strict reread")
    if recorded.get("choiceSamples") != len(audited["choiceRows"]) \
            or run.get("assemblies") != audited["assemblies"]:
        raise ValueError("recorded choice/assembly evidence differs from strict reread")
    first = json.loads(raw_lines[0])
    opening = first["observation"]
    opening_hash = hashlib.sha256(json.dumps(opening, sort_keys=True,
        separators=(",", ":")).encode("utf-8")).hexdigest()
    return {"status": "complete", **recorded, "jsonl": str(jsonl), "illegalActions": 0,
            "exceptions": 0, "deckTemplate": run.get("deckTemplate"),
            "openingStateKey": first["stateKey"], "openingObservationSha256": opening_hash,
            "openingMonsters": [creature["MonsterId"] for creature in opening["Creatures"]
                                if creature["MonsterId"] is not None]}


def audit_wave(manifest_path: Path) -> dict:
    manifest_path = manifest_path.resolve(strict=True)
    base = manifest_path.parent
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("format") != RESEARCH_WAVE_FORMAT:
        raise ValueError("unsupported research manifest")
    request = manifest["request"]
    _verify_request(base, request)
    expected = _expected_cells(request)
    seen: set[tuple[str, str, str, str]] = set()
    rows = []
    for run in manifest["runs"]:
        cell = (run.get("partition"), run.get("seed"), run.get("encounter"), run.get("policy"))
        if cell not in expected or cell in seen or run.get("startType") != "full_combat" \
                or run.get("scenario") != "ordinary":
            raise ValueError(f"missing, duplicate or unplanned research cell: {cell}")
        seen.add(cell)
        row = {"partition": cell[0], "seed": cell[1], "encounter": cell[2],
               "policy": cell[3], "sourceStatus": run.get("status")}
        if run.get("status") == "complete":
            try:
                row.update(_check_completed(base, run, request))
            except (OSError, KeyError, TypeError, ValueError) as error:
                row.update({"status": "error", "error": f"strict reread: {error}"})
        else:
            row.update({"status": run.get("status"), "error": run.get("error")})
            partial = base / run["jsonl"]
            if partial.is_file():
                try:
                    row["partialStrictSamples"] = len(read_jsonl(partial))
                except (OSError, ValueError) as error:
                    row["partialStrictError"] = str(error)
        rows.append(row)
    if seen != expected:
        raise ValueError(f"research grid incomplete in manifest: {len(seen)}/{len(expected)} cells")
    return {"format": "azcombat.research-report.v1", "phase": request["phase"],
            "sourceManifest": str(manifest_path), "sourceManifestSha256": sha256(manifest_path),
            "splitSha256": request["splitSha256"], "request": request, "runs": rows}


def summarize_teacher(report: dict) -> dict:
    if report["phase"] != "teacher":
        raise ValueError("not a teacher wave")
    rows = report["runs"]
    eligible = [row for row in rows if row["status"] == "complete"
                and row["outcome"] in {"win", "loss"} and row["terminal"]]
    exclusions = [{"seed": row["seed"], "partition": row["partition"],
                   "encounter": row["encounter"], "reason": row.get("error") or
                   ("unresolved" if row.get("outcome") == "unresolved" else row["status"])}
                  for row in rows if row not in eligible]
    train_seeds = {row["seed"] for row in eligible if row["partition"] == "train"}
    validation_seeds = {row["seed"] for row in eligible if row["partition"] == "validation"}
    train_encounters = {row["encounter"] for row in eligible if row["partition"] == "train"}
    validation_encounters = {row["encounter"] for row in eligible if row["partition"] == "validation"}
    train_decks = {row["deckTemplate"] for row in eligible if row["partition"] == "train"}
    validation_decks = {row["deckTemplate"] for row in eligible if row["partition"] == "validation"}
    samples = sum(row["samples"] for row in eligible)
    ready = report["request"].get("deckPlanPath") is not None \
        and all(row["status"] not in {"pending", "running", "interrupted"} for row in rows) \
        and len(train_seeds) >= MIN_TRAIN_SEEDS \
        and len(validation_seeds) >= MIN_VALIDATION_SEEDS \
        and train_encounters == set(RESEARCH_ENCOUNTERS) \
        and validation_encounters == set(RESEARCH_ENCOUNTERS) \
        and len(train_decks) >= MIN_TRAIN_DECK_TEMPLATES \
        and len(validation_decks) >= MIN_VALIDATION_DECK_TEMPLATES \
        and samples >= MIN_TERMINAL_DECISIONS
    return {"plannedTasks": len(rows), "statusCounts": dict(Counter(
                row["outcome"] if row["status"] == "complete" else row["status"] for row in rows)),
            "byEncounter": {encounter: dict(Counter(
                row["outcome"] if row["status"] == "complete" else row["status"]
                for row in rows if row["encounter"] == encounter)) for encounter in RESEARCH_ENCOUNTERS},
            "terminalBattles": len(eligible), "terminalSeeds": len(train_seeds | validation_seeds),
            "trainSeeds": len(train_seeds), "validationSeeds": len(validation_seeds),
            "terminalDecisionSamples": samples,
            "naturalChoiceSamples": sum(row["choiceSamples"] for row in eligible),
            "deckTemplates": dict(Counter(row["deckTemplate"] for row in eligible)),
            "openingMonsterRosters": {encounter: sorted({tuple(row["openingMonsters"])
                for row in eligible if row["encounter"] == encounter}) for encounter in RESEARCH_ENCOUNTERS},
            "minimumData": {"trainSeeds": MIN_TRAIN_SEEDS,
                            "validationSeeds": MIN_VALIDATION_SEEDS,
                            "terminalDecisionSamples": MIN_TERMINAL_DECISIONS,
                            "bothEncountersPerSplit": True,
                            "trainDeckTemplates": MIN_TRAIN_DECK_TEMPLATES,
                            "validationDeckTemplates": MIN_VALIDATION_DECK_TEMPLATES},
            "readyForTraining": ready,
            "trainingInputs": [row["jsonl"] for row in eligible],
            "excluded": exclusions}


def _arm_summary(rows: list[dict]) -> dict:
    counts = Counter(row["outcome"] if row["status"] == "complete" else row["status"] for row in rows)
    valid = [row for row in rows if row["status"] == "complete"]
    terminal = [row for row in valid if row["outcome"] in {"win", "loss"}]
    wins = [row for row in valid if row["outcome"] == "win"]
    return {"tasks": len(rows), "counts": dict(counts),
            "terminalRewardMean": mean(row["valueTarget"] for row in terminal) if terminal else None,
            "playerHpChangeMean": mean(row["playerHp"] - row["entryHp"] for row in terminal) if terminal else None,
            "winningHpLossMean": mean(row["entryHp"] - row["playerHp"] for row in wins) if wins else None,
            "decisionSamples": sum(row["samples"] for row in valid),
            "naturalChoiceSamples": sum(row["choiceSamples"] for row in valid),
            "deckTemplates": dict(Counter(row["deckTemplate"] for row in valid)),
            "simulations": sum(sum(row["simulations"]) for row in valid),
            "decisionElapsedMilliseconds": sum(sum(row["elapsedMilliseconds"]) for row in valid),
            "priorCalls": sum(row["priorCalls"] for row in valid),
            "valueCalls": sum(row["valueCalls"] for row in valid),
            "fallbacksInValidRuns": sum(row["fallbacks"] for row in valid),
            "invalidOrExceptionRuns": sum(row["status"] == "error" for row in rows)}


def summarize_evaluation(report: dict) -> dict:
    if report["phase"] != "evaluation":
        raise ValueError("not an evaluation wave")
    rows = report["runs"]
    policies = ("pure-mcts", "old-tree", "new-tree")
    by_arm = {policy: _arm_summary([row for row in rows if row["policy"] == policy])
              for policy in policies}
    by_encounter = {encounter: {policy: _arm_summary([
        row for row in rows if row["encounter"] == encounter and row["policy"] == policy])
        for policy in policies} for encounter in RESEARCH_ENCOUNTERS}
    cells = {(row["seed"], row["encounter"], row["policy"]): row for row in rows}
    pairs = []
    for seed in report["request"]["evaluationSeeds"]:
        for encounter in RESEARCH_ENCOUNTERS:
            pair = {policy: cells[(seed, encounter, policy)] for policy in policies}
            complete = all(pair[policy]["status"] == "complete" for policy in policies)
            aligned = complete and len({(pair[policy]["openingStateKey"],
                                        pair[policy]["openingObservationSha256"],
                                        pair[policy]["deckTemplate"])
                                        for policy in policies}) == 1
            arms = {}
            for policy in policies:
                entry = pair[policy]
                arms[policy] = {key: entry.get(key) for key in (
                    "status", "error", "outcome", "valueTarget", "entryHp", "playerHp",
                    "enemyDamageLost", "samples", "choiceSamples", "deckTemplate",
                    "priorCalls", "valueCalls", "fallbacks")}
                arms[policy]["simulationsTotal"] = sum(entry["simulations"]) \
                    if entry["status"] == "complete" else None
                arms[policy]["decisionElapsedMillisecondsTotal"] = sum(
                    entry["elapsedMilliseconds"]) if entry["status"] == "complete" else None
            pairs.append({"seed": seed, "encounter": encounter,
                          "sameOpeningRoot": aligned,
                          "arms": arms})
    return {"plannedTasks": len(rows), "byArm": by_arm, "byEncounter": by_encounter,
            "pairedBattles": pairs,
            "completePairs": sum(pair["sameOpeningRoot"] for pair in pairs),
            "mismatchedOpeningRoots": sum(all(pair["arms"][policy]["status"] == "complete"
                for policy in policies) and not pair["sameOpeningRoot"] for pair in pairs)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wave", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError("research report output already exists")
    report = audit_wave(args.wave / "manifest.json")
    report["summary"] = summarize_teacher(report) if report["phase"] == "teacher" else \
        summarize_evaluation(report)
    with args.output.open("x", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    print(json.dumps({"phase": report["phase"], "summary": report["summary"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
