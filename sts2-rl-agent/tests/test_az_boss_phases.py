"""Native three-form fights and the staged public/reward boundary."""
import json
from dataclasses import replace

import pytest

from sts2_env.az.boss_phases import (
    BossPhaseState, FORM_HP, REWARD_VERSION, KNOCKOUT, DEFEAT, RESPAWN,
    BITE, CLAW, POUNCE, LACERATE, BIG, GROWL,
)
from sts2_env.az.rewards import validate_reward
from sts2_env.cards.ironclad import create_ironclad_starter_deck
from sts2_env.core.combat import CombatState
from sts2_env.core.enums import CardId, PowerId
from sts2_env.core.rng import Rng
from sts2_env.monsters.act3 import create_test_subject


def native_combat(seed):
    world = CombatState(2000, 2000, create_ironclad_starter_deck(), seed,
                        character_id="Ironclad")
    enemy, ai = create_test_subject(Rng(seed))
    world.add_enemy(enemy, ai)
    world.start_combat()
    return world, enemy, ai


def check(state, enemy, ai):
    state.check_public_enemy(enemy, ai.current_move.intents)
    assert enemy.get_power_amount(PowerId.INTANGIBLE) == state.intangible_at_player_boundary
    return state


@pytest.mark.parametrize("seed", [0, 42, 43])
@pytest.mark.parametrize("rounds_per_form", [0, 1, 4, 7])
def test_native_complete_three_form_fight(seed, rounds_per_form):
    world, enemy, ai = native_combat(seed)
    state = BossPhaseState()
    check(state, enemy, ai)
    for phase in range(3):
        for _ in range(rounds_per_form):
            visible = state.intent
            world._execute_enemy_turn()
            state = state.after_move(visible)
            check(state, enemy, ai)
            assert not world.is_over
        assert world.kill_creature(enemy)
        state = state.knock_out()
        check(state, enemy, ai)
        assert enemy not in world.hittable_enemies
        assert world.enemies[0] is enemy
        if phase < 2:
            assert not world.is_over
            progress = state.damage_progress
            visible = state.intent
            world._execute_enemy_turn()
            state = state.after_move(visible)
            check(state, enemy, ai)
            assert state.damage_progress == progress
            assert enemy.current_hp == FORM_HP[phase + 1]
            assert enemy in world.hittable_enemies
        else:
            assert world.is_over and world.player_won
            assert state.terminal_reward("win", world.player.current_hp, 2000) > .8


def second_form():
    state = BossPhaseState().knock_out()
    return state.after_move(state.intent)


def third_form():
    state = second_form().knock_out()
    return state.after_move(state.intent)


def test_finite_budget_continuity_healing_and_no_extra_revival():
    first = BossPhaseState().with_hp(40)
    assert first.damage_progress == pytest.approx(60 / 600)
    assert first.with_hp(100).damage_progress == 0
    second = second_form()
    assert second.damage_progress == pytest.approx(100 / 600)
    for _ in range(10):
        injured = second.with_hp(1)
        assert injured.damage_progress == pytest.approx(299 / 600)
        second = injured.with_hp(200)
        assert second.damage_progress == pytest.approx(100 / 600)
    third = third_form()
    assert third.damage_progress == .5
    assert third.with_hp(150).damage_progress == .75
    done = third.knock_out()
    assert done.damage_progress == 1
    with pytest.raises(ValueError):
        done.knock_out()
    with pytest.raises(ValueError):
        done.after_move((("HEAL", 0, 1), ("BUFF", 0, 1)))
    assert BossPhaseState().events == ()


def test_roundtrip_and_staged_reward_not_admitted_to_old_training():
    state = third_form().with_hp(123)
    assert BossPhaseState.from_dict(json.loads(json.dumps(state.to_dict()))) == state
    assert validate_reward(REWARD_VERSION) == REWARD_VERSION
    from sts2_env.az.encoder import schema_for
    from sts2_env.az.content import SUMMON_CONTENT
    with pytest.raises(ValueError):
        schema_for("observable", REWARD_VERSION, SUMMON_CONTENT)


@pytest.mark.parametrize("events,hp", [
    ((RESPAWN,), 200), ((DEFEAT,), 0), ((CLAW,), 100),
    ((KNOCKOUT, KNOCKOUT), 0), ((KNOCKOUT, BITE), 0),
    ((KNOCKOUT, RESPAWN, KNOCKOUT, RESPAWN, KNOCKOUT), 0),
    ((KNOCKOUT, RESPAWN, KNOCKOUT, RESPAWN, DEFEAT, BITE), 0),
    ((), True), ((), 0), ((), 101), ((), -1), ((), float("nan")),
])
def test_invalid_histories_and_health_rejected(events, hp):
    with pytest.raises(ValueError):
        BossPhaseState(hp, events).validate()


@pytest.mark.parametrize("reason", [None, "time_limit", "win"])
def test_terminal_priority_and_knockout_not_victory(reason):
    if reason == "win":
        state = BossPhaseState().knock_out()
    else:
        state = third_form().knock_out()
    with pytest.raises(ValueError):
        state.terminal_reward(reason, 20, 80)
    assert third_form().terminal_reward(None, 20, 80) == 0
    assert third_form().terminal_reward("time_limit", 20, 80) == 0
    assert third_form().terminal_reward("death", 0, 80) == -.9


def test_public_observer_does_not_read_ai_private_state_or_rng():
    _, enemy, ai = native_combat(42)
    state = BossPhaseState()
    intents = ai.current_move.intents
    ai._current_state_id = "unreadable-private-state"
    ai.state_log = ["private-history-is-not-public-history"]
    check_before = enemy.current_hp
    state.check_public_enemy(enemy, intents)
    assert enemy.current_hp == check_before
    with pytest.raises(ValueError):
        state.check_public_enemy(enemy, intents, ascension=9)
    with pytest.raises(ValueError):
        state.check_public_enemy(enemy, intents, players=2)
    enemy.max_hp = 200
    with pytest.raises(ValueError):
        state.check_public_enemy(enemy, intents)


def test_public_phase_disambiguates_identical_multi_attack_intents():
    second, third = second_form(), third_form()
    assert second.intent == third.intent
    assert second.cursor[2] == CLAW and third.cursor[2] == LACERATE
    assert second.after_move(second.intent).cursor[2] == POUNCE
    assert third.after_move(third.intent).cursor[2] == BIG


def test_native_burn_generation_and_phase3_strength():
    world, enemy, ai = native_combat(7)
    state = BossPhaseState()
    for _ in range(2):
        world.kill_creature(enemy)
        state = state.knock_out()
        intent = state.intent
        world._execute_enemy_turn()
        state = state.after_move(intent)
    for _ in range(2):
        intent = state.intent
        world._execute_enemy_turn()
        state = state.after_move(intent)
    assert state.cursor[2] == GROWL
    burns_before = sum(c.card_id == CardId.BURN for c in world.discard_pile)
    strength_before = enemy.get_power_amount(PowerId.STRENGTH)
    intent = state.intent
    world._execute_enemy_turn()
    state = state.after_move(intent)
    check(state, enemy, ai)
    assert sum(c.card_id == CardId.BURN for c in world.discard_pile) - burns_before == 3
    assert enemy.get_power_amount(PowerId.STRENGTH) - strength_before == 2


@pytest.mark.parametrize("block,expected_wounds", [(0, 3), (10, 2), (20, 1), (30, 0), (999, 0)])
def test_native_phase2_wounds_count_unblocked_hits(block, expected_wounds):
    world, enemy, ai = native_combat(12)
    world.kill_creature(enemy)
    world._execute_enemy_turn()
    state = second_form()
    check(state, enemy, ai)
    world.player.block = block
    before = sum(c.card_id == CardId.WOUND for c in world.discard_pile)
    world._execute_enemy_turn()
    state = state.after_move(state.intent)
    check(state, enemy, ai)
    assert sum(c.card_id == CardId.WOUND for c in world.discard_pile) - before == expected_wounds


def test_native_player_death_during_intermediate_form_is_not_victory():
    world, enemy, ai = native_combat(13)
    world.kill_creature(enemy)
    world._execute_enemy_turn()
    world.player.current_hp = 1
    world._execute_enemy_turn()
    assert world.is_over and not world.player_won
    assert enemy.current_hp == 200
    assert second_form().terminal_reward("death", 0, 80) == pytest.approx(-1 + .2 / 6)


@pytest.mark.parametrize("patch", [{"extra": 1}, {"events": ()}, {"version": "legacy"}])
def test_malformed_serialized_state_rejected(patch):
    data = BossPhaseState().to_dict() | patch
    with pytest.raises(ValueError):
        BossPhaseState.from_dict(data)


@pytest.mark.parametrize("hp", [True, float("inf"), float("nan"), -1])
def test_invalid_terminal_hp_rejected(hp):
    with pytest.raises(ValueError):
        BossPhaseState().terminal_reward("time_limit", hp, 80)


def test_version_rejection_and_immutable_branch_history():
    root = BossPhaseState()
    left = root.after_move(root.intent)
    right = root.knock_out()
    assert root.events == () and left.events == (BITE,) and right.events == (KNOCKOUT,)
    with pytest.raises(ValueError):
        replace(root, version="primary-roster-hp-v5").validate()
