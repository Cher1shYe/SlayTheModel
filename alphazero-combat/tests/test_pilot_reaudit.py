from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from azcombat.experiments import sha256
from azcombat.pilot_audit import _audit_attempt
from azcombat.pilot_reaudit import _preserved_inventory, build_continuation
from test_pilot_audit import _file, _manifest


def _failed_evidence(root: Path) -> tuple[dict, Path, dict]:
    manifest = json.loads(_manifest(root).read_text(encoding="utf-8"))
    task = manifest["tasks"][0]
    relative = f"attempts/{task['taskId']}/attempt-001"
    directory = root / relative
    directory.mkdir(parents=True)
    stage = directory / "trajectory.stage"
    stage.mkdir()
    _file(stage / "stage_provenance.json", b"{}")
    raw = {"provenance": {"enemyHpTransitions": [{"enemyDamageEvents": [
        {"unblockedDamage": 1, "overkillDamage": 8, "creditedDamage": 1}]}],
        "decisionMetrics": [{"choiceLayer": 0}],
        "generatedDeck": {"requestedCards": ["STRIKE_IRONCLAD"], "actualDeck": []},
        "entryHp": 80}, "observation": {}, "stateKey": "root", "legalActions": []}
    _file(directory / "trajectory.jsonl", (json.dumps(raw) + "\n").encode())
    error = "native transition 0 has a malformed damage event"
    probe = {"status": "failed", "exitCode": 0, "error": error,
             "output": str((directory / "trajectory.jsonl").resolve()),
             "seed": task["seed"], "encounter": task["encounter"],
             "requestedSearchMode": task["requestedSearchMode"], "modelSha256": None,
             "generatedScenarioPath": str((root / task["generatedScenario"]).resolve()),
             "generatedScenarioSha256": task["generatedScenarioSha256"],
             "fixtureCards": None, "forceCard": None, "initialHp": None,
             "regressionOnly": False, "maxDecisions": 256, "budgetMilliseconds": 1000,
             "maxSimulations": None, "timeoutSeconds": 1800, "rootParityOutput": None,
             "stageRoot": str(stage.resolve())}
    _file(directory / "trajectory.probe.json", json.dumps(probe).encode())
    meta = {"taskId": task["taskId"], "attemptNumber": 1, "status": "failed",
            "startedAtUtc": "2026-09-25T00:00:00Z", "finishedAtUtc": "2026-09-25T00:01:00Z",
            "error": "ValueError: " + error, "failureClass": "protocol-or-unclassified",
            "jsonl": relative + "/trajectory.jsonl",
            "probeReport": relative + "/trajectory.probe.json", "rootParityOutput": None,
            "jsonlSha256": sha256(directory / "trajectory.jsonl"),
            "probeReportSha256": sha256(directory / "trajectory.probe.json"),
            "stageProvenanceSha256": sha256(stage / "stage_provenance.json")}
    _file(directory / "attempt.json", json.dumps(meta).encode())
    return task, directory, meta


def _probe_result() -> dict:
    # Protocol plumbing test double, not real battle or calibration evidence.
    return {"outcome": "unresolved", "valueTarget": -0.25, "samples": 1,
            "rewardLedger": {"captures": 1}, "enemyDamageLost": 1, "entryHp": 80,
            "playerHp": 3, "priorCalls": 0, "valueCalls": 0, "fallbacks": 0,
            "assemblies": {}}


class PilotReauditTests(unittest.TestCase):
    def test_reaudit_preserves_failure_and_calls_full_probe_without_launch(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            task, directory, meta = _failed_evidence(root)
            originals = {p: p.read_bytes() for p in directory.rglob("*") if p.is_file()}
            with patch("azcombat.pilot_audit.audit_probe", return_value=_probe_result()) as audit, \
                    patch("azcombat.pilot_audit.read_jsonl", return_value=[]), \
                    patch("azcombat.native_probe.run_probe") as launch:
                result = _audit_attempt(root, task, 1, directory, reaudit_overkill=True)
            audit.assert_called_once()
            launch.assert_not_called()
            self.assertEqual(result["originalAttemptStatus"], "failed")
            self.assertEqual(result["originalError"], meta["error"])
            self.assertEqual(result["outcome"], "unresolved")
            self.assertEqual(result["acceptanceStatus"], "accepted-after-reaudit")
            for path, content in originals.items():
                self.assertEqual(path.read_bytes(), content)

    def test_nonzero_worker_exit_is_not_accepted(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            task, directory, meta = _failed_evidence(root)
            probe_path = directory / "trajectory.probe.json"
            probe = json.loads(probe_path.read_text())
            probe["exitCode"] = 1
            meta["probeReportSha256"] = _file(probe_path, json.dumps(probe).encode())
            _file(directory / "attempt.json", json.dumps(meta).encode())
            with patch("azcombat.pilot_audit.audit_probe") as audit:
                with self.assertRaisesRegex(ValueError, "exitCode"):
                    _audit_attempt(root, task, 1, directory, reaudit_overkill=True)
                audit.assert_not_called()

    def test_other_failure_and_changed_evidence_cannot_be_reclassified(self):
        for changed_file in (False, True):
            with self.subTest(changed_file=changed_file), TemporaryDirectory() as tmp:
                root = Path(tmp)
                task, directory, meta = _failed_evidence(root)
                if changed_file:
                    with (directory / "trajectory.jsonl").open("a") as handle:
                        handle.write(" ")
                else:
                    meta["error"] = "ValueError: choice mismatch"
                    _file(directory / "attempt.json", json.dumps(meta).encode())
                with patch("azcombat.pilot_audit.audit_probe") as audit:
                    with self.assertRaises(ValueError):
                        _audit_attempt(root, task, 1, directory, reaudit_overkill=True)
                    audit.assert_not_called()

    def test_new_full_audit_error_is_not_suppressed(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            task, directory, _ = _failed_evidence(root)
            with patch("azcombat.pilot_audit.audit_probe", side_effect=ValueError("bad reward")):
                with self.assertRaisesRegex(ValueError, "bad reward"):
                    _audit_attempt(root, task, 1, directory, reaudit_overkill=True)

    def test_original_artifact_hash_mismatch_rejects_inventory(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "trajectory.jsonl"
            _file(path, b"original")
            report = {"tasks": [{"attempts": [{"artifacts": {
                "trajectory.jsonl": {"sha256": "0" * 64, "bytes": 8}}}]}]}
            with self.assertRaisesRegex(ValueError, "original evidence changed"):
                _preserved_inventory(root / "manifest.json", root / "audit.json", report)

    def test_continuation_keeps_exact_remaining_tasks_and_never_runs_them(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = _manifest(root)
            manifest = json.loads(path.read_text())
            report = {"errors": [], "failedAttempts": 0, "attempts": 4, "completedCombats": 4,
                      "reaudit": {"currentSourceSnapshot": {}, "originalAudit": {},
                                  "originalErrors": ["preserved failure"]},
                      "tasks": [{"taskId": task["taskId"],
                                 "status": "complete" if i < 4 else "planned",
                                 "attempts": [{"attemptNumber": 1, "outcome": "win",
                                               "artifacts": {}}] if i < 4 else []}
                                for i, task in enumerate(manifest["tasks"])]}
            plan = build_continuation(manifest, report, path)
            self.assertEqual(plan["tasks"], manifest["tasks"][4:])
            self.assertEqual(len(plan["acceptedOriginalTasks"]), 4)
            self.assertEqual(plan["seedPartitions"], manifest["seedPartitions"])
            self.assertFalse(plan["executableByOriginalPilotRunner"])
            failed = deepcopy(report)
            failed["errors"] = ["bad reward"]
            with self.assertRaisesRegex(ValueError, "all existing attempts"):
                build_continuation(manifest, failed, path)


if __name__ == "__main__":
    unittest.main()
