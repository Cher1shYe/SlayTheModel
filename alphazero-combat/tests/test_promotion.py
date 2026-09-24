from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from azcombat.experiments import SCENARIOS, run_wave
from azcombat.promotion import (ASSEMBLY, EXPORT_OUT, _expected_run_keys, _paired_runs, _require_scenario_result,
                                _scenario_spec, write_gate)


class PromotionSafetyTests(unittest.TestCase):
    def test_full_worker_log_has_exact_assembly_and_export_identity(self):
        log = ("SLAY_WORKER_ASSEMBLY label=NativeWorker path=C:\\stage\\NativeWorker.dll "
               "mvid=7ff424b8-8fde-4d97-8b53-f86c544bd74e sha256=" + "A" * 64 + "\n"
               "SLAY_WORKER_EXPORT_OUT=C:\\data\\run.jsonl\n")
        self.assertEqual(ASSEMBLY.findall(log)[0][1], "C:\\stage\\NativeWorker.dll")
        self.assertEqual(EXPORT_OUT.findall(log), ["C:\\data\\run.jsonl"])
        self.assertEqual(ASSEMBLY.findall("SLAY_WORKER_ALPHAZERO pure-mcts:no-model-configured"), [])

    def test_scenario_identity_and_native_fixture_must_match(self):
        spec = SCENARIOS["native_death"]
        entry = {"scenario": "native_death", "startType": "full_combat",
                 "fixture": {"choiceFixture": True, "fixtureCards": spec["fixtureCards"], "initialHp": 1}}
        native = {"choiceFixture": True, "fixtureCards": spec["fixtureCards"],
                  "budgetMilliseconds": 1000, "maxDecisions": 15,
                  "startProvenance": {"nativeInitialHpFixture": 1, "entryHp": 1}}
        self.assertEqual(_scenario_spec(entry, native, 1000, 15), spec)
        for changed_entry, changed_native in (
            ({**entry, "scenario": "purity_choice"}, native),
            ({**entry, "fixture": {**entry["fixture"], "initialHp": 2}}, native),
            (entry, {**native, "choiceFixture": False}),
            (entry, {**native, "startProvenance": None}),
            (entry, {**native, "maxDecisions": 14}),
        ):
            with self.subTest(entry=changed_entry, native=changed_native), self.assertRaises(ValueError):
                _scenario_spec(changed_entry, changed_native, 1000, 15)

    def test_choice_and_death_must_be_observed_not_declared(self):
        for scenario, choices, death in (("purity_choice", [], False),
                                         ("native_death", [True], False)):
            with self.subTest(scenario=scenario), self.assertRaises(ValueError):
                _require_scenario_result(scenario, choices, death)
        _require_scenario_result("purity_choice", [False, True], False)
        _require_scenario_result("native_death", [], True)

    def test_missing_or_unpaired_scenario_cannot_cover_matrix(self):
        expected = _expected_run_keys(["a", "b"], ["CULTISTS_NORMAL"])
        self.assertEqual(len(expected), 16)
        self.assertEqual(_paired_runs(expected, {}), [])
        key = ("a", "CULTISTS_NORMAL", "native_death", "full_combat")
        baseline = (*key, "baseline")
        candidate = (*key, "candidate")
        self.assertEqual(_paired_runs(expected, {candidate: {"outcome": "loss"}}), [])
        self.assertEqual(len(_paired_runs(expected, {baseline: {"outcome": "loss"},
                                                     candidate: {"outcome": "loss"}})), 1)
        self.assertNotEqual(len(_paired_runs(expected, {baseline: {}, candidate: {}})), len(expected) // 2)

    def test_duplicate_or_fake_scenario_rejected_before_any_output(self):
        with TemporaryDirectory() as directory:
            for scenarios in (["ordinary", "ordinary"], ["fabricated_nested"]):
                output = Path(directory) / "new-wave"
                with self.subTest(scenarios=scenarios), self.assertRaises(ValueError):
                    run_wave(mode="evaluate", output=output, game_dir=Path(directory),
                             ritsu_root=Path(directory), model=Path(directory) / "missing.onnx",
                             seeds=["a", "b"], encounters=["CULTISTS_NORMAL"], scenarios=scenarios)
                self.assertFalse(output.exists())

    def test_selfplay_requires_champion_before_any_output(self):
        with TemporaryDirectory() as directory:
            output = Path(directory) / "new-wave"
            with self.assertRaises(ValueError):
                run_wave(mode="selfplay", output=output, game_dir=Path(directory),
                         ritsu_root=Path(directory), model=Path(directory) / "missing.onnx",
                         seeds=["a", "b"], encounters=["CULTISTS_NORMAL"])
            self.assertFalse(output.exists())

    def test_unregistered_encounter_rejected_before_any_output(self):
        with TemporaryDirectory() as directory:
            output = Path(directory) / "new-wave"
            with self.assertRaises(ValueError):
                run_wave(mode="evaluate", output=output, game_dir=Path(directory),
                         ritsu_root=Path(directory), model=Path(directory) / "missing.onnx",
                         seeds=["a", "b"], encounters=["UNKNOWN_ENCOUNTER"])
            self.assertFalse(output.exists())

    def test_denied_gate_does_not_replace_champion(self):
        with TemporaryDirectory() as directory:
            base = Path(directory)
            champion = base / "champion.json"
            report = base / "gate.json"
            champion.write_text('{"previous":"unchanged"}', encoding="utf-8")
            write_gate({"approved": False, "reasons": ["missing death evidence"]}, report, champion)
            self.assertEqual(json.loads(champion.read_text(encoding="utf-8")), {"previous": "unchanged"})
            self.assertTrue(report.is_file())
            with self.assertRaises(FileExistsError):
                write_gate({"approved": False}, report, champion)


if __name__ == "__main__":
    unittest.main()
