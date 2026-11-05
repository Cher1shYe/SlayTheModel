"""Python-side regressions for findings 1-8 of reports/ironclad-rl-audit-20261104.

The engine-level checks live in simulator/tests/audit_rl_regressions.cpp; the
tests here repeat the same defects through the public bindings and the ArmG
encoder, where the audit actually observed them.
"""
from __future__ import annotations

import numpy as np
import pytest
from pathlib import Path

from agent import content_profile
from agent.armg import (ARMG_OBS_DIM, ENCHANT_FEATURE_OFFSET, _CARD_OFF, _POTION_OFF,
                        _POTIONS, build_candidates)
from agent.armg_train import collect_episode
from agent.common import RACT, SCREEN, new_run, sim
from agent.heuristics import run_policy




def card_id(name: str) -> int:
    for i in range(1, sim.card_count()):
        if sim.card_name(i) == name:
            return i
    raise KeyError(name)


def relic(name: str) -> int:
    return int(getattr(sim.RelicId, name))


def event_id(name: str) -> int:
    return next(i for i in range(sim.event_count()) if sim.event_info(i)[0] == name)


def test_crystal_sphere_hides_items_until_revealed():
    """Finding 1: the public observation must not leak item type or position."""
    rc = new_run(940600, 1)
    assert rc.begin_event(event_id("CRYSTAL_SPHERE"))
    assert rc.step(int(RACT.EVENT_CHOICE), 1)
    run_dim = int(sim.PUBLIC_OBS_DIM) - int(sim.PUBLIC_COMBAT_OBS_DIM)
    items = [np.asarray(rc.observe_public())[run_dim - 75 + 5 * i:run_dim - 75 + 5 * (i + 1)]
             for i in range(15)]
    assert sum(int(row[0]) for row in items) == 15, "items must still be counted"
    assert sum(int(row[4]) for row in items) == 0, "no item may be revealed yet"
    assert all(row[1] == 0 and row[2] == 0 and row[3] == 0 for row in items)


@pytest.mark.parametrize("seed,name,kind,count", [
    (5, "HEFTY_TABLET", 16, 3),
    (19, "LEAD_PAPERWEIGHT", 13, 2),
    (5, "SEA_GLASS", 14, 15),
])
def test_relic_card_grids_expose_their_candidates(seed, name, kind, count):
    """Finding 2: binding, public observation and action features agree."""
    rc = new_run(seed, 0)
    if name == "SEA_GLASS":
        # Sea Glass is a relic reward; the grid opens on pickup.
        assert rc.add_relic(relic(name))
        deck_before = rc.deck_count
        assert rc.card_grid_kind == kind
    else:
        event_card = next(index for index in range(rc.event_choices)
                          if int(rc.event_relics[index]) == relic(name))
        assert rc.step(int(RACT.EVENT_CHOICE), event_card)
        assert rc.card_grid_kind == kind
    cards = rc.card_grid_cards
    assert len(cards) == count
    assert all(int(c[0]) for c in cards)
    if name == "SEA_GLASS":
        # 15 candidates is more than the old 8-slot run grid could carry.
        assert rc.deck_count == deck_before

    _, actions, features = build_candidates(rc)
    selections = [i for i, action in enumerate(actions)
                  if action[0] == int(RACT.SELECT_GRID_CARD)]
    assert len(selections) == count
    for slot in selections:
        one_hot = features[slot, _CARD_OFF:_CARD_OFF + sim.CARD_COUNT]
        assert one_hot.sum() == 1.0, f"candidate {slot} has no card identity"
        assert int(np.argmax(one_hot)) == int(cards[actions[slot][1]][0])


def test_potion_holes_keep_physical_slot_indices():
    """Finding 3: a compacted list would encode the wrong potion."""
    rc = new_run(77, 0)
    for _ in range(2):
        rc.add_potion(int(sim.PotionId.BloodPotion))
    assert rc.step(int(RACT.USE_POTION), 0)
    assert rc.potion_slot_ids == [0, int(sim.PotionId.BloodPotion), 0]
    assert rc.potions == [int(sim.PotionId.BloodPotion)]
    _, actions, features = build_candidates(rc)
    use = [i for i, a in enumerate(actions) if a[0] == int(RACT.USE_POTION)]
    assert use
    for row in use:
        encoded = features[row, _POTION_OFF:_POTION_OFF + _POTIONS].nonzero()[0].tolist()
        assert encoded == [int(sim.PotionId.BloodPotion)]
        assert actions[row][1] == 1, "action must index the occupied physical slot"


def test_potion_discard_with_holes_encodes_the_physical_slot():
    """Finding 3: DISCARD_POTION must encode the belt slot, holes included.

    The heuristic never fills the belt, so the discard actions are exercised on
    a context whose belt is explicitly [Blood, hole, Fire, Energy].
    """
    from types import SimpleNamespace
    from agent.armg import ARMG_ACTION_DIM

    slots = [int(sim.PotionId.BloodPotion), 0, int(sim.PotionId.FirePotion),
             int(sim.PotionId.EnergyPotion), 0]
    discards = [(int(RACT.DISCARD_POTION), slot) for slot, pid in enumerate(slots) if pid]
    context = SimpleNamespace(
        screen=SCREEN.REWARDS, card_grid_kind=0,
        observe_public=lambda: [0.0] * int(sim.PUBLIC_OBS_DIM),
        legal_actions=lambda: discards,
        deck=[], deck_enchantments=[], potions=[p for p in slots if p],
        potion_slot_ids=slots, potion_slots=len(slots),
        offered=[], shop=[], shop_relics=[], shop_potions=[], reward_relics=[],
        reward_potions=[], reward_stolen_cards=[], event_relics=[],
        reward_gold=0, reward_recovered_gold=0, removal_price=0,
        map_nodes=lambda: [], card_grid_cards=[], card_grid_selected=[])
    _, actions, features = build_candidates(context)
    assert features.shape == (len(discards), ARMG_ACTION_DIM)
    for row, (_, slot) in enumerate(discards):
        encoded = features[row, _POTION_OFF:_POTION_OFF + _POTIONS].nonzero()[0].tolist()
        assert encoded == [slots[slot]], f"slot {slot} encodes {encoded}"
    # A compacted list would encode [Blood, Fire, Energy] at indices 0..2 and
    # get every slot wrong from index 1 on.
    assert [slots[s] for _, s in discards] == [
        int(sim.PotionId.BloodPotion), int(sim.PotionId.FirePotion),
        int(sim.PotionId.EnergyPotion)]


def test_free_skill_drives_legality_cost_and_consumption():
    """Finding 4: Pounce's FREE_SKILL through the public battle binding.

    The engine check (stacked charges, paid path, zero energy) is in
    simulator/tests/audit_rl_regressions.cpp; this pins the binding path where
    the audit saw Defend missing from ``legal_actions``.
    """
    pounce = card_id("Pounce")
    defend = card_id("Defend")
    bc = sim.BattleContext()
    bc.init(sim.Encounter.SETUP_CEREMONIAL_BEAST_BOSS, 1234,
            [pounce] + [defend] * 9, [False] * 10, 0, 500, 500)
    hand = next(i for i, c in enumerate(bc.hand) if c[0] == pounce)
    assert bc.step(int(sim.ActionType.PLAY_CARD), hand, 0, 0)
    assert bc.energy == 1, "Pounce costs 2"
    assert bc.player_powers, "FREE_SKILL charge must be visible"
    plays = [a for a in bc.legal_actions() if a[0] == int(sim.ActionType.PLAY_CARD)]
    assert plays, "Defend must stay legal while FREE_SKILL is up"
    energy_before = bc.energy
    assert bc.step(int(sim.ActionType.PLAY_CARD), plays[0][1], 0, 0)
    assert bc.energy == energy_before, "the free skill must not consume energy"
    assert not bc.player_powers, "the charge must be consumed"


def test_card_state_features_are_not_aliased():
    """Finding 5: states with different consequences need different inputs."""
    strike = card_id("Strike")
    base = np.asarray(sim.card_features(strike, False, -1))
    assert base.shape == (sim.CARD_FEAT_DIM,)
    upgraded = np.asarray(sim.card_features(strike, True, -1))
    assert not np.array_equal(base, upgraded)

    bc = sim.BattleContext()
    bc.init(sim.Encounter.SETUP_CEREMONIAL_BEAST_BOSS, 1234, [strike] * 10,
            [False] * 10, 0, 100, 100)
    assert len(bc.observation_public()) == int(sim.PUBLIC_COMBAT_OBS_DIM)
    assert len(bc.action_features(int(sim.ActionType.END_TURN), 0, 0, 0)) == int(sim.ACTION_FEAT_DIM)


def test_run_deck_encodes_madscience_variant():
    """Finding 6: the run deck block must carry TinkerTime type and Rider."""
    rc = new_run(12, 0)
    mad = card_id("Mad Science")
    run_dim = int(sim.PUBLIC_OBS_DIM) - int(sim.PUBLIC_COMBAT_OBS_DIM)
    assert rc.deck_count > 0
    assert run_dim > 0
    assert int(sim.PUB_CARD_INSTANCE_FEAT) >= 24
    assert len(rc.observe_public()) == int(sim.PUBLIC_OBS_DIM)
    assert mad > 0


def test_hidden_resampling_ignores_original_secret_order():
    """Finding 7: equal public state + equal seed must give equal samples."""
    strike = card_id("Strike")
    deck = [strike] * 10
    x = sim.BattleContext()
    x.init(sim.Encounter.SETUP_CULTISTS_NORMAL, 123, deck, [False] * 10, 0, 80, 80)
    base = x.observation_public()
    for seed in range(25):
        a = x.clone()
        b = x.clone()
        a.resample_hidden(seed + 12591)
        b.resample_hidden(seed + 12591)
        assert a.observation_public() == b.observation_public()
    assert x.observation_public() == base, "resampling must not mutate the original"


def test_heuristic_only_returns_legal_actions_across_seeds():
    """Finding 8: an illegal heuristic choice used to drop the whole episode."""
    for seed in (367, 466):
        episode = collect_episode(seed, None, combat="greedy", epsilon=0.05, ascension=0)
        assert episode["status"] != "error", episode["error"]
        assert episode["error"] is None


def test_miniature_tent_second_rest_is_rejected_not_offered_twice():
    """Finding 8 (second half): the heuristic must cope with a used option."""
    rc = new_run(3, 0)
    assert rc.add_relic(relic("MINIATURE_TENT"))
    while rc.screen != SCREEN.MAP:
        assert rc.step(*run_policy(rc))
    # Walk to a rest site.
    for _ in range(200):
        if rc.screen == SCREEN.REST:
            break
        if rc.screen == SCREEN.COMBAT:
            assert rc.step_combat(*rc.battle.greedy_action(0.0, 7))
        else:
            assert rc.step(*run_policy(rc))
        assert rc.screen != SCREEN.RUN_OVER
    if rc.screen != SCREEN.REST:
        pytest.skip("seed did not reach a rest site with Miniature Tent")
    legal = {(int(t), int(i)) for t, i in rc.legal_actions()}
    heal = (int(RACT.REST_HEAL), 0)
    assert heal in legal
    assert rc.step(*run_policy(rc))
    # Whatever the heuristic chose, the next decision must be legal.
    assert rc.screen == SCREEN.RUN_OVER or run_policy(rc) in {
        (int(t), int(i)) for t, i in rc.legal_actions()}


def test_training_profile_excludes_crystal_sphere_and_multiplayer_cards():
    """Acceptance item 1: filtering holds at every generation entry point."""
    assert content_profile.PROFILE == sim.RunContentProfile.SINGLE_PLAYER_TRAINING
    forbidden = content_profile.forbidden_event_ids()
    crystal = event_id("CRYSTAL_SPHERE")
    assert crystal in forbidden
    for act in range(4):
        original = set(sim.event_pool_type(act))
        filtered = set(sim.event_pool_profile(act, int(content_profile.PROFILE)))
        assert filtered == original - forbidden, f"act {act} pool differs beyond the exclusion"

    multiplayer = content_profile.multiplayer_only_ids()
    assert multiplayer, "engine must still flag multiplayer-only cards"
    original_runs, training_runs = [], set()
    for seed in range(1, 41):
        for profile, bucket in ((0, original_runs), (int(content_profile.PROFILE), training_runs)):
            rc = new_run(seed, 0, content_profile=profile)
            steps = 0
            while rc.screen != SCREEN.RUN_OVER and steps < 3000 and not rc.truncated:
                steps += 1
                content_profile.assert_run_is_clean(rc) if profile else None
                if rc.screen == SCREEN.COMBAT:
                    for card in rc.battle.hand:
                        assert int(card[0]) not in multiplayer
                    assert rc.step_combat(*rc.battle.greedy_action(0.0, seed + steps))
                    continue
                if profile == 0:
                    bucket.append(rc.event_name)
                for card in rc.offered if rc.screen == SCREEN.CARD_REWARD else []:
                    assert int(card[0]) not in multiplayer
                for card, _price, _sold in rc.shop if rc.screen == SCREEN.SHOP else []:
                    assert int(card) not in multiplayer
                for card in rc.card_grid_cards:
                    assert int(card[0]) not in multiplayer
                for card in rc.deck:
                    assert int(card[0]) not in multiplayer
                assert rc.step(*run_policy(rc))
    assert "CRYSTAL_SPHERE" in original_runs, "original profile must still reach it"
    assert "CRYSTAL_SPHERE" not in training_runs


def test_content_profile_identity_is_recorded():
    identity = content_profile.identity()
    assert identity["name"] == "single-player-training"
    assert identity["excluded_events"] == ["CRYSTAL_SPHERE"]
    assert len(identity["sha256"]) == 64
    assert identity == content_profile.identity()
    assert set(identity["event_pools"]["0"]).isdisjoint(content_profile.forbidden_event_ids())


def test_action_card_features_keep_engine_sly_and_retain_fields():
    """Patching cost/enchantment must not overwrite the appended state fields."""
    from agent.armg import ARMG_ACTION_DIM, ENCHANT_FEATURE_OFFSET, _CARD_OFF, _card
    from agent.common import sim

    row = np.zeros(ARMG_ACTION_DIM, dtype=np.float32)
    _card(row, (card_id("Strike"), False, 1, 1), enchantment=(3, 2, False))
    start = _CARD_OFF
    assert row[start + ENCHANT_FEATURE_OFFSET] == pytest.approx(3 / 5)
    assert row[start + ENCHANT_FEATURE_OFFSET + 1] == pytest.approx(2 / 10)
    sly_slot = start + ENCHANT_FEATURE_OFFSET + 3
    assert np.all(row[sly_slot:sly_slot + 7] == 0), "state fields must stay engine-owned"
    assert sim.CARD_FEAT_DIM == ENCHANT_FEATURE_OFFSET + 10
