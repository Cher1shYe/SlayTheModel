import json
from dataclasses import replace

import pytest

from sts2_env.az.boss_phases import BossPhaseState
from sts2_env.az.boss_reconstruction import BossEnemySnapshot, capture_enemy, create_enemy, restore_enemy
from sts2_env.cards.ironclad import create_ironclad_starter_deck
from sts2_env.core.combat import CombatState
from sts2_env.core.enums import PowerId
from sts2_env.core.rng import Rng
from sts2_env.monsters.act3 import create_test_subject


def original():
    world = CombatState(5000, 5000, create_ironclad_starter_deck(), 42, character_id="Ironclad")
    enemy, ai = create_test_subject(Rng(42))
    world.add_enemy(enemy, ai)
    world.start_combat()
    return world, enemy, ai, BossPhaseState()


def take_round(world, state):
    intent = state.intent
    world._execute_enemy_turn()
    return state.after_move(intent)


def capture(world, state):
    enemy = world.enemies[0]
    return capture_enemy(enemy, world.enemy_ais[enemy.combat_id].current_move.intents, state)


def particle(snapshot, reference):
    # Player fields are a test fixture, not part of enemy reconstruction.
    world = CombatState(reference.player.current_hp, reference.player.max_hp, [], 19, character_id="Ironclad")
    enemy, ai = create_enemy(snapshot, Rng(19))
    world.add_enemy(enemy, ai)
    world.start_combat()
    restore_enemy(enemy, ai, snapshot)
    world.player.block = reference.player.block
    for power, value in reference.player.powers.items():
        world.player.apply_power(power, value.amount)
        world.player.powers[power].skip_next_tick = value.skip_next_tick
    return world, enemy, ai


def public_result(world, state):
    return (capture(world, state), world.player.current_hp, world.player.block,
            tuple(sorted((p.name, v.amount, v.skip_next_tick) for p, v in world.player.powers.items())),
            tuple(c.card_id.name for c in world.discard_pile), world.is_over, world.player_won)


@pytest.mark.parametrize("phase,moves,knocked_out", [
    (phase, moves, knocked_out) for phase in range(3)
    for moves in (0, 1, 2, 5, 12) for knocked_out in (False, True)
    if not (phase == 2 and knocked_out)
])
def test_rebuilt_future_matches_native_across_phases(phase, moves, knocked_out):
    world, enemy, ai, state = original()
    for _ in range(phase):
        world.kill_creature(enemy)
        state = take_round(world, state.knock_out())
    for _ in range(moves):
        state = take_round(world, state)
    if knocked_out:
        world.kill_creature(enemy)
        state = state.knock_out()
    snapshot = capture(world, state)
    snapshot = BossEnemySnapshot.from_dict(json.loads(json.dumps(snapshot.to_dict())))
    left, le, la = particle(snapshot, world)
    right, re, ra = particle(snapshot, world)
    # Past generated cards aren't part of the enemy snapshot. Compare new ones.
    world.discard_pile.clear()
    baseline_right = public_result(right, state)
    original_snapshot = capture(world, state)
    initial_state = state
    for _ in range(8):
        intent = state.intent
        world._execute_enemy_turn()
        left._execute_enemy_turn()
        state = state.after_move(intent)
        assert public_result(left, state) == public_result(world, state)
    assert public_result(right, initial_state) == baseline_right
    assert snapshot == original_snapshot
    assert le is not enemy and le is not re
    assert la is not ai and la is not ra
    for key in le.powers.keys() & re.powers.keys():
        assert le.powers[key] is not re.powers[key]


def test_rebuilt_phase2_knockout_resumes_phase3_not_phase2_again():
    world, enemy, ai, state = original()
    world.kill_creature(enemy)
    state = take_round(world, state.knock_out())
    for _ in range(6):
        state = take_round(world, state)
    world.kill_creature(enemy)
    state = state.knock_out()
    rebuilt, new_enemy, _ = particle(capture(world, state), world)
    state = take_round(rebuilt, state)
    assert new_enemy.max_hp == 300
    assert not new_enemy.has_power(PowerId.ADAPTABLE)
    assert new_enemy.has_power(PowerId.NEMESIS)
    assert capture(rebuilt, state).phase.cursor[0] == 2


def test_source_private_memory_does_not_enter_snapshot():
    world, enemy, ai, state = original()
    expected = capture(world, state)
    intents = ai.current_move.intents
    ai.state_log = ["not public"]
    ai._current_state_id = "not public"
    ai._performed_first_move = True
    assert capture_enemy(enemy, intents, state) == expected


@pytest.mark.parametrize("change", [
    {"version": "old"}, {"block": True}, {"block": -1},
    {"powers": (("WEAK", 1),)}, {"powers": (("ENRAGE", True),)},
    {"powers": (("ENRAGE", 2), ("ADAPTABLE", 1))},
    {"powers": (("ADAPTABLE", 1), ("ENRAGE", 3))},
])
def test_invalid_snapshot_rejected(change):
    world, _, _, state = original()
    with pytest.raises(ValueError):
        replace(capture(world, state), **change).validate()


def test_mismatched_factory_closure_rejected():
    world, _, _, state = original()
    snapshot = capture(world, state)
    enemy, ai = create_test_subject(Rng(1))
    with pytest.raises(ValueError, match="closure"):
        restore_enemy(enemy, ai, snapshot)


def test_final_defeat_rejected_as_actionable_particle():
    world, enemy, _, state = original()
    for _ in range(2):
        world.kill_creature(enemy)
        state = take_round(world, state.knock_out())
    world.kill_creature(enemy)
    state = state.knock_out()
    with pytest.raises(ValueError, match="Terminal"):
        create_enemy(capture(world, state), Rng(0))


@pytest.mark.parametrize("args", [
    {"completed_respawns": True}, {"completed_respawns": 3},
    {"completed_respawns": -1}, {"completed_multi_claws": -1},
    {"completed_multi_claws": 1}, {"completed_respawns": 1, "completed_multi_claws": True},
])
def test_native_factory_reconstruction_memory_is_strict(args):
    with pytest.raises(ValueError):
        create_test_subject(Rng(0), **args)


def _reconstruct_in_worker(record):
    snapshot = BossEnemySnapshot.from_dict(record)
    reference, _, _, _ = original()
    world, _, _ = particle(snapshot, reference)
    state = snapshot.phase
    result = []
    for _ in range(5):
        state = take_round(world, state)
        result.append((capture(world, state).to_dict(), world.player.current_hp,
                       [c.card_id.name for c in world.discard_pile]))
    return result


def test_serial_and_spawned_reconstruction_match():
    from concurrent.futures import ProcessPoolExecutor
    import multiprocessing
    world, enemy, _, state = original()
    records = [capture(world, state).to_dict()]
    for _ in range(2):
        world.kill_creature(enemy)
        state = state.knock_out()
        records.append(capture(world, state).to_dict())
        state = take_round(world, state)
        for _ in range(3):
            state = take_round(world, state)
        records.append(capture(world, state).to_dict())
    expected = [_reconstruct_in_worker(record) for record in records]
    with ProcessPoolExecutor(2, mp_context=multiprocessing.get_context("spawn")) as pool:
        assert list(pool.map(_reconstruct_in_worker, records)) == expected
