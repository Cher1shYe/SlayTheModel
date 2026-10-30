import pytest

from agent.common import SCREEN, new_run
from agent.heuristics import run_policy


def _combat():
    rc = new_run(101)
    for _ in range(100):
        if rc.screen == SCREEN.COMBAT:
            return rc
        assert rc.step(*run_policy(rc))
    raise AssertionError("combat not reached")


def test_mcts_binding_returns_legal_actions_without_mutating_run():
    rc = _combat()
    state = rc.state_hash()
    for resample in (False, True):
        line, done, victory = rc.battle.mcts(32, 4.242640687, 42, resample)
        assert line and line[0] in rc.battle.legal_actions()
        assert done == 32
        assert isinstance(victory, bool)
        assert state == rc.state_hash()


@pytest.mark.parametrize("sims,c,epsilon", [(-1, 1.5, .05), (4, -1, .05),
                                            (4, float('nan'), .05), (4, 1.5, 2)])
def test_mcts_binding_rejects_invalid_search_parameters(sims, c, epsilon):
    rc = _combat()
    with pytest.raises(ValueError):
        rc.battle.mcts(sims, c, 0, False, False, epsilon)


def test_root_prior_binding_alignment_validation_and_determinism():
    rc = _combat()
    state = rc.state_hash()
    legal = rc.battle.legal_actions()
    assert len(legal) > 1
    for i, action in enumerate(legal):
        one_hot = [float(j == i) for j in range(len(legal))]
        line, done, _ = rc.battle.mcts_priors(1, legal, one_hot, 3.0, 42)
        assert done == 1 and line[0] == action
    prior = [1.0] * len(legal)
    first = rc.battle.mcts_priors(32, legal, prior, 3.0, 42)
    assert first == rc.battle.mcts_priors(32, legal, prior, 3.0, 42)
    assert first[1] == 32 and first[0][0] in legal
    assert rc.state_hash() == state
    invalid_inputs = [
        (legal[::-1], prior),
        (legal, prior[:-1]),
        (legal, [0.0] * len(legal)),
        (legal, [float('nan')] + prior[1:]),
        (legal, [-1.0] + prior[1:]),
    ]
    for actions, probabilities in invalid_inputs:
        with pytest.raises(ValueError):
            rc.battle.mcts_priors(8, actions, probabilities)
