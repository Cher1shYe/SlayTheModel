import numpy as np
import pytest

from agent.armg_prior_train import SEED_BASE, _behavior_distribution, _split_records


def test_behavior_mixture_preserves_exploration_and_prior_target():
    prior = np.asarray([.5, .3, .2])
    saved = prior.copy()
    initial = _behavior_distribution(prior)
    np.testing.assert_allclose(initial, [.45, .31, .24])
    behavior = _behavior_distribution(prior, [.1, .2, .7])
    np.testing.assert_allclose(behavior, .7*np.asarray([.1, .2, .7]) + .2*prior + .1/3)
    np.testing.assert_array_equal(prior, saved)
    assert np.all(behavior > 0) and np.isclose(behavior.sum(), 1)


@pytest.mark.parametrize("prior,model", [([.5, .5], [1]), ([.5, .5], [0, 0]), ([0, 1], None)])
def test_invalid_behavior_inputs_rejected(prior, model):
    with pytest.raises(ValueError):
        _behavior_distribution(prior, model)


def test_replayed_games_keep_their_validation_membership():
    old = [{"seed": SEED_BASE+i} for i in range(6)]
    new = [{"seed": SEED_BASE+i} for i in range(6, 12)]
    old_train, old_val = _split_records(old)
    all_train, all_val = _split_records(old + new)
    assert {r["seed"] for r in old_val}.issubset({r["seed"] for r in all_val})
    assert not ({r["seed"] for r in old_val} & {r["seed"] for r in all_train})
    assert {r["seed"] for r in old_train}.issubset({r["seed"] for r in all_train})
