from __future__ import annotations

import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from azcombat.r4_admission import admit_r4
from azcombat.samples import write_jsonl
from azcombat.schema import ActionNode
from test_schema_reward import observation
from test_training import sample


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _trajectory(path: Path, *, seed: str, encounter: str, policy: str,
                source: str | None, history_reset: bool, outcome: str) -> str:
    item = sample(seed).to_dict()
    item["outcome"] = outcome
    item["provenance"] = {
        "requestedSearchMode": "pure-mcts" if policy == "pure-mcts"
                               else "policy-value-tree-v1",
        "searchMode": "pure-mcts" if policy == "pure-mcts"
                      else "policy-value-tree-v1",
        "searchSemanticsVersion": "azcombat.search.v3",
        "rewardLedgerVersion": "azcombat.reward-ledger.v2",
        "regressionOnly": False,
        "seed": seed,
        "encounter": encounter,
        "modelFallbacks": 0,
        "decisionMetrics": [{"choiceLayer": 0,
                              "searchMode": "pure-mcts" if policy == "pure-mcts"
                              else "policy-value-tree-v1",
                              "networkFallbacks": 0}],
        "enemyHpTransitions": [{
            **({"damageCaptureSource": source} if source is not None else {}),
            "historyReset": history_reset,
        }],
    }
    path.write_text(json.dumps(item) + "\n", encoding="utf-8")
    return _sha(path)


def _fixture(root: Path) -> Path:
    (root / "attempts").mkdir()
    train_seeds = [f"train-seed-{index}" for index in range(4)]
    validation_seed = "validation-seed"
    split = root / "split.json"
    split.write_text(json.dumps({
        "format": "azcombat.seed-split.v1",
        "trainSeeds": ["old-train-seed"],
        "validationSeeds": ["old-validation-seed"],
        "evaluationSeeds": ["old-sealed-seed"],
    }), encoding="utf-8")
    model = root / "candidate.onnx"
    model.write_bytes(b"candidate")
    model_manifest = root / "candidate.manifest.json"
    model_manifest.write_text(json.dumps({"featureAbi": "azcombat.features.v4",
                                          "observationSchemaVersion": 3}), encoding="utf-8")
    manifest = {
        "format": "azcombat.natural-pilot.v2",
        "contracts": {
            "observationSchemaVersion": 3,
            "featureAbi": "azcombat.features.v4",
            "searchSemanticsVersion": "azcombat.search.v3",
            "rewardLedgerVersion": "azcombat.reward-ledger.v2",
        },
        "seedPartitions": {
            "train": train_seeds, "validation": [validation_seed],
            "finalEvaluationSealed": ["sealed-seed"],
        },
        "historicalSeedSplit": {"path": str(split), "sha256": _sha(split)},
        "treeCandidate": {
            "onnxPath": str(model), "onnxSha256": _sha(model),
            "manifestPath": str(model_manifest),
            "manifestSha256": _sha(model_manifest),
            "parameterCount": 1970,
            "usage": "fixed-behavior-policy-only",
            "trainingRewardLedgerVersion": "azcombat.reward-ledger.v1",
        },
    }
    tasks = []
    for index in range(20):
        seed_index = index // 4
        seed = train_seeds[seed_index] if seed_index < 4 else validation_seed
        partition = "train" if seed_index < 4 else "validation"
        policy = "pure-mcts" if index % 2 == 0 else "tree-candidate"
        encounter = "CULTISTS_NORMAL" if (index // 2) % 2 == 0 else "LIVING_FOG_NORMAL"
        source = None if index < 10 else "native-damage-command-v1"
        reset = index % 3 == 0
        outcome = "unresolved" if index == 19 else "win"
        task_id = f"{index:03d}-{encounter}-{policy}"
        attempt_dir = root / "attempts" / task_id / "attempt-001"
        attempt_dir.mkdir(parents=True)
        trajectory = attempt_dir / "trajectory.jsonl"
        trajectory_hash = _trajectory(trajectory, seed=seed, encounter=encounter,
                                      policy=policy, source=source,
                                      history_reset=reset, outcome=outcome)
        relative = str(trajectory.relative_to(root)).replace("/", "\\")
        tasks.append({
            "taskId": task_id, "seed": seed, "partition": partition,
            "encounter": encounter, "policy": policy,
            "requestedSearchMode": "pure-mcts" if policy == "pure-mcts"
                                   else "policy-value-tree-v1",
            "requestedModelSha256": None if policy == "pure-mcts" else _sha(model),
            "generatedScenario": f"inputs/{seed_index:03d}-{encounter}.json",
            "generatedScenarioSha256": "",
            "startType": "full_combat",
            "status": "complete", "attempts": [{
                "attemptNumber": 1, "status": "complete",
                "acceptanceStatus": "accepted", "outcome": outcome,
                "modelSha256": None if policy == "pure-mcts" else _sha(model),
                "valueTarget": 0.6,
                "decisions": 1,
                "artifacts": {relative: {"sha256": trajectory_hash}},
            }],
        })
    # The real R4 matrix shares one legal opening spec between the paired
    # policies.  Keep that invariant in the fixture while making every task's
    # trajectory hash distinct for duplicate-input detection.
    for index, spec in enumerate({
            (task["seed"], task["encounter"]): root / task["generatedScenario"]
            for task in tasks}.items()):
        (path := spec[1]).parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"seed": spec[0][0], "encounterId": spec[0][1]}),
                        encoding="utf-8")
        digest = _sha(path)
        for task in tasks:
            if task["seed"] == spec[0][0] and task["encounter"] == spec[0][1]:
                task["generatedScenarioSha256"] = digest
    manifest["tasks"] = tasks
    manifest["treeCandidate"]["onnxSha256"] = _sha(model)
    manifest["treeCandidate"]["manifestSha256"] = _sha(model_manifest)
    manifest["seedPartitions"]["train"] = train_seeds
    manifest_path = root / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    manifest_hash = _sha(manifest_path)
    (root / "manifest.sha256").write_text(manifest_hash + "\n", encoding="ascii")
    audit = {
        "format": "azcombat.natural-pilot-audit.v1", "status": "complete",
        "plannedCombats": 20, "completedCombats": 20, "failedTasks": 0,
        "errors": [], "tasks": tasks, "historicalFailedAttempts": [],
        "executionRepairManifest": {"path": str(manifest_path),
                                     "sha256": manifest_hash},
    }
    audit_path = root / "audit.json"
    audit_path.write_text(json.dumps(audit), encoding="utf-8")
    return audit_path


class R4AdmissionTests(unittest.TestCase):
    def test_indexes_each_accepted_task_once_and_preserves_capture_evidence(self):
        with TemporaryDirectory() as directory:
            audit = _fixture(Path(directory))
            result = admit_r4(audit)
        self.assertEqual(result["format"], "azcombat.r4-training-admission.v1")
        self.assertEqual(result["status"], "admitted")
        self.assertEqual(result["summary"]["samples"], 20)
        self.assertEqual(result["summary"]["byPolicy"], {"pure-mcts": 10, "tree-candidate": 10})
        self.assertEqual(result["summary"]["byOutcome"], {"win": 19, "unresolved": 1})
        entries = {entry["taskId"]: entry for entry in result["entries"]}
        self.assertEqual(entries["000-CULTISTS_NORMAL-pure-mcts"]["captureEvidence"]["sources"], ["missing"])
        self.assertEqual(entries["010-LIVING_FOG_NORMAL-pure-mcts"]["captureEvidence"]["sources"],
                         ["native-damage-command-v1"])
        self.assertEqual(entries["000-CULTISTS_NORMAL-pure-mcts"]["captureEvidence"]["historyResetTrue"], 1)
        self.assertEqual(entries["001-CULTISTS_NORMAL-tree-candidate"]["captureEvidence"]["historyResetTrue"], 0)
        self.assertEqual(result["plan"]["unresolvedHandling"]["label"], "preserve-not-death")

    def test_reaudit_or_replay_cannot_create_a_second_accepted_source(self):
        with TemporaryDirectory() as directory:
            audit = _fixture(Path(directory))
            raw = json.loads(audit.read_text(encoding="utf-8"))
            first = raw["tasks"][0]["attempts"][0]
            raw["tasks"][0]["attempts"].append(dict(first))
            audit.write_text(json.dumps(raw), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "exactly one accepted source"):
                admit_r4(audit)

    def test_scenario_hash_is_an_admission_input_not_a_display_field(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            audit = _fixture(root)
            scenario = next((root / "inputs").glob("*.json"))
            scenario.write_text(scenario.read_text(encoding="utf-8") + "\nchanged", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "frozen scenario input SHA256 changed"):
                admit_r4(audit)

    def test_fallback_is_not_silently_admitted(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            audit = _fixture(root)
            raw_audit = json.loads(audit.read_text(encoding="utf-8"))
            task = raw_audit["tasks"][0]
            attempt = task["attempts"][0]
            artifact = next(name for name in attempt["artifacts"]
                            if name.endswith("trajectory.jsonl"))
            trajectory = root / artifact.replace("\\", "/")
            row = json.loads(trajectory.read_text(encoding="utf-8"))
            row["provenance"]["modelFallbacks"] = 1
            trajectory.write_text(json.dumps(row) + "\n", encoding="utf-8")
            attempt["artifacts"][artifact]["sha256"] = _sha(trajectory)
            # The immutable artifact hash gate fires before provenance is
            # trusted; either way an edited trajectory cannot be admitted.
            with self.assertRaisesRegex(ValueError, "SHA256 changed"):
                admit_r4(audit)

    def test_rejects_a_changed_value_label_even_with_matching_file_hash(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            audit = _fixture(root)
            raw_audit = json.loads(audit.read_text(encoding="utf-8"))
            attempt = raw_audit["tasks"][0]["attempts"][0]
            artifact = next(name for name in attempt["artifacts"]
                            if name.endswith("trajectory.jsonl"))
            trajectory = root / artifact.replace("\\", "/")
            row = json.loads(trajectory.read_text(encoding="utf-8"))
            row["valueTarget"] = -0.75
            trajectory.write_text(json.dumps(row) + "\n", encoding="utf-8")
            attempt["artifacts"][artifact]["sha256"] = _sha(trajectory)
            audit.write_text(json.dumps(raw_audit), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "value target differs"):
                admit_r4(audit)

    def test_rejects_task_moved_across_frozen_seed_partition(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            audit = _fixture(root)
            manifest_path = root / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["tasks"][0]["partition"] = "validation"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            raw_audit = json.loads(audit.read_text(encoding="utf-8"))
            raw_audit["tasks"][0]["partition"] = "validation"
            raw_audit["executionRepairManifest"]["sha256"] = _sha(manifest_path)
            audit.write_text(json.dumps(raw_audit), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "partition differs from frozen seed split"):
                admit_r4(audit)

    def test_rejects_pair_with_different_frozen_input(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            audit = _fixture(root)
            manifest_path = root / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            second = manifest["tasks"][1]
            replacement = root / "inputs" / "different.json"
            replacement.write_text('{"different": true}', encoding="utf-8")
            second["generatedScenario"] = "inputs/different.json"
            second["generatedScenarioSha256"] = _sha(replacement)
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            raw_audit = json.loads(audit.read_text(encoding="utf-8"))
            raw_audit["executionRepairManifest"]["sha256"] = _sha(manifest_path)
            audit.write_text(json.dumps(raw_audit), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "paired input differs"):
                admit_r4(audit)


if __name__ == "__main__":
    unittest.main()
