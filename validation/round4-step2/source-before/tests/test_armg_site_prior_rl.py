import math
from pathlib import Path

import numpy as np
import pytest
import torch

from agent.armg import ARMG_ACTION_DIM, ARMG_OBS_DIM, _CARD_OFF
from agent.armg_site_prior_loss import CardSkipPrior, backward_prior
from agent.common import RACT, SCREEN


DATA = Path('runs/armg_spire_wr50_prior_20261030/data')


def prior():
    if not DATA.exists():
        pytest.skip('real community snapshot is unavailable')
    return CardSkipPrior(DATA)


def reward_record(teacher, act=1):
    ironclad = next(i for i, name in teacher.site.card_ids.items()
                    if teacher.pools.get(name) == 'ironclad'
                    and teacher.score(teacher.site.card_row(i))[1])
    colorless = next(i for i, name in teacher.site.card_ids.items()
                     if teacher.pools.get(name) == 'colorless'
                     and teacher.site.rating(teacher.site.card_row(i))[1])
    unknown = next(i for i in range(len(teacher.site.card_ids)+50)
                   if i not in teacher.site.card_ids)
    state = np.zeros(ARMG_OBS_DIM, dtype=np.float32)
    state[4] = act/3
    state[38 + int(SCREEN.CARD_REWARD)] = 1
    features = np.zeros((5, ARMG_ACTION_DIM), dtype=np.float32)
    features[0, int(RACT.SKIP_CARD)] = 1
    features[1, int(RACT.TAKE_CARD)] = 1
    features[1, _CARD_OFF+ironclad] = 1
    features[2, int(RACT.TAKE_CARD)] = 1
    features[2, _CARD_OFF+colorless] = 1
    features[3, int(RACT.TAKE_CARD)] = 1
    features[3, _CARD_OFF+unknown] = 1
    features[4, int(RACT.SACRIFICE_CARD_REWARD)] = 1
    return state, features, 0


def test_all_three_skip_ratings_and_colorless_exclusion():
    teacher = prior()
    probabilities = []
    for act in (1, 2, 3):
        target = teacher.target(reward_record(teacher, act))
        assert target['eligible']
        assert target['indices'] == [0, 1]  # colorless, unknown and sacrifice are still legal in RL
        assert target['colorless_excluded'] == 1 and target['unknown_cards'] == 1
        probabilities.append(target['target'][0])
    assert probabilities[0] < probabilities[1] < probabilities[2]
    ratios = [float(p/(1-p)) for p in probabilities]
    assert ratios[1]/ratios[0] == pytest.approx(math.exp(100*math.log(10)/800), rel=1e-5)
    assert ratios[2]/ratios[1] == pytest.approx(math.exp(100*math.log(10)/800), rel=1e-5)


def test_weak_prior_kl_has_gradient_and_logs_skip_coverage():
    teacher = prior()
    record = reward_record(teacher, 2)
    class Model(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.param = torch.nn.Parameter(torch.zeros(5))
        def forward(self, obs, actions):
            return self.param[:actions.shape[1]].expand(obs.shape[0], -1)
    model = Model()
    result = backward_prior(model, [([record], 1.0)], teacher, strength=.05)
    assert result['eligible_decisions'] == 1 and result['act2_chosen_skip'] == 1
    assert result['colorless_excluded'] == 1 and result['unknown_cards'] == 1
    assert result['kl'] >= 0 and result['ce'] > 0
    assert model.param.grad[0] != 0 and model.param.grad[1] != 0
    assert model.param.grad[2] == 0 and model.param.grad[3] == 0 and model.param.grad[4] == 0


def test_non_reward_and_no_covered_cards_do_not_get_prior():
    teacher = prior()
    obs, features, choice = reward_record(teacher)
    obs[38 + int(SCREEN.CARD_REWARD)] = 0
    assert teacher.target((obs, features, choice)) is None
    obs[38 + int(SCREEN.CARD_REWARD)] = 1
    features[1] = features[3]
    result = teacher.target((obs, features, choice))
    assert not result['eligible'] and result['unknown_cards'] == 2 and result['colorless_excluded'] == 1


def test_offered_but_never_picked_ironclad_stays_in_prior_with_shrinkage(monkeypatch):
    teacher = prior()
    card = next(i for i, name in teacher.site.card_ids.items()
                if teacher.pools.get(name) == 'ironclad'
                and teacher.score(teacher.site.card_row(i))[1])
    record = reward_record(teacher)
    original = teacher.site.card_row
    row = {'offered': 170, 'picked': 0, 'elo': 1200}
    monkeypatch.setattr(teacher.site, 'card_row', lambda i: row if i == card else original(i))
    record[1][1, _CARD_OFF:_CARD_OFF+len(teacher.site.card_ids)+50] = 0
    record[1][1, _CARD_OFF+card] = 1
    target = teacher.target(record)
    assert target['eligible'] and target['colorless_excluded'] == 1 and target['zero_pick_cards'] == 1
    assert target['indices'] == [0, 1]
    score, available = teacher.score(teacher.site.card_row(card))
    expected = np.clip((teacher.site.card_row(card)['elo'] - 1500) * math.log(10) / 800 * 2 / 52, -1.5, 1.5)
    assert available and score == pytest.approx(expected)


def test_colorless_choice_remains_in_policy_gradient():
    from agent.armg_train import backward_weighted
    teacher = prior()
    obs, features, _ = reward_record(teacher)
    class Model(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.param = torch.nn.Parameter(torch.zeros(5))
        def forward(self, obs, actions):
            return self.param[:actions.shape[1]].expand(obs.shape[0], -1)
    model = Model()
    backward_weighted(model, [([(obs, features, 2)], 1.0)])
    assert model.param.grad[2] < 0  # sampled colorless action is trained by RL
