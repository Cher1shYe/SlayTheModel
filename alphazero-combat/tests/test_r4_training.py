from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from azcombat.r4_training import load_r4_admission, train_r4, verify_r4_weights
from azcombat.training import TrainConfig


ROOT = Path(__file__).resolve().parents[2]
INDEX = ROOT / "artifacts" / "alphazero" / "r4-training-admission-20260926-001" / "index.json"


@unittest.skipUnless(INDEX.exists(),
                     "R4 admission index was intentionally removed during artifact cleanup; regenerate it before replaying these integration tests")
class R4TrainingAdmissionTests(unittest.TestCase):
    def test_frozen_index_loads_with_partition_and_weight_contract(self):
        dataset = load_r4_admission(INDEX)
        self.assertEqual(len(dataset.train), 1052)
        self.assertEqual(len(dataset.validation), 152)
        self.assertEqual(len(dataset.value_samples), 939)
        masses = verify_r4_weights(dataset)
        self.assertAlmostEqual(masses["trainPolicyMass"], 1.0, places=8)
        self.assertAlmostEqual(masses["trainUnresolvedValueMass"], 0.0, places=8)

    def test_changed_trajectory_hash_is_rejected(self):
        raw = json.loads(INDEX.read_text(encoding="utf-8"))
        raw["entries"][0]["trajectorySha256"] = "0" * 64
        with TemporaryDirectory() as directory:
            path = Path(directory) / "index.json"
            path.write_text(json.dumps(raw), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "trajectory provenance changed"):
                load_r4_admission(path)

    def test_sealed_seed_cannot_be_added_to_entries(self):
        raw = json.loads(INDEX.read_text(encoding="utf-8"))
        raw["plan"]["seedUse"]["sealedEvaluation"] = [raw["entries"][0]["seed"]]
        with TemporaryDirectory() as directory:
            path = Path(directory) / "index.json"
            path.write_text(json.dumps(raw), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "sealed evaluation seed"):
                load_r4_admission(path)

    def test_smoke_configuration_is_frozen(self):
        dataset = load_r4_admission(INDEX)
        with TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "frozen configuration"):
                train_r4(dataset, Path(directory) / "candidate.pt", TrainConfig(epochs=1, hidden=16))
