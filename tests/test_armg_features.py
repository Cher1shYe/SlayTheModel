from types import SimpleNamespace

import numpy as np
import torch

from agent import armg
from agent.common import RACT, SCREEN, new_run, sim


def _shop_context():
    return SimpleNamespace(
        screen=SCREEN.SHOP, observe_public=lambda: [0.0] * int(sim.PUBLIC_OBS_DIM),
        legal_actions=lambda: [(int(RACT.BUY_CARD), 0), (int(RACT.BUY_RELIC), 0),
                               (int(RACT.BUY_RELIC), 1), (int(RACT.BUY_POTION), 0),
                               (int(RACT.REMOVE_CARD), 0), (int(RACT.LEAVE_SHOP), 0)],
        deck=[(73, False, 1, 1)], deck_enchantments=[(0, 0, False)],
        offered=[], shop=[(6, 100, False)],
        shop_relics=[(1, 120, False), (2, 140, False)],
        shop_potions=[(1, 30, False)], potions=[], card_grid_kind=0,
        removal_price=75,
    )


def test_shop_candidates_are_public_legal_and_item_specific():
    obs, actions, features = armg.build_candidates(_shop_context())
    assert obs.shape == (armg.ARMG_OBS_DIM,)
    assert features.shape == (len(actions), armg.ARMG_ACTION_DIM)
    assert np.isfinite(obs).all() and np.isfinite(features).all()
    relic_rows = features[1:3, armg._RELIC_OFF:armg._POTION_OFF]
    assert relic_rows.sum(axis=1).tolist() == [1, 1]
    assert not np.array_equal(*relic_rows)
    assert features[3, armg._POTION_OFF:armg._MAP_OFF].sum() == 1
    assert features[0, armg._META_OFF + 4] != features[4, armg._META_OFF + 4]
    model = armg.ArmGScorer()
    scores = model(torch.from_numpy(obs)[None], torch.from_numpy(features)[None])
    assert scores.shape == (1, len(actions))
    scores.sum().backward()
    assert all(p.grad is not None for p in model.parameters())


def test_map_and_ancient_choices_include_destination_and_relic():
    run = new_run(1)
    obs, actions, features = armg.build_candidates(run)
    assert len(actions) == 3
    assert all(features[i, armg._RELIC_OFF:armg._POTION_OFF].sum() == 1
               for i in range(3))
    assert not np.array_equal(features[0, armg._RELIC_OFF:armg._POTION_OFF],
                              features[1, armg._RELIC_OFF:armg._POTION_OFF])
    assert run.step(*actions[0])
    # Some Ancient choices open a reward or card grid before the map.
    from agent.heuristics import run_policy
    for _ in range(30):
        if run.screen == SCREEN.MAP:
            break
        assert run.step(*run_policy(run))
    assert run.screen == SCREEN.MAP
    _, actions, features = armg.build_candidates(run)
    assert all(a[0] == int(RACT.MOVE) for a in actions)
    assert all(row[armg._MAP_OFF:armg._MAP_OFF + armg._MAP_TYPES].sum() == 1 for row in features)


def test_grid_includes_actual_cards_and_selected_state():
    run = new_run(123)
    event = next(i for i in range(sim.event_count()) if sim.event_info(i)[0] == 'ROOM_FULL_OF_CHEESE')
    assert run.begin_event(event)
    assert run.step(int(RACT.EVENT_CHOICE), 0)
    _, actions, before = armg.build_candidates(run)
    assert len(actions) == 8
    assert not np.array_equal(before[0, armg._CARD_OFF:armg._CARD_OFF + CARD_ID_DIM],
                              before[1, armg._CARD_OFF:armg._CARD_OFF + CARD_ID_DIM])
    assert run.step(*actions[0])
    _, actions, after = armg.build_candidates(run)
    index = actions.index((int(RACT.SELECT_GRID_CARD), 0))
    assert after[index, armg._META_OFF + 5] == 1


CARD_ID_DIM = int(sim.CARD_COUNT)


def test_scroll_boxes_encodes_all_three_cards_in_each_bundle():
    run = new_run(123)
    assert run.add_relic(int(sim.RelicId.SCROLL_BOXES))
    _, actions, features = armg.build_candidates(run)
    assert len(actions) == 2
    for row in features:
        for i in range(3):
            start = armg._CARD_OFF + i * int(sim.CARD_FEAT_DIM)
            assert row[start:start + CARD_ID_DIM].sum() == 1


def test_factored_forward_matches_shared_mlp():
    torch.manual_seed(42)
    model = armg.ArmGScorer()
    obs = torch.randn(2, armg.ARMG_OBS_DIM)
    candidates = torch.randn(2, 3, armg.ARMG_ACTION_DIM)
    expanded = obs.unsqueeze(1).expand(-1, 3, -1)
    expected = model.net(torch.cat((expanded, candidates), dim=-1)).squeeze(-1)
    torch.testing.assert_close(model(obs, candidates), expected, rtol=1e-5, atol=1e-6)
