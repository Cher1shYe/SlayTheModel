from __future__ import annotations

import json
import hashlib
from dataclasses import replace
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import torch

from azcombat.samples import TrainingSample, write_jsonl, read_jsonl
from azcombat.schema import ActionNode
from azcombat.training import (CombatDataset, DeepSetsPolicyValue, TrainConfig,
                               encode_actions, encode_observation, load_checkpoint,
                               split_by_seed, train)
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
