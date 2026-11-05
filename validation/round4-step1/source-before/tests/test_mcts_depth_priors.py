"""Contract tests for the isolated depth-prior simulator build."""
import pytest
import sts2_sim as sim


def battle():
    strike = next(i for i in range(sim.card_count()) if sim.card_name(i) == "Strike")
    bc = sim.BattleContext()
    bc.init(int(sim.Encounter.SETUP_CEREMONIAL_BEAST_BOSS), 1234,
            [strike] * 10, [False] * 10, 0, 100, 100)
    assert len(bc.legal_actions()) > 1
    return bc


def test_one_depth_equals_original_root_prior():
    bc = battle()
    actions = bc.legal_actions()
    priors = [float(i + 1) for i in range(len(actions))]
    seen = []
    def get_prior(node):
        assert node.legal_actions() == actions
        seen.append(1)
        return priors
    assert bc.mcts_depth_priors(200, get_prior, 1, 3.0, 42) == bc.mcts_priors(
        200, actions, priors, 3.0, 42)
    assert len(seen) == 1


def test_node_priors_use_distinct_node_states_and_are_deterministic():
    bc = battle()
    def search(depth):
        obs = []
        def prior(node):
            obs.append(tuple(node.observation_public()))
            return [1.0] * len(node.legal_actions())
        result = bc.mcts_depth_priors(100, prior, depth, 3.0, 42)
        return result, obs
    one, one_obs = search(1)
    four, four_obs = search(4)
    again, again_obs = search(4)
    assert one[1] == four[1] == 100
    assert len(one_obs) == 1 and len(four_obs) > 1
    assert len(set(four_obs)) > 1
    assert (four, four_obs) == (again, again_obs)


def test_two_levels_never_infer_beyond_one_action_from_root():
    bc = battle()
    reachable = {tuple(bc.observation_public())}
    for action in bc.legal_actions():
        child = bc.clone()
        assert child.step(*action)
        if child.outcome == sim.Outcome.UNDECIDED and len(child.legal_actions()) > 1:
            reachable.add(tuple(child.observation_public()))
    visited = []
    def callback(node):
        visited.append(tuple(node.observation_public()))
        return [1.0] * len(node.legal_actions())
    bc.mcts_depth_priors(200, callback, 2, 3.0, 42)
    assert len(visited) > 1
    assert set(visited) <= reachable


def test_invalid_callback_results_and_exception():
    bc = battle()
    for callback in (lambda node: [], lambda node: [-1] * len(node.legal_actions()),
                     lambda node: [0] * len(node.legal_actions()),
                     lambda node: [float('nan')] * len(node.legal_actions())):
        with pytest.raises(ValueError):
            bc.mcts_depth_priors(10, callback, 4)
    def broken(node):
        raise RuntimeError('callback failure')
    with pytest.raises(RuntimeError, match='callback failure'):
        bc.mcts_depth_priors(10, broken, 4)
