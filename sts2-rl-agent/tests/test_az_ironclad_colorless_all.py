"""Batch 5: all remaining Ironclad/Colorless single-player admissions.

Covers the six-link contract for every new token: native factory, public
observation, dynamic action table, entity encoding, particle/MCTS rebuild and
behavioural parity. Synthetic fixtures only; no training or heldout data.
"""
from dataclasses import replace
import numpy as np
import pytest
import torch

from tests.test_az_content_expansion import arranged, check, particle, play, recipe
from tests.test_az_player_abilities import step
from sts2_env.az.action_candidates import action_candidates
from sts2_env.az.all_cards import (ALLY_ONLY, ALLY_REQUIRED, FACTORIES as ALL_FACTORIES,
                                   RETURNING)
from sts2_env.az.content import EXPANSION_CONTENT
from sts2_env.az.content_expansion import CODEC, descriptor
from sts2_env.az.config import EpisodeLimits
from sts2_env.az.information import observe
from sts2_env.az.rewards import V7

FILLER = ['STRIKE_IRONCLAD'] * 3 + ['DEFEND_IRONCLAD'] * 3


def refresh(env):
    env._information = observe(env.world, env.information.history, env.limits, 80, V7,
                               EXPANSION_CONTENT, *env.public_initial)


def end_turn(env, rng=None):
    rng = rng if rng is not None else np.random.default_rng(5)
    p = particle(env, rng)
    expected = p.step(0)
    env.step(0)
    assert env.information == expected
    return env.information


@pytest.mark.parametrize('name', list(ALL_FACTORIES))
@pytest.mark.parametrize('upgraded', [False, True])
def test_batch5_descriptors_and_codec(name, upgraded):
    token = name + ('+' if upgraded else '')
    card = CODEC._reference(token)
    d = descriptor(token)
    assert (d.cost, d.card_type) == (card.cost, card.card_type.value)
    assert CODEC.capture(CODEC.restore(CODEC.capture(card))) == CODEC.capture(card)
    assert set(card.keywords) <= {o.kind for o in d.effects}
    from sts2_env.az.boss_cards import CODEC as OLD
    with pytest.raises(ValueError):
        OLD.capture(card)


@pytest.mark.parametrize('name', list(ALL_FACTORIES))
def test_batch5_dynamic_mcts_rebuild(name):
    from sts2_env.az.dynamic_search import plan_dynamic
    from sts2_env.az.model_factory import create_transformer
    from sts2_env.az.search_config import DYNAMIC_RISK
    torch.set_num_threads(1); torch.manual_seed(5)
    env = _observed_env([name] * 3 + FILLER, [name], max_turns=3, max_decisions=15)
    model = create_transformer('XS', EXPANSION_CONTENT, V7)
    before = env.information
    a = plan_dynamic(before, model, model_version='engineering', budget=3, search_seed=7,
                     search_version=DYNAMIC_RISK)
    b = plan_dynamic(before, model, model_version='engineering', budget=3, search_seed=7,
                     search_version=DYNAMIC_RISK)
    assert a.root_visits == b.root_visits
    assert a.action in action_candidates(before)[1]
    assert before == env.information


@pytest.mark.parametrize('name', list(ALL_FACTORIES))
@pytest.mark.parametrize('upgraded', [False, True])
def test_batch5_particle_trajectory(name, upgraded):
    env = _observed_env([name] * 3 + FILLER, [name, 'STRIKE_IRONCLAD'], upgraded=upgraded,
                        encounter='setup_bygone_effigy_elite', max_turns=8, max_decisions=40)
    rng = np.random.default_rng(31)
    while not env.outcome().done:
        check(env.information)
        p = particle(env, rng)
        action = int(rng.choice(np.flatnonzero(env.information.legal_mask)))
        predicted = p.step(action)
        env.step(action)
        assert predicted == env.information


def _observed_env(names, hand, *, upgraded=False, encounter='setup_bygone_effigy_elite',
                  max_turns=15, max_decisions=100):
    return arranged(names, hand, upgraded=upgraded, encounter=encounter,
                    limits=EpisodeLimits(max_turns=max_turns, max_decisions=max_decisions))


@pytest.mark.parametrize('name', ALLY_REQUIRED)
def test_ally_required_cards_are_unplayable_single_player(name):
    env = arranged([name] * 3 + FILLER, [name, 'STRIKE_IRONCLAD'])
    slot = env.information.hand.index(name)
    assert not [a for a in action_candidates(env.information)[0] if a.source_ref == f'hand/{slot}']


@pytest.mark.parametrize('name', ALLY_ONLY)
def test_ally_only_skills_are_playable_noops(name):
    env = arranged([name] * 3 + FILLER, [name, 'STRIKE_IRONCLAD'])
    before = env.information
    play(env, name)
    after = env.information
    assert after.player_block == before.player_block
    assert len(after.draw_composition) == len(before.draw_composition)
    assert len(after.hand) == len(before.hand) - 1


def test_feed_kill_raises_max_hp_and_reconstructs():
    env = arranged(['FEED'] * 3 + FILLER, ['FEED'])
    env.world.enemies[0].current_hp = 6
    refresh(env)
    particle(env, np.random.default_rng(4))
    play(env, 'FEED')
    assert env.information.termination_reason == 'win'
    assert env.information.player_max_hp == 83


def test_tank_doubles_powered_attack_damage():
    plain = arranged(['DEFEND_IRONCLAD'] * 3 + ['STRIKE_IRONCLAD'] * 3, ['DEFEND_IRONCLAD'],
                     encounter='setup_fuzzy_wurm_crawler_weak')
    end_turn(plain)
    tanked = arranged(['TANK_CARD'] + ['DEFEND_IRONCLAD'] * 3 + ['STRIKE_IRONCLAD'] * 2,
                      ['TANK_CARD'], encounter='setup_fuzzy_wurm_crawler_weak')
    play(tanked, 'TANK_CARD')
    end_turn(tanked)
    assert plain.information.player_hp - tanked.information.player_hp == 4
    with pytest.raises(ValueError):
        replace(tanked.information, player_abilities=(('TANK', 2),)).validate()


def test_gold_axe_counts_prior_plays_and_gang_up_is_flat():
    env = arranged(['GOLD_AXE'] + ['STRIKE_IRONCLAD'] * 2 + ['DEFEND_IRONCLAD'] * 2 + ['BASH'],
                   ['GOLD_AXE', 'STRIKE_IRONCLAD', 'DEFEND_IRONCLAD'])
    play(env, 'STRIKE_IRONCLAD'); play(env, 'DEFEND_IRONCLAD')
    hp = env.information.enemy_hp
    play(env, 'GOLD_AXE')
    assert hp - env.information.enemy_hp == 2
    env = arranged(['GANG_UP'] * 3 + FILLER, ['GANG_UP'])
    hp = env.information.enemy_hp
    play(env, 'GANG_UP')
    assert hp - env.information.enemy_hp == 5


def test_corruption_makes_skills_free_and_exhausts_them():
    env = arranged(['CORRUPTION_CARD'] + ['DEFEND_IRONCLAD'] * 2 + FILLER,
                   ['CORRUPTION_CARD', 'DEFEND_IRONCLAD'])
    play(env, 'CORRUPTION_CARD')
    energy = env.information.energy
    play(env, 'DEFEND_IRONCLAD')
    assert env.information.energy == energy
    assert env.information.exhaust.count('DEFEND_IRONCLAD') == 1
    assert dict(env.information.player_abilities)['CORRUPTION'] == 1


@pytest.mark.parametrize('name', sorted(RETURNING))
def test_return_to_hand_before_next_draw(name):
    env = arranged([name] * 2 + FILLER, [name, 'STRIKE_IRONCLAD'])
    play(env, name)
    info = end_turn(env)
    assert name in info.hand
    particle(env, np.random.default_rng(8))


def test_knockdown_status_lifecycle_and_rebuild():
    env = arranged(['KNOCKDOWN'] * 3 + FILLER, ['KNOCKDOWN'])
    play(env, 'KNOCKDOWN')
    assert (0, 'KNOCKDOWN', 2) in env.information.basic_statuses
    particle(env, np.random.default_rng(9))
    end_turn(env)
    assert not env.information.basic_statuses


def test_hand_of_greed_damage_and_beacon_power_noop():
    env = arranged(['HAND_OF_GREED'] * 3 + FILLER, ['HAND_OF_GREED'])
    hp = env.information.enemy_hp
    play(env, 'HAND_OF_GREED')
    assert hp - env.information.enemy_hp == 20
    env = arranged(['BEACON_OF_HOPE'] * 3 + FILLER, ['BEACON_OF_HOPE'])
    block = env.information.player_block
    play(env, 'BEACON_OF_HOPE')
    assert env.information.player_block == block
    assert dict(env.information.player_abilities)['BEACON_OF_HOPE'] == 1
    particle(env, np.random.default_rng(10))


def test_scope_still_rejects_deferred_tokens():
    for token in ('ALCHEMIZE', 'ENTROPY', 'JACK_OF_ALL_TRADES', 'SPLASH', 'HIDDEN_GEM'):
        with pytest.raises(ValueError):
            descriptor(token)
        with pytest.raises(ValueError):
            recipe([token] * 3 + FILLER)


def test_nostalgia_returns_first_attack_to_draw_top():
    env = arranged(['NOSTALGIA_CARD'] * 2 + FILLER, ['NOSTALGIA_CARD', 'STRIKE_IRONCLAD'])
    play(env, 'NOSTALGIA_CARD')
    assert dict(env.information.player_abilities)['NOSTALGIA'] == 1
    play(env, 'STRIKE_IRONCLAD')
    assert env.information.known_top == ('STRIKE_IRONCLAD',)
    info = end_turn(env)
    assert 'STRIKE_IRONCLAD' in info.hand and not info.known_top


def test_prolong_defers_current_block_to_next_turn():
    env = arranged(['PROLONG'] * 2 + ['DEFEND_IRONCLAD'] * 2 + ['STRIKE_IRONCLAD'] * 2,
                   ['DEFEND_IRONCLAD', 'DEFEND_IRONCLAD', 'PROLONG'])
    play(env, 'DEFEND_IRONCLAD'); play(env, 'DEFEND_IRONCLAD'); play(env, 'PROLONG')
    assert dict(env.information.player_abilities)['BLOCK_NEXT_TURN'] == 10
    info = end_turn(env)
    assert info.player_block == 10 and not info.player_abilities
    particle(env, np.random.default_rng(12))


def test_gambit_kills_on_unblocked_powered_attack():
    env = arranged(['THE_GAMBIT'] * 2 + ['DEFEND_IRONCLAD'] * 2 + ['STRIKE_IRONCLAD'] * 2,
                   ['THE_GAMBIT'], encounter='setup_shrinker_beetle_weak')
    play(env, 'THE_GAMBIT')
    assert dict(env.information.player_abilities)['THE_GAMBIT'] == 1
    end_turn(env)
    info = end_turn(env)
    assert info.termination_reason == 'death' and info.player_hp == 0


def test_next_turn_block_requires_current_turn_prolong_play():
    env = arranged(['PROLONG'] * 2 + FILLER, ['PROLONG'])
    env._information = replace(env.information, player_abilities=(('BLOCK_NEXT_TURN', 5),))
    with pytest.raises(ValueError):
        env.information.validate()


def test_automation_and_panache_public_counters_roundtrip():
    env = arranged(['AUTOMATION'] * 2 + FILLER, ['AUTOMATION', 'DEFEND_IRONCLAD'])
    play(env, 'AUTOMATION')
    assert dict(env.information.player_abilities)['AUTOMATION'] == 1
    particle(env, np.random.default_rng(13))
    with pytest.raises(ValueError):
        replace(env.information, player_abilities=()).validate()


def test_rolling_boulder_hits_at_turn_start_and_grows():
    env = arranged(['ROLLING_BOULDER'] * 2 + ['DEFEND_IRONCLAD'] * 2 + ['STRIKE_IRONCLAD'] * 2,
                   ['ROLLING_BOULDER'], encounter='setup_bygone_effigy_elite')
    play(env, 'ROLLING_BOULDER')
    assert dict(env.information.player_abilities)['ROLLING_BOULDER'] == 5
    hp = env.information.enemy_hp
    info = end_turn(env)
    assert hp - info.enemy_hp == 5
    assert dict(info.player_abilities)['ROLLING_BOULDER'] == 10


def test_the_bomb_countdown_and_explosion():
    env = arranged(['THE_BOMB_CARD'] * 2 + ['DEFEND_IRONCLAD'] * 2 + ['STRIKE_IRONCLAD'] * 2,
                   ['THE_BOMB_CARD'], encounter='setup_bygone_effigy_elite')
    play(env, 'THE_BOMB_CARD')
    assert dict(env.information.player_abilities)['THE_BOMB'] == 3
    first = end_turn(env)
    assert dict(first.player_abilities)['THE_BOMB'] == 2
    second = end_turn(env)
    assert dict(second.player_abilities)['THE_BOMB'] == 1
    hp = second.enemy_hp
    third = end_turn(env)
    assert hp - third.enemy_hp == 40 and 'THE_BOMB' not in dict(third.player_abilities)


def test_panache_triggers_on_fifth_play_after_application():
    # Panache resets its counter at every turn end, so five zero-cost plays are
    # made in a single turn; the fifth play after the application triggers.
    env = arranged(['PANACHE_CARD'] + ['FINESSE'] * 5,
                   ['PANACHE_CARD'] + ['FINESSE'] * 5, encounter='setup_bygone_effigy_elite')
    play(env, 'PANACHE_CARD')
    hp = env.information.enemy_hp
    for _ in range(5):
        slot = env.information.hand.index('FINESSE')
        assert env.information.legal_mask[1 + slot]
        play(env, 'FINESSE')
    assert hp - env.information.enemy_hp == 10
