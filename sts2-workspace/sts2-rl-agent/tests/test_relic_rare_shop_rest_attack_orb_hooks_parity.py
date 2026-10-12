"""Parity tests for rare/shop relic rest, attack, and orb hooks."""

import sts2_env.powers  # noqa: F401

from sts2_env.cards.defect import create_defect_starter_deck
from sts2_env.cards.ironclad import create_ironclad_starter_deck, make_inflame, make_thunderclap
from sts2_env.cards.ironclad_basic import make_bash, make_defend_ironclad, make_strike_ironclad
from sts2_env.core.combat import CombatState
from sts2_env.core.enums import CombatSide, OrbType, PowerId, ValueProp
from sts2_env.core.rng import Rng
from sts2_env.monsters.act1_weak import create_shrinker_beetle
from sts2_env.orbs.all import create_orb
from sts2_env.run.rest_site import generate_rest_site_options
from sts2_env.run.run_state import RunState


IRONCLAD_CHARACTER_ID = "Ironclad"
GIRYA_RELIC_NAME = "GIRYA"
GIRYA_MAX_LIFTS = 3
GIRYA_PARITY_SEED = 1801


def _make_ironclad_combat(
    relics: list[str] | None = None,
    *,
    seed: int = 1800,
    player_state=None,
) -> CombatState:
    combat = CombatState(
        player_hp=80,
        player_max_hp=80,
        deck=create_ironclad_starter_deck(),
        rng_seed=seed,
        character_id="Ironclad",
        relics=relics or [],
        player_state=player_state,
    )
    creature, ai = create_shrinker_beetle(Rng(seed))
    combat.add_enemy(creature, ai)
    combat.start_combat()
    return combat


def _make_defect_combat(
    relics: list[str] | None = None,
    *,
    seed: int = 1810,
) -> CombatState:
    combat = CombatState(
        player_hp=75,
        player_max_hp=75,
        deck=create_defect_starter_deck(),
        rng_seed=seed,
        character_id="Defect",
        relics=relics or [],
    )
    creature, ai = create_shrinker_beetle(Rng(seed))
    combat.add_enemy(creature, ai)
    combat.start_combat()
    return combat


def _combat_relic(combat: CombatState, relic_name: str):
    return next(relic for relic in combat.relics if relic.relic_id.name == relic_name)


class TestRelicRareShopRestAttackOrbHooksParity:
    def test_girya_lift_option_caps_at_three_and_grants_strength_in_combat(self):
        """Matches Girya.cs: add Lift up to 3 times, then grant that much Strength in combat."""
        run_state = RunState(seed=GIRYA_PARITY_SEED, character_id=IRONCLAD_CHARACTER_ID)
        assert run_state.player.obtain_relic(GIRYA_RELIC_NAME)

        for lifts_done in range(1, GIRYA_MAX_LIFTS + 1):
            option = next(option for option in generate_rest_site_options(run_state.player) if option.option_id == "LIFT")
            assert option.execute(run_state.player) == f"Lifted! ({lifts_done}/{GIRYA_MAX_LIFTS})"

        assert all(option.option_id != "LIFT" for option in generate_rest_site_options(run_state.player))

        combat = _make_ironclad_combat(seed=GIRYA_PARITY_SEED, player_state=run_state.player)
        assert combat.player.get_power_amount(PowerId.STRENGTH) == GIRYA_MAX_LIFTS

    def test_shovel_adds_dig_option_and_queues_a_relic_reward(self):
        """Matches Shovel.cs: rest sites add Dig, which offers a relic reward."""
        run_state = RunState(seed=1802, character_id="Ironclad")
        assert run_state.player.obtain_relic("SHOVEL")

        dig = next(option for option in generate_rest_site_options(run_state.player) if option.option_id == "DIG")
        run_state.pending_rewards.clear()

        assert dig.execute(run_state.player) == "Found a relic"
        assert len(run_state.pending_rewards) == 1

    def test_kunai_grants_one_dexterity_after_every_third_attack(self):
        """Matches Kunai.cs: each third Attack played this turn grants Dexterity."""
        combat = _make_ironclad_combat(["Kunai"], seed=1803)
        enemy = combat.enemies[0]
        enemy.max_hp = 200
        enemy.current_hp = 200
        combat.hand = [make_strike_ironclad(), make_strike_ironclad(), make_strike_ironclad()]
        for card in combat.hand:
            card.owner = combat.player
        combat.energy = 3

        assert combat.play_card(0, 0)
        assert combat.play_card(0, 0)
        assert combat.play_card(0, 0)
        assert combat.player.get_power_amount(PowerId.DEXTERITY) == 1

    def test_shuriken_grants_one_strength_after_every_third_attack(self):
        """Matches Shuriken.cs: each third Attack played this turn grants Strength."""
        combat = _make_ironclad_combat(["Shuriken"], seed=1804)
        enemy = combat.enemies[0]
        enemy.max_hp = 200
        enemy.current_hp = 200
        combat.hand = [make_strike_ironclad(), make_strike_ironclad(), make_strike_ironclad()]
        for card in combat.hand:
            card.owner = combat.player
        combat.energy = 3

        assert combat.play_card(0, 0)
        assert combat.play_card(0, 0)
        assert combat.play_card(0, 0)
        assert combat.player.get_power_amount(PowerId.STRENGTH) == 1

    def test_paper_krane_makes_weak_enemies_hit_for_six_instead_of_seven(self):
        """Matches PaperKrane.cs: Weak multiplier is reduced by an extra 15% against the owner."""
        combat = _make_ironclad_combat(["PaperKrane"], seed=1805)
        enemy = combat.enemies[0]
        hp_before = combat.player.current_hp
        enemy.apply_power(PowerId.WEAK, 1, applier=combat.player)

        combat.deal_damage(enemy, combat.player, 10, ValueProp.MOVE)

        assert combat.player.current_hp == hp_before - 6

    def test_emotion_chip_triggers_all_orb_passives_after_losing_hp_previous_turn(self):
        """Matches EmotionChip.cs: unblocked HP loss in the previous round triggers all passives once."""
        combat = _make_defect_combat(["EmotionChip"], seed=1806)
        combat.player.block = 0
        combat.orb_queue.orbs = [create_orb(OrbType.FROST)]

        combat.deal_damage(combat.enemies[0], combat.player, 5, ValueProp.MOVE)
        combat.end_player_turn()

        assert combat.round_number == 2
        assert combat.player.block == 2

    def test_emotion_chip_triggers_after_non_fully_blocked_zero_damage(self):
        """Matches EmotionChip.cs: previous-round history checks !WasFullyBlocked."""
        combat = _make_defect_combat(["EmotionChip"], seed=1825)
        combat.player.block = 0
        combat.orb_queue.orbs = [create_orb(OrbType.FROST)]

        combat.deal_damage(combat.enemies[0], combat.player, 0, ValueProp.MOVE)
        combat.end_player_turn()

        assert combat.round_number == 2
        assert combat.player.block == 2

    def test_emotion_chip_does_not_trigger_after_fully_blocked_damage(self):
        combat = _make_defect_combat(["EmotionChip"], seed=1826)
        combat.player.block = 5
        combat.orb_queue.orbs = [create_orb(OrbType.FROST)]

        combat.deal_damage(combat.enemies[0], combat.player, 3, ValueProp.MOVE)
        combat.end_player_turn()

        assert combat.round_number == 2
        assert combat.player.block == 0

    def test_gambling_chip_discards_selected_cards_and_draws_that_many_on_round_one(self):
        """Matches GamblingChip.cs: on round 1, discard any selected hand cards and draw that many."""
        combat = _make_ironclad_combat(["GamblingChip"], seed=1807)
        relic = _combat_relic(combat, "GAMBLING_CHIP")
        strike = make_strike_ironclad()
        defend = make_defend_ironclad()
        bash = make_bash()
        inflame = make_inflame()
        thunderclap = make_thunderclap()
        for card in (strike, defend, bash, inflame, thunderclap):
            card.owner = combat.player

        combat.pending_choice = None
        combat.hand = [strike, defend, bash]
        combat.draw_pile = [inflame, thunderclap]
        combat.discard_pile = []

        relic.after_player_turn_start(combat.player, combat)

        assert combat.pending_choice is not None
        assert combat.pending_choice.is_multi
        assert combat.resolve_pending_choice(0) is True
        assert combat.resolve_pending_choice(1) is True
        assert combat.resolve_pending_choice(None) is True
        assert combat.pending_choice is None
        assert [card.card_id.name for card in combat.discard_pile] == ["STRIKE_IRONCLAD", "DEFEND_IRONCLAD"]
        assert [card.card_id.name for card in combat.hand] == ["BASH", "INFLAME", "THUNDERCLAP"]

    def test_gambling_chip_can_confirm_without_discarding_or_drawing(self):
        """Matches GamblingChip.cs: zero selected hand cards leaves hand and piles unchanged."""
        combat = _make_ironclad_combat(["GamblingChip"], seed=1808)
        relic = _combat_relic(combat, "GAMBLING_CHIP")
        strike = make_strike_ironclad()
        defend = make_defend_ironclad()
        bash = make_bash()
        inflame = make_inflame()
        for card in (strike, defend, bash, inflame):
            card.owner = combat.player

        combat.pending_choice = None
        combat.hand = [strike, defend, bash]
        combat.draw_pile = [inflame]
        combat.discard_pile = []

        relic.after_player_turn_start(combat.player, combat)

        assert combat.pending_choice is not None
        assert combat.pending_choice.min_choices == 0
        assert combat.pending_choice.max_choices == 3
        assert combat.pending_choice.allow_skip is True

        assert combat.resolve_pending_choice(None) is True
        assert combat.pending_choice is None
        assert combat.hand == [strike, defend, bash]
        assert combat.draw_pile == [inflame]
        assert combat.discard_pile == []
