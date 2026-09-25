from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from azcombat.native_probe import _audit_generated_deck, _selected_candidate_indices, run_probe


def _model(base: Path) -> Path:
    path = base / "candidate.onnx"
    path.write_bytes(b"probe-launch-test")
    path.with_suffix(".manifest.json").write_text(json.dumps({
        "format": "azcombat.onnx.v4", "featureAbi": "azcombat.features.v4",
        "inputs": {"entities": ["N", 12], "globals": [4], "actions": ["A", 19]},
        "outputs": {"logits": ["A"], "value": []},
        "onnxSha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }), encoding="utf-8")
    return path


class NativeProbeEntryTests(unittest.TestCase):
    def test_generated_deck_launch_and_actual_order_audit(self):
        with TemporaryDirectory() as directory:
            base = Path(directory)
            spec_path = base / "scenario.json"
            cards = ["STRIKE_IRONCLAD", "BASH", "ARMAMENTS"]
            empty = {"count": 0, "ids": [], "upgradeLevels": 0}
            spec = {"schemaVersion": 1, "mode": "Setup", "seed": "probe-seed",
                    "characterId": "IRONCLAD", "encounterId": "CULTISTS_NORMAL",
                    "ascension": 0, "includeStartingDeck": False,
                    "includeStartingRelics": True, "includeAscendersBane": False,
                    "characterCards": {"count": len(cards), "ids": cards, "upgradeLevels": 0},
                    "colorlessCards": empty, "relics": empty, "potions": empty}
            spec_path.write_text(json.dumps(spec), encoding="utf-8")
            digest = hashlib.sha256(spec_path.read_bytes()).hexdigest()
            output = base / "battle.jsonl"
            with patch("azcombat.native_probe.shutil.which", return_value="pwsh"), \
                    patch("azcombat.native_probe.subprocess.run", side_effect=RuntimeError("intercept")) as launch:
                with self.assertRaisesRegex(RuntimeError, "intercept"):
                    run_probe(output=output, seed="probe-seed", encounter="CULTISTS_NORMAL",
                              search_mode="pure-mcts", generated_scenario=spec_path,
                              game_dir=base, ritsu_root=base)
            self.assertEqual(launch.call_args.kwargs["env"]["STS2_MCTS_EXPORT_GENERATED_SCENARIO"],
                             str(spec_path.resolve()))
            self.assertNotIn("STS2_MCTS_EXPORT_CHOICE_FIXTURE", launch.call_args.kwargs["env"])
            report = json.loads(output.with_suffix(".probe.json").read_text(encoding="utf-8"))
            self.assertEqual(report["generatedScenarioSha256"], digest)
            expected = {"generatedScenarioPath": str(spec_path), "generatedScenarioSha256": digest,
                        "seed": "probe-seed", "encounter": "CULTISTS_NORMAL"}
            native = {"generatedDeck": {"specPath": str(spec_path), "specSha256": digest,
                                        "catalogFingerprint": "a" * 64,
                                        "requestedCards": cards, "resolvedCards": cards,
                                        "actualDeck": [{"id": card, "upgradeLevel": 0} for card in cards],
                                        "characterId": "IRONCLAD", "encounterId": "CULTISTS_NORMAL",
                                        "resolverEncounterId": "FUZZY_WURM_CRAWLER_WEAK",
                                        "ascension": 0, "includeStartingDeck": False}}
            _audit_generated_deck(native, expected)
            native["generatedDeck"]["resolverEncounterId"] = ""
            with self.assertRaisesRegex(ValueError, "provenance or actual card order differs"):
                _audit_generated_deck(native, expected)
            native["generatedDeck"]["resolverEncounterId"] = "FUZZY_WURM_CRAWLER_WEAK"
            native["generatedDeck"]["actualDeck"][1]["id"] = "DEFEND_IRONCLAD"
            with self.assertRaisesRegex(ValueError, "actual card order differs"):
                _audit_generated_deck(native, expected)

    def test_duplicate_choice_candidates_map_by_occurrence_without_guessing(self):
        choice = {"candidates": [
            {"modelId": "CARD.PREPARED", "upgradeLevel": 0, "combatCardIndex": 7},
            {"modelId": "CARD.PREPARED", "upgradeLevel": 0, "combatCardIndex": 9},
        ]}
        selected = {"SelectedCards": [{"CardId": "PREPARED", "UpgradeLevel": 0,
                                        "OptionOccurrence": 1}]}
        self.assertEqual(_selected_candidate_indices(choice, selected), [9])
        selected["SelectedCards"][0]["OptionOccurrence"] = 2
        with self.assertRaisesRegex(ValueError, "not in the choice candidates"):
            _selected_candidate_indices(choice, selected)

    def test_forced_candidate_is_regression_only_and_uncapped(self):
        with TemporaryDirectory() as directory:
            base = Path(directory)
            model = _model(base)
            output = base / "choice.jsonl"
            with patch("azcombat.native_probe.shutil.which", return_value="pwsh"), \
                    patch("azcombat.native_probe.subprocess.run", side_effect=RuntimeError("intercept")) as launch:
                with self.assertRaisesRegex(RuntimeError, "intercept"):
                    run_probe(output=output, seed="probe-seed", encounter="CULTISTS_NORMAL",
                              search_mode="policy-value-tree-v1", model=model,
                              fixture_cards=["PURITY", "DEFEND_IRONCLAD"], force_card="PURITY",
                              max_decisions=1, budget_ms=1000, max_simulations=None,
                              game_dir=base, ritsu_root=base)
            command = launch.call_args.args[0]
            env = launch.call_args.kwargs["env"]
            self.assertEqual(command[command.index("-SearchMode") + 1], "policy-value-tree-v1")
            self.assertIn("-OnnxModel", command)
            self.assertNotIn("-MaxSimulations", command)
            self.assertNotIn("-SkipBuild", command)
            self.assertEqual(env["STS2_MCTS_EXPORT_FORCE_CARD"], "PURITY")
            self.assertNotIn("STS2_MCTS_EXPORT_MAX_SIMULATIONS", env)
            self.assertEqual(command[command.index("-TimeoutSeconds") + 1], "700")
            self.assertEqual(command[command.index("-StageRoot") + 1],
                             str(output.with_suffix(".stage").resolve()))
            report = json.loads(output.with_suffix(".probe.json").read_text(encoding="utf-8"))
            self.assertTrue(report["regressionOnly"])
            self.assertEqual(report["stageRoot"], str(output.with_suffix(".stage").resolve()))
            self.assertIsNone(report["maxSimulations"])
            self.assertEqual(report["status"], "failed")

    def test_full_combat_timeout_is_explicit_without_skipping_release(self):
        with TemporaryDirectory() as directory:
            base = Path(directory)
            output = base / "battle.jsonl"
            with patch("azcombat.native_probe.shutil.which", return_value="pwsh"), \
                    patch("azcombat.native_probe.subprocess.run", side_effect=RuntimeError("intercept")) as launch:
                with self.assertRaisesRegex(RuntimeError, "intercept"):
                    run_probe(output=output, seed="probe-seed", encounter="CULTISTS_NORMAL",
                              search_mode="pure-mcts", max_decisions=256, budget_ms=1000,
                              timeout_seconds=1800, game_dir=base, ritsu_root=base)
            command = launch.call_args.args[0]
            self.assertEqual(command[command.index("-TimeoutSeconds") + 1], "1800")
            self.assertEqual(launch.call_args.kwargs["timeout"], 2100)
            self.assertNotIn("-SkipBuild", command)

    def test_explicit_regression_only_and_existing_stage_are_fail_closed(self):
        with TemporaryDirectory() as directory:
            base = Path(directory)
            output = base / "headbutt.jsonl"
            with patch("azcombat.native_probe.shutil.which", return_value="pwsh"), \
                    patch("azcombat.native_probe.subprocess.run", side_effect=RuntimeError("intercept")) as launch:
                with self.assertRaisesRegex(RuntimeError, "intercept"):
                    run_probe(output=output, seed="headbutt", encounter="CULTISTS_NORMAL",
                              search_mode="pure-mcts", regression_only=True,
                              game_dir=base, ritsu_root=base)
            self.assertEqual(launch.call_args.kwargs["env"]["STS2_MCTS_EXPORT_REGRESSION_ONLY"], "1")
            self.assertTrue(json.loads(output.with_suffix(".probe.json").read_text())["regressionOnly"])
            next_output = base / "another.jsonl"
            next_output.with_suffix(".stage").mkdir()
            with patch("azcombat.native_probe.subprocess.run") as forbidden:
                with self.assertRaisesRegex(FileExistsError, "new isolated stage"):
                    run_probe(output=next_output, seed="headbutt", encounter="CULTISTS_NORMAL",
                              search_mode="pure-mcts", game_dir=base, ritsu_root=base)
            forbidden.assert_not_called()

    def test_failed_launch_retains_only_its_own_stage_logs(self):
        with TemporaryDirectory() as directory:
            base = Path(directory)
            output = base / "failure.jsonl"
            def failed_launch(command, **_kwargs):
                stage = Path(command[command.index("-StageRoot") + 1])
                stage.mkdir()
                (stage / "stdout.txt").write_text("this run\n", encoding="utf-8")
                (stage / "stderr.txt").write_text("this failure\n", encoding="utf-8")
                return subprocess.CompletedProcess(command, 1, "launcher\n", "publish failed\n")
            with patch("azcombat.native_probe.shutil.which", return_value="pwsh"), \
                    patch("azcombat.native_probe.subprocess.run", side_effect=failed_launch):
                with self.assertRaisesRegex(RuntimeError, "NativeWorker failed"):
                    run_probe(output=output, seed="seed", encounter="CULTISTS_NORMAL",
                              search_mode="pure-mcts", game_dir=base, ritsu_root=base)
            self.assertEqual(output.with_suffix(".worker.stdout.txt").read_text(), "this run\n")
            self.assertEqual(output.with_suffix(".worker.stderr.txt").read_text(), "this failure\n")
            self.assertEqual(output.with_suffix(".launcher.stderr.txt").read_text(), "publish failed\n")
            self.assertEqual(json.loads(output.with_suffix(".probe.json").read_text())["status"], "failed")

    def test_root_parity_is_opt_in_and_kept_out_of_pure_teacher(self):
        with TemporaryDirectory() as directory:
            base = Path(directory)
            output = base / "parity.jsonl"
            sidecar = base / "parity.root.jsonl"
            with self.assertRaisesRegex(ValueError, "requires a tree model"):
                run_probe(output=output, seed="seed", encounter="CULTISTS_NORMAL",
                          search_mode="pure-mcts", root_parity_output=sidecar,
                          game_dir=base, ritsu_root=base)
            with patch("azcombat.native_probe.shutil.which", return_value="pwsh"), \
                    patch("azcombat.native_probe.subprocess.run", side_effect=RuntimeError("intercept")) as launch:
                with self.assertRaisesRegex(RuntimeError, "intercept"):
                    run_probe(output=output, seed="seed", encounter="CULTISTS_NORMAL",
                              search_mode="policy-value-tree-v1", model=_model(base),
                              root_parity_output=sidecar, game_dir=base, ritsu_root=base)
            self.assertEqual(launch.call_args.kwargs["env"]["STS2_ALPHAZERO_ROOT_PARITY_OUT"],
                             str(sidecar.resolve()))

    def test_outer_timeout_keeps_partial_launcher_logs_and_is_not_unresolved(self):
        with TemporaryDirectory() as directory:
            base = Path(directory)
            output = base / "battle.jsonl"
            expired = subprocess.TimeoutExpired("pwsh", 2100, output=b"publish started\n",
                                                stderr=b"worker timeout\n")
            with patch("azcombat.native_probe.shutil.which", return_value="pwsh"), \
                    patch("azcombat.native_probe.subprocess.run", side_effect=expired):
                with self.assertRaises(subprocess.TimeoutExpired):
                    run_probe(output=output, seed="probe-seed", encounter="CULTISTS_NORMAL",
                              search_mode="pure-mcts", timeout_seconds=1800,
                              game_dir=base, ritsu_root=base)
            self.assertIn("publish started", output.with_suffix(".launcher.stdout.txt").read_text())
            self.assertIn("worker timeout", output.with_suffix(".launcher.stderr.txt").read_text())
            report = json.loads(output.with_suffix(".probe.json").read_text())
            self.assertEqual(report["status"], "failed")
            self.assertNotIn("outcome", report)

    def test_invalid_force_or_mode_is_rejected_before_output(self):
        with TemporaryDirectory() as directory:
            base = Path(directory)
            output = base / "choice.jsonl"
            with self.assertRaisesRegex(ValueError, "forced-card regression"):
                run_probe(output=output, seed="probe-seed", encounter="CULTISTS_NORMAL",
                          search_mode="pure-mcts", fixture_cards=["DEFEND_IRONCLAD"],
                          force_card="PURITY", game_dir=base, ritsu_root=base)
            with self.assertRaisesRegex(ValueError, "requires one"):
                run_probe(output=output, seed="probe-seed", encounter="CULTISTS_NORMAL",
                          search_mode="policy-value-tree-v1", game_dir=base, ritsu_root=base)
            self.assertFalse(output.exists())
            self.assertFalse(output.with_suffix(".probe.json").exists())


if __name__ == "__main__":
    unittest.main()
