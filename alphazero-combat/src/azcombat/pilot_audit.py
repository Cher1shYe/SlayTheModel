"""Read-only, fail-closed audit of the frozen 20-combat natural pilot.

Every attempt remains visible, including publication failures and partial
JSONL.  A complete combat is counted once, never once per decision row.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import re
from statistics import median
from typing import Any

from .experiments import checked_model, sha256
from .native_probe import audit_probe
from .natural_pilot import (PILOT_ENCOUNTERS, PILOT_FORMAT, PILOT_POLICIES,
                            _source_snapshot, _validated_enemy_damage_regression)
from .samples import read_jsonl
from .versions import (FEATURE_ABI, OBSERVATION_SCHEMA_VERSION, REWARD_LEDGER_VERSION,
                       SEARCH_SEMANTICS_VERSION)


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    _require(isinstance(value, dict), f"JSON root must be an object: {path}")
    return value


def _partial_jsonl(path: Path | None) -> dict | None:
    if path is None or not path.is_file():
        return None
    lines = path.read_bytes().splitlines()
    parsed = 0
    first_error = None
    for number, line in enumerate(lines, 1):
        try:
            value = json.loads(line.decode("utf-8"))
            if not isinstance(value, dict):
                raise ValueError("JSONL row root is not an object")
            parsed += 1
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
            if first_error is None:
                first_error = f"line {number}: {type(error).__name__}: {error}"
    return {"lines": len(lines), "parsedRows": parsed,
            "firstParseError": first_error, "sha256": sha256(path)}


def _relative(root: Path, raw: str, *, label: str) -> Path:
    _require(isinstance(raw, str) and raw and not Path(raw).is_absolute(),
             f"{label} must be a relative path")
    path = (root / raw).resolve()
    _require(path.is_relative_to(root.resolve()), f"{label} escapes pilot directory")
    return path


def _referenced_hash(item: dict, *, path_key: str = "path", hash_key: str = "sha256") -> None:
    _require(isinstance(item, dict) and isinstance(item.get(path_key), str)
             and isinstance(item.get(hash_key), str), "frozen reference is incomplete")
    path = Path(item[path_key]).resolve(strict=True)
    _require(sha256(path).lower() == item[hash_key].lower(),
             f"frozen reference changed: {path}")


def _validate_manifest(manifest: dict, root: Path, *, verify_source: bool) -> dict[str, dict]:
    _require(manifest.get("format") == PILOT_FORMAT
             and manifest.get("purpose") == "collection-reliability-and-coverage-only",
             "not the frozen natural-pilot collection plan")
    contracts = manifest.get("contracts")
    reward = contracts.get("rewardDefinition") if isinstance(contracts, dict) else None
    _require(isinstance(contracts, dict)
             and contracts.get("observationSchemaVersion") == OBSERVATION_SCHEMA_VERSION
             and contracts.get("featureAbi") == FEATURE_ABI
             and contracts.get("searchSemanticsVersion") == SEARCH_SEMANTICS_VERSION
             and contracts.get("rewardLedgerVersion") == REWARD_LEDGER_VERSION
             and isinstance(reward, dict)
             and reward.get("source") == "alphazero-combat/src/azcombat/reward.py:score_result"
             and set(reward) == {"source", "win", "loss", "unresolved", "invalid"},
             "frozen observation/feature/search/reward contracts differ")
    rules = manifest.get("collectionRules")
    _require(isinstance(rules, dict) and rules.get("maximumAttemptsPerTask") == 2
             and rules.get("allOutcomesRetained") is True
             and rules.get("regressionOnly") is False
             and rules.get("treeAndPureDataSeparate") is True
             and rules.get("noForcedActionsOrHp") is True,
             "frozen collection/retry rules are incomplete")
    for name in ("crossRootRegression", "enemyDamageRegression", "budgetEvidence",
                 "historicalSeedSplit", "deckTemplates"):
        _referenced_hash(manifest.get(name))
    damage_reference = manifest["enemyDamageRegression"]
    _validated_enemy_damage_regression(_json(Path(damage_reference["path"])))
    tree = manifest.get("treeCandidate")
    _require(isinstance(tree, dict), "frozen tree candidate identity is missing")
    _referenced_hash(tree, path_key="onnxPath", hash_key="onnxSha256")
    _referenced_hash(tree, path_key="manifestPath", hash_key="manifestSha256")
    _require(checked_model(Path(tree["onnxPath"])).lower() == tree["onnxSha256"].lower(),
             "frozen tree candidate manifest/weights differ")
    source = manifest.get("sourceSnapshot")
    _require(isinstance(source, dict) and isinstance(source.get("sourceTreeSha256"), str),
             "frozen source snapshot is missing")
    if verify_source:
        repo = Path(__file__).resolve().parents[3]
        _require(_source_snapshot(repo) == source,
                 "current source differs from the frozen pre-collection snapshot")
    partitions = manifest.get("seedPartitions")
    _require(isinstance(partitions, dict), "frozen seed partitions are missing")
    train = partitions.get("train")
    validation = partitions.get("validation")
    final = partitions.get("finalEvaluationSealed")
    _require(isinstance(train, list) and len(train) == 4
             and isinstance(validation, list) and len(validation) == 1
             and isinstance(final, list) and len(final) >= 5
             and all(isinstance(seed, str) and seed for seed in [*train, *validation, *final])
             and len(set([*train, *validation, *final])) == len(train) + len(validation) + len(final),
             "pilot/final-evaluation seed isolation differs")
    tasks = manifest.get("tasks")
    _require(isinstance(tasks, list) and len(tasks) == 20,
             "natural pilot must have exactly 20 pre-registered combat tasks")
    assignments = manifest["deckTemplates"].get("assignments")
    cards = manifest["deckTemplates"].get("cards")
    _require(isinstance(assignments, dict) and isinstance(cards, dict),
             "frozen deck template assignments are missing")
    by_id: dict[str, dict] = {}
    matrix: set[tuple[str, str, str]] = set()
    scenario_pairs: dict[tuple[str, str], tuple[str, str]] = {}
    budget = None
    for task in tasks:
        _require(isinstance(task, dict), "frozen task is malformed")
        task_id = task.get("taskId")
        seed, encounter, policy = (task.get("seed"), task.get("encounter"), task.get("policy"))
        _require(isinstance(task_id, str) and re.fullmatch(r"[A-Za-z0-9_-]+", task_id)
                 and task_id not in by_id, "task ID is unsafe or duplicated")
        _require(seed in [*train, *validation] and encounter in PILOT_ENCOUNTERS
                 and policy in PILOT_POLICIES, f"task {task_id} has unregistered seed/encounter/policy")
        _require(task.get("partition") == ("train" if seed in train else "validation")
                 and task.get("startType") == "full_combat"
                 and task.get("deckTemplate") == assignments.get(seed)
                 and task["deckTemplate"] in cards,
                 f"task {task_id} changes split, start or deck template")
        mode = "pure-mcts" if policy == "pure-mcts" else "policy-value-tree-v1"
        expected_model = None if policy == "pure-mcts" else tree["onnxSha256"]
        _require(task.get("requestedSearchMode") == mode
                 and task.get("requestedModelSha256") == expected_model,
                 f"task {task_id} search/model identity differs")
        task_budget = tuple(task.get(key) for key in
                            ("budgetMilliseconds", "maxSimulations", "maxDecisions",
                             "workerCancellationSeconds", "timeoutSeconds",
                             "pythonSubprocessTimeoutSeconds"))
        _require(task_budget[0] == 1000 and task_budget[1] is None
                 and task_budget[2:] == (256, 600, 1800, 2100),
                 f"task {task_id} search/trajectory budget differs")
        if budget is None:
            budget = task_budget
        _require(task_budget == budget, f"task {task_id} changes the paired budget")
        scenario = _relative(root, task.get("generatedScenario"), label="generated scenario")
        _require(scenario.is_file() and sha256(scenario).lower()
                 == str(task.get("generatedScenarioSha256", "")).lower(),
                 f"task {task_id} generated opening changed")
        spec = _json(scenario)
        _require(spec.get("seed") == seed and spec.get("encounterId") == encounter
                 and spec.get("characterCards", {}).get("ids") == cards[task["deckTemplate"]]
                 and spec.get("includeStartingDeck") is False
                 and spec.get("includeStartingRelics") is True,
                 f"task {task_id} generated opening differs from frozen deck")
        pair = (seed, encounter)
        scenario_identity = (str(scenario), task["generatedScenarioSha256"])
        if pair in scenario_pairs:
            _require(scenario_pairs[pair] == scenario_identity,
                     f"paired tasks for {seed}/{encounter} use different opening specs")
        scenario_pairs[pair] = scenario_identity
        matrix.add((seed, encounter, policy))
        by_id[task_id] = task
    _require(len(matrix) == 20, "natural pilot task matrix has duplicates or gaps")
    return by_id


def _audit_attempt(root: Path, task: dict, attempt_number: int, attempt_dir: Path,
                   *, reaudit_overkill: bool = False) -> dict:
    task_id = task["taskId"]
    expected_relative = f"attempts/{task_id}/attempt-{attempt_number:03d}"
    _require(attempt_dir.resolve() == (root / expected_relative).resolve(),
             f"task {task_id} attempt path differs from frozen convention")
    meta = _json(attempt_dir / "attempt.json")
    _require(meta.get("taskId") == task_id and meta.get("attemptNumber") == attempt_number
             and meta.get("status") in {"complete", "failed"}
             and isinstance(meta.get("startedAtUtc"), str)
             and isinstance(meta.get("finishedAtUtc"), str),
             f"task {task_id} attempt {attempt_number} metadata is incomplete")
    expected_paths = {
        "jsonl": f"{expected_relative}/trajectory.jsonl",
        "probeReport": f"{expected_relative}/trajectory.probe.json",
        "rootParityOutput": (f"{expected_relative}/trajectory.root-parity.jsonl"
                             if task["policy"] == "tree-candidate" else None),
    }
    for key, expected in expected_paths.items():
        _require(meta.get(key) == expected,
                 f"task {task_id} attempt {attempt_number} {key} differs from frozen path")
    files = {key: _relative(root, path, label=key) if path else None
             for key, path in expected_paths.items()}
    evidence_files = [path for path in attempt_dir.iterdir() if path.is_file()]
    stage = attempt_dir / "trajectory.stage"
    evidence_files.extend(stage / name for name in
                          ("stage_provenance.json", "stdout.txt", "stderr.txt")
                          if (stage / name).is_file())
    artifacts = {str(path.relative_to(root)): {"sha256": sha256(path), "bytes": path.stat().st_size}
                 for path in evidence_files}
    for key, path in (("jsonlSha256", files["jsonl"]),
                      ("probeReportSha256", files["probeReport"]),
                      ("rootParitySha256", files["rootParityOutput"]),
                      ("stageProvenanceSha256", stage / "stage_provenance.json")):
        if key in meta:
            _require(path is not None and path.is_file() and sha256(path) == meta[key],
                     f"task {task_id} attempt {attempt_number} {key} changed")
    historical_failure = meta["status"] == "failed"
    if historical_failure:
        _require(isinstance(meta.get("error"), str) and meta["error"],
                 f"task {task_id} failed attempt lacks an error")
        _require(meta.get("failureClass") in {"infrastructure", "protocol-or-unclassified"},
                 f"task {task_id} failure class is missing")
        if not reaudit_overkill:
            return {"attemptNumber": attempt_number, "status": "failed",
                    "failureClass": meta["failureClass"], "error": meta["error"],
                    "rawJsonl": _partial_jsonl(files["jsonl"]),
                    "artifacts": artifacts}
        _require(meta["failureClass"] == "protocol-or-unclassified"
                 and re.fullmatch(r"ValueError: native transition \d+ has a malformed damage event",
                                  meta["error"]) is not None,
                 f"task {task_id} historical failure is not eligible for overkill re-audit")
        _require(all(key in meta for key in ("jsonlSha256", "probeReportSha256",
                                             "stageProvenanceSha256"))
                 and (files["rootParityOutput"] is None or "rootParitySha256" in meta),
                 f"task {task_id} re-audit requires hashes of original evidence")
    else:
        _require(meta.get("error") is None, f"task {task_id} complete attempt records an error")
        _require(meta.get("samples") is not None and meta.get("outcome") is not None
                 and meta.get("valueTarget") is not None,
                 f"task {task_id} completed attempt lacks saved result")
    probe_path = files["probeReport"]
    jsonl = files["jsonl"]
    parity = files["rootParityOutput"]
    assert probe_path is not None and jsonl is not None
    probe = _json(probe_path)
    expected_probe = {
        "status": "failed" if historical_failure else "complete",
        "exitCode": 0, "output": str(jsonl.resolve()),
        "seed": task["seed"], "encounter": task["encounter"],
        "requestedSearchMode": task["requestedSearchMode"],
        "modelSha256": task["requestedModelSha256"],
        "generatedScenarioPath": str(_relative(root, task["generatedScenario"], label="scenario")),
        "generatedScenarioSha256": task["generatedScenarioSha256"],
        "fixtureCards": None, "forceCard": None, "initialHp": None,
        "regressionOnly": False, "maxDecisions": task["maxDecisions"],
        "budgetMilliseconds": task["budgetMilliseconds"],
        "maxSimulations": task["maxSimulations"],
        "timeoutSeconds": task["timeoutSeconds"],
        "rootParityOutput": str(parity.resolve()) if parity else None,
        "stageRoot": str(jsonl.with_suffix(".stage").resolve()),
    }
    for key, expected in expected_probe.items():
        _require(probe.get(key) == expected,
                 f"task {task_id} attempt {attempt_number} probe {key} differs from frozen task")
    if historical_failure:
        _require(probe.get("error") == meta["error"].removeprefix("ValueError: "),
                 f"task {task_id} original probe error differs from attempt")
    result = audit_probe(jsonl, expected=probe)
    if not historical_failure:
        for key in ("samples", "outcome", "valueTarget", "jsonlSha256", "priorCalls",
                    "valueCalls", "fallbacks"):
            _require(probe.get(key) == result.get(key),
                     f"task {task_id} attempt {attempt_number} saved probe audit {key} differs")
        for key in ("samples", "outcome", "valueTarget", "assemblies"):
            _require(meta.get(key) == result[key],
                     f"task {task_id} attempt {attempt_number} result {key} differs")
    raw = [json.loads(line) for line in jsonl.read_text(encoding="utf-8").splitlines()]
    provenance = raw[0]["provenance"]
    if historical_failure:
        index = int(re.search(r"transition (\d+)", meta["error"])[1])
        _require(index < len(provenance["enemyHpTransitions"]),
                 f"task {task_id} original failure transition is outside the ledger")
        events = provenance["enemyHpTransitions"][index]["enemyDamageEvents"]
        _require(any(event["overkillDamage"] > event["unblockedDamage"] for event in events),
                 f"task {task_id} original failure has no overkill-ordering evidence")
    choices = sum(item.observation["choice"] is not None for item in read_jsonl(jsonl))
    nested = sum(metric["choiceLayer"] > 1 for metric in provenance["decisionMetrics"])
    return {"attemptNumber": attempt_number, "status": "complete", "outcome": result["outcome"],
            "originalAttemptStatus": meta["status"], "originalProbeStatus": probe["status"],
            "workerExitCode": probe["exitCode"], "originalError": meta.get("error"),
            "acceptanceStatus": "accepted-after-reaudit" if historical_failure else "accepted",
            "valueTarget": result["valueTarget"], "decisions": result["samples"],
            "combatDecisions": result["rewardLedger"]["captures"],
            "choiceDecisions": choices, "nestedChoiceDecisions": nested,
            "enemyHpLost": result["enemyDamageLost"], "entryHp": result["entryHp"],
            "settledHp": result["playerHp"], "rewardLedger": result["rewardLedger"],
            "priorCalls": result["priorCalls"], "valueCalls": result["valueCalls"],
            "fallbacks": result["fallbacks"], "modelSha256": probe["modelSha256"],
            "assemblies": result["assemblies"], "opening": {
                "observation": raw[0]["observation"], "stateKey": raw[0]["stateKey"],
                "orderedActionIds": [action["actionId"] for action in raw[0]["legalActions"]],
                "requestedCards": provenance["generatedDeck"]["requestedCards"],
                "actualDeck": provenance["generatedDeck"]["actualDeck"],
                "entryHp": provenance["entryHp"]}, "artifacts": artifacts}


def audit_pilot(manifest_path: Path, *, verify_source: bool = True,
                reaudit_overkill: bool = False,
                inherited_roots: dict[str, Path] | None = None) -> dict:
    """Return every task/attempt plus protocol errors without altering pilot files."""
    manifest_path = manifest_path.resolve(strict=True)
    root = manifest_path.parent
    _require(manifest_path.name == "manifest.json", "pilot audit requires manifest.json")
    digest = sha256(manifest_path)
    _require((root / "manifest.sha256").read_text(encoding="ascii").strip().lower() == digest,
             "frozen manifest SHA256 changed")
    manifest = _json(manifest_path)
    tasks = _validate_manifest(manifest, root, verify_source=verify_source)
    inherited_roots = inherited_roots or {}
    _require(set(inherited_roots) <= set(tasks), "inherited tasks are not registered")
    attempts_root = root / "attempts"
    _require(attempts_root.is_dir(), "pilot attempts directory is missing")
    unexpected = sorted(path.name for path in attempts_root.iterdir()
                        if not path.is_dir() or path.name not in tasks)
    _require(not unexpected, f"unregistered pilot task directories: {unexpected}")
    results = []
    errors = []
    completed_by_pair: dict[tuple[str, str], dict[str, dict]] = defaultdict(dict)
    for task in manifest["tasks"]:
        task_id = task["taskId"]
        attempt_root = inherited_roots.get(task_id, root)
        _require(task_id not in inherited_roots or not (attempts_root / task_id).exists(),
                 f"inherited task {task_id} was rerun in the continuation")
        task_dir = attempt_root / "attempts" / task_id
        attempts = []
        if task_dir.exists():
            _require(task_dir.is_dir(), f"task {task_id} attempt path is not a directory")
            names = sorted(path.name for path in task_dir.iterdir())
            expected = [f"attempt-{number:03d}" for number in range(1, len(names) + 1)]
            if names != expected or len(names) > 2:
                errors.append(f"task {task_id} has missing, extra or excessive attempt slots: {names}")
                attempts.extend({"attemptNumber": None, "status": "audit-failed",
                                 "error": f"unregistered attempt path: {name}"} for name in names)
            else:
                for number, name in enumerate(names, 1):
                    try:
                        options = {"reaudit_overkill": True} if reaudit_overkill and (
                            not inherited_roots or task_id in inherited_roots) else {}
                        attempt_result = _audit_attempt(attempt_root, task, number, task_dir / name, **options)
                        if task_id in inherited_roots:
                            attempt_result["artifactBaseDirectory"] = str(attempt_root)
                        attempts.append(attempt_result)
                    except (OSError, KeyError, TypeError, ValueError) as error:
                        message = f"task {task_id} attempt {number} protocol audit failed: {error}"
                        errors.append(message)
                        attempts.append({"attemptNumber": number, "status": "audit-failed",
                                         "error": str(error)})
        complete = [attempt for attempt in attempts if attempt["status"] == "complete"]
        if len(complete) > 1 or complete and attempts[-1] is not complete[0]:
            errors.append(f"task {task_id} was retried after a complete combat")
        if len(attempts) > 1 and (attempts[0]["status"] != "failed"
                                 or attempts[0].get("failureClass") != "infrastructure"):
            errors.append(f"task {task_id} retried after a non-infrastructure failure")
        for attempt in attempts:
            if attempt["status"] == "failed" \
                    and attempt.get("failureClass") == "protocol-or-unclassified":
                errors.append(f"task {task_id} attempt {attempt['attemptNumber']} "
                              f"stopped on a protocol-or-unclassified failure: {attempt['error']}")
        if complete:
            status = "complete"
            completed_by_pair[(task["seed"], task["encounter"])][task["policy"]] = complete[0]
        elif attempts:
            status = "failed"
        else:
            status = "planned"
        results.append({"taskId": task_id, "seed": task["seed"],
                        "encounter": task["encounter"], "policy": task["policy"],
                        "partition": task["partition"], "status": status,
                        "attempts": attempts})
    paired = []
    for seed in [*manifest["seedPartitions"]["train"],
                 *manifest["seedPartitions"]["validation"]]:
        for encounter in PILOT_ENCOUNTERS:
            pair = completed_by_pair[(seed, encounter)]
            if set(pair) != set(PILOT_POLICIES):
                paired.append({"seed": seed, "encounter": encounter, "status": "unpaired",
                               "available": sorted(pair)})
                continue
            pure = pair["pure-mcts"]["opening"]
            tree = pair["tree-candidate"]["opening"]
            differing = [key for key in ("observation", "stateKey", "orderedActionIds",
                                         "requestedCards", "actualDeck", "entryHp")
                         if pure[key] != tree[key]]
            if differing:
                errors.append(f"paired opening differs for {seed}/{encounter}: {differing}")
                paired.append({"seed": seed, "encounter": encounter,
                               "status": "mismatch", "fields": differing})
            else:
                paired.append({"seed": seed, "encounter": encounter, "status": "matched"})
    grouped: dict[str, Counter] = defaultdict(Counter)
    for encounter in PILOT_ENCOUNTERS:
        for policy in PILOT_POLICIES:
            grouped[f"{encounter}|{policy}"]
    completed = []
    for task in results:
        if task["status"] != "complete":
            continue
        attempt = next(item for item in task["attempts"] if item["status"] == "complete")
        completed.append(attempt)
        grouped[f"{task['encounter']}|{task['policy']}"][attempt["outcome"]] += 1
    rewards = [item["valueTarget"] for item in completed]
    lengths = [item["decisions"] for item in completed]
    summary: dict[str, Any] = {
        "format": "azcombat.natural-pilot-audit.v1", "manifestSha256": digest,
        "status": "protocol-error" if errors else "complete" if len(completed) == 20 else "incomplete",
        "plannedCombats": 20, "completedCombats": len(completed),
        "failedTasks": sum(task["status"] == "failed" for task in results),
        "failedAttempts": sum(attempt["status"] != "complete"
                              for task in results for attempt in task["attempts"]),
        "attempts": sum(len(task["attempts"]) for task in results),
        "retries": sum(max(0, len(task["attempts"]) - 1) for task in results),
        "decisionRows": sum(item["decisions"] for item in completed),
        "combatDecisionRoots": sum(item["combatDecisions"] for item in completed),
        "naturalChoiceRows": sum(item["choiceDecisions"] for item in completed),
        "nestedChoiceRows": sum(item["nestedChoiceDecisions"] for item in completed),
        "naturalDeathCombats": sum(item["outcome"] == "loss" for item in completed),
        "byEncounterPolicy": {key: {outcome: counts[outcome]
                                     for outcome in ("win", "loss", "unresolved")}
                              for key, counts in sorted(grouped.items())},
        "rewardDistribution": {"min": min(rewards), "median": median(rewards),
                               "max": max(rewards)} if rewards else None,
        "trajectoryDecisionLength": {"min": min(lengths), "median": median(lengths),
                                     "max": max(lengths)} if lengths else None,
        "pairedOpenings": paired, "errors": errors, "tasks": results,
    }
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--output", type=Path,
                        help="write a new audit JSON outside the frozen pilot; never overwrite")
    args = parser.parse_args()
    report = audit_pilot(args.manifest)
    rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output is not None:
        output = args.output.resolve()
        if output.is_relative_to(args.manifest.resolve().parent):
            raise ValueError("audit output must be outside the frozen pilot directory")
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("x", encoding="utf-8") as handle:
            handle.write(rendered)
        print(json.dumps({"status": report["status"], "plannedCombats": 20,
                          "completedCombats": report["completedCombats"],
                          "attempts": report["attempts"], "report": str(output)},
                         ensure_ascii=False))
    else:
        print(rendered, end="")
    return 0 if report["status"] == "complete" else 1


if __name__ == "__main__":
    raise SystemExit(main())
