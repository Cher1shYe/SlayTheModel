from __future__ import annotations

import json
import hashlib
from dataclasses import replace
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import torch

from azcombat.samples import TrainingSample, write_jsonl, read_jsonl
from azcombat.schema import ActionNode
from azcombat.training import (CombatDataset, DeepSetsPolicyValue, TrainConfig,
                               _loss, encode_actions, encode_observation, load_checkpoint,
                               load_seed_split, split_by_manifest, split_by_seed, train)
from azcombat.train_cli import main as train_main
from test_schema_reward import observation


def sample(seed: str) -> TrainingSample:
    return TrainingSample(seed, "full_combat", observation(), (
        ActionNode("PlayCard", "play", {"CardId": "STRIKE_IRONCLAD", "Damage": 6}),
        ActionNode("EndTurn", "end", terminal=True),
    ), {"play": 9, "end": 1}, 0.6, "win")


class TrainingTests(unittest.TestCase):
    def test_forced_regression_is_strictly_valid_but_not_training_data(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "regression.jsonl"
            raw = sample("forced").to_dict()
            raw["provenance"] = {"regressionOnly": True, "forcedFixtureCard": "BURNING_PACT"}
            path.write_text(json.dumps(raw) + "\n", encoding="utf-8")
            self.assertEqual(len(read_jsonl(path, allow_regression=True)), 1)
            with self.assertRaisesRegex(ValueError, "regression-only"):
                CombatDataset([path])
            raw["visitPolicy"] = {"illegal": 1}
            path.write_text(json.dumps(raw) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "unknown action"):
                read_jsonl(path, allow_regression=True)

    def test_strict_dataset_and_seed_isolation(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "data.jsonl"
            write_jsonl([sample("one"), sample("two"), sample("one")], path)
            data = CombatDataset([path])
            train_set, valid = split_by_seed(data.samples)
            self.assertFalse({x.seed for x in train_set} & {x.seed for x in valid})
            self.assertEqual(len(train_set) + len(valid), 3)
            with self.assertRaises(ValueError):
                split_by_seed([sample("one")])
            raw = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
            raw["observation"]["futureDraws"] = []
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(raw) + "\n")
            with self.assertRaisesRegex(ValueError, "line 4"):
                CombatDataset([path])

    def test_candidate_scoring_and_permutation_invariance(self):
        item = sample("one")
        entities, globals_ = encode_observation(item)
        ids, actions = encode_actions(item)
        self.assertEqual(ids, ["play", "end"])
        model = DeepSetsPolicyValue(16).eval()
        with torch.no_grad():
            logits, value = model(entities, globals_, actions)
            shuffled, other = model(entities.flip(0), globals_, actions)
        self.assertTrue(torch.allclose(logits, shuffled, atol=1e-6))
        self.assertTrue(torch.allclose(value, other, atol=1e-6))
        self.assertFalse(torch.equal(actions[0], actions[1]))

    def test_replay_identity_and_precomputed_damage_are_not_features(self):
        item = sample("one")
        original = encode_actions(item)[1]
        altered = replace(item, legal_actions=(
            ActionNode("PlayCard", "different-state-key", {
                "CardId": "STRIKE_IRONCLAD", "Damage": 999, "TargetHp": 1,
                "CardStateKey": "hidden-rng-and-future", "CardStateOccurrence": 19,
            }), item.legal_actions[1]))
        self.assertTrue(torch.equal(original, encode_actions(altered)[1]))

    def test_old_feature_checkpoint_is_rejected_even_at_same_width(self):
        with TemporaryDirectory() as directory:
            legacy = Path(directory) / "legacy.pt"
            torch.save({"format": "azcombat.checkpoint.v1", "config": {"hidden": 16},
                        "model": DeepSetsPolicyValue(16).state_dict()}, legacy)
            with self.assertRaisesRegex(ValueError, "unsupported checkpoint format"):
                load_checkpoint(legacy)

    def test_hidden_draw_pile_is_fail_closed_until_projection_exists(self):
        raw = deepcopy(observation())
        raw["players"][0]["piles"].append({"pileType": "Draw", "cards": [
            deepcopy(raw["players"][0]["piles"][0]["cards"][0])]})
        with self.assertRaisesRegex(ValueError, "hidden draw pile"):
            encode_observation(replace(sample("one"), observation=raw))

    def test_experimental_width_is_unchanged(self):
        self.assertEqual(sum(parameter.numel() for parameter in DeepSetsPolicyValue(16).parameters()), 1970)

    def test_train_checkpoint_round_trip(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "data.jsonl"
            checkpoint = Path(directory) / "run" / "candidate.pt"
            write_jsonl([sample("one"), sample("two")], path)
            metadata = train(CombatDataset([path]), checkpoint, TrainConfig(epochs=1, hidden=16))
            model, loaded = load_checkpoint(checkpoint)
            self.assertEqual(loaded["metadata"], metadata)
            self.assertTrue(checkpoint.is_file())
            self.assertEqual(set(metadata["trainSeeds"] + metadata["validationSeeds"]), {"one", "two"})
            entities, global_, actions = (*encode_observation(sample("one")), encode_actions(sample("one"))[1])
            self.assertEqual(tuple(model(entities, global_, actions)[0].shape), (2,))

    def test_frozen_seed_split_keeps_trajectories_together_and_selects_best_epoch(self):
        with TemporaryDirectory() as directory:
            base = Path(directory)
            first, second = base / "cultists.jsonl", base / "fog.jsonl"
            split = base / "seeds.json"
            checkpoint = base / "candidate.pt"
            write_jsonl([sample("train"), sample("valid")], first)
            write_jsonl([sample("train"), sample("valid")], second)
            split.write_text(json.dumps({"format": "azcombat.seed-split.v1",
                                         "trainSeeds": ["train"], "validationSeeds": ["valid"],
                                         "evaluationSeeds": ["held-out"]}), encoding="utf-8")
            dataset = CombatDataset([first, second])
            training, validation = split_by_manifest(dataset.samples, load_seed_split(split))
            self.assertEqual([s.seed for s in training], ["train", "train"])
            self.assertEqual([s.seed for s in validation], ["valid", "valid"])
            metadata = train(dataset, checkpoint, TrainConfig(epochs=3, hidden=16, seed=5),
                             seed_split=split)
            model, _ = load_checkpoint(checkpoint)
            self.assertEqual(metadata["trainSamples"], 2)
            self.assertEqual(metadata["validationSamples"], 2)
            self.assertEqual(metadata["reservedEvaluationSeeds"], ["held-out"])
            self.assertEqual(metadata["missingTrainSeeds"], [])
            self.assertEqual(metadata["missingValidationSeeds"], [])
            self.assertEqual(metadata["selectionMetric"], "validationLoss")
            self.assertLess(metadata["history"][-1]["trainLoss"], metadata["history"][0]["trainLoss"])
            self.assertLess(metadata["history"][-1]["trainPolicyLoss"],
                            metadata["history"][0]["trainPolicyLoss"])
            self.assertLess(metadata["history"][-1]["trainValueLoss"],
                            metadata["history"][0]["trainValueLoss"])
            self.assertEqual(metadata["selectedEpoch"], min(metadata["history"],
                             key=lambda epoch: epoch["validationLoss"])["epoch"])
            self.assertAlmostEqual(sum(_loss(model, s)[0].item() for s in validation) / len(validation),
                                   metadata["history"][metadata["selectedEpoch"] - 1]["validationLoss"],
                                   places=5)
            for epoch in metadata["history"]:
                self.assertAlmostEqual(epoch["trainLoss"],
                                       epoch["trainPolicyLoss"] + epoch["trainValueLoss"], places=5)
                self.assertAlmostEqual(epoch["validationLoss"],
                                       epoch["validationPolicyLoss"] + epoch["validationValueLoss"], places=5)
                self.assertGreaterEqual(epoch["validationValueMae"], 0)

    def test_frozen_seed_split_records_missing_and_rejects_extra_or_unresolved(self):
        with TemporaryDirectory() as directory:
            base = Path(directory)
            split = base / "seeds.json"
            data = base / "data.jsonl"
            groups = {"format": "azcombat.seed-split.v1", "trainSeeds": ["train"],
                      "validationSeeds": ["valid"], "evaluationSeeds": ["held-out"]}
            split.write_text(json.dumps(groups), encoding="utf-8")
            write_jsonl([sample("train"), sample("valid")], data)
            for bad in ({**groups, "evaluationSeeds": ["valid"]},
                        {**groups, "trainSeeds": ["train", "train"]}):
                split.write_text(json.dumps(bad), encoding="utf-8")
                with self.assertRaises(ValueError):
                    load_seed_split(split)
            split.write_text(json.dumps(groups), encoding="utf-8")
            write_jsonl([sample("train"), sample("valid")], data)
            groups_with_missing = {**groups, "trainSeeds": ["train", "missing-train"],
                                   "validationSeeds": ["valid", "missing-valid"]}
            split.write_text(json.dumps(groups_with_missing), encoding="utf-8")
            metadata = train(CombatDataset([data]), base / "missing.pt",
                             TrainConfig(epochs=1, hidden=16), seed_split=split)
            self.assertEqual(metadata["missingTrainSeeds"], ["missing-train"])
            self.assertEqual(metadata["missingValidationSeeds"], ["missing-valid"])
            self.assertEqual(metadata["observedTrainSeeds"], 1)
            self.assertEqual(metadata["observedValidationSeeds"], 1)
            split.write_text(json.dumps(groups), encoding="utf-8")
            write_jsonl([sample("train")], data)
            with self.assertRaisesRegex(ValueError, "nonempty train and validation"):
                train(CombatDataset([data]), base / "empty-side.pt", TrainConfig(epochs=1, hidden=16),
                      seed_split=split)
            write_jsonl([sample("train"), sample("valid"), sample("held-out")], data)
            with self.assertRaisesRegex(ValueError, "undeclared/evaluation"):
                train(CombatDataset([data]), base / "extra.pt", TrainConfig(epochs=1, hidden=16),
                      seed_split=split)
            write_jsonl([sample("train"), replace(sample("valid"), outcome="unresolved")], data)
            with self.assertRaisesRegex(ValueError, "completed full-combat"):
                train(CombatDataset([data]), base / "unresolved.pt", TrainConfig(epochs=1, hidden=16),
                      seed_split=split)

    def test_teacher_audit_binds_training_to_terminal_file_hashes(self):
        with TemporaryDirectory() as directory:
            base = Path(directory)
            train_data, valid_data = base / "train.jsonl", base / "valid.jsonl"
            split = base / "seeds.json"
            write_jsonl([sample("train")], train_data)
            write_jsonl([sample("valid")], valid_data)
            split.write_text(json.dumps({"format": "azcombat.seed-split.v1",
                                         "trainSeeds": ["train"], "validationSeeds": ["valid"],
                                         "evaluationSeeds": ["held-out"]}), encoding="utf-8")
            inputs = [train_data.resolve(), valid_data.resolve()]
            report = {"phase": "teacher", "sourceManifestSha256": "a" * 64,
                      "splitSha256": hashlib.sha256(split.read_bytes()).hexdigest(),
                      "runs": [{"status": "complete", "outcome": "win", "terminal": True,
                                "jsonl": str(path), "jsonlSha256": hashlib.sha256(path.read_bytes()).hexdigest()}
                               for path in inputs],
                      "summary": {"readyForTraining": True,
                                  "trainingInputs": [str(path) for path in inputs]}}
            dataset = CombatDataset(inputs)
            metadata = train(dataset, base / "teacher.pt", TrainConfig(epochs=1, hidden=16),
                             seed_split=split, teacher_report=report)
            self.assertEqual(metadata["teacherWaveManifestSha256"], "a" * 64)
            self.assertEqual(metadata["teacherTerminalBattles"], 2)
            self.assertEqual(len(metadata["teacherAuditSha256"]), 64)
            changed = deepcopy(report)
            changed["runs"][0]["jsonlSha256"] = "0" * 64
            with self.assertRaisesRegex(ValueError, "teacher training inputs differ"):
                train(dataset, base / "bad-hash.pt", TrainConfig(epochs=1, hidden=16),
                      seed_split=split, teacher_report=changed)
            changed = deepcopy(report)
            changed["summary"]["readyForTraining"] = False
            with self.assertRaisesRegex(ValueError, "teacher audit"):
                train(dataset, base / "not-ready.pt", TrainConfig(epochs=1, hidden=16),
                      seed_split=split, teacher_report=changed)
            with self.assertRaisesRegex(ValueError, "teacher training inputs differ"):
                train(CombatDataset([train_data]), base / "missing-file.pt",
                      TrainConfig(epochs=1, hidden=16), seed_split=split, teacher_report=report)

    def test_teacher_cli_reaudits_wave_and_rejects_unready_or_explicit_inputs(self):
        with TemporaryDirectory() as directory:
            base = Path(directory)
            split = base / "seeds.json"
            split.write_text("split", encoding="utf-8")
            wave = base / "wave"
            wave.mkdir()
            report = {"splitSha256": hashlib.sha256(split.read_bytes()).hexdigest()}
            summary = {"readyForTraining": True, "trainingInputs": [str(base / "terminal.jsonl")]}
            args = ["train", "--checkpoint", str(base / "new.pt"), "--seed-split", str(split),
                    "--teacher-wave", str(wave)]
            with patch("sys.argv", args), patch("azcombat.train_cli.audit_wave", return_value=report) as audit, \
                    patch("azcombat.train_cli.summarize_teacher", return_value=summary), \
                    patch("azcombat.train_cli.CombatDataset") as dataset, \
                    patch("azcombat.train_cli.train", return_value={}) as train_call:
                self.assertEqual(train_main(), 0)
            audit.assert_called_once_with(wave / "manifest.json")
            dataset.assert_called_once_with([base / "terminal.jsonl"])
            self.assertEqual(train_call.call_args.kwargs["teacher_report"]["summary"], summary)
            with patch("sys.argv", args), patch("azcombat.train_cli.audit_wave", return_value=report), \
                    patch("azcombat.train_cli.summarize_teacher", return_value={"readyForTraining": False}), \
                    patch("azcombat.train_cli.train") as forbidden:
                with self.assertRaisesRegex(ValueError, "minimum audited terminal data"):
                    train_main()
            forbidden.assert_not_called()
            with patch("sys.argv", [*args, str(base / "other.jsonl")]):
                with self.assertRaises(SystemExit):
                    train_main()

    def test_selfplay_continuation_preserves_width_and_seed_lineage(self):
        with TemporaryDirectory() as directory:
            base = Path(directory)
            source_data, new_data = base / "mcts.jsonl", base / "selfplay.jsonl"
            parent, child = base / "parent.pt", base / "child.pt"
            write_jsonl([sample("one"), sample("two")], source_data)
            write_jsonl([sample("three"), sample("four")], new_data)
            old = train(CombatDataset([source_data]), parent, TrainConfig(epochs=1, hidden=16))
            before, _ = load_checkpoint(parent)
            newer = train(CombatDataset([new_data]), child, TrainConfig(epochs=1, hidden=16),
                          init_checkpoint=parent)
            after, _ = load_checkpoint(child)
            self.assertEqual(newer["parentCheckpointSha256"], hashlib.sha256(parent.read_bytes()).hexdigest())
            self.assertEqual(newer["generation"], 1)
            self.assertEqual(set(newer["trainSeeds"] + newer["validationSeeds"]), {"one", "two", "three", "four"})
            self.assertFalse(set(newer["trainSeeds"]) & set(newer["validationSeeds"]))
            self.assertEqual(sum(p.numel() for p in before.parameters()),
                             sum(p.numel() for p in after.parameters()))
            self.assertTrue(any(not torch.equal(left, right) for left, right in
                                zip(before.parameters(), after.parameters(), strict=True)))
            with self.assertRaises(ValueError):
                train(CombatDataset([source_data]), base / "bad.pt", TrainConfig(epochs=1, hidden=16),
                      init_checkpoint=parent)
            with self.assertRaises(ValueError):
                train(CombatDataset([new_data]), base / "bad.pt", TrainConfig(epochs=1, hidden=32),
                      init_checkpoint=parent)
            forged_audit = {"format": "azcombat.bootstrap-audit.v1", "valid": True,
                            "sourceCheckpointSha256": hashlib.sha256(parent.read_bytes()).hexdigest(),
                            "seeds": ["three", "four"], "inputFiles": [{"path": str(new_data.resolve()),
                                                                        "sha256": "0" * 64}]}
            with self.assertRaisesRegex(ValueError, "bootstrap audit"):
                train(CombatDataset([new_data]), base / "bad.pt", TrainConfig(epochs=1, hidden=16),
                      init_checkpoint=parent, bootstrap_audit=forged_audit)
            self.assertFalse((base / "bad.pt").exists())
            with self.assertRaises(FileExistsError):
                train(CombatDataset([new_data]), child, TrainConfig(epochs=1, hidden=16),
                      init_checkpoint=parent)


if __name__ == "__main__":
    unittest.main()
