import unittest
import numpy as np
import torch

from sts2_env.az.puct import search_debug, plan_debug
from sts2_env.az.encoder import encode_debug
from sts2_env.az.network import PolicyValueNetwork
from sts2_env.az.scenarios import make_scenario, starter_scenario
from sts2_env.cards import base as card_base
from sts2_env.search.clone import clone_state


class Toy:
    def __init__(self, path=(), forced=False):
        self.path = path
        self.forced = forced

    def clone(self):
        return Toy(self.path, self.forced)

    def legal_mask(self):
        mask = np.zeros(115, dtype=bool)
        mask[:1 if self.forced else 2] = True
        return mask

    def step(self, action):
        self.path += (action,)

    def terminal_value(self):
        if len(self.path) == 2:
            return 1.0 if self.path[0] == 1 else -1.0
        return None


def predict(state):
    mask = state.legal_mask()
    return mask / mask.sum(), 0.6


class PuctTests(unittest.TestCase):
    def test_optimal_action_and_no_sign_flip(self):
        domain = Toy()
        result = search_debug(domain, predict, model_version="toy", budget=128)
        self.assertEqual(result.action, 1)
        self.assertGreater(result.root.edges[1].q, 0.9)
        self.assertEqual(result.simulations, 128)
        self.assertEqual(result.root_visits.sum(), 128)
        np.testing.assert_array_equal(result.policy_target, result.root_visits / 128)
        self.assertEqual(domain.path, ())

    def test_depth_limit_bootstraps_and_terminal_bypasses_network(self):
        def evaluate(state):
            self.assertIsNone(state.terminal_value())
            return predict(state)
        result = search_debug(Toy(), evaluate, model_version="toy", budget=8, max_depth=1)
        self.assertTrue(all(abs(edge.q - 0.6) < 1e-9 for edge in result.root.edges.values()))
        terminal = search_debug(Toy((1, 0)), lambda s: self.fail("terminal evaluated"), model_version="toy")
        self.assertIsNone(terminal.action)
        self.assertEqual(terminal.simulations, 0)
        search_debug(Toy(), evaluate, model_version="toy", budget=64)

    def test_forced_action_zero_simulations(self):
        result = search_debug(Toy(forced=True), lambda s: self.fail("forced evaluated"), model_version="toy")
        self.assertTrue(result.forced_action)
        self.assertEqual(result.simulations, 0)
        self.assertEqual(result.root_visits.sum(), 0)
        self.assertEqual(result.policy_target[0], 1)

    def test_noise_determinism_and_temperature_label_separation(self):
        options = dict(model_version="toy", budget=16, search_seed=22)
        before = search_debug(Toy(), predict, **options)
        noisy = search_debug(Toy(), predict, training=True, temperature=1, **options)
        repeated = search_debug(Toy(), predict, training=True, temperature=0, **options)
        after = search_debug(Toy(), predict, **options)
        np.testing.assert_array_equal(before.root_visits, after.root_visits)
        np.testing.assert_array_equal(noisy.root_visits, repeated.root_visits)
        np.testing.assert_array_equal(noisy.policy_target, repeated.policy_target)
        self.assertFalse(np.array_equal(before.root_priors, noisy.root_priors))

    def test_prediction_failure_restores_allocator(self):
        saved = card_base._next_instance_id
        def broken(state):
            card_base._get_next_id()
            raise RuntimeError("inference failed")
        with self.assertRaises(RuntimeError):
            search_debug(Toy(), broken, model_version="toy")
        self.assertEqual(card_base._next_instance_id, saved)

    def test_combat_root_and_rng_unchanged(self):
        torch.set_num_threads(1)
        torch.manual_seed(3)
        world = make_scenario(starter_scenario(1))
        twin = clone_state(world)
        model = PolicyValueNetwork()
        saved = card_base._next_instance_id
        first = plan_debug(world, model, model_version="debug-0", budget=16)
        second = plan_debug(world, model, model_version="debug-0", budget=16)
        self.assertEqual(saved, card_base._next_instance_id)
        np.testing.assert_array_equal(first.root_visits, second.root_visits)
        self.assertEqual(encode_debug(world).to_dict(), encode_debug(twin).to_dict())
        self.assertEqual([c.instance_id for c in world.draw_pile], [c.instance_id for c in twin.draw_pile])
        self.assertEqual(world.rng.next_int(0, 99999), twin.rng.next_int(0, 99999))


if __name__ == "__main__":
    unittest.main()
