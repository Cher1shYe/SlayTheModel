from collections import Counter
from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import torch

from sts2_env.az.adapter import ObservableCombatAdapter
from sts2_env.az.config import EpisodeLimits
from sts2_env.az.encoder import encode_information, encode_debug, OBSERVABLE_SCHEMA
from sts2_env.az.information import observe, PublicHistory, BeliefSampler
from sts2_env.az.network import PolicyValueNetwork, save_checkpoint, load_checkpoint
from sts2_env.az.observable_puct import plan_observable
from sts2_env.az.scenarios import starter_scenario
from sts2_env.cards import base as card_base
from sts2_env.search.clone import clone_state


class InformationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(1)

    def test_hidden_permutation_preserves_search_labels_at_multiple_turns(self):
        torch.manual_seed(5)
        model = PolicyValueNetwork("observable")
        env = ObservableCombatAdapter(starter_scenario(2))
        for turn in range(3):
            twin = clone_state(env.world)
            twin.draw_pile.reverse()
            for _ in range(20):
                twin.rng.next_int(0, 99999)
            for card in twin.hand + twin.draw_pile:
                card.instance_id += 12345
            twin.enemy_ais[0].state_log = ["PRIVATE_SENTINEL"]
            info = observe(twin, env.information.history)
            self.assertEqual(info, env.information)
            for noisy in (False, True):
                opts = dict(model_version="observable-initial", search_seed=19, budget=32, training=noisy)
                a = plan_observable(env.information, model, **opts)
                b = plan_observable(info, model, **opts)
                np.testing.assert_array_equal(a.root_priors, b.root_priors)
                np.testing.assert_array_equal(a.root_visits, b.root_visits)
                np.testing.assert_array_equal(a.policy_target, b.policy_target)
                self.assertEqual(a.action, b.action)
            env.step(0)

    def test_observer_never_reads_draw_order_or_rng(self):
        class ForbiddenList(list):
            def __iter__(self):
                raise AssertionError("Hidden draw order read")
            def __len__(self):
                raise AssertionError("Hidden pile inspected")
        env = ObservableCombatAdapter(starter_scenario(4))
        env.world.draw_pile = ForbiddenList()
        env.world.rng = object()
        env.world.enemy_ais[0].state_log = None
        self.assertEqual(observe(env.world, PublicHistory()), env.information)
        document = env.information.key()
        for forbidden in ("environment_seed", "scenario_id", "instance_id", "rng", "model_version"):
            self.assertNotIn(forbidden, document)

    def test_conditional_particles_and_rng_aliases(self):
        env = ObservableCombatAdapter(starter_scenario(1))
        rng = np.random.default_rng(12)
        orders = set()
        first_cards = Counter()
        for _ in range(500):
            particle = BeliefSampler().sample(env.information, rng)
            w = particle.world
            order = tuple(c.card_id.name for c in w.draw_pile)
            orders.add(order)
            first_cards[order[0]] += 1
            self.assertEqual(Counter(order), Counter(env.information.draw_composition))
            self.assertEqual(particle.info, env.information)
            self.assertIs(w.rng, w.shuffle_rng)
            self.assertIs(w.rng, w.monster_ai_rng)
            self.assertIs(w.rng, w.combat_card_selection_rng)
            self.assertIs(w.rng, w.combat_targets_rng)
        self.assertGreater(len(orders), 1)
        for name, count in Counter(env.information.draw_composition).items():
            self.assertAlmostEqual(first_cards[name] / 500, count / len(env.information.draw_composition), delta=0.07)

    def test_particle_draws_keep_causal_order(self):
        env = ObservableCombatAdapter(starter_scenario(1))
        particle = BeliefSampler().sample(env.information, np.random.default_rng(7))
        order = tuple(c.card_id.name for c in particle.world.draw_pile)
        info = particle.step(0)
        self.assertEqual(info.hand, order[:5])
        self.assertEqual(info.history.enemy_moves, ("SHRINKER_MOVE",))

    def test_reconstruction_transition_parity_across_complete_games(self):
        # Couple only test hypothetical draws/RNG to isolate reconstruction
        # accuracy; production BeliefSampler never receives these hidden values.
        rng = np.random.default_rng(17)
        checked = 0
        for seed in range(10):
            env = ObservableCombatAdapter(starter_scenario(seed))
            while not env.outcome().done:
                particle = BeliefSampler().sample(env.information, rng)
                by_name = {}
                for card in particle.world.draw_pile:
                    by_name.setdefault(card.card_id.name, []).append(card)
                particle.world.draw_pile = [by_name[c.card_id.name].pop() for c in env.world.draw_pile]
                by_name = {}
                for card in particle.world.discard_pile:
                    by_name.setdefault(card.card_id.name, []).append(card)
                particle.world.discard_pile = [by_name[c.card_id.name].pop() for c in env.world.discard_pile]
                particle.world.rng = clone_state(env.world.rng)
                action = int(rng.choice(np.flatnonzero(env.information.legal_mask)))
                predicted = particle.step(action)
                env.step(action)
                self.assertEqual(predicted, env.information)
                checked += 1
        self.assertGreater(checked, 100)

    def test_encoder_and_mode_boundaries(self):
        env = ObservableCombatAdapter(starter_scenario(1))
        encoded = encode_information(env.information)
        self.assertEqual(encoded.information_mode, "observable")
        self.assertEqual(list(encoded.numeric.shape), OBSERVABLE_SCHEMA["shapes"]["numeric"])
        np.testing.assert_array_equal(encoded.numeric[:-2], encode_debug(env.world).numeric)
        with self.assertRaises(TypeError):
            BeliefSampler().sample(env.world, np.random.default_rng(1))
        with self.assertRaises(TypeError):
            plan_observable(env.world, PolicyValueNetwork("observable"), model_version="x")
        with self.assertRaises(ValueError):
            plan_observable(env.information, PolicyValueNetwork(), model_version="x")
        with self.assertRaises(ValueError):
            replace(env.information, known_top=("BASH",)).validate()

    def test_checkpoint_mode_and_schema(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "observable.pt"
            model = PolicyValueNetwork("observable")
            save_checkpoint(path, model, "observable-0", {}, {})
            restored, _ = load_checkpoint(path, "observable")
            self.assertEqual(restored.information_mode, "observable")
            with self.assertRaises(ValueError):
                load_checkpoint(path, "full_state_debug")

    def test_sampler_exception_and_search_preserve_global_allocator(self):
        env = ObservableCombatAdapter(starter_scenario(1))
        saved = card_base._next_instance_id
        with patch("sts2_env.az.information.observe", side_effect=RuntimeError("injected")):
            with self.assertRaises(RuntimeError):
                BeliefSampler().sample(env.information, np.random.default_rng(1))
        self.assertEqual(saved, card_base._next_instance_id)
        original = env.information
        plan_observable(original, PolicyValueNetwork("observable"), model_version="m2", budget=8)
        self.assertEqual(saved, card_base._next_instance_id)
        self.assertEqual(original, env.information)

    def test_public_limit_is_terminal_and_not_searched(self):
        env = ObservableCombatAdapter(starter_scenario(1), EpisodeLimits(max_decisions=1))
        env.step(0)
        self.assertEqual(env.information.termination_reason, "time_limit")
        result = plan_observable(env.information, PolicyValueNetwork("observable"), model_version="m2")
        self.assertEqual(result.simulations, 0)
        self.assertIsNone(result.action)


if __name__ == "__main__":
    unittest.main()
