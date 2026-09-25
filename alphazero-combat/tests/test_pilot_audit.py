from __future__ import annotations

import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from azcombat.pilot_audit import audit_pilot


def _file(path: Path, value: bytes) -> str:
    path.write_bytes(value)
    return hashlib.sha256(value).hexdigest()


def _manifest(root: Path) -> Path:
    (root / "inputs").mkdir()
    (root / "attempts").mkdir()
    refs = {}
    for name in ("cross-root", "enemy-damage", "budget", "split", "deck", "candidate.onnx",
                 "candidate.manifest.json"):
        path = root / name
        refs[name] = {"path": str(path), "sha256": _file(path, name.encode())}
    damage_regression = {
        "format": "azcombat.enemy-damage-ledger-regression.v1",
        "regressionOnly": True,
        "status": "passed",
        "despawnUnresolved": {}, "lethalOverkill": {}, "despawnLoss": {},
    }
    refs["enemy-damage"]["sha256"] = _file(
        root / "enemy-damage", json.dumps(damage_regression).encode())
    seeds = [f"FRESH-{index}" for index in range(5)]
    cards = {name: ["STRIKE_IRONCLAD"] for name in "ABCDE"}
    tasks = []
    for index, seed in enumerate(seeds):
        for encounter in ("CULTISTS_NORMAL", "LIVING_FOG_NORMAL"):
            relative = f"inputs/{index:03d}-{encounter}.json"
            scenario = {"seed": seed, "encounterId": encounter,
                        "includeStartingDeck": False, "includeStartingRelics": True,
                        "characterCards": {"ids": cards["ABCDE"[index]]}}
            digest = _file(root / relative, json.dumps(scenario).encode())
            for policy in ("pure-mcts", "tree-candidate"):
                tasks.append({"taskId": f"{index:03d}-{encounter}-{policy}",
                              "seed": seed, "partition": "train" if index < 4 else "validation",
                              "encounter": encounter, "policy": policy,
                              "requestedSearchMode": "pure-mcts" if policy == "pure-mcts"
                                                     else "policy-value-tree-v1",
                              "requestedModelSha256": None if policy == "pure-mcts"
                                                      else refs["candidate.onnx"]["sha256"],
                              "startType": "full_combat", "deckTemplate": "ABCDE"[index],
                              "generatedScenario": relative, "generatedScenarioSha256": digest,
                              "budgetMilliseconds": 1000, "maxSimulations": None,
                              "maxDecisions": 256, "workerCancellationSeconds": 600,
                              "timeoutSeconds": 1800, "pythonSubprocessTimeoutSeconds": 2100})
    manifest = {"format": "azcombat.natural-pilot.v2",
                "purpose": "collection-reliability-and-coverage-only",
                "contracts": {"observationSchemaVersion": 3,
                              "featureAbi": "azcombat.features.v4",
                              "searchSemanticsVersion": "azcombat.search.v3",
                              "rewardLedgerVersion": "azcombat.reward-ledger.v2",
                              "rewardDefinition": {"source": "alphazero-combat/src/azcombat/reward.py:score_result",
                                                   "win": "formula", "loss": "formula",
                                                   "unresolved": "formula", "invalid": "reject"}},
                "collectionRules": {"maximumAttemptsPerTask": 2,
                                    "allOutcomesRetained": True, "regressionOnly": False,
                                    "treeAndPureDataSeparate": True, "noForcedActionsOrHp": True},
                "crossRootRegression": refs["cross-root"],
                "enemyDamageRegression": refs["enemy-damage"],
                "budgetEvidence": refs["budget"],
                "historicalSeedSplit": refs["split"],
                "deckTemplates": {**refs["deck"], "assignments": dict(zip(seeds, "ABCDE")),
                                  "cards": cards, "reusedHistoricalTemplates": True},
                "treeCandidate": {"onnxPath": refs["candidate.onnx"]["path"],
                                  "onnxSha256": refs["candidate.onnx"]["sha256"],
                                  "manifestPath": refs["candidate.manifest.json"]["path"],
                                  "manifestSha256": refs["candidate.manifest.json"]["sha256"],
                                  "usage": "fixed-behavior-policy-only",
                                  "trainingRewardLedgerVersion": "azcombat.reward-ledger.v1"},
                "sourceSnapshot": {"sourceTreeSha256": "frozen"},
                "seedPartitions": {"train": seeds[:4], "validation": seeds[4:],
                                   "finalEvaluationSealed": [f"SEALED-{i}" for i in range(5)]},
                "tasks": tasks}
    path = root / "manifest.json"
    digest = _file(path, json.dumps(manifest).encode())
    (root / "manifest.sha256").write_text(digest + "\n", encoding="ascii")
    return path


def _complete(policy: str, *, observation: dict | None = None) -> dict:
    return {"attemptNumber": 1, "status": "complete", "outcome": "win",
            "valueTarget": 0.4, "decisions": 3, "combatDecisions": 2,
            "choiceDecisions": 1, "nestedChoiceDecisions": 0,
            "opening": {"observation": observation or {"root": 1}, "stateKey": "same",
                        "orderedActionIds": ["play", "end"],
                        "requestedCards": ["STRIKE_IRONCLAD"],
                        "actualDeck": [{"id": "STRIKE_IRONCLAD", "upgradeLevel": 0}],
                        "entryHp": 80}, "policy": policy}


class PilotBatchAuditTests(unittest.TestCase):
    def test_failed_attempt_reports_partial_jsonl_without_calling_it_a_loss(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = _manifest(root)
            task_id = "000-CULTISTS_NORMAL-pure-mcts"
            attempt_dir = root / "attempts" / task_id / "attempt-001"
            attempt_dir.mkdir(parents=True)
            partial = b'{"row":1}\n{"unfinished":\n'
            digest = _file(attempt_dir / "trajectory.jsonl", partial)
            metadata = {"taskId": task_id, "attemptNumber": 1, "status": "failed",
                        "startedAtUtc": "2026-09-25T01:00:00Z",
                        "finishedAtUtc": "2026-09-25T01:01:00Z",
                        "failureClass": "protocol-or-unclassified",
                        "error": "reward audit stopped",
                        "jsonl": f"attempts/{task_id}/attempt-001/trajectory.jsonl",
                        "probeReport": f"attempts/{task_id}/attempt-001/trajectory.probe.json",
                        "rootParityOutput": None, "jsonlSha256": digest}
            _file(attempt_dir / "attempt.json", json.dumps(metadata).encode())
            model_hash = hashlib.sha256(b"candidate.onnx").hexdigest()
            with patch("azcombat.pilot_audit.checked_model", return_value=model_hash):
                report = audit_pilot(manifest, verify_source=False)
            attempt = report["tasks"][0]["attempts"][0]
            self.assertEqual(report["status"], "protocol-error")
            self.assertEqual(report["completedCombats"], 0)
            self.assertEqual(report["naturalDeathCombats"], 0)
            self.assertEqual(attempt["rawJsonl"]["lines"], 2)
            self.assertEqual(attempt["rawJsonl"]["parsedRows"], 1)
            self.assertIn("line 2", attempt["rawJsonl"]["firstParseError"])
            self.assertEqual(attempt["artifacts"][str((attempt_dir / "trajectory.jsonl")
                                                     .relative_to(root))]["sha256"], digest)

    def test_frozen_plan_without_attempts_remains_incomplete_not_fake_loss(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = _manifest(root)
            model_hash = hashlib.sha256(b"candidate.onnx").hexdigest()
            with patch("azcombat.pilot_audit.checked_model", return_value=model_hash):
                result = audit_pilot(manifest, verify_source=False)
            self.assertEqual(result["status"], "incomplete")
            self.assertEqual(result["plannedCombats"], 20)
            self.assertEqual(result["completedCombats"], 0)
            self.assertEqual(result["decisionRows"], 0)
            self.assertEqual(result["naturalDeathCombats"], 0)
            self.assertEqual(len(result["pairedOpenings"]), 10)
            self.assertTrue(all(pair["status"] == "unpaired"
                                for pair in result["pairedOpenings"]))

    def test_paired_opening_audits_per_combat_not_decision(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = _manifest(root)
            ids = [f"000-CULTISTS_NORMAL-{policy}" for policy in
                   ("pure-mcts", "tree-candidate")]
            for task_id in ids:
                (root / "attempts" / task_id / "attempt-001").mkdir(parents=True)
            model_hash = hashlib.sha256(b"candidate.onnx").hexdigest()
            with patch("azcombat.pilot_audit.checked_model", return_value=model_hash), \
                    patch("azcombat.pilot_audit._audit_attempt",
                          side_effect=lambda _root, task, *_: _complete(task["policy"])):
                result = audit_pilot(manifest, verify_source=False)
            self.assertEqual(result["completedCombats"], 2)
            self.assertEqual(result["decisionRows"], 6)
            self.assertEqual(result["byEncounterPolicy"]["CULTISTS_NORMAL|pure-mcts"]["win"], 1)
            self.assertEqual(result["byEncounterPolicy"]["CULTISTS_NORMAL|tree-candidate"]["win"], 1)
            self.assertEqual(result["pairedOpenings"][0]["status"], "matched")

    def test_pair_mismatch_is_protocol_error_not_outcome_filter(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = _manifest(root)
            for policy in ("pure-mcts", "tree-candidate"):
                (root / "attempts" / f"000-CULTISTS_NORMAL-{policy}" / "attempt-001").mkdir(parents=True)
            model_hash = hashlib.sha256(b"candidate.onnx").hexdigest()
            def attempt(_root: Path, task: dict, *_args: object) -> dict:
                return _complete(task["policy"], observation={"root": task["policy"]})
            with patch("azcombat.pilot_audit.checked_model", return_value=model_hash), \
                    patch("azcombat.pilot_audit._audit_attempt", side_effect=attempt):
                result = audit_pilot(manifest, verify_source=False)
            self.assertEqual(result["status"], "protocol-error")
            self.assertIn("paired opening differs", result["errors"][0])
            self.assertEqual(result["completedCombats"], 2)

    def test_manifest_mutation_fails_before_reading_attempts(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = _manifest(root)
            with manifest.open("a", encoding="utf-8") as handle:
                handle.write(" ")
            with self.assertRaisesRegex(ValueError, "manifest SHA256 changed"):
                audit_pilot(manifest, verify_source=False)

    def test_old_reward_ledger_contract_cannot_be_audited_as_new_pilot(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = _manifest(root)
            plan = json.loads(manifest.read_text(encoding="utf-8"))
            plan["contracts"]["rewardLedgerVersion"] = "azcombat.reward-ledger.v1"
            (root / "manifest.sha256").write_text(
                _file(manifest, json.dumps(plan).encode()) + "\n", encoding="ascii")
            model_hash = hashlib.sha256(b"candidate.onnx").hexdigest()
            with patch("azcombat.pilot_audit.checked_model", return_value=model_hash):
                with self.assertRaisesRegex(ValueError, "reward contracts differ"):
                    audit_pilot(manifest, verify_source=False)

    def test_protocol_failure_cannot_be_retried_into_a_complete_task(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = _manifest(root)
            task_id = "000-CULTISTS_NORMAL-pure-mcts"
            for number in (1, 2):
                (root / "attempts" / task_id / f"attempt-{number:03d}").mkdir(parents=True)
            model_hash = hashlib.sha256(b"candidate.onnx").hexdigest()

            def attempt(_root: Path, task: dict, number: int, *_args: object) -> dict:
                if number == 1:
                    return {"attemptNumber": 1, "status": "failed",
                            "failureClass": "protocol-or-unclassified", "error": "bad choice"}
                return _complete(task["policy"])

            with patch("azcombat.pilot_audit.checked_model", return_value=model_hash), \
                    patch("azcombat.pilot_audit._audit_attempt", side_effect=attempt):
                result = audit_pilot(manifest, verify_source=False)
            self.assertEqual(result["status"], "protocol-error")
            self.assertTrue(any("non-infrastructure failure" in error
                                for error in result["errors"]))

    def test_preserved_protocol_failure_marks_batch_protocol_error(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = _manifest(root)
            task_id = "000-CULTISTS_NORMAL-tree-candidate"
            (root / "attempts" / task_id / "attempt-001").mkdir(parents=True)
            model_hash = hashlib.sha256(b"candidate.onnx").hexdigest()
            with patch("azcombat.pilot_audit.checked_model", return_value=model_hash), \
                    patch("azcombat.pilot_audit._audit_attempt", return_value={
                        "attemptNumber": 1, "status": "failed",
                        "failureClass": "protocol-or-unclassified", "error": "choice parity mismatch"}):
                result = audit_pilot(manifest, verify_source=False)
            self.assertEqual(result["status"], "protocol-error")
            self.assertEqual(result["failedTasks"], 1)
            self.assertEqual(result["completedCombats"], 0)


if __name__ == "__main__":
    unittest.main()
