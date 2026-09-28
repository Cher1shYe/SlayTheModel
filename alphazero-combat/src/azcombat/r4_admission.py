"""Strict admission/indexing for the frozen R4 natural-pilot data.

This module only reads and indexes accepted trajectories.  It never rewrites
JSONL, converts outcomes, or starts training.  The index is deliberately more
specific than the general pilot audit: it records the source of native damage
evidence and keeps re-audits/history-reset evidence visible.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
from typing import Any

from .samples import read_jsonl
from .training import load_seed_split
from .versions import FEATURE_ABI, OBSERVATION_SCHEMA_VERSION, REWARD_LEDGER_VERSION, SEARCH_SEMANTICS_VERSION


FORMAT = "azcombat.r4-training-admission.v1"
EXPECTED_PILOT_FORMAT = "azcombat.natural-pilot.v2"
EXPECTED_AUDIT_FORMAT = "azcombat.natural-pilot-audit.v1"
EXPECTED_POLICIES = ("pure-mcts", "tree-candidate")
EXPECTED_OUTCOMES = ("win", "loss", "unresolved")


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    _require(isinstance(value, dict), f"JSON root must be an object: {path}")
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _reference(path: Path, expected: str, label: str) -> None:
    _require(path.is_file(), f"{label} is missing: {path}")
    _require(_sha256(path).lower() == expected.lower(), f"{label} SHA256 changed: {path}")


def _artifact_path(base: Path, relative: str) -> Path:
    path = Path(relative)
    if not path.is_absolute():
        path = base / path
    return path.resolve(strict=True)


def _choice(row: dict[str, Any]) -> bool:
    observation = row.get("observation")
    if not isinstance(observation, dict):
        raise ValueError("sample observation is not an object")
    return observation.get("Choice", observation.get("choice")) is not None


def _capture_evidence(rows: list[dict[str, Any]]) -> dict[str, Any]:
    sources: set[str] = set()
    protocols: set[str] = set()
    reference_transitions: list[dict[str, Any]] | None = None
    for row_number, row in enumerate(rows, 1):
        provenance = row.get("provenance")
        _require(isinstance(provenance, dict), f"row {row_number} has no provenance")
        transitions = provenance.get("enemyHpTransitions")
        _require(isinstance(transitions, list), f"row {row_number} has no enemyHpTransitions")
        if reference_transitions is None:
            reference_transitions = transitions
        else:
            _require(transitions == reference_transitions,
                     f"row {row_number} enemyHpTransitions differ from trajectory provenance")
        for transition in transitions:
            _require(isinstance(transition, dict), f"row {row_number} has malformed HP transition")
            # Missing is deliberately distinct from the legacy history-slice
            # label.  Passing the strict audit does not manufacture evidence
            # that the native event command was used.
            source = transition.get("damageCaptureSource", "missing")
            _require(isinstance(source, str) and source in {
                     "missing", "legacy-history-slice", "native-damage-command-v1"},
                     f"row {row_number} has unknown damageCaptureSource")
            protocol = "legacy-history-slice" if source in {"missing", "legacy-history-slice"} else source
            _require(type(transition.get("historyReset")) is bool,
                     f"row {row_number} historyReset is missing")
            sources.add(source)
            protocols.add(protocol)
    _require(len(sources) == 1 and len(protocols) == 1,
             "a trajectory mixes damageCaptureSource protocols")
    source = next(iter(sources))
    protocol = next(iter(protocols))
    assert reference_transitions is not None
    history_reset = sum(int(item["historyReset"]) for item in reference_transitions)
    return {"sources": [source], "protocols": [protocol], "historyResetTrue": history_reset,
            "historyResetTrajectory": history_reset > 0,
            "transitionCount": len(reference_transitions),
            "hasIndependentEventEvidence": protocol == "native-damage-command-v1"}


def _manifest_for_audit(audit_path: Path, audit: dict[str, Any]) -> tuple[Path, dict[str, Any]]:
    reference = audit.get("executionRepairManifest")
    _require(isinstance(reference, dict) and isinstance(reference.get("path"), str)
             and isinstance(reference.get("sha256"), str),
             "audit does not identify its frozen manifest")
    manifest_path = Path(reference["path"]).resolve(strict=True)
    _reference(manifest_path, reference["sha256"], "frozen manifest")
    if isinstance(audit.get("manifestSha256"), str):
        _require(_sha256(manifest_path).lower() == audit["manifestSha256"].lower(),
                 "audit/manifest SHA256 differs")
    return manifest_path, _load(manifest_path)


def _validate_contracts(manifest_path: Path, manifest: dict[str, Any]) -> None:
    _require(manifest.get("format") == EXPECTED_PILOT_FORMAT, "unsupported pilot manifest")
    contracts = manifest.get("contracts")
    _require(isinstance(contracts, dict)
             and contracts.get("observationSchemaVersion") == OBSERVATION_SCHEMA_VERSION
             and contracts.get("featureAbi") == FEATURE_ABI
             and contracts.get("searchSemanticsVersion") == SEARCH_SEMANTICS_VERSION
             and contracts.get("rewardLedgerVersion") == REWARD_LEDGER_VERSION,
             "frozen R4 contracts differ from current contracts")
    tree = manifest.get("treeCandidate")
    _require(isinstance(tree, dict) and tree.get("parameterCount") == 1970
             and tree.get("usage") == "fixed-behavior-policy-only",
             "tree candidate is not the fixed 1,970-parameter behavior candidate")
    model = _artifact_path(manifest_path.parent, tree.get("onnxPath", ""))
    _reference(model, str(tree.get("onnxSha256", "")), "tree candidate ONNX")
    model_manifest = _artifact_path(manifest_path.parent, tree.get("manifestPath", ""))
    _reference(model_manifest, str(tree.get("manifestSha256", "")),
               "tree candidate ONNX manifest")
    candidate = _load(model_manifest)
    _require(candidate.get("featureAbi") == FEATURE_ABI
             and candidate.get("observationSchemaVersion") == OBSERVATION_SCHEMA_VERSION,
             "tree candidate feature/observation ABI differs")
    partitions = manifest.get("seedPartitions")
    _require(isinstance(partitions, dict), "frozen R4 seed partitions are missing")
    groups: dict[str, list[str]] = {}
    for name in ("train", "validation", "finalEvaluationSealed"):
        values = partitions.get(name)
        _require(isinstance(values, list) and values
                 and all(isinstance(seed, str) and seed for seed in values)
                 and len(values) == len(set(values)), f"invalid frozen R4 {name} seeds")
        groups[name] = list(values)
    all_seeds = groups["train"] + groups["validation"] + groups["finalEvaluationSealed"]
    _require(len(groups["train"]) == 4 and len(groups["validation"]) == 1
             and len(all_seeds) == len(set(all_seeds)),
             "R4 must retain four training and one validation seed without overlap")
    historical = manifest.get("historicalSeedSplit")
    _require(isinstance(historical, dict), "historical seed split reference is missing")
    split = _artifact_path(manifest_path.parent, historical.get("path", ""))
    _reference(split, str(historical.get("sha256", "")), "historical seed split")
    old = load_seed_split(split)
    _require(not (set(all_seeds) & set(old["trainSeeds"])
                  or set(all_seeds) & set(old["validationSeeds"])
                  or set(all_seeds) & set(old["evaluationSeeds"])),
             "R4 seed overlaps historical split")


def _task_map(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    tasks = manifest.get("tasks")
    _require(isinstance(tasks, list) and tasks, "frozen manifest has no tasks")
    result: dict[str, dict[str, Any]] = {}
    for task in tasks:
        _require(isinstance(task, dict) and isinstance(task.get("taskId"), str),
                 "manifest task is malformed")
        _require(task["taskId"] not in result, f"duplicate manifest taskId: {task['taskId']}")
        _require(task.get("policy") in EXPECTED_POLICIES, f"unknown policy: {task.get('policy')}")
        result[task["taskId"]] = task
    return result


def _accepted_attempt(task_id: str, task: dict[str, Any]) -> dict[str, Any]:
    attempts = task.get("attempts")
    _require(isinstance(attempts, list), f"audit task {task_id} has no attempt list")
    accepted = [attempt for attempt in attempts
                if isinstance(attempt, dict)
                and str(attempt.get("acceptanceStatus", "")).startswith("accepted")]
    _require(len(accepted) == 1, f"task {task_id} does not have exactly one accepted source")
    attempt = accepted[0]
    _require(attempt.get("status") == "complete", f"accepted task {task_id} is not complete")
    _require(attempt.get("outcome") in EXPECTED_OUTCOMES, f"task {task_id} has invalid outcome")
    return attempt


def _trajectory_path(attempt: dict[str, Any], audit_root: Path) -> tuple[Path, str, dict[str, Any]]:
    artifacts = attempt.get("artifacts")
    _require(isinstance(artifacts, dict), "accepted attempt has no artifact inventory")
    matches = [(name, identity) for name, identity in artifacts.items()
               if isinstance(name, str) and name.lower().endswith("trajectory.jsonl")]
    _require(len(matches) == 1, "accepted attempt must identify exactly one trajectory JSONL")
    relative, identity = matches[0]
    _require(isinstance(identity, dict) and isinstance(identity.get("sha256"), str),
             "trajectory artifact hash is missing")
    base = Path(attempt.get("artifactBaseDirectory") or audit_root)
    path = _artifact_path(base, relative)
    _reference(path, identity["sha256"], "accepted trajectory")
    return path, identity["sha256"].lower(), identity


def _read_raw(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            value = json.loads(line)
            _require(isinstance(value, dict), f"trajectory row {line_number} is not an object")
            rows.append(value)
    return rows


def admit_r4(audit_path: Path) -> dict[str, Any]:
    """Build a read-only admission index from one frozen R4 audit."""
    audit_path = Path(audit_path).resolve(strict=True)
    audit = _load(audit_path)
    _require(audit.get("format") == EXPECTED_AUDIT_FORMAT
             and audit.get("status") == "complete"
             and audit.get("errors") == []
             and audit.get("failedTasks") == 0,
             "unsupported or incomplete R4 audit")
    manifest_path, manifest = _manifest_for_audit(audit_path, audit)
    _validate_contracts(manifest_path, manifest)
    manifest_tasks = _task_map(manifest)
    expected_matrix = {(seed, encounter, policy)
                       for seed in [*manifest["seedPartitions"]["train"],
                                    *manifest["seedPartitions"]["validation"]]
                       for encounter in ("CULTISTS_NORMAL", "LIVING_FOG_NORMAL")
                       for policy in EXPECTED_POLICIES}
    actual_matrix = {(task.get("seed"), task.get("encounter"), task.get("policy"))
                     for task in manifest_tasks.values()}
    _require(len(actual_matrix) == len(manifest_tasks) == len(expected_matrix)
             and actual_matrix == expected_matrix,
             "R4 frozen task matrix differs from 5 seed x 2 encounter x 2 policy")
    paired_inputs: dict[tuple[str, str], tuple[str, str]] = {}
    for task in manifest_tasks.values():
        pair = (task["seed"], task["encounter"])
        identity = (task.get("generatedScenario"), task.get("generatedScenarioSha256"))
        if pair in paired_inputs:
            _require(paired_inputs[pair] == identity,
                     f"task {task['taskId']} paired input differs")
        else:
            paired_inputs[pair] = identity
    audit_tasks = audit.get("tasks")
    _require(isinstance(audit_tasks, list), "audit has no task list")
    _require(len(audit_tasks) == len(manifest_tasks), "audit/manifest task counts differ")
    seen_task_ids: set[str] = set()
    seen_trajectory_hashes: set[str] = set()
    entries: list[dict[str, Any]] = []
    by_policy: Counter[str] = Counter()
    by_outcome: Counter[str] = Counter()
    by_source: Counter[str] = Counter()
    by_node_type: Counter[str] = Counter()
    by_policy_node: Counter[str] = Counter()
    by_outcome_node: Counter[str] = Counter()
    pending_entries: list[dict[str, Any]] = []
    for audited_task in audit_tasks:
        _require(isinstance(audited_task, dict) and isinstance(audited_task.get("taskId"), str),
                 "audit task is malformed")
        task_id = audited_task["taskId"]
        _require(task_id not in seen_task_ids, f"duplicate audited taskId: {task_id}")
        seen_task_ids.add(task_id)
        _require(task_id in manifest_tasks, f"audit task is not in frozen manifest: {task_id}")
        task = manifest_tasks[task_id]
        expected_partition = ("train" if task["seed"] in manifest["seedPartitions"]["train"]
                              else "validation" if task["seed"] in manifest["seedPartitions"]["validation"]
                              else None)
        _require(task.get("partition") == expected_partition,
                 f"task {task_id} partition differs from frozen seed split")
        for key in ("seed", "partition", "encounter", "policy"):
            _require(audited_task.get(key, task.get(key)) == task.get(key),
                     f"task {task_id} {key} differs from frozen manifest")
        attempt = _accepted_attempt(task_id, audited_task)
        path, trajectory_hash, artifact_identity = _trajectory_path(attempt, audit_path.parent)
        _require(trajectory_hash not in seen_trajectory_hashes,
                 f"trajectory JSONL is counted more than once: {path}")
        seen_trajectory_hashes.add(trajectory_hash)
        rows = _read_raw(path)
        strict_samples = read_jsonl(path, require_current_search_semantics=True)
        _require(len(rows) == len(strict_samples) == int(attempt.get("decisions", -1)),
                 f"task {task_id} row count differs from accepted audit")
        _require(rows, f"task {task_id} has no rows")
        outcome = attempt["outcome"]
        value_target = attempt.get("valueTarget")
        _require(type(value_target) in (int, float),
                 f"task {task_id} accepted value target is missing")
        policy = task["policy"]
        source_evidence = _capture_evidence(rows)
        expected_model_hash = (manifest["treeCandidate"].get("onnxSha256")
                               if task["policy"] == "tree-candidate" else None)
        _require(attempt.get("modelSha256") == expected_model_hash,
                 f"task {task_id} model identity differs from frozen behavior policy")
        choices = 0
        fallbacks = 0
        search_modes: set[str] = set()
        reward_versions: set[str] = set()
        model_hashes: set[str | None] = set()
        for index, (row, sample) in enumerate(zip(rows, strict_samples, strict=True)):
            provenance = row["provenance"]
            _require(sample.seed == task["seed"] and sample.outcome == outcome,
                     f"task {task_id} sample {index} seed/outcome differs")
            _require(sample.value_target == value_target,
                     f"task {task_id} sample {index} value target differs from accepted audit")
            _require(provenance.get("regressionOnly") is False,
                     f"task {task_id} is regressionOnly")
            _require(provenance.get("searchSemanticsVersion") == SEARCH_SEMANTICS_VERSION
                     and provenance.get("rewardLedgerVersion") == REWARD_LEDGER_VERSION,
                     f"task {task_id} sample {index} contract differs")
            requested = provenance.get("requestedSearchMode")
            actual = provenance.get("searchMode")
            expected_mode = "pure-mcts" if policy == "pure-mcts" else "policy-value-tree-v1"
            _require(requested == actual == expected_mode,
                     f"task {task_id} sample {index} search mode differs")
            fallbacks += int(provenance.get("modelFallbacks", 0) or 0)
            metrics = provenance.get("decisionMetrics")
            _require(isinstance(metrics, list) and index < len(metrics),
                     f"task {task_id} sample {index} lacks decision metric")
            metric = metrics[index]
            _require(isinstance(metric, dict) and metric.get("searchMode") == expected_mode
                     and int(metric.get("networkFallbacks", 0) or 0) == 0,
                     f"task {task_id} sample {index} has fallback or mode mismatch")
            choices += int(_choice(row))
            search_modes.add(actual)
            reward_versions.add(provenance["rewardLedgerVersion"])
            model_hashes.add(attempt.get("modelSha256") if policy == "tree-candidate" else None)
        _require(fallbacks == 0, f"task {task_id} has model fallbacks")
        scenario = (manifest_path.parent / task["generatedScenario"]).resolve(strict=True)
        _reference(scenario, task["generatedScenarioSha256"], "frozen scenario input")
        rows_count = len(rows)
        ordinary = rows_count - choices
        by_policy[policy] += rows_count
        by_outcome[outcome] += rows_count
        by_source[source_evidence["protocols"][0]] += rows_count
        by_node_type["ordinary"] += ordinary
        by_node_type["choice"] += choices
        by_policy_node[f"{policy}|ordinary"] += ordinary
        by_policy_node[f"{policy}|choice"] += choices
        by_outcome_node[f"{outcome}|ordinary"] += ordinary
        by_outcome_node[f"{outcome}|choice"] += choices
        pending_entries.append({
            "taskId": task_id,
            "seed": task["seed"],
            "partition": task["partition"],
            "encounter": task["encounter"],
            "policy": policy,
            "modelRole": "pure-mcts-reference-policy" if policy == "pure-mcts"
                         else "fixed-tree-behavior-policy-only",
            "modelSha256": (task.get("requestedModelSha256") if policy == "tree-candidate" else None),
            "inputPath": str(scenario),
            "inputSha256": task["generatedScenarioSha256"].lower(),
            "trajectoryPath": str(path),
            "trajectorySha256": trajectory_hash,
            "rowCount": rows_count,
            "ordinaryRows": ordinary,
            "choiceRows": choices,
            "outcome": outcome,
            "acceptanceStatus": attempt.get("acceptanceStatus"),
            "acceptedAfterReaudit": attempt.get("acceptanceStatus") == "accepted-after-reaudit",
            "originalAttemptStatus": attempt.get("originalAttemptStatus"),
            "originalProbeStatus": attempt.get("originalProbeStatus"),
            "originalError": attempt.get("originalError"),
            "captureEvidence": source_evidence,
            "searchModes": sorted(search_modes),
            "rewardLedgerVersions": sorted(reward_versions),
            "modelHashesObserved": sorted(x for x in model_hashes if x is not None),
            "fallbacks": fallbacks,
            "assemblies": attempt.get("assemblies"),
            "trajectoryRowWeightFormula": "1 / rowCount",
            "policyHeadWeightFormula": "0.5 / (eligibleTrajectoriesByPolicy * rowCount)",
            "valueHeadWeightFormula": "same as policy for win/loss; 0 for unresolved in R4 pilot",
        })
    _require(seen_task_ids == set(manifest_tasks), "audit does not cover exactly the frozen task set")
    _require(len(pending_entries) == 20 and len(seen_trajectory_hashes) == 20,
             "R4 admission requires exactly 20 unique accepted trajectories")
    historical = audit.get("historicalFailedAttempts", [])
    _require(isinstance(historical, list), "historicalFailedAttempts is malformed")
    sealed = list(manifest["seedPartitions"]["finalEvaluationSealed"])
    train = list(manifest["seedPartitions"]["train"])
    validation = list(manifest["seedPartitions"]["validation"])
    unresolved_rows = by_outcome["unresolved"]
    eligible_by_partition_policy: Counter[tuple[str, str]] = Counter(
        (entry["partition"], entry["policy"]) for entry in pending_entries)
    value_eligible_by_partition_policy: Counter[tuple[str, str]] = Counter(
        (entry["partition"], entry["policy"]) for entry in pending_entries
        if entry["outcome"] in {"win", "loss"})
    for entry in pending_entries:
        policy_count = eligible_by_partition_policy[(entry["partition"], entry["policy"])]
        value_count = value_eligible_by_partition_policy[(entry["partition"], entry["policy"])]
        entry["policyRowWeight"] = 0.5 / (policy_count * entry["rowCount"])
        entry["valueRowWeight"] = (0.0 if entry["outcome"] == "unresolved" else
                                    0.5 / (value_count * entry["rowCount"]))
        entry["policyEligible"] = True
        entry["valueEligible"] = entry["outcome"] in {"win", "loss"}
    entries = pending_entries
    plan = {
        "model": {"parameterCount": 1970, "featureAbi": FEATURE_ABI,
                  "observationSchemaVersion": OBSERVATION_SCHEMA_VERSION,
                  "treeCandidateBehaviorOnly": True,
                  "treeCandidateTrainingRewardLedgerVersion": manifest["treeCandidate"].get(
                      "trainingRewardLedgerVersion")},
        "strategyWeighting": {
            "policyAndValue": "equal behavior-stratum mass, then equal trajectory mass within each strategy, then equal row mass within a trajectory",
            "policyStratumMass": {"pure-mcts": 0.5, "tree-candidate": 0.5},
            "rowFormula": "0.5 / (number of eligible trajectories in strategy * trajectory row count)",
            "requiresWeightedTrainer": True,
            "currentRowWiseTrainerIsNotAdmitted": True,
        },
        "unresolvedHandling": {
            "label": "preserve-not-death",
            "rows": unresolved_rows,
            "keepInIndex": True,
            "policySupervisionWeight": 1.0,
            "valueSupervisionWeight": 0.0,
            "reason": "decision-limit termination is not a realized terminal outcome; do not turn it into loss or fabricate a value label",
            "laterRequirement": "pre-register a separate sensitivity run after independent validation evidence; never select it after looking at results",
        },
        "seedUse": {"train": train, "validation": validation,
                    "sealedEvaluation": sealed, "sealedEvaluationLoaded": False},
        "sourceUse": {
            "legacy-history-slice": "retain and label separately; no new event-evidence claim",
            "native-damage-command-v1": "retain and label as independent event evidence",
            "oldHistoryReset": "diagnostic evidence only; no relabeling",
        },
    }
    return {
        "format": FORMAT,
        "status": "admitted",
        "admissionTool": {"path": str(Path(__file__).resolve()),
                          "sha256": _sha256(Path(__file__).resolve())},
        "auditPath": str(audit_path),
        "auditSha256": _sha256(audit_path),
        "manifestPath": str(manifest_path),
        "manifestSha256": _sha256(manifest_path),
        "sourceSnapshot": manifest.get("sourceSnapshot"),
        "treeCandidate": manifest.get("treeCandidate"),
        "summary": {"tasks": len(entries), "samples": sum(x["rowCount"] for x in entries),
                    "ordinaryRows": by_node_type["ordinary"], "choiceRows": by_node_type["choice"],
                    "byPolicy": dict(by_policy), "byOutcome": dict(by_outcome),
                    "byCaptureSource": dict(by_source), "byNodeType": dict(by_node_type),
                    "byPolicyNodeType": dict(by_policy_node), "byOutcomeNodeType": dict(by_outcome_node),
                    "historicalExecutionAttempts": audit.get("allExecutionAttempts"),
                    "historicalFailedAttempts": len(historical),
                    "unresolvedRows": unresolved_rows},
        "historicalFailedAttempts": historical,
        "entries": sorted(entries, key=lambda item: item["taskId"]),
        "plan": plan,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("audit", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = admit_r4(args.audit)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
