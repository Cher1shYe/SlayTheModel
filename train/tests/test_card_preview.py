"""Checklist A1: displayed (modified) card damage/block in the public observation.

The native-rule derivations live in sim/tests/card_preview_native.cpp. Here:
* the values reach PublicState/encode correctly (only for Hand/Play cards that have the
  variable, explicit unknown for unported calculated variables);
* across random simulator games, the preview of plain single-hit cards equals what the
  engine actually deals / grants when the card is played (end-to-end consistency);
* display values never change the action identity of a card.
"""
import random

import numpy as np
import pytest

from spire_rl import public_obs as p
from spire_rl.sim import sim

DAMAGE_FIRST = {  # one DamageCmd on the target(s) before any other effect that changes HP/block
    "CARD.STRIKE_IRONCLAD", "CARD.BASH", "CARD.ANGER", "CARD.POMMEL_STRIKE", "CARD.HEADBUTT", "CARD.IRON_WAVE",
    "CARD.BODY_SLAM", "CARD.BULLY", "CARD.REND", "CARD.ASHEN_STRIKE", "CARD.MIND_BLAST", "CARD.GOLD_AXE",
    "CARD.UPPERCUT", "CARD.THUNDERCLAP", "CARD.BLUDGEON", "CARD.CLASH", "CARD.HEMOKINESIS",
}
BLOCK_FIRST = {"CARD.DEFEND_IRONCLAD", "CARD.SHRUG_IT_OFF", "CARD.IMPERVIOUS", "CARD.FLAME_BARRIER"}
# Enemy powers that change neither incoming damage outside the ModifyDamage hooks nor block afterwards.
QUIET_ENEMY_POWERS = {"POWER.VULNERABLE_POWER", "POWER.WEAK_POWER", "POWER.STRENGTH_POWER", "POWER.RITUAL_POWER"}
# Player powers that add block on card play (would break the block measurement).
NOISY_PLAYER_POWERS = {"POWER.RAGE_POWER", "POWER.FEEL_NO_PAIN_POWER", "POWER.JUGGERNAUT_POWER"}


def first_combat():
    rc = sim.RunContext(); rc.init_seed("PARITY0001", 10)
    for _ in range(12):
        if rc.screen == sim.RunScreen.COMBAT:
            return rc
        s = p.from_simulator(rc)
        p.step_simulator(rc, s, next((i for i, a in enumerate(s.actions)
                                      if a.key.kind == "neow_relic" and a.key.args[0] == "GOLDEN_PEARL"), 0))
    raise AssertionError("no combat")


def test_hand_cards_carry_display_values_only_for_their_variables():
    state = p.from_simulator(first_combat())
    hand = [c for c in state.facts["cards"] if c["pile"] == "hand"]
    assert hand
    for card in hand:
        names = {n for n, _ in card["dynamicVars"]}
        assert (card["displayDamage"] is not None) == bool(names & {"Damage", "CalculatedDamage"}), card["modelId"]
        assert (card["displayBlock"] is not None) == bool(names & {"Block", "CalculatedBlock"}), card["modelId"]
        if card["displayDamage"] is not None:
            assert len(card["displayDamageVs"]) == len(state.facts["enemies"])
        if card["modelId"] == "CARD.STRIKE_IRONCLAD":
            assert card["displayDamage"] == 6 and card["displayDamageVs"] == (6,) * len(state.facts["enemies"])
    for card in state.facts["cards"]:
        if card["pile"] not in ("hand", "play"):
            assert card["displayDamage"] is None and card["displayBlock"] is None and card["displayDamageVs"] is None


def test_encoded_block_and_unsupported_flag():
    state = p.from_simulator(first_combat())
    obs = p.encode(state)
    hand_rows = [i for i, k in enumerate(obs.kind) if k == 16]
    strike = next(i for i in hand_rows if obs.num[i, 0] == 0 and obs.num[i, 544] == 1 and obs.num[i, 545] == pytest.approx(6 / 30))
    assert obs.num[strike, 548] == 0
    assert obs.num[strike, 552] == 1 and obs.num[strike, 553] == pytest.approx(6 / 30)
    card = dict(next(c for c in state.facts["cards"] if c["pile"] == "hand"))
    card.update(displayDamage=None, displayBlock=None, displayDamageVs=None, previewUnsupported=True)
    row = np.zeros(p.NUM, np.float32)
    p._fill_card_row(card, row)
    assert row[548] == 1 and row[544] == 0 and row[546] == 0 and not row[552:564].any()


def test_unported_calculated_variable_is_explicit_unknown():
    raw = {"previewDamage": p.PREVIEW_UNSUPPORTED, "previewBlock": 0, "previewDamageVs": [p.PREVIEW_UNSUPPORTED]}
    result = {"pile": "hand", "dynamicVars": (("CalculatedDamage", 1), ("CalculationBase", 1), ("ExtraDamage", 1))}
    p._display_values(result, raw, "simulator", "test")
    assert result["previewUnsupported"] and result["displayDamage"] is None and result["displayDamageVs"] is None


def test_native_hand_card_without_preview_is_rejected_unless_legacy():
    result = {"pile": "hand", "dynamicVars": (("Damage", 6),)}
    p._display_values(result, {}, "native", "test")
    assert result["displayDamage"] == p.MISSING_PREVIEW
    with pytest.raises(p.ObservationCoverageError):
        p._display_values(dict(result), {}, "simulator", "test")


def test_display_values_do_not_change_card_identity():
    state = p.from_simulator(first_combat())
    card = next(c for c in state.facts["cards"] if c["pile"] == "hand" and c["displayDamage"] is not None)
    changed = dict(card, displayDamage=card["displayDamage"] + 5, displayDamageVs=None)
    assert p._card_text(card) == p._card_text(changed)


def _enemy_by_order(facts, order):
    return next((e for e in facts["enemies"] if e["order"] == order), None)


def test_preview_matches_engine_damage_and_block_in_random_games():
    rng = random.Random(23)
    checked = {"damage": 0, "block": 0, "modified": 0}
    for seed in range(60):
        rc = sim.RunContext(); rc.init(5100 + seed, 10)
        for _ in range(1500):
            if rc.is_terminal:
                break
            s = p.from_simulator(rc)
            if not s.actions:
                break
            if s.facts["combat"] is not None and s.facts["screen"] == "combat":
                player_powers = {ident for ident, *_ in s.facts["powers"]}
                for index, action in enumerate(s.actions):
                    if action.key.kind != "play":
                        continue
                    card = next(c for c in s.facts["cards"] if c["pile"] == "hand" and c["position"] == action.key.args[0][0])
                    target = action.key.args[1][0] if len(action.key.args) > 1 and action.key.args[1] is not None else None
                    if card["replay"] or card["enchantedReplay"]:
                        continue  # played more than once (e.g. Glam): the preview is per play
                    if card["modelId"] in DAMAGE_FIRST and card["displayDamageVs"] is not None:
                        orders = [target] if target is not None else [e["order"] for e in s.facts["enemies"] if e["hittable"]]
                        before = {o: _enemy_by_order(s.facts, o) for o in orders}
                        if any(e is None or not {pw[0] for pw in e["powers"]} <= QUIET_ENEMY_POWERS for e in before.values()):
                            continue
                        copy = rc.clone()
                        p.step_simulator(copy, s, index)
                        after = p.from_simulator(copy).facts if not copy.is_terminal and copy.screen == sim.RunScreen.COMBAT else None
                        if after is None or len(after["enemies"]) != len(s.facts["enemies"]):
                            continue
                        for o, e in before.items():
                            a = _enemy_by_order(after, o)
                            if a is None or not a["alive"] or a["modelId"] != e["modelId"]:
                                continue
                            lost = (e["hp"] + e["block"]) - (a["hp"] + a["block"])
                            assert lost == card["displayDamageVs"][o], (seed, card["modelId"], o, card["displayDamageVs"], lost)
                            checked["damage"] += 1
                            checked["modified"] += card["displayDamageVs"][o] != card["damage"]
                    if card["modelId"] in BLOCK_FIRST and card["displayBlock"] is not None and not player_powers & NOISY_PLAYER_POWERS:
                        copy = rc.clone()
                        p.step_simulator(copy, s, index)
                        if copy.is_terminal or copy.screen != sim.RunScreen.COMBAT:
                            continue
                        gained = p.from_simulator(copy).facts["player"]["block"] - s.facts["player"]["block"]
                        assert gained == card["displayBlock"], (seed, card["modelId"], card["displayBlock"], gained)
                        checked["block"] += 1
            plays = [i for i, a in enumerate(s.actions) if a.key.kind == "play"]
            pool = plays if plays and rng.random() < 0.85 else range(len(s.actions))
            p.step_simulator(rc, s, rng.choice(list(pool)))
    # Enough real comparisons, including some where modifiers changed the printed number.
    assert checked["damage"] > 300 and checked["block"] > 100 and checked["modified"] > 30, checked
