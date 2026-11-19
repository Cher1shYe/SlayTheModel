import numpy as np

from types import SimpleNamespace

from a9.adapter import combat_choices, grid_choice_rows, observe, step_policy_action
from a9.layout import project_combat_actions, project_public
from spire_rl.sim import sim


def test_combat_action_columns_keep_card_potion_choice_and_target():
    raw = np.arange(732, dtype=np.float32)[None, :]
    encoded = project_combat_actions(raw, np.array([5]))[0]
    np.testing.assert_array_equal(encoded[:6], [0, 0, 0, 0, 0, 1])
    assert encoded[6] == 5 and encoded[602] == 601
    assert encoded[603] == 602 and encoded[667] == 666
    assert encoded[674] == 0 and encoded[675] == 674
    assert encoded[699] == 698 and encoded[722] == 722


def test_run_and_combat_blocks_have_independent_offsets():
    raw = np.zeros(sim.PUBLIC_OBS_DIM, np.float32)
    raw[sim.PUBLIC_RUN_DIM] = 0.5
    raw[sim.PUBLIC_RUN_DIM + 1] = 0.4
    out = project_public(raw)
    assert out.shape == (79280,)
    np.testing.assert_array_equal(out[29198:29200], raw[sim.PUBLIC_RUN_DIM:sim.PUBLIC_RUN_DIM + 2])
    assert np.count_nonzero(out) == 2


def test_final_boss_mode_is_scoped_and_keeps_v14_choices():
    normal = sim.RunContext()
    normal.init(7540000, 9)
    rc = sim.RunContext()
    rc.init_final_boss_evaluation(7540000, 9)
    assert rc.screen == sim.RunScreen.EVENT
    for action in [(12, 2), (12, 0), (0, 1)]:
        obs, actions = observe(rc, sim)
        assert actions == [tuple(a) for a in rc.legal_actions()]
        assert obs['action_num'].shape == (len(actions), 729)
        assert obs['token_num'].shape[1] == 80
        assert action in actions and rc.step_final_boss_evaluation(action)
    assert rc.screen == sim.RunScreen.REWARDS
    assert (18, 0) in observe(rc, sim)[1]
    before_skip = set(observe(rc, sim)[1])
    assert rc.step_final_boss_evaluation((18, 0))
    assert rc.step_final_boss_evaluation((2, 0))
    assert set(observe(rc, sim)[1]) == before_skip - {(18, 0)}
    assert not rc.step_final_boss_evaluation((18, 0))
    other = sim.RunContext()
    other.init(7540000, 9)
    np.testing.assert_array_equal(normal.observe_public(), other.observe_public())
    assert not np.array_equal(normal.macro_observation()['edges'], rc.macro_observation()['edges'])


def test_optional_hand_multi_pick_can_finish_or_add_an_unselected_card():
    first, second, finish, potion = (2, 0, 0, 11), (2, 0, 0, 12), (3, 0, 0, 0), (5, 0, 0, 0)
    battle = SimpleNamespace(pending_info=(24, 1, 2, 2), pending_selected_uids=[11],
                             legal_actions=lambda: [first, second, finish, potion])
    assert combat_choices(battle) == [second, finish, potion]
    battle.pending_selected_uids.append(12)
    assert combat_choices(battle) == [finish, potion]
    battle.pending_selected_uids.clear()
    assert combat_choices(battle) == [first, second, finish, potion]


def test_mandatory_hand_single_is_confirmed_once():
    pick, finish = (2, 0, 0, 11), (3, 0, 0, 0)
    battle = SimpleNamespace(pending_info=(2, 1, 1, 2), pending_optional=False,
                             pending_selected_uids=[11], legal_actions=lambda: [pick, finish])
    calls = []
    def step(action):
        calls.append(action)
        return True
    rc = SimpleNamespace(screen=sim.RunScreen.COMBAT, battle=battle, is_terminal=False,
                         step_final_boss_evaluation=step)
    assert step_policy_action(rc, sim, pick) and calls == [pick, finish]
    calls.clear()
    battle.pending_optional = True
    assert step_policy_action(rc, sim, pick) and calls == [pick]


def test_grid_filter_keeps_original_indices_and_other_actions():
    rc = SimpleNamespace(card_grid_selected=[True, False], card_grid_kind=19)
    actions = [(25, 0), (25, 1), (26, 0), (20, 0)]
    assert grid_choice_rows(rc, actions) == [1, 2, 3]
    rc.card_grid_selected = [False, False]
    assert grid_choice_rows(rc, actions) == [0, 1, 3]
