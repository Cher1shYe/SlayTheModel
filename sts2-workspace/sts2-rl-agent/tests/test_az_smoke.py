"""M1 debug wiring only; this is not the M3 two-iteration observable test."""
import json
from pathlib import Path
import tempfile
import unittest

import torch

from scripts.smoke_alphazero_debug import run
from sts2_env.az.network import load_debug_checkpoint
from sts2_env.az.scenarios import save_manifest, starter_scenario


class DebugSmokeTests(unittest.TestCase):
    def test_completed_episode_labels_and_checkpoint(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = root / "manifest.json"
            save_manifest(manifest, [starter_scenario(0)])
            report = run(root / "run", manifest, episodes=1, budget=2, updates=1)
            out = root / "run" / "full_state_debug"
            record = json.loads(next((out / "episodes").glob("*.json")).read_text())
            self.assertTrue(record["complete"])
            self.assertEqual(len(record["rows"]), report["samples"])
            for row in record["rows"]:
                self.assertEqual(row["z"], report["episodes"][0]["reward"])
                self.assertEqual(row["information_mode"], "full_state_debug")
                self.assertNotIn("environment_seed", row)
                self.assertEqual(sum(row["root_visits"]), row["search_simulations"])
                self.assertAlmostEqual(sum(row["policy_target"]), 1)
            initial, _ = load_debug_checkpoint(out / "initial.pt")
            candidate, _ = load_debug_checkpoint(out / "candidate.pt")
            self.assertTrue(any(not torch.equal(a, b) for a, b in zip(initial.parameters(), candidate.parameters())))
            self.assertEqual(report["checkpoint_roundtrip"], "passed")
            with self.assertRaisesRegex(ValueError, "empty"):
                run(root / "run", manifest, episodes=1, budget=2, updates=1)

    def test_test_split_cannot_supply_debug_training(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = root / "manifest.json"
            save_manifest(manifest, [starter_scenario(500, "test")])
            with self.assertRaisesRegex(ValueError, "training recipes"):
                run(root / "run", manifest, episodes=1, budget=2, updates=1)


if __name__ == "__main__":
    unittest.main()
