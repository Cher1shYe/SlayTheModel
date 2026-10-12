import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import numpy as np

from sts2_env.az.adapter import CombatAdapter, CombatInterfaceError, replay
from sts2_env.az.config import EpisodeLimits, derive_seed
from sts2_env.az.scenarios import starter_scenario, save_manifest, load_manifest, validate_manifest


def fingerprint(env):
    w = env.world
    def cards(pile):
        return [(c.card_id.name, c.upgraded, c.cost) for c in pile]
    def creature(c):
        return c.current_hp, c.block, sorted((p.name, v.amount) for p, v in c.powers.items())
    return (creature(w.player), [creature(c) for c in w.enemies], w.energy,
            [cards(p) for p in (w.hand, w.draw_pile, w.discard_pile, w.exhaust_pile)],
            env.outcome(), env.legal_mask().tolist())


class ScenarioTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name)

    def env(self, seed=1, **kwargs):
        return CombatAdapter(starter_scenario(seed), error_dir=self.path, **kwargs)

    def test_manifest_roundtrip_and_tampering(self):
        recipes = [starter_scenario(1), starter_scenario(2, "validation"), starter_scenario(3, "test")]
        path = self.path / "manifest.json"
        save_manifest(path, recipes)
        self.assertEqual(load_manifest(path), recipes)
        data = json.loads(path.read_text())
        data["scenarios"][0]["player_hp"] = 50
        path.write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError, "hash"):
            load_manifest(path)

    def test_split_overlap_rejected(self):
        with self.assertRaises(ValueError):
            validate_manifest([starter_scenario(1), starter_scenario(1, "test")])

    def test_unsupported_recipe_rejected(self):
        for changes in ({"relics": ("BURNING_BLOOD",)}, {"potions": ("FIRE",)},
                        {"encounter_id": "setup_nibbits_weak"}, {"ascension": 1},
                        {"rules_version": "unknown"}, {"player_hp": 0},
                        {"deck": ()}, {"environment_seed": True}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                replace(starter_scenario(1), **changes)

    def test_full_combat_replay_each_step(self):
        for seed in range(5):
            env = self.env(seed)
            twin = self.env(seed)
            rng = np.random.default_rng(seed)
            while not env.outcome().done:
                self.assertEqual(fingerprint(env), fingerprint(twin))
                action = int(rng.choice(np.flatnonzero(env.legal_mask())))
                env.step(action)
                twin.step(action)
            rebuilt = replay(env.recipe, env.actions, error_dir=self.path)
            self.assertEqual(fingerprint(env), fingerprint(rebuilt))

    def test_empty_resources_and_potion_mask(self):
        env = self.env()
        self.assertEqual(env.world.relics, [])
        self.assertEqual(env.world.potions, [])
        self.assertEqual(env.legal_mask().shape, (115,))
        self.assertFalse(env.legal_mask()[61:].any())

    def test_limit_is_not_death(self):
        env = self.env(limits=EpisodeLimits(max_decisions=1))
        result = env.step(0)
        self.assertEqual(result.termination_reason, "time_limit")
        self.assertEqual(result.reward, -1)
        self.assertFalse(env.world.is_over)
        self.assertFalse(env.legal_mask().any())
        env = self.env(limits=EpisodeLimits(max_turns=1))
        self.assertEqual(env.step(0).termination_reason, "time_limit")

    def test_death_and_win_rewards(self):
        env = self.env()
        while not env.outcome().done:
            env.step(0)
        self.assertEqual(env.outcome().termination_reason, "death")
        self.assertEqual(env.outcome().reward, -1)
        env = self.env()
        env.world.enemies[0].current_hp = 1
        action = int(next(a for a in np.flatnonzero(env.legal_mask()) if 11 <= a < 61))
        self.assertEqual(env.step(action).reward, 1)
        self.assertEqual(env.outcome().termination_reason, "win")

    def test_illegal_action_preserves_reproduction_record(self):
        env = self.env()
        with self.assertRaises(CombatInterfaceError):
            env.step(114)
        record = json.loads(next(self.path.glob("*.json")).read_text())
        self.assertEqual(record["actions"], [])
        self.assertEqual(record["scenario"], json.loads(json.dumps(env.recipe.to_dict())))
        self.assertTrue(env.failed)

    def test_engine_rejection_not_a_loss(self):
        env = self.env()
        action = int(np.flatnonzero(env.legal_mask())[1])
        with patch.object(env.world, "play_card", return_value=False):
            with self.assertRaisesRegex(CombatInterfaceError, "rejected"):
                env.step(action)
        self.assertFalse(env.outcome().done)
        self.assertEqual(env.actions, [])

    def test_choice_and_capacity_fail_fast(self):
        env = self.env()
        env.world.hand *= 3
        with self.assertRaisesRegex(CombatInterfaceError, "capacity"):
            env.step(0)
        env = self.env()
        env.world.request_card_choice(prompt="unsupported", cards=env.world.hand[:2],
                                      source_pile="hand", resolver=lambda c: None)
        with self.assertRaisesRegex(CombatInterfaceError, "Choice"):
            env.step(0)

    def test_stable_purpose_seeds(self):
        a = derive_seed(42, 1, "job-1", "search")
        self.assertEqual(a, derive_seed(42, 1, "job-1", "search"))
        self.assertNotEqual(a, derive_seed(42, 1, "job-1", "world"))


if __name__ == "__main__":
    unittest.main()
