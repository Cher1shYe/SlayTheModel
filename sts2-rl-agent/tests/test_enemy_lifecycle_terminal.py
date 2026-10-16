"""Native terminal rules needed before AZ can admit summons/revival."""
import pytest

from sts2_env.cards.ironclad import create_ironclad_starter_deck
from sts2_env.core.combat import CombatState
from sts2_env.core.enums import PowerId
from sts2_env.core.rng import Rng
from sts2_env.monsters.act1 import create_fogmog
from sts2_env.monsters.act2 import create_decimillipede_segment, apply_decimillipede_segment_room_setup


def fogmog_combat():
    world = CombatState(80, 80, create_ironclad_starter_deck(), 19, character_id="Ironclad")
    boss, ai = create_fogmog(Rng(19))
    world.add_enemy(boss, ai)
    world.start_combat()
    ai.current_move.perform(world)
    return world, boss, world.enemies[1]


@pytest.mark.parametrize("reviving", [False, True])
def test_last_primary_death_wins_with_alive_or_reviving_minion(reviving):
    world, boss, eye = fogmog_combat()
    if reviving:
        world.kill_creature(eye)
        assert eye.powers[PowerId.ILLUSION].is_reviving
        assert not world.is_over
    world.kill_creature(boss)
    assert world.is_over and world.player_won
    assert world.enemies[1] is eye


def test_illusion_revives_in_same_slot_while_primary_alive():
    world, boss, eye = fogmog_combat()
    for _ in range(3):
        assert world.kill_creature(eye)
        assert not world.is_over
        assert eye not in world.hittable_enemies
        ai = world.enemy_ais[eye.combat_id]
        ai.current_move.perform(world)
        ai.on_move_performed()
        assert eye.current_hp == 6 and eye in world.hittable_enemies
        assert world.enemies == [boss, eye]


def test_all_segments_dead_wins_despite_old_reviving_flags():
    world = CombatState(80, 80, create_ironclad_starter_deck(), 20, character_id="Ironclad")
    for i in range(2):
        enemy, ai = create_decimillipede_segment(Rng(20 + i), i)
        world.add_enemy(enemy, ai)
        apply_decimillipede_segment_room_setup(enemy, world)
    world.start_combat()
    first, second = world.enemies
    world.kill_creature(first)
    assert not world.is_over
    assert first.powers[PowerId.REATTACH].is_reviving
    world.kill_creature(second)
    assert world.is_over and world.player_won
    first.powers[PowerId.REATTACH].do_reattach(first)
    assert first.current_hp == 0
