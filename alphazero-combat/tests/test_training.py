from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import torch

from azcombat.samples import TrainingSample, write_jsonl
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


if __name__ == "__main__":
    unittest.main()
