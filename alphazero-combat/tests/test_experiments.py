from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import torch

from azcombat.experiments import checked_model, run_research_wave, run_wave
from azcombat.training import DeepSetsPolicyValue, load_checkpoint


def _model(base: Path) -> Path:
    model = base / "candidate.onnx"
    model.write_bytes(b"model-for-launch-contract-test")
    model.with_suffix(".manifest.json").write_text(json.dumps({
        "format": "azcombat.onnx.v4", "featureAbi": "azcombat.features.v4",
        "inputs": {"entities": ["N", 12], "globals": [4], "actions": ["A", 19]},
        "outputs": {"logits": ["A"], "value": []},
        "onnxSha256": hashlib.sha256(model.read_bytes()).hexdigest(),
        "checkpointSha256": "0" * 64,
        "training": {"trainSeeds": ["trained"], "validationSeeds": ["validated"]},
    }), encoding="utf-8")
    return model


def _split(base: Path) -> tuple[Path, dict]:
    split = {"format": "azcombat.seed-split.v1",
             "trainSeeds": [f"train-{index}" for index in range(20)],
             "validationSeeds": [f"validation-{index}" for index in range(5)],
             "evaluationSeeds": [f"evaluation-{index}" for index in range(10)]}
    path = base / "split.json"
    path.write_text(json.dumps(split), encoding="utf-8")
    return path, split


def _lineage_model(base: Path, train: list[str], validation: list[str]) -> Path:
    base.mkdir()
    model = _model(base)
    model.write_bytes(("model-for-launch-contract-test-" + base.name).encode("ascii"))
    manifest_path = model.with_suffix(".manifest.json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["onnxSha256"] = hashlib.sha256(model.read_bytes()).hexdigest()
    manifest["training"] = {"trainSeeds": train, "validationSeeds": validation}
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return model


def _deck_plan(base: Path, split_path: Path, split: dict) -> Path:
    templates = {name: {"characterCards": ["STRIKE_IRONCLAD", "DEFEND_IRONCLAD", "BASH", card]}
                 for name, card in zip("ABCDE", ("ARMAMENTS", "HEADBUTT", "BURNING_PACT",
                                                 "ARMAMENTS", "HEADBUTT"), strict=True)}
    seeds = split["trainSeeds"] + split["validationSeeds"] + split["evaluationSeeds"]
    plan = {"format": "azcombat.deck-plan.v1",
            "seedSplitSha256": hashlib.sha256(split_path.read_bytes()).hexdigest(),
            "templates": templates,
            "assignments": {seed: "ABCDE"[index % 5] for index, seed in enumerate(seeds)}}
    path = base / "deck-plan.json"
    path.write_text(json.dumps(plan), encoding="utf-8")
    return path


def _probe_audit() -> dict:
    return {"assemblies": {label: {"path": f"stage/{label}.dll",
                                    "mvid": "00000000-0000-0000-0000-000000000001",
                                    "sha256": "a" * 64}
                           for label in ("nativeWorker", "search", "combatSolver")},
            "samples": 2, "outcome": "loss", "valueTarget": -0.9, "terminal": True,
            "entryHp": 80, "playerHp": 0, "initialEnemyEffectiveHp": 100,
            "enemyDamageLost": 20, "choiceRows": [], "simulations": [100, 200],
            "elapsedMilliseconds": [1000, 1001], "priorCalls": 0,
            "valueCalls": 0, "fallbacks": 0, "jsonlSha256": "j",
            "workerStdoutSha256": "w"}


class ExperimentEntryTests(unittest.TestCase):
    def test_r2_frozen_deck_plan_reuses_exact_spec_for_three_arms(self):
        with TemporaryDirectory() as directory:
            base = Path(directory)
            split_path, split = _split(base)
            plan_path = _deck_plan(base, split_path, split)
            new = _lineage_model(base / "new", [split["trainSeeds"][0]],
                                 [split["validationSeeds"][0]])
            with patch("azcombat.native_probe.run_probe", return_value=_probe_audit()) as probe:
                wave = run_research_wave(phase="evaluation", split_path=split_path,
                                         deck_plan=plan_path, output=base / "r2", game_dir=base,
                                         ritsu_root=base, new_model=new)
            self.assertEqual(len(wave["runs"]), 60)
            self.assertEqual(wave["request"]["deckPlanSha256"], hashlib.sha256(plan_path.read_bytes()).hexdigest())
            self.assertEqual(wave["request"]["newOnnxManifestSha256"],
                             hashlib.sha256(new.with_suffix(".manifest.json").read_bytes()).hexdigest())
            self.assertEqual(wave["request"]["newCheckpointSha256"], "0" * 64)
            self.assertEqual(probe.call_count, 40)
            first_three = wave["runs"][:3]
            self.assertEqual(len({run["generatedScenario"] for run in first_three}), 1)
            self.assertEqual(len({run["generatedScenarioSha256"] for run in first_three}), 1)
            spec_path = base / "r2" / first_three[0]["generatedScenario"]
            self.assertEqual({call.kwargs["generated_scenario"] for call in probe.call_args_list[:2]},
                             {spec_path.resolve()})
            spec = json.loads(spec_path.read_text(encoding="utf-8"))
            self.assertEqual(spec["seed"], split["evaluationSeeds"][0])
            self.assertEqual(spec["encounterId"], "CULTISTS_NORMAL")
            self.assertEqual(spec["characterCards"]["ids"],
                             ["STRIKE_IRONCLAD", "DEFEND_IRONCLAD", "BASH", "ARMAMENTS"])
            self.assertFalse(spec["includeStartingDeck"])
            self.assertEqual(spec["colorlessCards"], {"count": 0, "ids": [], "upgradeLevels": 0})
            self.assertEqual(len(list((base / "r2" / "inputs").glob("*.json"))), 20)
            with patch("azcombat.native_probe.run_probe") as forbidden:
                with self.assertRaisesRegex(ValueError, "resume request differs"):
                    run_research_wave(phase="evaluation", split_path=split_path,
                                      deck_plan=None, output=base / "r2", game_dir=base,
                                      ritsu_root=base, new_model=new, resume=True)
            forbidden.assert_not_called()
            spec_path.write_text(spec_path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
            with patch("azcombat.native_probe.run_probe") as forbidden:
                with self.assertRaisesRegex(ValueError, "scenario specification SHA256 changed"):
                    run_research_wave(phase="evaluation", split_path=split_path,
                                      deck_plan=plan_path, output=base / "r2", game_dir=base,
                                      ritsu_root=base, new_model=new, resume=True)
            forbidden.assert_not_called()

    def test_deck_plan_must_match_all_35_seeds_and_nonstarter_cards(self):
        with TemporaryDirectory() as directory:
            base = Path(directory)
            split_path, split = _split(base)
            plan_path = _deck_plan(base, split_path, split)
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
            del plan["assignments"][split["evaluationSeeds"][0]]
            plan_path.write_text(json.dumps(plan), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "assign every frozen seed"):
                run_research_wave(phase="teacher", split_path=split_path, deck_plan=plan_path,
                                  output=base / "invalid", game_dir=base, ritsu_root=base)
            plan["assignments"][split["evaluationSeeds"][0]] = "A"
            plan["templates"]["A"]["characterCards"] = ["STRIKE_IRONCLAD", "BASH"]
            plan_path.write_text(json.dumps(plan), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "including a nonstarter"):
                run_research_wave(phase="teacher", split_path=split_path, deck_plan=plan_path,
                                  output=base / "invalid", game_dir=base, ritsu_root=base)
            self.assertFalse((base / "invalid").exists())

    def test_research_teacher_predeclares_jobs_and_resume_never_retries_failed(self):
        with TemporaryDirectory() as directory:
            base = Path(directory)
            split_path, _ = _split(base)
            output = base / "teacher"
            with patch("azcombat.native_probe.run_probe", side_effect=RuntimeError("first failed")) as probe:
                with self.assertRaisesRegex(RuntimeError, "first failed"):
                    run_research_wave(phase="teacher", split_path=split_path, output=output,
                                      game_dir=base, ritsu_root=base)
            manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(len(manifest["runs"]), 50)
            self.assertEqual([run["status"] for run in manifest["runs"][:2]], ["error", "pending"])
            self.assertEqual(manifest["request"]["maxSimulations"], None)
            self.assertTrue(all(run["requestedSearchMode"] == "pure-mcts"
                                and run["requestedModelSha256"] is None
                                for run in manifest["runs"]))
            self.assertEqual(probe.call_args.kwargs["search_mode"], "pure-mcts")
            self.assertIsNone(probe.call_args.kwargs["model"])
            self.assertIsNone(probe.call_args.kwargs["max_simulations"])
            self.assertEqual(probe.call_args.kwargs["max_decisions"], 256)
            with patch("azcombat.native_probe.run_probe", return_value=_probe_audit()) as resumed:
                result = run_research_wave(phase="teacher", split_path=split_path, output=output,
                                           game_dir=base, ritsu_root=base, resume=True)
            self.assertEqual(resumed.call_count, 49)
            self.assertEqual(result["status"], "complete-with-errors")
            self.assertEqual(result["runs"][0]["status"], "error")
            self.assertEqual(result["runs"][1]["audit"]["samples"], 2)
            split_path.write_text(split_path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
            with patch("azcombat.native_probe.run_probe") as forbidden:
                with self.assertRaisesRegex(ValueError, "resume request differs"):
                    run_research_wave(phase="teacher", split_path=split_path, output=output,
                                      game_dir=base, ritsu_root=base, resume=True)
            forbidden.assert_not_called()

    def test_research_evaluation_uses_three_uncapped_arms_and_records_missing_old_model(self):
        with TemporaryDirectory() as directory:
            base = Path(directory)
            split_path, split = _split(base)
            old = _lineage_model(base / "old", ["old-train"], ["old-validation"])
            new = _lineage_model(base / "new", [split["trainSeeds"][0]],
                                 [split["validationSeeds"][0]])
            def staged_probe(**kwargs):
                audit = _probe_audit()
                for identity in audit["assemblies"].values():
                    identity["path"] = str(kwargs["output"].with_suffix(".stage") / "loaded.dll")
                return audit
            with patch("azcombat.native_probe.run_probe", side_effect=staged_probe) as probe:
                result = run_research_wave(phase="evaluation", split_path=split_path,
                                           output=base / "evaluation", game_dir=base,
                                           ritsu_root=base, old_model=old, new_model=new)
            self.assertEqual(result["status"], "complete")
            self.assertEqual(probe.call_count, 60)
            self.assertEqual([call.kwargs["search_mode"] for call in probe.call_args_list[:3]],
                             ["pure-mcts", "policy-value-tree-v1", "policy-value-tree-v1"])
            self.assertEqual([call.kwargs["model"] for call in probe.call_args_list[:3]],
                             [None, old.resolve(), new.resolve()])
            self.assertEqual([run["requestedSearchMode"] for run in result["runs"][:3]],
                             ["pure-mcts", "policy-value-tree-v1", "policy-value-tree-v1"])
            self.assertTrue(all(call.kwargs["max_simulations"] is None
                                for call in probe.call_args_list))
            with patch("azcombat.native_probe.run_probe", return_value=_probe_audit()) as missing_probe:
                missing = run_research_wave(phase="evaluation", split_path=split_path,
                                            output=base / "evaluation-missing-old", game_dir=base,
                                            ritsu_root=base, new_model=new)
            self.assertEqual(missing["status"], "complete-with-missing")
            self.assertEqual(missing_probe.call_count, 40)
            self.assertEqual(sum(run["status"] == "unavailable" for run in missing["runs"]), 20)

    def test_research_isolated_stage_still_rejects_changed_assembly_build(self):
        with TemporaryDirectory() as directory:
            base = Path(directory)
            split_path, _ = _split(base)
            audits = [_probe_audit(), _probe_audit()]
            audits[1]["assemblies"]["search"]["sha256"] = "b" * 64
            with patch("azcombat.native_probe.run_probe", side_effect=audits) as probe:
                with self.assertRaisesRegex(ValueError, "MVID/SHA256 differs"):
                    run_research_wave(phase="teacher", split_path=split_path,
                                      output=base / "teacher", game_dir=base, ritsu_root=base)
            self.assertEqual(probe.call_count, 2)
            manifest = json.loads((base / "teacher" / "manifest.json").read_text())
            self.assertEqual([run["status"] for run in manifest["runs"][:2]], ["complete", "error"])

    def test_research_rejects_old_lineage_overlap_before_creating_output(self):
        with TemporaryDirectory() as directory:
            base = Path(directory)
            split_path, split = _split(base)
            old = _lineage_model(base / "old", [split["trainSeeds"][0]], ["old-validation"])
            output = base / "teacher"
            with self.assertRaisesRegex(ValueError, "overlap old model"):
                run_research_wave(phase="teacher", split_path=split_path, output=output,
                                  game_dir=base, ritsu_root=base, old_model=old)
            self.assertFalse(output.exists())

    def test_only_current_onnx_manifest_and_hash_are_accepted(self):
        with TemporaryDirectory() as directory:
            model = _model(Path(directory))
            manifest_path = model.with_suffix(".manifest.json")
            original = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(checked_model(model), original["onnxSha256"])
            with_schema = {**original, "observationSchemaVersion": 3}
            manifest_path.write_text(json.dumps(with_schema), encoding="utf-8")
            self.assertEqual(checked_model(model), original["onnxSha256"])
            for change in ({"format": "azcombat.onnx.v1"},
                           {"featureAbi": "azcombat.features.v3"},
                           {"observationSchemaVersion": 2},
                           {"onnxSha256": "0" * 64},
                           {"inputs": {"entities": ["N", 13]}}):
                with self.subTest(change=change):
                    manifest_path.write_text(json.dumps({**with_schema, **change}), encoding="utf-8")
                    with self.assertRaises(ValueError):
                        checked_model(model)

    def test_checkpoint_v3_feature_v4_is_loaded_but_old_or_wrong_abi_is_not(self):
        with TemporaryDirectory() as directory:
            checkpoint = Path(directory) / "candidate.pt"
            payload = {"format": "azcombat.checkpoint.v3", "featureAbi": "azcombat.features.v4",
                       "config": {"hidden": 16}, "metadata": {},
                       "model": DeepSetsPolicyValue(16).state_dict()}
            torch.save(payload, checkpoint)
            self.assertEqual(sum(p.numel() for p in load_checkpoint(checkpoint)[0].parameters()), 1970)
            for change in ({"format": "azcombat.checkpoint.v1"},
                           {"featureAbi": "azcombat.features.v3"},
                           {"observationSchemaVersion": 2}):
                with self.subTest(change=change):
                    torch.save({**payload, **change}, checkpoint)
                    with self.assertRaisesRegex(ValueError, "unsupported checkpoint"):
                        load_checkpoint(checkpoint)

    def test_launch_clears_external_knobs_and_passes_explicit_modes_and_caps(self):
        with TemporaryDirectory() as directory:
            base = Path(directory)
            model = _model(base)
            polluted = {"STS2_ALPHAZERO_ONNX_MODEL": "wrong.onnx",
                        "STS2_ALPHAZERO_SEARCH_MODE": "post-mcts-rerank",
                        "STS2_ALPHAZERO_SHADOW": "1",
                        "STS2_MCTS_EXPORT_MAX_SIMULATIONS": "9999",
                        "STS2_MCTS_EXPORT_BUDGET_MS": "50"}
            for mode, expected_search, has_model in (("evaluate", "pure-mcts", False),
                                                     ("bootstrap", "policy-value-tree-v1", True)):
                with self.subTest(mode=mode), patch.dict(os.environ, polluted), \
                        patch("azcombat.experiments.shutil.which", return_value="pwsh"), \
                        patch("azcombat.experiments.subprocess.run", side_effect=RuntimeError("intercept")) as launch:
                    with self.assertRaisesRegex(RuntimeError, "intercept"):
                        run_wave(mode=mode, output=base / f"wave-{mode}", game_dir=base,
                                 ritsu_root=base, model=model, seeds=["new-a", "new-b"],
                                 encounters=["CULTISTS_NORMAL"], scenarios=["ordinary"],
                                 budget_ms=1000, max_simulations=50, max_decisions=3)
                    command = launch.call_args.args[0]
                    env = launch.call_args.kwargs["env"]
                    self.assertEqual(command[command.index("-SearchMode") + 1], expected_search)
                    self.assertEqual(command[command.index("-MaxSimulations") + 1], "50")
                    self.assertEqual(command[command.index("-BudgetMilliseconds") + 1], "1000")
                    stage = Path(command[command.index("-StageRoot") + 1])
                    self.assertEqual(stage,
                                     (base / f"wave-{mode}" /
                                      "000-CULTISTS_NORMAL-ordinary-full_combat-"
                                      f"{'baseline' if mode == 'evaluate' else 'candidate'}.stage").resolve())
                    self.assertEqual("-OnnxModel" in command, has_model)
                    self.assertNotIn("STS2_ALPHAZERO_ONNX_MODEL", env)
                    self.assertNotIn("STS2_ALPHAZERO_SHADOW", env)
                    self.assertEqual(env["STS2_ALPHAZERO_SEARCH_MODE"], expected_search)
                    self.assertEqual(env["STS2_MCTS_EXPORT_MAX_SIMULATIONS"], "50")
                    self.assertEqual(env["STS2_MCTS_EXPORT_BUDGET_MS"], "1000")

    def test_failed_publish_keeps_manifest_entry_and_launcher_logs_without_worker_logs(self):
        with TemporaryDirectory() as directory:
            base = Path(directory)
            model = _model(base)
            output = base / "failed-wave"
            failure = subprocess.CompletedProcess(["pwsh"], 1, "stage created\n", "copy failed\n")
            with patch("azcombat.experiments.shutil.which", return_value="pwsh"), \
                    patch("azcombat.experiments.subprocess.run", return_value=failure):
                with self.assertRaisesRegex(RuntimeError, "NativeWorker failed"):
                    run_wave(mode="bootstrap", output=output, game_dir=base, ritsu_root=base,
                             model=model, seeds=["new-a", "new-b"],
                             encounters=["CULTISTS_NORMAL"], scenarios=["ordinary"])
            manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(len(manifest["runs"]), 1)
            run = manifest["runs"][0]
            self.assertEqual(run["status"], "failed")
            self.assertEqual(Path(run["stageRoot"]), (output / "000-CULTISTS_NORMAL-ordinary-full_combat-candidate.stage").resolve())
            self.assertEqual((output / run["stdout"]).read_text(), "stage created\n")
            self.assertEqual((output / run["stderr"]).read_text(), "copy failed\n")
            self.assertFalse((output / run["workerStdout"]).exists())


if __name__ == "__main__":
    unittest.main()
