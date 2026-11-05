from types import SimpleNamespace

import numpy as np
import torch

from agent.armg_need import (
    AOE, BLOCK, DRAW, ENERGY, JUNK, SCALING, STRENGTH, SUSTAIN,
    NeedConfig, apply_need_to_logits, need_overlay,
)
from agent.common import CARD_COUNT, RACT, SCREEN, sim


def _card(name):
    for i in range(1, CARD_COUNT):
        if sim.card_name(i) == name:
            return (i, False, i, 1)
    raise AssertionError(name)


def _run(deck, offered, *, act=0, screen=SCREEN.CARD_REWARD, grid=0):
    return SimpleNamespace(deck=[_card(c) for c in deck],
                           offered=[_card(c) for c in offered],
                           screen=screen, card_grid_kind=grid, act=act)


def test_checked_card_names_exist_and_no_sts1_specific_id_silently_misses():
    known = {sim.card_name(i) for i in range(1, CARD_COUNT)}
    assert (AOE | BLOCK | DRAW | ENERGY | JUNK | SCALING | STRENGTH | SUSTAIN) <= known


def test_bonuses_follow_deck_needs_and_act():
    actions = [(int(RACT.TAKE_CARD), 0), (int(RACT.TAKE_CARD), 1),
               (int(RACT.TAKE_CARD), 2), (int(RACT.SKIP_CARD), 0)]
    deck = ["Strike"] * 5 + ["Defend"] * 4 + ["Bash"]
    offers = ["Shrug It Off", "Whirlwind", "Feed"]
    cfg = NeedConfig(balance=0.0)
    a, mask, active = need_overlay(_run(deck, offers), actions, cfg)
    b, _, _ = need_overlay(_run(deck + ["Shrug It Off"] * 4 + ["Whirlwind", "Feed"], offers), actions, cfg)
    third, _, _ = need_overlay(_run(deck, offers, act=2), actions, cfg)
    assert active and mask.all() and a[3] == 0
    assert a[0] > b[0] and a[1] > b[1] and a[2] > b[2]
    assert third[0] > a[0]  # extra defensive priority applies in Act 3 only


def test_only_adverse_unplayable_status_is_filtered_when_skip_is_legal():
    actions = [(int(RACT.TAKE_CARD), 0), (int(RACT.TAKE_CARD), 1),
               (int(RACT.SKIP_CARD), 0)]
    rc = _run(["Strike"], ["Burn", "Anger"])
    _, mask, _ = need_overlay(rc, actions)
    assert mask.tolist() == [False, True, True]
    _, mandatory, _ = need_overlay(rc, actions[:1])
    assert mandatory.tolist() == [True]
    _, disabled, _ = need_overlay(rc, actions, NeedConfig(junk_filter=False))
    assert disabled.all()


def test_non_reward_and_grid_unchanged_and_zscore_keeps_gradients():
    actions = [(int(RACT.TAKE_CARD), 0), (int(RACT.SKIP_CARD), 0)]
    for rc in (_run(["Strike"], ["Anger"], screen=SCREEN.SHOP),
               _run(["Strike"], ["Anger"], grid=1)):
        _, mask, active = need_overlay(rc, actions)
        assert not active and mask.all()
    x = torch.tensor([1.0, 2.0, 3.0], requires_grad=True)
    out = apply_need_to_logits(x, [0.0, 1.0, 0.0], [True, True, False], True)
    assert torch.isneginf(out[2])
    torch.log_softmax(out, dim=0)[1].backward()
    assert torch.isfinite(x.grad).all() and x.grad.abs().sum() > 0


def test_equal_logits_and_nonreward_handle_finite_gradients():
    x = torch.tensor([1.0, 1.0], requires_grad=True)
    out = apply_need_to_logits(x, [0.2, 0.0], [True, True], True)
    assert torch.isfinite(out).all()
    out.sum().backward()
    assert torch.isfinite(x.grad).all()
    y = torch.tensor([1.0, 2.0])
    assert apply_need_to_logits(y, [999, 999], [False, False], False) is y
