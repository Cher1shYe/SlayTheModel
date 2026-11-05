from types import SimpleNamespace

import numpy as np
import pytest

from agent.armg_relic import ENERGY_RELIC_IDS, relic_action
from agent.common import RACT, SCREEN, new_run, sim


def action(kind, index):
    return (int(kind), index)


def event(**overrides):
    defaults = dict(screen=SCREEN.EVENT, event_name="OROBAS", event_page=0,
                    event_card_selection=0, card_grid_kind=0, event_relics=[])
    return SimpleNamespace(**(defaults | overrides))


def shop(**overrides):
    defaults = dict(screen=SCREEN.SHOP, card_grid_kind=0, gold=100, shop_relics=[])
    return SimpleNamespace(**(defaults | overrides))


def test_shop_prefers_only_legal_affordable_unsold_relics_and_uses_scores():
    rc = shop(shop_relics=[(1, 80, False), (2, 120, False), (3, 50, True), (4, 90, False)])
    actions = [action(RACT.BUY_CARD, 0), *(action(RACT.BUY_RELIC, i) for i in range(4)),
               action(RACT.LEAVE_SHOP, 0)]
    assert relic_action(rc, actions, np.array([10, 0.1, 9, 10, 0.9, 5])) == action(RACT.BUY_RELIC, 3)
    assert relic_action(rc, actions) == action(RACT.BUY_RELIC, 0)
    assert relic_action(rc, [actions[0], actions[2], actions[3], actions[-1]]) is None
    assert rc.gold == 100  # Selection never charges gold or mutates inventory.


def test_ancient_selects_visible_legal_energy_and_respects_model_ties():
    offers = [int(sim.RelicId.PRISMATIC_GEM), int(sim.RelicId.STORYBOOK), int(sim.RelicId.SOZU)]
    rc = event(event_relics=offers)
    actions = [action(RACT.EVENT_CHOICE, i) for i in range(3)]
    assert relic_action(rc, actions, [0.2, 10, 0.8]) == action(RACT.EVENT_CHOICE, 2)
    assert relic_action(rc, actions[:2]) == action(RACT.EVENT_CHOICE, 0)
    assert relic_action(rc, [actions[1]]) is None
    assert int(sim.RelicId.PUMPKIN_CANDLE) in ENERGY_RELIC_IDS
    assert int(sim.RelicId.SNECKO_EYE) not in ENERGY_RELIC_IDS  # draw, not an energy relic


@pytest.mark.parametrize("override", [
    {"event_name": "WELLSPRING"}, {"event_page": 1},
    {"event_card_selection": 1}, {"card_grid_kind": 4},
])
def test_event_override_is_limited_to_ancient_offer_page(override):
    rc = event(event_relics=[int(sim.RelicId.SOZU)], **override)
    assert relic_action(rc, [action(RACT.EVENT_CHOICE, 0)]) is None


def test_grid_or_absent_offer_does_not_force_action():
    assert relic_action(shop(card_grid_kind=5, shop_relics=[(1, 1, False)]),
                        [action(RACT.BUY_RELIC, 0)]) is None
    assert relic_action(event(event_relics=[0]), [action(RACT.EVENT_CHOICE, 0)]) is None
    with pytest.raises(ValueError):
        relic_action(shop(), [action(RACT.LEAVE_SHOP, 0)], [])


def test_actual_ancient_recommendations_are_engine_legal():
    seen = 0
    for seed in range(1, 81):
        rc = new_run(seed)
        for act in range(3):
            if act:
                assert rc.start_act(act)
            legal = [(int(kind), int(slot)) for kind, slot in rc.legal_actions()]
            chosen = relic_action(rc, legal)
            if chosen is not None:
                assert chosen in legal
                assert rc.event_relics[chosen[1]] in ENERGY_RELIC_IDS
                seen += 1
    assert seen > 0
