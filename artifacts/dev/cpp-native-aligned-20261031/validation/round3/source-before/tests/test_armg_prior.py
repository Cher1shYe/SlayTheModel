import json
from types import SimpleNamespace

import numpy as np
import pytest

from agent.armg_prior import LocalPrior
from agent.common import RACT, SCREEN


def snapshot(tmp_path):
    common = {"bracket": "solo:wr50:standard", "character": "IRONCLAD"}
    cards = [dict(id="AGGRESSION", elo=1700, offered=100, picked=60, upgraded=False),
             dict(id="ANGER", elo=1450, offered=50, picked=20, upgraded=False)]
    for name, rows in (("cards", cards), ("relics", []), ("potions", [])):
        (tmp_path / (name + ".json")).write_text(json.dumps(common | {"rows": rows}), encoding="utf-8")
    community = {"reward_skip_rate": 37.1, "rest_sites": [
        {"id": "HEAL", "pct_low_hp": 60, "pct_high_hp": 13},
        {"id": "SMITH", "pct_low_hp": 39, "pct_high_hp": 82}]}
    (tmp_path/"community.json").write_text(json.dumps(community), encoding="utf-8")
    return tmp_path


def test_card_reward_skip_and_unmatched_actions_all_keep_probability(tmp_path):
    prior = LocalPrior(snapshot(tmp_path))
    assert prior.card_row(1)["id"] == "AGGRESSION"  # local AGGRESSION_CARD
    rc = SimpleNamespace(screen=SCREEN.CARD_REWARD, card_grid_kind=0,
                         offered=[(1, False, 1, 1), (2, False, 2, 1), (3, False, 3, 1)],
                         deck=[(1, False, i, 1) for i in range(15)], act=0)
    actions = [(int(RACT.TAKE_CARD), i) for i in range(3)] + [
        (int(RACT.SKIP_CARD), 0), (int(RACT.SACRIFICE_CARD_REWARD), 0),
        (int(RACT.USE_POTION), 0)]
    q, source = prior.distribution(rc, actions)
    assert source == "card_website"
    assert q.shape == (6,) and np.isclose(q.sum(), 1) and np.all(q > 0)
    assert q[0] > q[1]
    assert q[4] > q[3]  # Pael action and ordinary skip are distinct.


def test_rest_category_weight_not_multiplied_by_upgrade_candidates(tmp_path):
    prior = LocalPrior(snapshot(tmp_path))
    rc = SimpleNamespace(screen=SCREEN.REST, hp=10, max_hp=80)
    actions = [(int(RACT.REST_HEAL), 0)] + [(int(RACT.REST_UPGRADE), i) for i in range(10)]
    q, source = prior.distribution(rc, actions)
    assert source == "rest_website" and q[0] > sum(q[1:])
    assert np.all(q > 0) and np.isclose(q.sum(), 1)


def test_rejects_wrong_cohort_and_forced_decision(tmp_path):
    p = snapshot(tmp_path)
    cards = json.loads((p/"cards.json").read_text(encoding="utf-8"))
    cards["character"] = "SILENT"
    (p/"cards.json").write_text(json.dumps(cards), encoding="utf-8")
    with pytest.raises(ValueError, match="cohort"):
        LocalPrior(p)
