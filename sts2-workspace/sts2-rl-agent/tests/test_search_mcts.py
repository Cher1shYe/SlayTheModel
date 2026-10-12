"""Search regressions, also runnable via unittest without pytest."""

import unittest
from sts2_env.search.mcts import STS2CombatEnv, search, legal_actions
from sts2_env.search.clone import clone_state
from sts2_env.cards import base as card_base
from sts2_env.monsters.act1_weak import create_shrinker_beetle
from sts2_env.core.rng import Rng


def signature(node):
    return (node.action, node.visits, node.total_value, tuple(node.untried),
            tuple(signature(child) for child in node.children))


class SearchTests(unittest.TestCase):
    def make_state(self):
        env = STS2CombatEnv()
        env.reset(seed=2)
        return env.combat

    def test_slots_aliases_and_rng_are_isolated(self):
        state = self.make_state()
        clone = clone_state(state)
        self.assertIsNot(state.player, clone.player)
        self.assertIs(clone.player.combat_state, clone)
        self.assertIsNot(state.hand[0], clone.hand[0])
        clone.player.current_hp -= 1
        self.assertNotEqual(clone.player.current_hp, state.player.current_hp)
        self.assertEqual(clone.rng.next_int(0, 10000), state.rng.next_int(0, 10000))
        self.assertIsNot(state.rng, clone.rng)

    def test_choice_callback_targets_clone(self):
        state = self.make_state()
        state.hand = []
        self.assertGreater(len(state.draw_pile), 1)
        state.request_card_choice(prompt="test", cards=state.draw_pile[:2],
                                  source_pile="draw", resolver=state.move_card_to_hand)
        clone = clone_state(state)
        self.assertTrue(clone.resolve_pending_choice(0))
        self.assertEqual(len(state.hand), 0)
        self.assertEqual(len(clone.hand), 1)
        self.assertIsNotNone(state.pending_choice)

    def test_monster_callback_targets_clone(self):
        creature, ai = create_shrinker_beetle(Rng(7))
        cloned_creature, cloned_ai = clone_state((creature, ai))
        refs = [cell.cell_contents for cell in cloned_ai.current_move.effect_fn.__closure__]
        self.assertTrue(any(obj is cloned_creature for obj in refs))
        self.assertFalse(any(obj is creature for obj in refs))

    def test_shared_recursive_closure_cells(self):
        items = []
        def append(value):
            items.append(value)
        def read():
            return items
        cloned_append, cloned_read = clone_state((append, read))
        cloned_append(1)
        self.assertEqual(items, [])
        self.assertEqual(cloned_read(), [1])
        def recursive(n):
            return 0 if not n else recursive(n - 1) + 1
        copied = clone_state(recursive)
        self.assertEqual(copied(3), 3)
        self.assertIs(copied.__closure__[0].cell_contents, copied)

    def test_replay_matches_reference_and_preserves_root(self):
        for seed in range(3):
            env = STS2CombatEnv()
            env.reset(seed=seed)
            state = env.combat
            original = clone_state(state)
            next_id = card_base._next_instance_id
            for depth in (0, 12):
                reference = search(state, 32, depth, seed=14, mode="reference")
                replay = search(state, 32, depth, seed=14, mode="replay")
                self.assertEqual(signature(reference.root), signature(replay.root))
                self.assertEqual(card_base._next_instance_id, next_id)
                self.assertEqual(state.player.current_hp, original.player.current_hp)
                self.assertEqual([c.instance_id for c in state.hand], [c.instance_id for c in original.hand])
                self.assertEqual(legal_actions(state), legal_actions(original))
                self.assertEqual(state.rng.counter, original.rng.counter)
                self.assertEqual(replay.clones, 32)

    def test_pending_choice_search_is_isolated(self):
        state = self.make_state()
        state.request_card_choice(prompt="test", cards=state.draw_pile[:2],
                                  source_pile="draw", resolver=state.move_card_to_hand)
        for depth in (0, 8):
            a = search(state, 16, depth, mode="reference")
            b = search(state, 16, depth, mode="replay")
            self.assertEqual(signature(a.root), signature(b.root))
        self.assertIsNotNone(state.pending_choice)

    def test_terminal_and_failure_restore_allocator(self):
        state = self.make_state()
        saved = card_base._next_instance_id
        def fail(_):
            card_base.new_card_instance_id()
            raise RuntimeError("evaluation failure")
        with self.assertRaises(RuntimeError):
            search(state, 1, 0, evaluator=fail)
        self.assertEqual(card_base._next_instance_id, saved)
        state.is_over = True
        state.player_won = True
        result = search(state, 32)
        self.assertIsNone(result.action)
        self.assertEqual(result.simulations, 0)

    def test_unsupported_objects_fail_loudly(self):
        with self.assertRaises(TypeError):
            clone_state(iter([1, 2]))

    def test_all_act1_encounters_match(self):
        from sts2_env.encounters.act1 import ALL_ACT1_ENCOUNTERS
        for setup in ALL_ACT1_ENCOUNTERS:
            with self.subTest(encounter=setup.__name__):
                env = STS2CombatEnv(encounter_pool=[setup])
                env.reset(seed=7)
                a = search(env.combat, 12, 12, mode="reference")
                b = search(env.combat, 12, 12, mode="replay")
                self.assertEqual(signature(a.root), signature(b.root))

    def test_spawned_workers_match_serial(self):
        from sts2_env.search.batch import SearchJob, SearchPool, run_job
        jobs = [SearchJob(seed, simulations=8, rollout_depth=4) for seed in range(2)]
        expected = [run_job(job) for job in jobs]
        with SearchPool(2) as pool:
            actual = pool.run(jobs)
            repeated = pool.run(jobs)
        for a, b, c in zip(expected, actual, repeated):
            self.assertEqual(a["tree_digest"], b["tree_digest"])
            self.assertEqual(a["tree_digest"], c["tree_digest"])


if __name__ == "__main__":
    unittest.main()
