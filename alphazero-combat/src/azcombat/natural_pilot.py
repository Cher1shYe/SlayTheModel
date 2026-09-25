"""Freeze and execute the bounded, paired natural-combat collection pilot.

This is intentionally separate from M4, champion and self-play entry points.
The immutable plan and every attempt live in an exclusive new output directory.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess

from .experiments import (_generated_scenario_bytes, _model_lineage,
                          _read_research_split, checked_model, sha256)
from .reward import Outcome, TerminalResult, score_result
from .versions import (FEATURE_ABI, OBSERVATION_SCHEMA_VERSION,
                       REWARD_LEDGER_VERSION, SEARCH_SEMANTICS_VERSION)


PILOT_FORMAT = "azcombat.natural-pilot.v2"
PILOT_ENCOUNTERS = ("CULTISTS_NORMAL", "LIVING_FOG_NORMAL")
PILOT_POLICIES = ("pure-mcts", "tree-candidate")
TREE_CANDIDATE_SHA256 = "b56006d70539a733a1485f2b76403205e3c7b8a04a96bfc636b525ae344ea190"
R3_DECK_PLAN_SHA256 = "c802dff60c5f212f6d8880e4a3655b53b3a344022b1520dc8816579329020463"
R1_SEED_SPLIT_SHA256 = "765c121a01a4e023814d5dfabf51dba28c248b553d8828f3ecf15ddde782dcb8"
_SEED_TOKEN = re.compile(r'"seed"\s*:\s*"([^"\\]+)"')
_SOURCE_PREFIXES = ("src/", "combat/src/", "tools/Sts2.NativeWorker/",
                    "alphazero-combat/src/azcombat/", "contracts/")
_SOURCE_FILES = {"scripts/native-worker.ps1", "global.json", "CombatSolver.csproj",
                 "combat/CombatSolver.csproj", "combat/.source-commit",
                 "Directory.Build.props", "Directory.Build.targets"}


def _canonical_json(value: dict) -> bytes:
    return (json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True,
                            encoding="utf-8", check=True)
    return result.stdout.strip()


def _source_snapshot(repo: Path) -> dict:
    paths = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z", "--",
         "src", "combat/src", "tools/Sts2.NativeWorker", "alphazero-combat/src/azcombat",
         "contracts", *_SOURCE_FILES],
        cwd=repo, capture_output=True, check=True).stdout.decode("utf-8").split("\0")
    digest = hashlib.sha256()
    source_files = []
    for raw in sorted(set(paths)):
        if not raw:
            continue
        relative = raw.replace("\\", "/")
        if not relative.startswith(_SOURCE_PREFIXES) and relative not in _SOURCE_FILES:
            continue
        if any(part in {"bin", "obj", ".godot"} for part in Path(relative).parts):
            continue
        path = repo / relative
        if not path.is_file():
            raise FileNotFoundError(f"source snapshot file disappeared: {path}")
        content_hash = sha256(path)
        digest.update(relative.encode("utf-8") + b"\0" + content_hash.encode("ascii") + b"\n")
        source_files.append(relative)
    if not source_files:
        raise ValueError("source snapshot is empty")
    pinned = repo / "combat" / ".source-commit"
    pinned_commit = pinned.read_text(encoding="utf-8").strip()
    if pinned_commit != "8826a333a6d48e05f0e368ee2db5d4a15092382e":
        raise ValueError("CombatSolver pinned source commit differs from the verified NativeWorker build")
    return {"rootCommit": _git(repo, "rev-parse", "HEAD"),
            "combatPinnedSourceCommit": pinned_commit,
            "combatSourceCommitFileSha256": sha256(pinned),
            "sourceTreeSha256": digest.hexdigest(), "sourceFileCount": len(source_files)}


def _historical_seeds(repo: Path) -> set[str]:
    """Inventory only seed-bearing configs and prior trajectory/manifest artifacts."""
    roots = (repo / "alphazero-combat" / "configs", repo / "artifacts" / "alphazero")
    files = [*roots[0].rglob("*.json"), *roots[1].rglob("*.json"),
             *roots[1].rglob("*.jsonl")]
    found: set[str] = set()
    for path in files:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            text = handle.read()
        found.update(_SEED_TOKEN.findall(text))
        if path.suffix == ".json":
            try:
                content = json.loads(text)
            except json.JSONDecodeError:
                continue  # The raw seed tokens above still detect a collision.
            def visit(value: object) -> None:
                if isinstance(value, dict):
                    for key, child in value.items():
                        if key in {"trainSeeds", "validationSeeds", "evaluationSeeds", "seeds"} \
                                and isinstance(child, list):
                            found.update(seed for seed in child if isinstance(seed, str))
                        visit(child)
                elif isinstance(value, list):
                    for child in value:
                        visit(child)
            visit(content)
    return found


def _validated_budget(path: Path) -> dict:
    wave = json.loads(path.read_text(encoding="utf-8"))
    request = wave.get("request") if isinstance(wave, dict) else None
    if wave.get("format") != "azcombat.research-wave.v1" or not isinstance(request, dict) \
            or wave.get("status") != "complete" or request.get("phase") != "evaluation" \
            or request.get("budgetMilliseconds") != 1000 \
            or "maxSimulations" not in request or request["maxSimulations"] is not None \
            or request.get("maxDecisions") != 256 or request.get("timeoutSeconds") != 1800 \
            or request.get("encounters") != list(PILOT_ENCOUNTERS):
        raise ValueError("pilot budget differs from verified R3 research wave")
    return {"budgetMilliseconds": 1000, "maxSimulations": None,
            "maxDecisions": 256, "workerCancellationSeconds": 600,
            "timeoutSeconds": 1800, "pythonSubprocessTimeoutSeconds": 2100}


def _worker_cancellation_seconds(repo: Path) -> int:
    source = (repo / "tools" / "Sts2.NativeWorker" / "Worker.cs").read_text(encoding="utf-8")
    if "new CancellationTokenSource(TimeSpan.FromMinutes(10))" not in source:
        raise ValueError("NativeWorker internal cancellation no longer matches the 600 s pilot contract")
    return 600


def _external_dependencies(game_dir: Path, ritsu_root: Path) -> dict:
    managed = game_dir / "data_sts2_windows_x86_64" / "sts2.dll"
    ritsu = ritsu_root / "compat" / "0.111.0" / "STS2-RitsuLib.dll"
    if not managed.is_file() or not ritsu.is_file():
        raise FileNotFoundError("pinned STS2/RitsuLib v0.111.0 assemblies are missing")
    return {"gameAssembly": {"path": str(managed.resolve()), "sha256": sha256(managed)},
            "ritsuAssembly": {"path": str(ritsu.resolve()), "sha256": sha256(ritsu)}}


def _validated_cross_root_regression(report: dict) -> None:
    cross = report.get("crossRoot") if isinstance(report, dict) else None
    if report.get("format") != "azcombat.cross-root-reward-regression.v1" \
            or report.get("regressionOnly") is not True \
            or report.get("status") != "passed" or not isinstance(cross, dict) \
            or cross.get("regressionOnly") is not True:
        raise ValueError("cross-root Native regression has not passed")
    initial = cross.get("initialEnemyHp")
    prefix_transition = cross.get("prefixTransition")
    branch_transition = cross.get("branchTransition")
    if type(initial) is not int or initial <= 0 \
            or not isinstance(prefix_transition, dict) \
            or not isinstance(branch_transition, dict):
        raise ValueError("cross-root Native regression lacks independent damage records")
    prefix, branch = prefix_transition.get("Damage"), branch_transition.get("Damage")
    if type(prefix) is not int or type(branch) is not int or prefix <= 0 or branch <= 0 \
            or prefix_transition.get("Before") != initial \
            or prefix_transition.get("After") != initial - prefix \
            or branch_transition.get("Before") != initial - prefix \
            or branch_transition.get("After") != initial - prefix - branch \
            or cross.get("capturedPrefixDamage") != prefix \
            or cross.get("branchDamage") != branch \
            or cross.get("totalEnemyHpLost") != prefix + branch:
        raise ValueError("cross-root Native damage records disagree")
    trajectory = cross.get("trajectoryId")
    for capture_id, field, expected_prefix in ((1, "firstCapture", 0),
                                                (2, "secondCapture", prefix),
                                                (3, "thirdCapture", prefix + branch)):
        capture = cross.get(field)
        if not isinstance(capture, dict) or capture.get("TrajectoryId") != trajectory \
                or capture.get("CaptureId") != capture_id \
                or not capture.get("CaptureBoundaryKey") \
                or capture.get("InitialEnemyEffectiveHp") != initial \
                or capture.get("CapturedEnemyDamagePrefix") != expected_prefix:
            raise ValueError(f"cross-root {field} is not aligned with independent damage")
    for name, outcome, captured, added in (("rewardInputs", Outcome.LOSS, prefix, branch),
                                           ("recapturedRewardInputs", Outcome.LOSS,
                                            prefix + branch, 0),
                                           ("unresolvedAtDecisionCap", Outcome.UNRESOLVED,
                                            prefix, branch)):
        ledger = cross.get(name)
        if name == "unresolvedAtDecisionCap":
            if not isinstance(ledger, dict) or ledger.get("terminationReason") != "decision_cap" \
                    or ledger.get("decisionCap") != ledger.get("executedDecisions"):
                raise ValueError("cross-root unresolved boundary is not an explicit decision cap")
            ledger = ledger.get("rewardInputs")
        if not isinstance(ledger, dict) or ledger.get("Outcome") != outcome.value \
                or ledger.get("TrajectoryId") != trajectory \
                or ledger.get("TrajectoryInitialEnemyHp") != initial \
                or ledger.get("CapturedEnemyDamagePrefix") != captured \
                or ledger.get("EnemyHpLost") != added \
                or ledger.get("TotalEnemyHpLost") != prefix + branch:
            raise ValueError(f"cross-root {name} does not preserve trajectory damage")
        expected_capture = cross["thirdCapture"] if name == "recapturedRewardInputs" \
            else cross["secondCapture"]
        if ledger.get("CaptureId") != expected_capture["CaptureId"] \
                or ledger.get("CaptureBoundaryKey") != expected_capture["CaptureBoundaryKey"]:
            raise ValueError(f"cross-root {name} uses a different Capture boundary")
        expected = score_result(TerminalResult(outcome, ledger["EntryHp"],
                                               ledger["SettledFinalHp"], prefix + branch, initial))
        if not math.isclose(ledger["Reward"], expected, rel_tol=0, abs_tol=1e-9):
            raise ValueError(f"cross-root {name} reward differs from independent damage")
    if cross.get("liveSettledHp") != 0 or cross["rewardInputs"].get("SettledFinalHp") != 0 \
            or cross["recapturedRewardInputs"].get("SettledFinalHp") != 0 \
            or not math.isclose(cross["actualReward"], cross["expectedLoss"],
                        rel_tol=0, abs_tol=1e-9) or not math.isclose(
                            cross["actualReward"], cross["rewardInputs"]["Reward"],
                            rel_tol=0, abs_tol=1e-9):
        raise ValueError("cross-root actual death reward differs from the ledger")


def _validated_enemy_damage_regression(report: dict) -> None:
    if not isinstance(report, dict) \
            or report.get("format") != "azcombat.enemy-damage-ledger-regression.v1" \
            or report.get("regressionOnly") is not True \
            or report.get("status") != "passed" \
            or any(not isinstance(report.get(case), dict) for case in
                   ("despawnUnresolved", "lethalOverkill", "despawnLoss")):
        raise ValueError("Native enemy-damage regression is missing a passed scenario")


def _validated_templates(path: Path) -> dict[str, list[str]]:
    plan = json.loads(path.read_text(encoding="utf-8"))
    templates = plan.get("templates") if isinstance(plan, dict) else None
    if plan.get("format") != "azcombat.deck-plan.v1" or not isinstance(templates, dict) \
            or set(templates) != set("ABCDE"):
        raise ValueError("pilot must reuse the five frozen R3 deck templates")
    cards_by_template = {}
    for name in "ABCDE":
        item = templates[name]
        cards = item.get("characterCards") if isinstance(item, dict) else None
        if not isinstance(cards, list) or not cards or any(
                type(card) is not str or re.fullmatch(r"[A-Z0-9_]+", card) is None
                for card in cards):
            raise ValueError(f"invalid historical deck template {name}")
        cards_by_template[name] = cards
    return cards_by_template


def freeze_pilot(*, output: Path, pilot_seeds: list[str],
                 final_evaluation_seeds: list[str], deck_plan: Path,
                 historical_split: Path, model: Path, game_dir: Path,
                 ritsu_root: Path, budget_evidence: Path,
                 cross_root_evidence: Path, enemy_damage_evidence: Path) -> dict:
    """Create a never-rewritten manifest and ten shared paired opening specs."""
    repo = Path(__file__).resolve().parents[3]
    if len(pilot_seeds) != 5 or len(final_evaluation_seeds) < 5 \
            or any(type(seed) is not str or not seed.strip() for seed in
                   [*pilot_seeds, *final_evaluation_seeds]) \
            or len(set([*pilot_seeds, *final_evaluation_seeds])) != \
            len(pilot_seeds) + len(final_evaluation_seeds):
        raise ValueError("pilot needs five distinct new seeds and at least five sealed final-evaluation seeds")
    old_split = _read_research_split(historical_split.resolve(strict=True))
    if sha256(historical_split).lower() != R1_SEED_SPLIT_SHA256:
        raise ValueError("pilot historical split is not the frozen R1 split")
    old_seeds = set().union(old_split["trainSeeds"], old_split["validationSeeds"],
                            old_split["evaluationSeeds"])
    old_seeds.update(_historical_seeds(repo))
    model = model.resolve(strict=True)
    model_hash = checked_model(model)
    if model_hash.lower() != TREE_CANDIDATE_SHA256:
        raise ValueError("pilot requires the fixed existing R3 tree candidate")
    old_seeds.update(_model_lineage(model))
    if overlap := old_seeds.intersection([*pilot_seeds, *final_evaluation_seeds]):
        raise ValueError(f"pilot/final-evaluation seed overlaps historical evidence: {sorted(overlap)}")
    budget_evidence = budget_evidence.resolve(strict=True)
    budget = _validated_budget(budget_evidence)
    if _worker_cancellation_seconds(repo) != budget["workerCancellationSeconds"]:
        raise ValueError("worker cancellation differs from the frozen pilot budget")
    deck_plan = deck_plan.resolve(strict=True)
    if sha256(deck_plan).lower() != R3_DECK_PLAN_SHA256:
        raise ValueError("pilot deck plan is not the frozen R3 template source")
    cards_by_template = _validated_templates(deck_plan)
    cross_root_evidence = cross_root_evidence.resolve(strict=True)
    regression = json.loads(cross_root_evidence.read_text(encoding="utf-8"))
    _validated_cross_root_regression(regression)
    enemy_damage_evidence = enemy_damage_evidence.resolve(strict=True)
    damage_regression = json.loads(enemy_damage_evidence.read_text(encoding="utf-8"))
    _validated_enemy_damage_regression(damage_regression)
    game_dir = game_dir.resolve(strict=True)
    ritsu_root = ritsu_root.resolve(strict=True)
    external = _external_dependencies(game_dir, ritsu_root)
    source = _source_snapshot(repo)
    assignments = {seed: "ABCDE"[index] for index, seed in enumerate(pilot_seeds)}
    tasks = []
    scenario_contents = {}
    for index, seed in enumerate(pilot_seeds):
        for encounter in PILOT_ENCOUNTERS:
            scenario = f"inputs/{index:03d}-{encounter}.json"
            contents = _generated_scenario_bytes(seed, encounter, cards_by_template[assignments[seed]])
            scenario_contents[scenario] = contents
            scenario_hash = hashlib.sha256(contents).hexdigest()
            for policy in PILOT_POLICIES:
                tasks.append({"taskId": f"{index:03d}-{encounter}-{policy}",
                              "seed": seed, "partition": "train" if index < 4 else "validation",
                              "encounter": encounter, "policy": policy,
                              "requestedSearchMode": "pure-mcts" if policy == "pure-mcts"
                                                     else "policy-value-tree-v1",
                              "requestedModelSha256": None if policy == "pure-mcts" else model_hash,
                              "startType": "full_combat", "deckTemplate": assignments[seed],
                              "generatedScenario": scenario,
                              "generatedScenarioSha256": scenario_hash, **budget})
    manifest = {
        "format": PILOT_FORMAT, "createdAtUtc": datetime.now(timezone.utc).isoformat(),
        "purpose": "collection-reliability-and-coverage-only",
        "gameVersion": "v0.111.0", "gameDir": str(game_dir), "ritsuRoot": str(ritsu_root),
        "externalBuildInputs": external,
        "contracts": {"observationSchemaVersion": OBSERVATION_SCHEMA_VERSION,
                      "featureAbi": FEATURE_ABI, "searchSemanticsVersion": SEARCH_SEMANTICS_VERSION,
                      "rewardLedgerVersion": REWARD_LEDGER_VERSION,
                      "rewardDefinition": {
                          "source": "alphazero-combat/src/azcombat/reward.py:score_result",
                          "win": "0.5 + atan((postCombatSettledHp - trajectoryEntryHp) / 20) / pi",
                          "loss": "-1.0 + 0.25 * min(totalActualEnemyHpLost / max(trajectoryInitialEnemyHp, 1), 1)",
                          "unresolved": "-0.5 + 0.25 * min(totalActualEnemyHpLost / max(trajectoryInitialEnemyHp, 1), 1)",
                          "invalid": "reject; no learning label"}},
        "sourceSnapshot": source,
        "crossRootRegression": {"path": str(cross_root_evidence),
                                "sha256": sha256(cross_root_evidence)},
        "enemyDamageRegression": {"path": str(enemy_damage_evidence),
                                  "sha256": sha256(enemy_damage_evidence)},
        "budgetEvidence": {"path": str(budget_evidence), "sha256": sha256(budget_evidence),
                           "uncappedSimulationsExplicit": True,
                           "historicalTeacherWaveCaveat":
                           "same R3 setup had 48 complete/2 errors; only the completed R3 evaluation-wave request is used as an entry/budget record, not E00-E09 outcomes or model selection",
                           "workerCancellationSeconds": 600,
                           "outerProcessTimeoutSeconds": 1800,
                           "pythonSubprocessTimeoutSeconds": 2100},
        "historicalSeedSplit": {"path": str(historical_split.resolve()),
                                "sha256": sha256(historical_split)},
        "seedPartitions": {"train": pilot_seeds[:4], "validation": pilot_seeds[4:],
                           "finalEvaluationSealed": final_evaluation_seeds},
        "deckTemplates": {"path": str(deck_plan), "sha256": sha256(deck_plan),
                          "reusedHistoricalTemplates": True,
                          "assignments": assignments, "cards": cards_by_template},
        "treeCandidate": {"onnxPath": str(model), "onnxSha256": model_hash,
                          "parameterCount": 1970,
                          "usage": "fixed-behavior-policy-only",
                          "trainingRewardLedgerVersion": "azcombat.reward-ledger.v1",
                          "manifestPath": str(model.with_suffix(".manifest.json")),
                          "manifestSha256": sha256(model.with_suffix(".manifest.json")),
                          "checkpointSha256": json.loads(model.with_suffix(".manifest.json").read_text(
                              encoding="utf-8"))["checkpointSha256"]},
        "collectionRules": {"maximumAttemptsPerTask": 2,
                            "retry": "manual-only after infrastructure failure, same frozen task",
                            "stop": "any protocol/audit discrepancy or unclassified failure",
                            "allOutcomesRetained": True, "regressionOnly": False,
                            "treeAndPureDataSeparate": True, "noForcedActionsOrHp": True,
                            "countUnit": "planned task/combat, not attempts or decisions",
                            "validationSeedCountCaveat": "one pilot validation seed; not for model selection"},
        "tasks": tasks,
    }
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    (output / "inputs").mkdir()
    (output / "attempts").mkdir()
    for relative, contents in scenario_contents.items():
        with (output / relative).open("xb") as handle:
            handle.write(contents)
    manifest_bytes = _canonical_json(manifest)
    with (output / "manifest.json").open("xb") as handle:
        handle.write(manifest_bytes)
    with (output / "manifest.sha256").open("x", encoding="ascii") as handle:
        handle.write(hashlib.sha256(manifest_bytes).hexdigest() + "\n")
    return manifest


def _read_frozen_manifest(path: Path) -> dict:
    path = path.resolve(strict=True)
    if path.name != "manifest.json":
        raise ValueError("pilot runner requires the frozen manifest.json")
    digest_path = path.with_suffix(".sha256")
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest_path.read_text(encoding="ascii").strip() != actual:
        raise ValueError("frozen pilot manifest SHA256 differs")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest.get("format") != PILOT_FORMAT or not isinstance(manifest.get("tasks"), list) \
            or len(manifest["tasks"]) != 20:
        raise ValueError("pilot manifest does not define exactly 20 frozen tasks")
    return manifest


def _assert_unchanged_inputs(manifest_path: Path, manifest: dict) -> None:
    repo = Path(__file__).resolve().parents[3]
    if _source_snapshot(repo) != manifest["sourceSnapshot"]:
        raise ValueError("Native/source tree changed after pilot plan freeze")
    for field in ("crossRootRegression", "enemyDamageRegression", "budgetEvidence",
                  "historicalSeedSplit"):
        item = manifest[field]
        path = Path(item["path"]).resolve(strict=True)
        if sha256(path).lower() != item["sha256"].lower():
            raise ValueError(f"frozen {field} changed")
    _validated_cross_root_regression(json.loads(
        Path(manifest["crossRootRegression"]["path"]).read_text(encoding="utf-8")))
    damage_regression = json.loads(Path(manifest["enemyDamageRegression"]["path"]).read_text(
        encoding="utf-8"))
    _validated_enemy_damage_regression(damage_regression)
    if _validated_budget(Path(manifest["budgetEvidence"]["path"])) != {
            key: manifest["tasks"][0][key] for key in
            ("budgetMilliseconds", "maxSimulations", "maxDecisions", "workerCancellationSeconds",
             "timeoutSeconds", "pythonSubprocessTimeoutSeconds")}: 
        raise ValueError("frozen pilot budget evidence differs from tasks")
    if _worker_cancellation_seconds(repo) != manifest["tasks"][0]["workerCancellationSeconds"]:
        raise ValueError("NativeWorker internal cancellation differs from pilot plan")
    model = manifest["treeCandidate"]
    if sha256(Path(model["onnxPath"])) .lower() != model["onnxSha256"].lower() \
            or sha256(Path(model["manifestPath"])) .lower() != model["manifestSha256"].lower() \
            or checked_model(Path(model["onnxPath"])) .lower() != model["onnxSha256"].lower():
        raise ValueError("pilot tree candidate changed")
    deck = manifest["deckTemplates"]
    if sha256(Path(deck["path"])) .lower() != deck["sha256"].lower():
        raise ValueError("pilot deck template source changed")
    if not Path(manifest["gameDir"]).is_dir() or not Path(manifest["ritsuRoot"]).is_dir():
        raise FileNotFoundError("pilot game or RitsuLib path changed")
    if _external_dependencies(Path(manifest["gameDir"]), Path(manifest["ritsuRoot"])) \
            != manifest["externalBuildInputs"]:
        raise ValueError("pinned game/RitsuLib build input changed")
    seen = set()
    for task in manifest["tasks"]:
        task_id = task["taskId"]
        if not isinstance(task_id, str) or re.fullmatch(
                r"\d{3}-(?:CULTISTS_NORMAL|LIVING_FOG_NORMAL)-(?:pure-mcts|tree-candidate)",
                task_id) is None or task_id in seen:
            raise ValueError("pilot task ID is invalid or duplicated")
        seen.add(task_id)
        scenario = (manifest_path.parent / task["generatedScenario"]).resolve(strict=True)
        if not scenario.is_relative_to(manifest_path.parent / "inputs") \
                or sha256(scenario).lower() != task["generatedScenarioSha256"].lower() \
                or scenario.read_bytes() != _generated_scenario_bytes(
                    task["seed"], task["encounter"], deck["cards"][task["deckTemplate"]]):
            raise ValueError(f"pilot opening specification changed for {task_id}")
        if task["policy"] == "pure-mcts":
            if task["requestedSearchMode"] != "pure-mcts" or task["requestedModelSha256"] is not None:
                raise ValueError("pure MCTS task requests a model")
        elif task["requestedSearchMode"] != "policy-value-tree-v1" \
                or task["requestedModelSha256"] != model["onnxSha256"]:
            raise ValueError("tree task differs from frozen candidate")


def _attempt_records(directory: Path) -> list[dict]:
    if not directory.exists():
        return []
    result = []
    for number, path in enumerate(sorted(directory.iterdir()), start=1):
        if not path.is_dir() or path.name != f"attempt-{number:03d}":
            raise ValueError(f"pilot attempt directory is missing, reordered or unexpected: {path}")
        record_path = path / "attempt.json"
        if not record_path.is_file():
            raise ValueError(f"pilot attempt lacks its preserved record: {path}")
        record = json.loads(record_path.read_text(encoding="utf-8"))
        if record.get("attemptNumber") != number or record.get("status") not in \
                {"running", "complete", "failed"}:
            raise ValueError(f"pilot attempt record is malformed: {record_path}")
        result.append(record)
    return result


def _save_attempt(path: Path, value: dict) -> None:
    temporary = path.with_name("attempt.json.tmp")
    temporary.write_bytes(_canonical_json(value))
    os.replace(temporary, path)


def _launch_attempt(manifest_path: Path, manifest: dict, task: dict,
                    number: int) -> dict:
    # Import lazily to keep the Native probe/experiments import graph acyclic.
    from .native_probe import run_probe

    output = manifest_path.parent
    task_id = task["taskId"]
    attempt = output / "attempts" / task_id / f"attempt-{number:03d}"
    attempt.mkdir(parents=True, exist_ok=False)
    jsonl = attempt / "trajectory.jsonl"
    parity = attempt / "trajectory.root-parity.jsonl" if task["policy"] == "tree-candidate" else None
    relative = lambda path: str(path.relative_to(output)).replace("\\", "/")
    record = {"format": "azcombat.natural-pilot-attempt.v1", "taskId": task_id,
              "attemptNumber": number, "status": "running",
              "startedAtUtc": datetime.now(timezone.utc).isoformat(),
              "jsonl": relative(jsonl), "probeReport": relative(jsonl.with_suffix(".probe.json")),
              "rootParityOutput": relative(parity) if parity is not None else None,
              "stageRoot": relative(jsonl.with_suffix(".stage")),
              "stageProvenance": relative(jsonl.with_suffix(".stage") / "stage_provenance.json")}
    record_path = attempt / "attempt.json"
    with record_path.open("xb") as handle:
        handle.write(_canonical_json(record))
    try:
        audit = run_probe(output=jsonl, seed=task["seed"], encounter=task["encounter"],
                          search_mode=task["requestedSearchMode"],
                          game_dir=Path(manifest["gameDir"]), ritsu_root=Path(manifest["ritsuRoot"]),
                          model=Path(manifest["treeCandidate"]["onnxPath"])
                          if task["policy"] == "tree-candidate" else None,
                          max_decisions=task["maxDecisions"], budget_ms=task["budgetMilliseconds"],
                          max_simulations=task["maxSimulations"],
                          timeout_seconds=task["timeoutSeconds"],
                          root_parity_output=parity,
                          generated_scenario=output / task["generatedScenario"],
                          regression_only=False)
        if audit.get("status") != "complete" or not jsonl.is_file() \
                or not jsonl.with_suffix(".probe.json").is_file() \
                or parity is not None and not parity.is_file():
            raise ValueError("Native probe returned without complete immutable trajectory evidence")
        record.update({"status": "complete", "samples": audit["samples"],
                       "outcome": audit["outcome"], "valueTarget": audit["valueTarget"],
                       "assemblies": audit["assemblies"]})
    except Exception as error:
        record.update({"status": "failed", "failureClass": "infrastructure"
                       if isinstance(error, (subprocess.TimeoutExpired, OSError))
                       else "protocol-or-unclassified",
                       "error": f"{type(error).__name__}: {error}"})
        raise
    finally:
        record["finishedAtUtc"] = datetime.now(timezone.utc).isoformat()
        for field, key in ((jsonl, "jsonlSha256"),
                           (jsonl.with_suffix(".probe.json"), "probeReportSha256"),
                           (jsonl.with_suffix(".stage") / "stage_provenance.json",
                            "stageProvenanceSha256"), (parity, "rootParitySha256")):
            if field is not None and field.is_file():
                record[key] = sha256(field)
        _save_attempt(record_path, record)
    return record


def run_pilot(manifest_path: Path, *, limit: int | None = None,
              retry_task: str | None = None) -> list[dict]:
    """Run pending frozen tasks serially; stop on the first error, never auto-retry."""
    if limit is not None and (type(limit) is not int or limit < 1):
        raise ValueError("pilot limit must be positive")
    manifest_path = manifest_path.resolve(strict=True)
    manifest = _read_frozen_manifest(manifest_path)
    _assert_unchanged_inputs(manifest_path, manifest)
    launched = []
    tasks = manifest["tasks"]
    if retry_task is not None:
        tasks = [task for task in tasks if task["taskId"] == retry_task]
        if len(tasks) != 1:
            raise ValueError("retry task is not in frozen pilot manifest")
    for task in tasks:
        records = _attempt_records(manifest_path.parent / "attempts" / task["taskId"])
        if records and any(record["taskId"] != task["taskId"] for record in records):
            raise ValueError("attempt is attached to a different frozen task")
        if retry_task is None:
            if any(record["status"] == "complete" for record in records):
                continue
            if records:
                raise ValueError(f"failed prior attempt requires explicit infrastructure review: {task['taskId']}")
        else:
            if len(records) != 1 or records[0]["status"] != "failed" \
                    or records[0].get("failureClass") != "infrastructure":
                raise ValueError("only one preserved infrastructure failure may be retried explicitly")
        # Recheck immediately before each full ExportRelease. A later source
        # mutation must not hide behind the first task's completed audit.
        _assert_unchanged_inputs(manifest_path, manifest)
        launched.append(_launch_attempt(manifest_path, manifest, task, len(records) + 1))
        if retry_task is not None or limit is not None and len(launched) >= limit:
            break
    return launched


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    freeze = sub.add_parser("freeze", help="write an exclusive immutable 20-task plan; do not launch")
    freeze.add_argument("--output", required=True, type=Path)
    freeze.add_argument("--pilot-seed", action="append", required=True)
    freeze.add_argument("--sealed-final-seed", action="append", required=True)
    freeze.add_argument("--deck-plan", required=True, type=Path)
    freeze.add_argument("--historical-split", required=True, type=Path)
    freeze.add_argument("--model", required=True, type=Path)
    freeze.add_argument("--game-dir", required=True, type=Path)
    freeze.add_argument("--ritsu-root", required=True, type=Path)
    freeze.add_argument("--budget-evidence", required=True, type=Path)
    freeze.add_argument("--cross-root-evidence", required=True, type=Path)
    freeze.add_argument("--enemy-damage-evidence", required=True, type=Path)
    run = sub.add_parser("run", help="run untouched tasks, or one explicit infrastructure retry")
    run.add_argument("--manifest", required=True, type=Path)
    run.add_argument("--limit", type=int)
    run.add_argument("--retry-task")
    args = parser.parse_args()
    if args.command == "freeze":
        manifest = freeze_pilot(output=args.output, pilot_seeds=args.pilot_seed,
                                final_evaluation_seeds=args.sealed_final_seed,
                                deck_plan=args.deck_plan, historical_split=args.historical_split,
                                model=args.model, game_dir=args.game_dir,
                                ritsu_root=args.ritsu_root,
                                budget_evidence=args.budget_evidence,
                                cross_root_evidence=args.cross_root_evidence,
                                enemy_damage_evidence=args.enemy_damage_evidence)
        print(json.dumps({"format": manifest["format"], "tasks": len(manifest["tasks"]),
                          "output": str(args.output.resolve())}, ensure_ascii=False))
    else:
        print(json.dumps({"attemptsLaunched": run_pilot(args.manifest, limit=args.limit,
                                                          retry_task=args.retry_task)},
                         ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
