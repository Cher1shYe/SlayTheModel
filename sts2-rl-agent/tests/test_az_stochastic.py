from dataclasses import dataclass, replace
import unittest

import numpy as np

from sts2_env.az.observable_puct import search_belief


@dataclass(frozen=True)
class ChanceInfo:
    stage: str = "root"
    utility: float | None = None
    legal_mask: tuple = (True, True) + (False,) * 113

    def key(self):
        return self.stage, self.utility

    def terminal_value(self):
        return self.utility


class ChanceParticle:
    def __init__(self, info, rng):
        self.info = info
        self.rng = rng

    def step(self, action):
        # Risky action expectation = .25 * 1 + .75 * -1 = -.5.
        # Safe action expectation = 0. Chance is sampled, never maximized.
        reward = (1.0 if self.rng.random() < 0.25 else -1.0) if action == 0 else 0.0
        self.info = ChanceInfo("terminal", reward, (False,) * 115)
        return self.info


def evaluate(info):
    if info.utility is not None:
        raise AssertionError("Network called on terminal outcome")
    mask = np.asarray(info.legal_mask)
    return mask / mask.sum(), 0.75


class StochasticTests(unittest.TestCase):
    def test_enumerated_chance_expectation_and_successor_counts(self):
        result = search_belief(ChanceInfo(), ChanceParticle, evaluate,
                               model_version="toy", search_seed=25, budget=4000, c_puct=100)
        risky, safe = result.root.edges[0], result.root.edges[1]
        self.assertEqual(len(risky.outcomes), 2)
        self.assertEqual(len(safe.outcomes), 1)
        self.assertAlmostEqual(risky.q, -0.5, delta=0.07)
        self.assertEqual(safe.q, 0)
        wins = sum(node.arrivals for (_, key), node in risky.outcomes.items() if key[1] == 1)
        self.assertAlmostEqual(wins / risky.visits, 0.25, delta=0.04)
        self.assertEqual(sum(n.arrivals for n in risky.outcomes.values()), risky.visits)
        self.assertEqual(result.root_visits.sum(), 4000)
        self.assertEqual(result.action, 1)

    def test_nonterminal_outcomes_share_action_stats_not_hidden_oracles(self):
        class HiddenParticle:
            def __init__(self, info, rng):
                self.info, self.hidden = info, int(rng.integers(2))
            def step(self, action):
                if self.info.stage == "root":
                    self.info = ChanceInfo("indistinguishable")
                else:
                    self.info = ChanceInfo("terminal", 1.0 if action == self.hidden else -1.0, (False,) * 115)
                return self.info
        result = search_belief(ChanceInfo(), HiddenParticle, evaluate,
                               model_version="toy", budget=3000, search_seed=3, c_puct=5)
        for edge in result.root.edges.values():
            self.assertEqual(len(edge.outcomes), 1)
            self.assertLess(abs(edge.q), 0.13)  # hidden-aware separate policies would approach +1
            child = next(iter(edge.outcomes.values()))
            self.assertGreater(sum(e.visits for e in child.edges.values()), 100)

    def test_same_information_inconsistent_mask_fails(self):
        def bad_sample(info, rng):
            altered = replace(info, legal_mask=(True,) + (False,) * 114)
            return ChanceParticle(altered, rng)
        with self.assertRaisesRegex(ValueError, "inconsistent legal"):
            search_belief(ChanceInfo(), bad_sample, evaluate, model_version="toy", budget=2)

    def test_depth_bootstrap_and_eval_noise_isolation(self):
        class LoopParticle:
            def __init__(self, info, rng):
                self.info = info
            def step(self, action):
                return self.info
        options = dict(model_version="toy", budget=8, max_depth=1, search_seed=2)
        before = search_belief(ChanceInfo(), LoopParticle, evaluate, **options)
        noisy = search_belief(ChanceInfo(), LoopParticle, evaluate, training=True, **options)
        after = search_belief(ChanceInfo(), LoopParticle, evaluate, **options)
        self.assertTrue(all(edge.q == 0.75 for edge in before.root.edges.values()))
        np.testing.assert_array_equal(before.root_visits, after.root_visits)
        self.assertFalse(np.array_equal(before.root_priors, noisy.root_priors))


if __name__ == "__main__":
    unittest.main()
