"""Focused Ironclad parity tests backed by decompiled card models."""

import sts2_env.powers  # noqa: F401
import sts2_env.relics  # noqa: F401

from sts2_env.cards.ironclad import (
    create_ironclad_starter_deck,
    make_armaments,
    make_burning_pact,
    make_cascade,
    make_headbutt,
    make_true_grit,
    make_whirlwind,
)
from sts2_env.cards.ironclad_basic import make_bash, make_defend_ironclad, make_strike_ironclad
from sts2_env.core.combat import CombatState
from sts2_env.core.enums import PowerId
from sts2_env.core.rng import Rng
from sts2_env.monsters.act1_weak import create_shrinker_beetle


def _make_combat(*, enemies: int = 1, relics: list[str] | None = None) -> CombatState:
    combat = CombatState(
        player_hp=80,
        player_max_hp=80,
        deck=create_ironclad_starter_deck(),
        rng_seed=42,
        character_id="Ironclad",
        relics=relics,
    )
    for i in range(enemies):
        creature, ai = create_shrinker_beetle(Rng(42 + i))
        combat.add_enemy(creature, ai)
    combat.start_combat()
    return combat


class TestIroncladParity:
    def test_armaments_plus_upgrades_all_unupgraded_hand_cards(self):
        """Matches Armaments.cs: gain block and, when upgraded, upgrade every non-upgraded hand card."""
        combat = _make_combat()
        strike = make_strike_ironclad()
        defend = make_defend_ironclad()
        combat.hand = [make_armaments(upgraded=True), strike, defend]
        combat.energy = 1

        assert combat.play_card(0)
        assert combat.player.block == 5
        assert combat.pending_choice is None
        assert strike.upgraded is True
        assert defend.upgraded is True

    def test_armaments_does_not_upgrade_after_block_ends_combat(self):
        combat = _make_combat()
        enemy = combat.enemies[0]
        enemy.current_hp = 5
        strike = make_strike_ironclad()
        combat.player.apply_power(PowerId.JUGGERNAUT, 5)
        combat.hand = [make_armaments(), strike]
        combat.energy = 1

        assert combat.play_card(0)
        assert combat.is_over
        assert strike.upgraded is False

    def test_armaments_plus_does_not_upgrade_hand_after_block_ends_combat(self):
        combat = _make_combat()
        enemy = combat.enemies[0]
        enemy.current_hp = 5
        strike = make_strike_ironclad()
        defend = make_defend_ironclad()
        combat.player.apply_power(PowerId.JUGGERNAUT, 5)
        combat.hand = [make_armaments(upgraded=True), strike, defend]
        combat.energy = 1

        assert combat.play_card(0)
        assert combat.is_over
        assert strike.upgraded is False
        assert defend.upgraded is False

    def test_burning_pact_exhausts_selected_card_then_draws(self):
        """Matches BurningPact.cs: select one hand card to exhaust, then draw the configured amount."""
        combat = _make_combat()
        strike = make_strike_ironclad()
        defend = make_defend_ironclad()
        draw_a = make_bash()
        draw_b = make_strike_ironclad()
        combat.hand = [make_burning_pact(), strike, defend]
        combat.draw_pile = [draw_a, draw_b]
        combat.energy = 1

        assert combat.play_card(0)
        assert combat.pending_choice is not None
        assert [option.card for option in combat.pending_choice.options] == [strike, defend]

        assert combat.resolve_pending_choice(1)
        assert combat.pending_choice is None
        assert defend in combat.exhaust_pile
        assert draw_a in combat.hand
        assert draw_b in combat.hand
        assert len(combat.hand) == 3

    def test_burning_pact_still_draws_when_no_other_hand_cards(self):
        """Matches BurningPact.cs: empty selection still continues to draw cards."""
        combat = _make_combat()
        draw_a = make_bash()
        draw_b = make_strike_ironclad()
        combat.hand = [make_burning_pact()]
        combat.draw_pile = [draw_a, draw_b]
        combat.energy = 1

        assert combat.play_card(0)
        assert combat.pending_choice is None
        assert draw_a in combat.hand
        assert draw_b in combat.hand

    def test_burning_pact_still_draws_when_selection_returns_none(self):
        """Matches BurningPact.cs: draw continues even when no selected card is returned."""
        combat = _make_combat()
        strike = make_strike_ironclad()
        defend = make_defend_ironclad()
        draw_a = make_bash()
        draw_b = make_strike_ironclad()
        combat.hand = [make_burning_pact(), strike, defend]
        combat.draw_pile = [draw_a, draw_b]
        combat.energy = 1

        assert combat.play_card(0)
        assert combat.pending_choice is not None

        resolver = combat.pending_choice.resolver
        combat.pending_choice = None
        resolver([])
        combat._resume_pending_play()  # noqa: SLF001

        assert strike in combat.hand
        assert defend in combat.hand
        assert draw_a in combat.hand
        assert draw_b in combat.hand

    def test_headbutt_puts_selected_discard_card_on_top_of_draw(self):
        """Matches Headbutt.cs: attack, then choose one discard card and place it on top of draw pile."""
        combat = _make_combat()
        enemy = combat.enemies[0]
        starting_hp = enemy.current_hp
        strike = make_strike_ironclad()
        defend = make_defend_ironclad()
        existing_top = make_bash()
        combat.hand = [make_headbutt()]
        combat.discard_pile = [strike, defend]
        combat.draw_pile = [existing_top]
        combat.energy = 1

        assert combat.play_card(0, 0)
        assert enemy.current_hp == starting_hp - 9
        assert combat.pending_choice is not None
        assert [option.card for option in combat.pending_choice.options] == [strike, defend]

        assert combat.resolve_pending_choice(1)
        assert combat.pending_choice is None
        assert combat.draw_pile[0] is defend
        assert combat.draw_pile[1] is existing_top
        assert defend not in combat.discard_pile
        assert strike in combat.discard_pile

    def test_true_grit_plus_exhausts_the_selected_hand_card(self):
        """Matches TrueGrit.cs: gain block, then upgraded version exhausts a selected hand card."""
        combat = _make_combat()
        strike = make_strike_ironclad()
        defend = make_defend_ironclad()
        combat.hand = [make_true_grit(upgraded=True), strike, defend]
        combat.energy = 1

        assert combat.play_card(0)
        assert combat.player.block == 9
        assert combat.pending_choice is not None
        assert [option.card for option in combat.pending_choice.options] == [strike, defend]

        assert combat.resolve_pending_choice(1)
        assert combat.pending_choice is None
        assert defend in combat.exhaust_pile
        assert strike in combat.hand

    def test_whirlwind_uses_all_energy_and_hits_all_enemies_per_energy(self):
        """Matches Whirlwind.cs: consume all current energy and deal repeated all-enemy hits."""
        combat = _make_combat(enemies=2)
        enemy_a, enemy_b = combat.enemies
        start_a = enemy_a.current_hp
        start_b = enemy_b.current_hp
        combat.hand = [make_whirlwind()]
        combat.energy = 3

        assert combat.play_card(0)
        assert combat.energy == 0
        assert enemy_a.current_hp == start_a - 15
        assert enemy_b.current_hp == start_b - 15

    def test_whirlwind_can_be_played_with_zero_energy_for_zero_hits(self):
        """Matches X-cost resource checks: X cards are playable at zero energy."""
        combat = _make_combat()
        enemy = combat.enemies[0]
        start = enemy.current_hp
        card = make_whirlwind()
        combat.hand = [card]
        combat.energy = 0

        assert combat.can_play_card(card) is True
        assert combat.play_card(0)
        assert enemy.current_hp == start
        assert card in combat.discard_pile

    def test_cascade_reference_cost_remains_playable_as_x_cost(self):
        """Matches Cascade.cs: base cost is -1 but HasEnergyCostX makes it playable."""
        combat = _make_combat()
        card = make_cascade()
        combat.hand = [card]
        combat.energy = 0

        assert card.cost == -1
        assert card.is_unplayable is False
        assert combat.can_play_card(card) is True

    def test_whirlwind_uses_modified_x_value_from_chemical_x(self):
        """Matches Whirlwind.cs + ChemicalX.cs: resolved X value includes X-value hooks."""
        combat = _make_combat(enemies=2, relics=["ChemicalX"])
        for enemy in combat.enemies:
            enemy.max_hp = 100
            enemy.current_hp = 100
        combat.hand = [make_whirlwind()]
        combat.energy = 1

        assert combat.play_card(0)
        assert [enemy.current_hp for enemy in combat.enemies] == [85, 85]

    def test_cascade_uses_x_value_to_autoplay_top_draw_cards(self):
        """Matches Cascade.cs: auto-play the top X draw-pile cards."""
        combat = _make_combat()
        enemy = combat.enemies[0]
        enemy.max_hp = 100
        enemy.current_hp = 100
        combat.hand = [make_cascade()]
        combat.draw_pile = [make_strike_ironclad(), make_strike_ironclad()]
        combat.energy = 2

        assert combat.play_card(0)
        assert combat.energy == 0
        assert enemy.current_hp == 88
