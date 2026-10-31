"""Contracts for public-information MCTS with node-specific PUCT."""
import pytest
import sts2_sim as sim


def battle():
    strike = next(i for i in range(sim.card_count()) if sim.card_name(i) == "Strike")
    defend = next(i for i in range(sim.card_count()) if sim.card_name(i) == "Defend")
    bc = sim.BattleContext()
    bc.init(int(sim.Encounter.SETUP_CEREMONIAL_BEAST_BOSS), 1234,
            [strike, defend] * 5, [False] * 10, 0, 100, 100)
    return bc


def test_resampled_search_executes_only_one_legal_action_and_preserves_source():
    bc = battle()
    before = (bc.observation_public(), bc.legal_actions())
    seen = []
    def prior(node):
        seen.append(tuple(node.observation_public()))
        return [1.0] * len(node.legal_actions())
    result = bc.mcts_depth_priors(300, prior, 3, 3.0, 42, False, .05, True)
    assert result[1] == 300 and len(result[0]) == 1
    assert result[0][0] in before[1]
    assert result[2] is False  # A lucky simulated win is not a real victory.
    assert (bc.observation_public(), bc.legal_actions()) == before
    assert len(seen) > 1 and len(set(seen)) > 1


def test_resampled_root_prior_and_depth_one_match():
    bc = battle()
    actions = bc.legal_actions()
    priors = [float(i + 1) for i in range(len(actions))]
    def prior(node):
        return priors
    expected = bc.mcts_priors(200, actions, priors, 3.0, 42, True, False, .05)
    assert bc.mcts_depth_priors(200, prior, 1, 3.0, 42, False, .05, True) == expected
    assert expected[1] == 200 and len(expected[0]) == 1


def test_resampled_search_is_reproducible_for_a_fixed_seed():
    bc = battle()
    def prior(node):
        return [1.0] * len(node.legal_actions())
    one = bc.mcts_depth_priors(200, prior, 4, 3.0, 71, False, .05, True)
    two = bc.mcts_depth_priors(200, prior, 4, 3.0, 71, False, .05, True)
    assert one == two


def test_search_does_not_depend_on_original_hidden_order_or_rng():
    bc = battle()
    a, b = bc.clone(), bc.clone()
    a.resample_hidden(123)
    b.resample_hidden(456)
    assert a.draw != b.draw
    assert a.observation_public() == b.observation_public()
    assert a.legal_actions() == b.legal_actions()
    def prior(node):
        return [1.0] * len(node.legal_actions())
    for depth in (1, 2, 4, 8):
        left = a.mcts_depth_priors(500, prior, depth, 3.0, 42, False, .05, True)
        right = b.mcts_depth_priors(500, prior, depth, 3.0, 42, False, .05, True)
        assert left == right


def test_resampled_invalid_prior_is_rejected():
    bc = battle()
    with pytest.raises(ValueError):
        bc.mcts_depth_priors(10, lambda node: [0.0] * len(node.legal_actions()),
                             2, 3.0, 2, False, .05, True)


def test_different_draws_after_same_action_get_distinct_node_priors():
    bc = battle()
    seen = []
    def prior(node):
        seen.append((node.turn, tuple(node.observation_public())))
        # Encourage the same end-turn root action so multiple possible hands
        # after it have to be distinguished in the tree.
        return [10000.0 if node.turn == bc.turn and a[0] == int(sim.ActionType.END_TURN)
                else 0.001 for a in node.legal_actions()]
    result = bc.mcts_depth_priors(500, prior, 2, 3.0, 42, False, .05, True)
    after_end = {obs for turn, obs in seen if turn > bc.turn}
    assert result[1] == 500
    assert len(after_end) > 1
