"""Parity tests for Defect orb-card and frost hooks."""

import sts2_env.powers  # noqa: F401

from sts2_env.cards.defect import (
    create_defect_starter_deck,
    make_ball_lightning,
    make_barrage,
    make_beam_cell,
    make_capacitor,
    make_chaos,
    make_chill,
    make_compile_driver,
    make_defragment,
    make_glacier,
    make_hailstorm,
    make_multi_cast,
    make_strike_defect,
)


BALL_LIGHTNING_DAMAGE = 7
BALL_LIGHTNING_UPGRADED_DAMAGE = 10
BARRAGE_DAMAGE = 5
BARRAGE_UPGRADED_DAMAGE = 7
BARRAGE_TEST_ORB_COUNT = 2
BEAM_CELL_DAMAGE = 3
BEAM_CELL_UPGRADED_DAMAGE = 4
BEAM_CELL_VULNERABLE = 1
BEAM_CELL_UPGRADED_VULNERABLE = 2
COMPILE_DRIVER_DAMAGE = 7
COMPILE_DRIVER_UPGRADED_DAMAGE = 10
from sts2_env.core.combat import CombatState
from sts2_env.core.enums import OrbType, PowerId
from sts2_env.core.rng import Rng
from sts2_env.monsters.act1_weak import create_shrinker_beetle


def _make_combat() -> CombatState:
    combat = CombatState(
        player_hp=75,
        player_max_hp=75,
        deck=create_defect_starter_deck(),
        rng_seed=42,
        character_id="Defect",
    )
    creature, ai = create_shrinker_beetle(Rng(42))
    combat.add_enemy(creature, ai)
    combat.start_combat()
    return combat


class TestDefectOrbCardAndFrostHookParity:
    def test_ball_lightning_deals_damage_and_channels_lightning(self):
        """Matches BallLightning.cs: attack target, then channel one Lightning orb."""
        combat = _make_combat()
        enemy = combat.enemies[0]
        starting_hp = enemy.current_hp
        combat.hand = [make_ball_lightning()]
        combat.energy = 1

        assert combat.play_card(0, 0)
        assert enemy.current_hp == starting_hp - BALL_LIGHTNING_DAMAGE
        assert len(combat.orb_queue.orbs) == 1
        assert combat.orb_queue.orbs[0].orb_type == OrbType.LIGHTNING

    def test_upgraded_ball_lightning_deals_ten_damage_and_still_channels_lightning(self):
        """Matches BallLightning.cs: upgrade changes Damage only."""
        combat = _make_combat()
        enemy = combat.enemies[0]
        starting_hp = enemy.current_hp
        combat.hand = [make_ball_lightning(upgraded=True)]
        combat.energy = 1

        assert combat.play_card(0, 0)
        assert enemy.current_hp == starting_hp - BALL_LIGHTNING_UPGRADED_DAMAGE
        assert [orb.orb_type for orb in combat.orb_queue.orbs] == [OrbType.LIGHTNING]

    def test_barrage_hits_once_per_current_orb(self):
        """Matches Barrage.cs: hit count equals current orb count."""
        combat = _make_combat()
        enemy = combat.enemies[0]
        starting_hp = enemy.current_hp
        combat.channel_orb(combat.player, "LIGHTNING")
        combat.channel_orb(combat.player, "FROST")
        combat.hand = [make_barrage()]
        combat.energy = 1

        assert combat.play_card(0, 0)
        assert enemy.current_hp == starting_hp - BARRAGE_DAMAGE * BARRAGE_TEST_ORB_COUNT

    def test_upgraded_barrage_hits_current_orb_count_with_seven_damage(self):
        """Matches Barrage.cs: upgrade changes Damage only."""
        combat = _make_combat()
        enemy = combat.enemies[0]
        starting_hp = enemy.current_hp
        combat.channel_orb(combat.player, "LIGHTNING")
        combat.channel_orb(combat.player, "FROST")
        combat.hand = [make_barrage(upgraded=True)]
        combat.energy = 1

        assert combat.play_card(0, 0)
        assert enemy.current_hp == starting_hp - BARRAGE_UPGRADED_DAMAGE * BARRAGE_TEST_ORB_COUNT

    def test_beam_cell_damage_and_vulnerable_match_reference_values(self):
        """Matches BeamCell.cs: damage target, then apply Vulnerable."""
        combat = _make_combat()
        enemy = combat.enemies[0]
        starting_hp = enemy.current_hp
        combat.hand = [make_beam_cell()]
        combat.energy = 0

        assert combat.play_card(0, 0)
        assert enemy.current_hp == starting_hp - BEAM_CELL_DAMAGE
        assert enemy.get_power_amount(PowerId.VULNERABLE) == BEAM_CELL_VULNERABLE

    def test_upgraded_beam_cell_upgrades_damage_and_vulnerable(self):
        """Matches BeamCell.cs: upgrade changes Damage and Vulnerable."""
        combat = _make_combat()
        enemy = combat.enemies[0]
        starting_hp = enemy.current_hp
        combat.hand = [make_beam_cell(upgraded=True)]
        combat.energy = 0

        assert combat.play_card(0, 0)
        assert enemy.current_hp == starting_hp - BEAM_CELL_UPGRADED_DAMAGE
        assert enemy.get_power_amount(PowerId.VULNERABLE) == BEAM_CELL_UPGRADED_VULNERABLE

    def test_capacitor_adds_orb_slots_up_to_cap(self):
        """Matches Capacitor.cs: add Repeat slots, clamped by queue max capacity."""
        combat = _make_combat()
        combat.orb_queue.capacity = 9
        combat.hand = [make_capacitor()]
        combat.energy = 1

        assert combat.play_card(0)
        assert combat.orb_queue.capacity == 10

    def test_upgraded_capacitor_adds_three_orb_slots(self):
        """Matches Capacitor.cs OnUpgrade: Repeat increases from 2 to 3."""
        combat = _make_combat()
        combat.orb_queue.capacity = 7
        combat.hand = [make_capacitor(upgraded=True)]
        combat.energy = 1

        assert combat.play_card(0)

        assert combat.orb_queue.capacity == 10

    def test_chaos_channels_random_orb_for_each_repeat(self):
        """Matches Chaos.cs: channel random orb Repeat times."""
        combat = _make_combat()
        card = make_chaos()
        card.effect_vars["repeat"] = 2
        combat.hand = [card]
        combat.energy = 1

        assert combat.play_card(0)
        assert len(combat.orb_queue.orbs) == 2
        assert {orb.orb_type for orb in combat.orb_queue.orbs}.issubset(
            {OrbType.LIGHTNING, OrbType.FROST, OrbType.DARK, OrbType.PLASMA, OrbType.GLASS}
        )

    def test_chill_channels_frost_once_per_hittable_enemy(self):
        """Matches Chill.cs: channel one Frost per current hittable enemy."""
        combat = _make_combat()
        second, second_ai = create_shrinker_beetle(Rng(43))
        combat.add_enemy(second, second_ai)
        combat.hand = [make_chill()]
        combat.energy = 0

        assert combat.play_card(0)
        assert len(combat.orb_queue.orbs) == 2
        assert all(orb.orb_type == OrbType.FROST for orb in combat.orb_queue.orbs)

    def test_compile_driver_draws_for_distinct_orb_types_only(self):
        """Matches CompileDriver.cs: draw count uses distinct orb ids, not total orb count."""
        combat = _make_combat()
        enemy = combat.enemies[0]
        draw_a = make_strike_defect()
        draw_b = make_strike_defect()
        draw_c = make_strike_defect()
        combat.channel_orb(combat.player, "LIGHTNING")
        combat.channel_orb(combat.player, "LIGHTNING")
        combat.channel_orb(combat.player, "FROST")
        combat.hand = [make_compile_driver()]
        combat.draw_pile = [draw_a, draw_b, draw_c]
        combat.energy = 1

        assert combat.play_card(0, 0)
        assert enemy.current_hp == enemy.max_hp - COMPILE_DRIVER_DAMAGE
        assert combat.hand == [draw_a, draw_b]

    def test_upgraded_compile_driver_deals_ten_damage_with_same_distinct_orb_draw(self):
        """Matches CompileDriver.cs: upgrade changes Damage only."""
        combat = _make_combat()
        enemy = combat.enemies[0]
        draw_a = make_strike_defect()
        draw_b = make_strike_defect()
        draw_c = make_strike_defect()
        combat.channel_orb(combat.player, "LIGHTNING")
        combat.channel_orb(combat.player, "LIGHTNING")
        combat.channel_orb(combat.player, "FROST")
        combat.hand = [make_compile_driver(upgraded=True)]
        combat.draw_pile = [draw_a, draw_b, draw_c]
        combat.energy = 1

        assert combat.play_card(0, 0)
        assert enemy.current_hp == enemy.max_hp - COMPILE_DRIVER_UPGRADED_DAMAGE
        assert combat.hand == [draw_a, draw_b]

    def test_defragment_applies_focus_that_scales_orb_passives(self):
        """Matches Defragment.cs: apply Focus to owner."""
        combat = _make_combat()
        enemy = combat.enemies[0]
        starting_hp = enemy.current_hp
        combat.channel_orb(combat.player, "LIGHTNING")
        combat.hand = [make_defragment()]
        combat.energy = 1

        assert combat.play_card(0)
        assert combat.player.get_power_amount(PowerId.FOCUS) == 1

        combat.end_player_turn()
        assert enemy.current_hp == starting_hp - 4

    def test_glacier_grants_block_and_channels_two_frost_orbs(self):
        """Matches Glacier.cs: gain block, then channel Frost twice."""
        combat = _make_combat()
        combat.hand = [make_glacier()]
        combat.energy = 2

        assert combat.play_card(0)
        assert combat.player.block == 6
        assert len(combat.orb_queue.orbs) == 2
        assert all(orb.orb_type == OrbType.FROST for orb in combat.orb_queue.orbs)

    def test_glacier_does_not_channel_after_block_ends_combat(self):
        combat = _make_combat()
        enemy = combat.enemies[0]
        enemy.current_hp = 5
        combat.player.apply_power(PowerId.JUGGERNAUT, 5)
        combat.hand = [make_glacier()]
        combat.energy = 2

        assert combat.play_card(0)
        assert combat.is_over
        assert len(combat.orb_queue.orbs) == 0

    def test_hailstorm_damages_enemies_at_turn_end_with_frost_orb(self):
        """Matches HailstormPower.cs: at owner turn end, deal damage if any Frost orb is present."""
        combat = _make_combat()
        enemy = combat.enemies[0]
        enemy.current_hp = enemy.max_hp = 100
        combat.channel_orb(combat.player, "FROST")
        combat.hand = [make_hailstorm()]
        combat.energy = 1

        assert combat.play_card(0)

        combat.end_player_turn()

        assert enemy.current_hp == 94

    def test_hailstorm_does_not_trigger_without_frost_orb(self):
        combat = _make_combat()
        enemy = combat.enemies[0]
        enemy.current_hp = enemy.max_hp = 100
        combat.channel_orb(combat.player, "DARK")
        combat.hand = [make_hailstorm()]
        combat.energy = 1

        assert combat.play_card(0)

        combat.end_player_turn()

        assert enemy.current_hp == 100

    def test_frost_orb_passive_block_triggers_after_block_gained_hooks(self):
        combat = _make_combat()
        enemy = combat.enemies[0]
        start_hp = enemy.current_hp
        combat.channel_orb(combat.player, "FROST")
        combat.player.apply_power(PowerId.JUGGERNAUT, 5)
        combat.player.block = 0

        combat.orb_queue.trigger_before_turn_end(combat)

        assert combat.player.block == 2
        assert enemy.current_hp == start_hp - 5

    def test_frost_orb_evoke_block_triggers_after_block_gained_hooks(self):
        combat = _make_combat()
        enemy = combat.enemies[0]
        start_hp = enemy.current_hp
        combat.channel_orb(combat.player, "FROST")
        combat.player.apply_power(PowerId.JUGGERNAUT, 5)
        combat.player.block = 0

        combat.orb_queue.evoke_front(combat)

        assert combat.player.block == 5
        assert enemy.current_hp == start_hp - 5

    def test_multi_cast_uses_x_energy_for_repeated_front_evoke(self):
        """Matches MultiCast.cs: evoke front orb X times and spend all energy."""
        combat = _make_combat()
        enemy = combat.enemies[0]
        starting_hp = enemy.current_hp
        combat.channel_orb(combat.player, "LIGHTNING")
        combat.hand = [make_multi_cast()]
        combat.energy = 3

        assert combat.play_card(0)
        assert combat.energy == 0
        assert enemy.current_hp == starting_hp - 24
        assert len(combat.orb_queue.orbs) == 0
