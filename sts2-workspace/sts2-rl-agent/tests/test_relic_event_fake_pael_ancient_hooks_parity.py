"""Parity tests for Fake, Pael, and ancient event relic hooks."""

import sts2_env.powers  # noqa: F401

from sts2_env.cards.factory import create_card
from sts2_env.cards.ironclad import create_ironclad_starter_deck
from sts2_env.cards.ironclad_basic import make_defend_ironclad, make_strike_ironclad
from sts2_env.core.combat import CombatState
from sts2_env.core.enums import CardId, CombatSide, PowerId, RoomType
from sts2_env.core.hooks import (
    fire_after_card_played,
    fire_after_energy_reset,
    fire_after_side_turn_start,
    fire_before_turn_end,
)
from sts2_env.core.rng import Rng
from sts2_env.monsters.act1_weak import create_shrinker_beetle
from sts2_env.run.reward_objects import AddCardsReward
from sts2_env.run.rooms import RoomVisitContext
from sts2_env.run.run_state import RunState
from sts2_env.relics.registry import create_relic_by_name


LEES_WAFFLE_MAX_HP_GAIN = 7


def _make_combat(relics: list[str] | None = None, *, seed: int = 991) -> CombatState:
    combat = CombatState(
        player_hp=80,
        player_max_hp=80,
        deck=create_ironclad_starter_deck(),
        rng_seed=seed,
        character_id="Ironclad",
        relics=relics or [],
    )
    creature, ai = create_shrinker_beetle(Rng(seed))
    combat.add_enemy(creature, ai)
    combat.start_combat()
    return combat


def _with_owner(cards: list, owner):
    for card in cards:
        card.owner = owner
    return cards


def _event_pet(combat: CombatState, monster_id: str):
    return next(
        (
            ally
            for ally in combat.allies
            if getattr(ally, "monster_id", None) == monster_id and getattr(ally, "is_pet", False)
        ),
        None,
    )


class _InsertAtEndRng:
    def __init__(self):
        self.calls = []

    def next_int(self, low: int, high: int) -> int:
        self.calls.append((low, high))
        return high


class TestRelicEventFakePaelAncientHooksParity:
    def test_fake_anchor_grants_four_block_at_combat_start(self):
        combat = _make_combat(["FakeAnchor"], seed=980)

        assert combat.player.block == 4

    def test_fake_anchor_block_triggers_after_block_gained_hooks(self):
        combat = CombatState(
            player_hp=80,
            player_max_hp=80,
            deck=create_ironclad_starter_deck(),
            rng_seed=990,
            character_id="Ironclad",
            relics=["FakeAnchor"],
        )
        enemy, ai = create_shrinker_beetle(Rng(990))
        combat.add_enemy(enemy, ai)
        start_hp = enemy.current_hp
        combat.player.apply_power(PowerId.JUGGERNAUT, 5)

        combat.start_combat()

        assert combat.player.block == 4
        assert enemy.current_hp == start_hp - 5

    def test_fake_blood_vial_heals_one_on_round_one_player_turn_start(self):
        combat = CombatState(
            player_hp=79,
            player_max_hp=80,
            deck=create_ironclad_starter_deck(),
            rng_seed=981,
            character_id="Ironclad",
            relics=["FakeBloodVial"],
        )
        creature, ai = create_shrinker_beetle(Rng(981))
        combat.add_enemy(creature, ai)

        combat.start_combat()

        assert combat.player.current_hp == 80

        combat.player.current_hp = 79
        combat.round_number = 2
        relic = next(relic for relic in combat.relics if relic.relic_id.name == "FAKE_BLOOD_VIAL")
        relic.after_player_turn_start_late(combat.player, combat)

        assert combat.player.current_hp == 79

    def test_fake_happy_flower_grants_energy_every_fifth_owner_turn_and_resets_counter(self):
        combat = _make_combat(["FakeHappyFlower"], seed=982)
        relic = next(relic for relic in combat.relics if relic.relic_id.name == "FAKE_HAPPY_FLOWER")

        assert combat.energy == 3
        assert relic._turns_seen == 1  # noqa: SLF001

        for expected_turns in (2, 3, 4):
            fire_after_side_turn_start(CombatSide.PLAYER, combat)
            assert combat.energy == 3
            assert relic._turns_seen == expected_turns  # noqa: SLF001

        fire_after_side_turn_start(CombatSide.PLAYER, combat)

        assert combat.energy == 4
        assert relic._turns_seen == 0  # noqa: SLF001

    def test_fake_lees_waffle_heals_ten_percent_of_max_hp_on_obtain(self):
        run_state = RunState(seed=983, character_id="Ironclad")
        run_state.player.max_hp = 85
        run_state.player.current_hp = 50

        assert run_state.player.obtain_relic("FakeLeesWaffle")

        assert run_state.player.current_hp == 58
        assert run_state.player.max_hp == 85

    def test_lees_waffle_grants_max_hp_and_heals_to_full_on_obtain(self):
        run_state = RunState(seed=983, character_id="Ironclad")
        run_state.player.max_hp = 80
        run_state.player.current_hp = 35

        assert run_state.player.obtain_relic("LeesWaffle")

        assert run_state.player.max_hp == 80 + LEES_WAFFLE_MAX_HP_GAIN
        assert run_state.player.current_hp == run_state.player.max_hp

    def test_fake_mango_grants_three_max_hp_on_obtain(self):
        run_state = RunState(seed=984, character_id="Ironclad")
        max_hp_before = run_state.player.max_hp
        hp_before = run_state.player.current_hp

        assert run_state.player.obtain_relic("FakeMango")

        assert run_state.player.max_hp == max_hp_before + 3
        assert run_state.player.current_hp == hp_before + 3

    def test_fake_merchants_rug_has_no_pickup_effect(self):
        run_state = RunState(seed=985, character_id="Ironclad")
        run_state.player.deck = create_ironclad_starter_deck()
        before = (
            run_state.player.gold,
            run_state.player.current_hp,
            run_state.player.max_hp,
            [card.card_id for card in run_state.player.deck],
        )

        assert run_state.player.obtain_relic("FakeMerchantsRug")

        assert (
            run_state.player.gold,
            run_state.player.current_hp,
            run_state.player.max_hp,
            [card.card_id for card in run_state.player.deck],
        ) == before

    def test_fake_orichalcum_grants_three_block_only_when_owner_ends_with_zero_block(self):
        combat = _make_combat(["FakeOrichalcum"], seed=986)

        combat.player.block = 0
        fire_before_turn_end(CombatSide.PLAYER, combat)
        assert combat.player.block == 3

        combat.player.block = 2
        fire_before_turn_end(CombatSide.PLAYER, combat)
        assert combat.player.block == 2

        combat.player.block = 0
        fire_before_turn_end(CombatSide.ENEMY, combat)
        assert combat.player.block == 0

    def test_fake_orichalcum_block_triggers_after_block_gained_hooks(self):
        combat = _make_combat(["FakeOrichalcum"], seed=990)
        enemy = combat.enemies[0]
        start_hp = enemy.current_hp
        combat.player.block = 0
        combat.player.apply_power(PowerId.JUGGERNAUT, 5)

        fire_before_turn_end(CombatSide.PLAYER, combat)

        assert combat.player.block == 3
        assert enemy.current_hp == start_hp - 5

    def test_fake_venerable_tea_set_adds_one_energy_once_after_rest_site(self):
        combat = _make_combat(["FakeVenerableTeaSet"], seed=987)
        relic = next(relic for relic in combat.relics if relic.relic_id.name == "FAKE_VENERABLE_TEA_SET")

        combat.energy = combat.max_energy
        relic.after_room_entered(combat.player, RoomVisitContext(RoomType.SHOP))
        fire_after_energy_reset(combat, combat.player)
        assert combat.energy == 3

        relic.after_room_entered(combat.player, RoomVisitContext(RoomType.REST_SITE))
        fire_after_energy_reset(combat, combat.player)
        assert combat.energy == 4

        fire_after_energy_reset(combat, combat.player)
        assert combat.energy == 4

    def test_paels_flesh_gains_energy_from_round_three_onward(self):
        """Matches PaelsFlesh.cs: owner gains 1 energy at side start from round 3 onward."""
        combat = _make_combat(["PaelsFlesh"], seed=989)

        assert combat.energy == 3

        combat.end_player_turn()
        assert combat.round_number == 2
        assert combat.energy == 3

        combat.end_player_turn()
        assert combat.round_number == 3
        assert combat.energy == 4

    def test_stackable_placeholder_relics_can_be_obtained_more_than_once(self):
        run_state = RunState(seed=988, character_id="Ironclad")

        assert run_state.player.obtain_relic("Circlet")
        assert run_state.player.obtain_relic("CIRCLET")
        assert run_state.player.obtain_relic("DeprecatedRelic")
        assert run_state.player.obtain_relic("DEPRECATED_RELIC")

        assert run_state.player.relics.count("CIRCLET") == 2
        assert run_state.player.relics.count("DEPRECATED_RELIC") == 2
        assert sum(relic.relic_id.name == "CIRCLET" for relic in run_state.player.relic_objects) == 2
        assert sum(relic.relic_id.name == "DEPRECATED_RELIC" for relic in run_state.player.relic_objects) == 2

    def test_non_stackable_relic_duplicates_are_rejected_by_canonical_id(self):
        run_state = RunState(seed=989, character_id="Ironclad")

        assert run_state.player.obtain_relic("Anchor")
        assert not run_state.player.obtain_relic("ANCHOR")

        assert run_state.player.relics == ["ANCHOR"]

    def test_big_mushroom_grants_max_hp_and_reduces_round_one_draw_by_two(self):
        run_state = RunState(seed=991, character_id="Ironclad")
        start_max_hp = run_state.player.max_hp
        assert run_state.player.obtain_relic("BIG_MUSHROOM")
        assert run_state.player.max_hp == start_max_hp + 20

        combat = _make_combat(["BigMushroom"], seed=991)
        assert len(combat.hand) == 3

    def test_biiig_hug_removes_four_cards_on_obtain_and_adds_soot_after_shuffle(self):
        run_state = RunState(seed=992, character_id="Ironclad")
        run_state.player.deck = create_ironclad_starter_deck()
        deck_before = len(run_state.player.deck)

        assert run_state.player.obtain_relic("BIIIG_HUG")
        assert len(run_state.player.deck) == deck_before - 4

        combat = _make_combat(["BiiigHug"], seed=992)
        combat.hand.clear()
        combat.draw_pile = []
        combat.discard_pile = [make_strike_ironclad()]

        combat.draw_cards(combat.player, 1)
        soot_count = sum(
            1
            for pile in (combat.hand, combat.draw_pile, combat.discard_pile, combat.exhaust_pile)
            for card in pile
            if card.card_id == CardId.SOOT
        )
        assert soot_count == 1

    def test_biiig_hug_inserts_soot_at_random_draw_position_after_shuffle(self):
        combat = CombatState(
            player_hp=80,
            player_max_hp=80,
            deck=[],
            rng_seed=992,
            character_id="Ironclad",
            relics=["BiiigHug"],
        )
        combat.draw_pile = _with_owner([make_strike_ironclad(), make_defend_ironclad()], combat.player)
        combat.rng = _InsertAtEndRng()

        combat.relics[0].after_shuffle(combat.player, combat)

        assert [card.card_id for card in combat.draw_pile] == [
            CardId.STRIKE_IRONCLAD,
            CardId.DEFEND_IRONCLAD,
            CardId.SOOT,
        ]
        assert combat.rng.calls == [(0, 2)]

    def test_byrdpip_transforms_byrdonis_egg_into_byrd_swoop_on_obtain(self):
        run_state = RunState(seed=996, character_id="Ironclad")
        run_state.player.deck = [*create_ironclad_starter_deck(), create_card(CardId.BYRDONIS_EGG)]

        assert run_state.player.obtain_relic("BYRDPIP")
        assert any(card.card_id == CardId.BYRD_SWOOP for card in run_state.player.deck)
        assert all(card.card_id != CardId.BYRDONIS_EGG for card in run_state.player.deck)

    def test_byrdpip_summons_pet_at_combat_start_and_when_obtained_mid_combat(self):
        combat = _make_combat(["Byrdpip"], seed=996)
        pet = _event_pet(combat, "BYRDPIP")
        assert pet is not None
        assert pet.pet_owner is combat.player

        mid_combat = _make_combat([], seed=997)
        assert mid_combat.current_player_state.player_state.obtain_relic("BYRDPIP")
        mid_pet = _event_pet(mid_combat, "BYRDPIP")
        assert mid_pet is not None
        assert mid_pet.pet_owner is mid_combat.player

    def test_paels_tooth_removes_upgradable_cards_and_returns_one_upgraded_after_combat(self):
        run_state = RunState(seed=997, character_id="Ironclad")
        run_state.player.deck = create_ironclad_starter_deck()
        starting_deck = len(run_state.player.deck)

        assert run_state.player.obtain_relic("PAELS_TOOTH")
        assert len(run_state.player.deck) == starting_deck - 5

        combat = CombatState(
            player_hp=80,
            player_max_hp=80,
            deck=list(run_state.player.deck),
            rng_seed=997,
            character_id="Ironclad",
            relics=list(run_state.player.relics),
            player_state=run_state.player,
        )
        creature, ai = create_shrinker_beetle(Rng(997))
        combat.add_enemy(creature, ai)
        combat.start_combat()
        combat._end_combat(player_won=True)

        assert len(run_state.player.deck) == starting_deck - 4
        assert len({card.instance_id for card in run_state.player.deck}) == len(run_state.player.deck)
        assert any(card.upgraded for card in run_state.player.deck)

    def test_paels_tooth_uses_deck_choice_for_cards_to_store(self):
        run_state = RunState(seed=997, character_id="Ironclad")
        run_state.enable_deck_choice_requests = True
        run_state.player.deck = create_ironclad_starter_deck()
        starting_deck = len(run_state.player.deck)

        assert run_state.player.obtain_relic("PAELS_TOOTH")
        assert run_state.pending_choice is not None
        assert len(run_state.player.deck) == starting_deck

        for index in range(5):
            assert run_state.resolve_pending_choice(index)
        assert run_state.resolve_pending_choice(None)

        assert run_state.pending_choice is None
        assert len(run_state.player.deck) == starting_deck - 5

    def test_paels_tooth_ignores_upgradable_eternal_cards(self):
        run_state = RunState(seed=997, character_id="Ironclad")
        grimoire = create_card(CardId.FORBIDDEN_GRIMOIRE)
        strike = create_card(CardId.STRIKE_IRONCLAD)
        run_state.player.deck = [grimoire, strike]

        assert run_state.player.obtain_relic("PAELS_TOOTH")

        assert run_state.player.deck == [grimoire]

    def test_paels_tooth_stores_cards_by_reference_entry_order(self):
        run_state = RunState(seed=997, character_id="Ironclad")
        run_state.player.deck = [
            create_card(CardId.THUNDERCLAP),
            create_card(CardId.THUNDER_CARD),
        ]

        assert run_state.player.obtain_relic("PAELS_TOOTH")
        tooth = next(relic for relic in run_state.player.relic_objects if relic.relic_id.name == "PAELS_TOOTH")

        assert [card.card_id for card in tooth._stored_cards] == [  # noqa: SLF001
            CardId.THUNDER_CARD,
            CardId.THUNDERCLAP,
        ]

    def test_paels_legion_doubles_block_then_enters_two_turn_cooldown(self):
        combat = _make_combat(["PaelsLegion"], seed=998)
        pet = _event_pet(combat, "PAELS_LEGION")
        assert pet is not None
        assert pet.pet_owner is combat.player

        mid_combat = _make_combat([], seed=999)
        assert mid_combat.current_player_state.player_state.obtain_relic("PaelsLegion")
        mid_pet = _event_pet(mid_combat, "PAELS_LEGION")
        assert mid_pet is not None
        assert mid_pet.pet_owner is mid_combat.player

        combat.player.block = 0
        combat.hand = [make_defend_ironclad(), make_defend_ironclad()]
        for card in combat.hand:
            card.owner = combat.player
        combat.energy = 2

        assert combat.play_card(0)
        assert combat.player.block == 10

        assert combat.play_card(0)
        assert combat.player.block == 15

        combat.end_player_turn()
        combat.hand = [make_defend_ironclad()]
        combat.hand[0].owner = combat.player
        combat.energy = 1
        assert combat.play_card(0)
        assert combat.player.block == 5

        combat.end_player_turn()
        combat.hand = [make_defend_ironclad()]
        combat.hand[0].owner = combat.player
        combat.energy = 1
        assert combat.play_card(0)
        assert combat.player.block == 10

    def test_paels_tears_uses_previous_turn_leftover_energy_until_next_turn_end(self):
        combat = _make_combat(["PaelsTears"], seed=999)
        relic = next(relic for relic in combat.relics if relic.relic_id.name == "PAELS_TEARS")

        combat.energy = 1
        combat.end_player_turn()

        assert combat.round_number == 2
        assert combat.energy == combat.max_energy + 2
        assert relic._had_leftover is True  # noqa: SLF001

        combat.energy = 0
        combat.end_player_turn()

        assert combat.round_number == 3
        assert combat.energy == combat.max_energy
        assert relic._had_leftover is False  # noqa: SLF001

    def test_tea_of_discourtesy_inserts_dazed_at_random_draw_positions(self):
        combat = CombatState(
            player_hp=80,
            player_max_hp=80,
            deck=[],
            rng_seed=999,
            character_id="Ironclad",
            relics=["TeaOfDiscourtesy"],
        )
        combat.draw_pile = _with_owner([make_strike_ironclad(), make_defend_ironclad()], combat.player)
        combat.rng = _InsertAtEndRng()

        combat.relics[0].before_combat_start(combat.player, combat)

        assert [card.card_id for card in combat.draw_pile] == [
            CardId.STRIKE_IRONCLAD,
            CardId.DEFEND_IRONCLAD,
            CardId.DAZED,
            CardId.DAZED,
        ]
        assert combat.rng.calls == [(0, 2), (0, 3)]

    def test_blessed_antler_adds_energy_and_three_dazed_on_round_one(self):
        combat = _make_combat(["BlessedAntler"], seed=993)
        total_dazed = sum(
            1
            for pile in (combat.hand, combat.draw_pile, combat.discard_pile, combat.exhaust_pile)
            for card in pile
            if card.card_id == CardId.DAZED
        )
        assert combat.max_energy == 4
        assert total_dazed == 3

    def test_blessed_antler_inserts_dazed_at_random_draw_positions(self):
        combat = CombatState(
            player_hp=80,
            player_max_hp=80,
            deck=[],
            rng_seed=993,
            character_id="Ironclad",
            relics=["BlessedAntler"],
        )
        combat.draw_pile = _with_owner([make_strike_ironclad(), make_defend_ironclad()], combat.player)
        combat.rng = _InsertAtEndRng()

        combat.relics[0].before_hand_draw(combat.player, combat)

        assert [card.card_id for card in combat.draw_pile] == [
            CardId.STRIKE_IRONCLAD,
            CardId.DEFEND_IRONCLAD,
            CardId.DAZED,
            CardId.DAZED,
            CardId.DAZED,
        ]
        assert combat.rng.calls == [(0, 2), (0, 3), (0, 4)]

    def test_bone_tea_upgrades_opening_hand_for_one_combat(self):
        combat = _make_combat(["BoneTea"], seed=994)
        assert combat.hand
        assert all(card.upgraded for card in combat.hand)

    def test_chosen_cheese_gains_one_max_hp_after_combat_victory(self):
        combat = _make_combat(["ChosenCheese"], seed=995)
        enemy = combat.enemies[0]
        enemy.current_hp = 6
        enemy.max_hp = 6
        max_hp_before = combat.player.max_hp
        combat.hand = [make_strike_ironclad()]
        combat.energy = 1

        assert combat.play_card(0, 0)
        assert combat.is_over and combat.player_won
        assert combat.player.max_hp == max_hp_before + 1

    def test_dusty_tome_sets_up_one_non_transcendence_ancient_card_for_each_character(self):
        """Matches DustyTome.cs: random Ancient card excludes ArchaicTooth Transcendence cards."""
        expected_by_character = {
            "Ironclad": CardId.CORRUPTION_CARD,
            "Silent": CardId.WRAITH_FORM,
            "Defect": CardId.BIASED_COGNITION_CARD,
            "Regent": CardId.THE_SEALED_THRONE,
            "Necrobinder": CardId.FORBIDDEN_GRIMOIRE,
        }

        for character_id, expected_card_id in expected_by_character.items():
            run_state = RunState(seed=995, character_id=character_id)
            dusty_tome = create_relic_by_name("DUSTY_TOME")

            assert dusty_tome.setup_for_player(run_state.player)
            assert dusty_tome._ancient_card_id == expected_card_id.name  # noqa: SLF001

            run_state.player.relics.append(dusty_tome.relic_id.name)
            run_state.player.relic_objects.append(dusty_tome)
            dusty_tome.after_obtained(run_state.player)

            added = run_state.player.deck[-1]
            assert added.card_id == expected_card_id
            assert added.upgraded is True

    def test_jewelry_box_deferred_followups_queue_apotheosis_reward(self):
        run_state = RunState(seed=996, character_id="Ironclad")
        run_state.defer_followup_rewards = True

        assert run_state.player.obtain_relic("JEWELRY_BOX")
        assert len(run_state.pending_rewards) == 1
        reward = run_state.pending_rewards[0]
        assert isinstance(reward, AddCardsReward)
        assert [card.card_id.name for card in reward.cards] == ["APOTHEOSIS"]

    def test_mango_grants_fourteen_max_hp_on_obtain(self):
        run_state = RunState(seed=997, character_id="Ironclad")
        max_hp_before = run_state.player.max_hp

        assert run_state.player.obtain_relic("MANGO")
        assert run_state.player.max_hp == max_hp_before + 14

    def test_new_leaf_transforms_one_card_on_obtain(self):
        run_state = RunState(seed=998, character_id="Ironclad")
        run_state.player.deck = create_ironclad_starter_deck()
        original_ids = [card.card_id for card in run_state.player.deck]

        assert run_state.player.obtain_relic("NEW_LEAF")
        new_ids = [card.card_id for card in run_state.player.deck]
        assert original_ids != new_ids
