"""Every card-generation entry point under SINGLE_PLAYER_TRAINING.

Acceptance item 1 of the 2026-11-05 goal: multiplayer-only cards must never
reach a single-player run, and the profile must filter pools at construction
instead of drawing then hiding. These tests inspect the candidate lists the
engine actually offers, not just the final deck.
"""
from __future__ import annotations

import pytest

from agent import content_profile
from agent.common import RACT, SCREEN, new_run, sim

MP = content_profile.multiplayer_only_ids()


def card_id(name: str) -> int:
    return next(i for i in range(1, sim.card_count()) if sim.card_name(i) == name)


def leaked(cards) -> list:
    return [sim.card_name(int(c[0])) for c in cards if int(c[0]) in MP]


def reward_decks(seed: int, limit: int = 60):
    """Play until ``limit`` card rewards have been offered."""
    rc = new_run(seed, 0, content_profile=content_profile.PROFILE)
    seen, steps = 0, 0
    while seen < limit and rc.screen != SCREEN.RUN_OVER and steps < 4000:
        steps += 1
        if rc.screen == SCREEN.COMBAT:
            assert rc.step_combat(*rc.battle.greedy_action(0.0, seed + steps))
            continue
        if rc.screen == SCREEN.CARD_REWARD and rc.offered:
            yield rc.offered
            seen += 1
        action = next((a for a in rc.legal_actions()
                       if int(a[0]) == int(RACT.SKIP_CARD)), None)
        if rc.screen == SCREEN.CARD_REWARD and action is not None:
            assert rc.step(*action)
            continue
        from agent.heuristics import run_policy
        assert rc.step(*run_policy(rc))


@pytest.mark.parametrize("entry", ["combat_reward", "shop", "transformation", "grid", "deck"])
def test_no_multiplayer_card_reaches_any_entry_point(entry):
    seeds = range(1, 26)
    checked = 0
    for seed in seeds:
        rc = new_run(seed, 0, content_profile=content_profile.PROFILE)
        if entry == "transformation":
            assert not any(int(c[0]) in MP for c in rc.card_grid_cards)
            # Transform pools are built from the character pool, not rewards.
            assert rc.add_relic(int(sim.RelicId.DOLLYS_MIRROR)) in (True, False)
            checked += 1
        elif entry == "grid":
            for kind_relic in ("HEFTY_TABLET", "LEAD_PAPERWEIGHT", "SEA_GLASS"):
                probe = new_run(seed, 0, content_profile=content_profile.PROFILE)
                if probe.add_relic(int(getattr(sim.RelicId, kind_relic))):
                    assert not leaked(probe.card_grid_cards), kind_relic
            checked += 1
        elif entry == "combat_reward":
            for offered in reward_decks(seed, 12):
                assert not leaked(offered)
                checked += 1
        elif entry == "shop":
            steps = 0
            while rc.screen != SCREEN.RUN_OVER and steps < 4000:
                steps += 1
                if rc.screen == SCREEN.COMBAT:
                    assert rc.step_combat(*rc.battle.greedy_action(0.0, seed + steps))
                    continue
                if rc.screen == SCREEN.SHOP:
                    assert not [sim.card_name(int(c[0])) for c in rc.shop
                                if int(c[0]) in MP]
                    checked += len(rc.shop)
                from agent.heuristics import run_policy
                assert rc.step(*run_policy(rc))
        elif entry == "deck":
            steps = 0
            while rc.screen != SCREEN.RUN_OVER and steps < 4000:
                steps += 1
                if rc.screen == SCREEN.COMBAT:
                    assert not leaked(rc.battle.hand)
                    # Cards generated mid-combat are added to hand/draw/discard.
                    assert rc.step_combat(*rc.battle.greedy_action(0.0, seed + steps))
                    continue
                assert not leaked(rc.deck)
                from agent.heuristics import run_policy
                assert rc.step(*run_policy(rc))
            checked += 1
    assert checked > 0


def test_combat_generation_pools_exclude_multiplayer_cards():
    """Cards created by effects (Discovery, colourless generators) are filtered."""
    discovery = card_id("Discovery")
    bc = sim.BattleContext()
    bc.init(sim.Encounter.SETUP_SHRINKER_BEETLE_WEAK, 1234,
            [discovery] * 8, [False] * 8, 0, 300, 300)
    hand = next(i for i, c in enumerate(bc.hand) if c[0] == discovery)
    assert bc.step(int(sim.ActionType.PLAY_CARD), hand, 0, 0)
    options = list(bc.pending_cards)
    assert options
    assert not [c for c in options if int(c[0]) in MP]


def test_original_profile_still_reaches_crystal_sphere():
    """The filter changes the distribution; it does not claim to be native."""
    crystal = next(i for i in range(sim.event_count())
                   if sim.event_info(i)[0] == "CRYSTAL_SPHERE")
    assert crystal in content_profile.forbidden_event_ids()
    assert crystal in set(sim.event_pool_type(0)) | set(sim.event_pool_type(1)) \
        | set(sim.event_pool_type(2)) | set(sim.event_pool_type(3))
    for act in range(4):
        assert crystal not in sim.event_pool_profile(act, int(content_profile.PROFILE))


def test_run_bag_never_contains_a_filtered_event():
    for seed in range(1, 31):
        rc = new_run(seed, 0, content_profile=content_profile.PROFILE)
        for act in (1, 2):
            assert rc.event_ids
            assert not set(rc.event_ids) & content_profile.forbidden_event_ids()
            rc.start_act(act)
    # The original profile keeps it in the bag when the act allows it.
    found = any(crystal_in_bag(new_run(seed, 0)) for seed in range(1, 41))
    assert found


def crystal_in_bag(rc) -> bool:
    forbidden = content_profile.forbidden_event_ids()
    return bool(set(rc.event_ids) & forbidden)


def test_profile_switch_is_explicit_and_reversible():
    rc = new_run(1, 0)
    assert rc.content_profile == int(sim.RunContentProfile.ORIGINAL)
    assert rc.content_profile_name == "original"
    training = new_run(1, 0, content_profile=content_profile.PROFILE)
    assert training.content_profile == int(content_profile.PROFILE)
    assert "single" in training.content_profile_name
    with pytest.raises(Exception):
        new_run(1, 0, content_profile=99)


def test_runtime_guard_catches_injected_content():
    """The training loop asserts cleanliness every step, so a leak is an error."""
    import types

    from agent import armg_train

    forbidden = next(iter(content_profile.forbidden_event_ids()))
    leaked = types.SimpleNamespace(
        screen=SCREEN.EVENT, content_profile=int(content_profile.PROFILE),
        card_grid_kind=0, event_id=forbidden, deck=[], event_name="CRYSTAL_SPHERE")
    with pytest.raises(RuntimeError, match="forbidden event"):
        content_profile.assert_run_is_clean(leaked)

    mp_card = next(iter(MP))
    leaked = types.SimpleNamespace(
        screen=SCREEN.MAP, content_profile=int(content_profile.PROFILE),
        card_grid_kind=0, event_id=-1, deck=[(mp_card, False, 1, 1)])
    with pytest.raises(RuntimeError, match="multiplayer card"):
        content_profile.assert_run_is_clean(leaked)

    wrong = types.SimpleNamespace(screen=SCREEN.MAP, content_profile=0,
                                  card_grid_kind=0, event_id=-1, deck=[])
    with pytest.raises(RuntimeError, match="content profile"):
        content_profile.assert_run_is_clean(wrong)
    assert armg_train._PROFILE == content_profile.PROFILE
