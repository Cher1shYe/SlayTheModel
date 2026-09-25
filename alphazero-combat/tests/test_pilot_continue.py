from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from azcombat.pilot_continue import freeze_continuation, run_continuation, _execution
from azcombat.natural_pilot import _canonical_json
from test_pilot_audit import _manifest


class PilotContinuationTests(unittest.TestCase):
    def test_freeze_copies_exact_scenarios_and_updates_only_explicit_source(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            original = root / "original"
            original.mkdir()
            parent_path = _manifest(original)
            parent = json.loads(parent_path.read_text())
            original_bytes = parent_path.read_bytes()
            plan_path = root / "plan.json"
            plan_path.write_text("{}")
            plan = {"tasks": parent["tasks"][4:],
                    "acceptedOriginalTasks": [{"taskId": t["taskId"]} for t in parent["tasks"][:4]]}
            with patch("azcombat.pilot_continue._validate_plan",
                       return_value=(plan, parent_path, parent, {})), \
                    patch("azcombat.pilot_continue._source_snapshot", return_value={"new": "snapshot"}), \
                    patch("azcombat.pilot_continue._assert_unchanged_inputs"):
                path = freeze_continuation(plan_path, root / "new")
            frozen = json.loads(path.read_text())
            self.assertEqual(frozen["tasks"], parent["tasks"])
            self.assertEqual(frozen["sourceSnapshot"], {"new": "snapshot"})
            self.assertEqual(len(frozen["continuation"]["remainingTaskIds"]), 16)
            self.assertEqual(parent_path.read_bytes(), original_bytes)
            for task in parent["tasks"]:
                self.assertEqual((path.parent / task["generatedScenario"]).read_bytes(),
                                 (original / task["generatedScenario"]).read_bytes())

    def test_runner_skips_inherited_and_complete_tasks_and_uses_same_task(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "manifest.json"
            path.write_text("{}")
            tasks = [{"taskId": name} for name in ("old", "done", "pending")]
            manifest = {"tasks": tasks, "continuation": {"plan": "frozen"}}
            report = {"errors": [], "failedAttempts": 0, "completedCombats": 3}
            with patch("azcombat.pilot_continue._execution", return_value=(manifest, {"old": Path(tmp)})), \
                    patch("azcombat.pilot_continue.audit_pilot", return_value=report), \
                    patch("azcombat.pilot_continue._attempt_records",
                          side_effect=[[{"status": "complete"}], []]), \
                    patch("azcombat.pilot_continue._launch_attempt",
                          return_value={"outcome": "loss", "samples": 4}) as launch:
                results = run_continuation(path)
            self.assertEqual(len(results), 1)
            self.assertEqual(launch.call_args.args, (path, manifest, tasks[2], 1))

    def test_runner_stops_on_first_error_and_writes_audit(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "manifest.json"
            path.write_text("{}")
            manifest = {"tasks": [{"taskId": "first"}, {"taskId": "second"}], "continuation": {}}
            with patch("azcombat.pilot_continue._execution", return_value=(manifest, {})), \
                    patch("azcombat.pilot_continue.audit_pilot", side_effect=[
                        {"errors": [], "failedAttempts": 0},
                        {"errors": ["bad reward"], "failedAttempts": 1}]), \
                    patch("azcombat.pilot_continue._attempt_records", return_value=[]), \
                    patch("azcombat.pilot_continue._launch_attempt", side_effect=ValueError("bad reward")) as launch:
                with self.assertRaisesRegex(ValueError, "bad reward"):
                    run_continuation(path)
            launch.assert_called_once()
            self.assertTrue((path.parent / "audit-after-first.json").is_file())

    def test_execution_rejects_task_mutation_even_with_rehashed_manifest(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "manifest.json"
            parent = {"tasks": [{"taskId": "a", "budgetMilliseconds": 1000}], "sourceSnapshot": {}}
            plan = {"tasks": parent["tasks"], "acceptedOriginalTasks": []}
            manifest = deepcopy(parent)
            manifest["tasks"][0]["budgetMilliseconds"] = 2000
            manifest["continuation"] = {"format": "azcombat.natural-pilot-execution-amendment.v1",
                                        "plan": {}, "parentManifest": {},
                                        "remainingTaskIds": ["a"], "acceptedTaskIds": []}
            with patch("azcombat.pilot_continue._read_frozen_manifest", return_value=manifest), \
                    patch("azcombat.pilot_continue._read_ref", return_value=(path, plan)), \
                    patch("azcombat.pilot_continue._validate_plan", return_value=(plan, path, parent, {})), \
                    patch("azcombat.pilot_continue._ref", return_value={}), \
                    patch("azcombat.pilot_continue._assert_unchanged_inputs") as check:
                with self.assertRaisesRegex(ValueError, "changes frozen"):
                    _execution(path)
                check.assert_not_called()


if __name__ == "__main__":
    unittest.main()
