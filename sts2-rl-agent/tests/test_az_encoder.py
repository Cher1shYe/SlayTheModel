import tempfile
import unittest
from pathlib import Path

import numpy as np
import torch

from sts2_env.az.encoder import SCHEMA, SCHEMA_HASH, encode_debug
from sts2_env.az.scenarios import make_scenario, starter_scenario
from sts2_env.az.network import (PolicyValueNetwork, batch_observations, masked_log_probs,
                                 policy_value_loss, save_debug_checkpoint, load_debug_checkpoint)
from sts2_env.search.clone import clone_state
from sts2_env.core.enums import PowerId


class EncoderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(1)

    def setUp(self):
        self.world = make_scenario(starter_scenario(1))

    def test_schema_shapes_and_hidden_permutation(self):
        first = encode_debug(self.world)
        other = clone_state(self.world)
        other.draw_pile.reverse()
        other.rng.next_int(0, 999)
        for card in other.hand:
            card.instance_id += 10000
        second = encode_debug(other)
        for key, shape in SCHEMA["shapes"].items():
            self.assertEqual(list(getattr(first, key).shape), shape)
            np.testing.assert_array_equal(getattr(first, key), getattr(second, key))

    def test_power_timing_changes_observation(self):
        self.world.enemies[0].apply_power(PowerId.VULNERABLE, 2)
        first = encode_debug(self.world)
        self.world.enemies[0].powers[PowerId.VULNERABLE].skip_next_tick = True
        second = encode_debug(self.world)
        self.assertFalse(np.array_equal(first.numeric, second.numeric))

    def test_scope_rejection(self):
        self.world.hand[0].combat_vars["unmodeled"] = 1
        with self.assertRaises(ValueError):
            encode_debug(self.world)
        self.world.hand[0].combat_vars.clear()
        self.world.player.apply_power(PowerId.STRENGTH, 2)
        with self.assertRaises(ValueError):
            encode_debug(self.world)

    def test_masked_probabilities_and_finite_gradients(self):
        model = PolicyValueNetwork()
        obs = encode_debug(self.world)
        priors, value = model.predict(obs)
        self.assertTrue((priors[~obs.legal_mask] == 0).all())
        self.assertAlmostEqual(float(priors.sum()), 1, places=6)
        self.assertLessEqual(abs(value), 1)
        batch = batch_observations([obs])
        target = torch.as_tensor(priors[None])
        loss, metrics = policy_value_loss(model, batch, target, torch.tensor([1.]))
        loss.backward()
        self.assertTrue(all(torch.isfinite(p.grad).all() for p in model.parameters()))
        self.assertTrue(all(np.isfinite(value) for value in metrics.values()))
        bad = target.clone()
        bad[0, 114] = 0.1
        with self.assertRaises(ValueError):
            policy_value_loss(model, batch, bad, torch.tensor([1.]))

    def test_empty_mask_and_nonfinite_rejected(self):
        with self.assertRaises(ValueError):
            masked_log_probs(torch.zeros((1, 115)), torch.zeros((1, 115), dtype=torch.bool))
        with self.assertRaises(ValueError):
            masked_log_probs(torch.full((1, 115), float("nan")), torch.ones((1, 115), dtype=torch.bool))

    def test_checkpoint_roundtrip_and_isolation(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "debug.pt"
            model = PolicyValueNetwork()
            save_debug_checkpoint(path, model, "debug-0", {}, {})
            loaded, metadata = load_debug_checkpoint(path)
            self.assertEqual(metadata["schema_hash"], SCHEMA_HASH)
            obs = encode_debug(self.world)
            np.testing.assert_array_equal(model.predict(obs)[0], loaded.predict(obs)[0])
            with self.assertRaises(ValueError):
                load_debug_checkpoint(path, expected_mode="observable")
            metadata["schema_hash"] = "changed"
            torch.save(metadata, path)
            with self.assertRaises(ValueError):
                load_debug_checkpoint(path)
            path.write_bytes(b"corrupt")
            with self.assertRaises(Exception):
                load_debug_checkpoint(path)


if __name__ == "__main__":
    unittest.main()
