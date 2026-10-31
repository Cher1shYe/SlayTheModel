"""Public-search contracts for optional learned leaf evaluation."""
import pytest
import sts2_sim as sim


def battle():
    strike = next(i for i in range(sim.card_count()) if sim.card_name(i) == "Strike")
    defend = next(i for i in range(sim.card_count()) if sim.card_name(i) == "Defend")
    bc = sim.BattleContext()
    bc.init(int(sim.Encounter.SETUP_CEREMONIAL_BEAST_BOSS), 1234,
            [strike, defend] * 5, [False] * 10, 0, 100, 100)
    return bc


def prior(node):
    return [1.0] * len(node.legal_actions())


def test_value_callback_evaluates_public_leaf_and_preserves_source():
    bc = battle()
    before = (bc.observation_public(), bc.legal_actions())
    observed = []

    def value(node):
        assert node.outcome == sim.Outcome.UNDECIDED
        observed.append(tuple(node.observation_public()))
        return 1.0

    action, completed, won = bc.mcts_depth_priors(100, prior, 500, 3.0, 123,
                                                  False, .05, True, value)
    assert completed == 100
    assert 0 < len(observed) <= completed
    assert len(action) == 1 and action[0] in before[1]
    assert won is False
    assert (bc.observation_public(), bc.legal_actions()) == before
    assert len(set(observed)) > 1


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -float("inf")])
def test_value_callback_rejects_nonfinite_output(bad):
    with pytest.raises(ValueError, match="leaf value must be finite"):
        battle().mcts_depth_priors(20, prior, 500, 3.0, 123, False, .05,
                                   True, lambda node: bad)


def test_value_callback_requires_callable():
    with pytest.raises(ValueError, match="value_fn must be callable or None"):
        battle().mcts_depth_priors(20, prior, 500, 3.0, 123, False, .05, True, 4)


def test_none_value_leaves_original_rollout_unchanged():
    bc = battle()
    args = (100, prior, 2, 3.0, 123, False, .05, True)
    assert bc.mcts_depth_priors(*args) == bc.mcts_depth_priors(*args, None)


def test_leaf_values_change_search_choice():
    bc = battle()
    args = (300, prior, 500, 3.0, 1, False, .05, True)
    prefer_block = bc.mcts_depth_priors(*args, lambda node: node.player_block / 10.0)
    avoid_block = bc.mcts_depth_priors(*args, lambda node: -node.player_block / 10.0)
    assert prefer_block[1] == avoid_block[1] == 300
    assert prefer_block[0] != avoid_block[0]
