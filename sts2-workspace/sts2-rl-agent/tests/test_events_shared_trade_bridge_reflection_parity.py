"""Parity tests for shared and Act 2 event trade, bridge, and reflection paths."""

import sts2_env.events.act2  # noqa: F401
import sts2_env.events.shared  # noqa: F401

from sts2_env.cards.factory import create_card
from sts2_env.cards.ironclad import create_ironclad_starter_deck
from sts2_env.cards.status import make_bad_luck, make_spore_mind
from sts2_env.core.enums import CardId
from sts2_env.events.act2 import RelicTrader, SlipperyBridge, Symbiote
from sts2_env.events.shared import LostWisp, Reflections
from sts2_env.run.run_manager import RunManager
from sts2_env.run.run_state import PlayerState, RunState


def _make_run_state(seed: int = 91) -> RunState:
    run_state = RunState(seed=seed, character_id="Ironclad")
    run_state.initialize_run()
    run_state.player.deck = create_ironclad_starter_deck()
    return run_state


class _NoopShuffleRng:
    def shuffle(self, seq) -> None:
        pass


class _FirstChoiceRng:
    def __init__(self) -> None:
        self.choice_calls = 0

    def choice(self, seq):
        self.choice_calls += 1
        return seq[0]


class _LastChoiceRng:
    def __init__(self) -> None:
        self.choice_calls = 0

    def choice(self, seq):
        self.choice_calls += 1
        return seq[-1]


def test_relic_trader_excludes_starter_relics_and_swaps_selected_relic():
    run_state = _make_run_state(91)
    run_state.current_act_index = 1
    for relic_id in ("ANCHOR", "VAJRA", "BONE_FLUTE", "JUZU_BRACELET", "LANTERN"):
        run_state.player.obtain_relic(relic_id)

    event = RelicTrader()
    event.rng = _NoopShuffleRng()
    options = event.generate_initial_options(run_state)

    assert len(options) == 3
    assert "BURNING_BLOOD" not in event._owned_relic_choices  # noqa: SLF001
    old_relic = event._owned_relic_choices[0]  # noqa: SLF001
    new_relic = event._new_relic_choices[0]  # noqa: SLF001
    starting_relics = len(run_state.player.relics)

    result = event.choose(run_state, "trade_0")

    assert result.finished
    assert len(run_state.player.relics) == starting_relics
    assert old_relic not in run_state.player.relics
    assert new_relic in run_state.player.relics


def test_relic_trader_uses_event_rng_without_advancing_up_front_rng():
    run_state = _make_run_state(911)
    run_state.current_act_index = 1
    for relic_id in ("ANCHOR", "VAJRA", "BONE_FLUTE", "JUZU_BRACELET", "LANTERN"):
        run_state.player.obtain_relic(relic_id)
    event = RelicTrader()
    up_front_counter = run_state.rng.up_front.counter

    options = event.generate_initial_options(run_state)

    assert len(options) == 3
    assert run_state.rng.up_front.counter == up_front_counter


def test_relic_trader_requires_all_players_to_have_five_tradable_relics():
    run_state = _make_run_state(912)
    run_state.current_act_index = 1
    for relic_id in ("ANCHOR", "VAJRA", "BONE_FLUTE", "JUZU_BRACELET", "LANTERN"):
        run_state.player.obtain_relic(relic_id)
    ally = run_state.add_player(PlayerState(player_id=2, character_id="Silent"))
    for relic_id in ("BAG_OF_PREPARATION", "AKABEKO", "ART_OF_WAR", "BAG_OF_MARBLES"):
        ally.obtain_relic(relic_id)

    event = RelicTrader()

    assert event.is_allowed(run_state) is False

    ally.obtain_relic("CENTENNIAL_PUZZLE")

    assert event.is_allowed(run_state) is True


def test_relic_trader_uses_reference_tradable_relic_rules():
    run_state = _make_run_state(913)
    run_state.current_act_index = 1
    for relic_id in (
        "ANCHOR",
        "VAJRA",
        "BONE_FLUTE",
        "JUZU_BRACELET",
        "LANTERN",
        "PEAR",
        "BYRDPIP",
        "SEA_GLASS",
        "LEES_WAFFLE",
        "LIZARD_TAIL",
    ):
        run_state.player.obtain_relic(relic_id)
    lizard_tail = next(relic for relic in run_state.player.relic_objects if relic.relic_id.name == "LIZARD_TAIL")
    lizard_tail._was_used = True  # noqa: SLF001

    event = RelicTrader()
    event.rng = _NoopShuffleRng()
    options = event.generate_initial_options(run_state)

    assert len(options) == 3
    assert event._owned_relic_choices == ["ANCHOR", "BONE_FLUTE", "JUZU_BRACELET"]  # noqa: SLF001
    assert "PEAR" not in event._owned_relic_choices  # noqa: SLF001
    assert "BYRDPIP" not in event._owned_relic_choices  # noqa: SLF001
    assert "SEA_GLASS" not in event._owned_relic_choices  # noqa: SLF001
    assert "LEES_WAFFLE" not in event._owned_relic_choices  # noqa: SLF001
    assert "LIZARD_TAIL" not in event._owned_relic_choices  # noqa: SLF001


def test_relic_trader_sorts_tradable_relics_before_shuffling_like_stable_shuffle():
    run_state = _make_run_state(914)
    run_state.current_act_index = 1
    for relic_id in ("VAJRA", "LANTERN", "ANCHOR", "JUZU_BRACELET", "BONE_FLUTE"):
        run_state.player.obtain_relic(relic_id)
    event = RelicTrader()
    event.rng = _NoopShuffleRng()

    event.generate_initial_options(run_state)

    assert event._owned_relic_choices == ["ANCHOR", "BONE_FLUTE", "JUZU_BRACELET"]  # noqa: SLF001


def test_slippery_bridge_hold_on_escalates_damage_and_overcome_removes_card():
    run_state = _make_run_state(92)
    run_state.total_floor = 7
    event = SlipperyBridge()

    options = event.generate_initial_options(run_state)
    assert options[1].description == "Take 3 damage, reroll card"

    starting_hp = run_state.player.current_hp
    first = event.choose(run_state, "hold_on")
    assert not first.finished
    assert run_state.player.current_hp == starting_hp - 3
    assert first.next_options[1].description == "Take 4 damage, reroll card"

    second = event.choose(run_state, "hold_on")
    assert not second.finished
    assert run_state.player.current_hp == starting_hp - 7
    assert second.next_options[1].description == "Take 5 damage, reroll card"

    deck_before = len(run_state.player.deck)
    overcome = event.choose(run_state, "overcome")
    assert overcome.finished
    assert len(run_state.player.deck) == deck_before - 1


def test_slippery_bridge_preselects_non_basic_card_and_overcome_removes_it():
    run_state = _make_run_state(921)
    run_state.total_floor = 7
    strike = create_card(CardId.STRIKE_IRONCLAD)
    skill = create_card(CardId.SHRUG_IT_OFF)
    anger = create_card(CardId.ANGER)
    run_state.player.deck = [strike, skill, anger]
    event = SlipperyBridge()
    event.rng = _FirstChoiceRng()
    niche_counter = run_state.rng.niche.counter

    options = event.generate_initial_options(run_state)
    assert [option.option_id for option in options] == ["overcome", "hold_on"]
    assert event.rng.choice_calls == 1
    assert event._random_card_to_lose is skill  # noqa: SLF001

    result = event.choose(run_state, "overcome")

    assert result.finished
    assert event.rng.choice_calls == 1
    assert run_state.rng.niche.counter == niche_counter
    assert skill not in run_state.player.deck
    assert strike in run_state.player.deck
    assert anger in run_state.player.deck


def test_slippery_bridge_hold_on_rerolls_away_from_previous_card_type():
    run_state = _make_run_state(922)
    run_state.total_floor = 7
    strike = create_card(CardId.STRIKE_IRONCLAD)
    bash = create_card(CardId.BASH)
    anger = create_card(CardId.ANGER)
    run_state.player.deck = [strike, bash, anger]
    event = SlipperyBridge()
    event.rng = _LastChoiceRng()

    event.generate_initial_options(run_state)
    assert event._random_card_to_lose is anger  # noqa: SLF001

    result = event.choose(run_state, "hold_on")

    assert result.finished is False
    assert event.rng.choice_calls == 2
    assert event._random_card_to_lose is bash  # noqa: SLF001


def test_slippery_bridge_hold_on_damage_can_end_run_before_next_options():
    mgr = RunManager(seed=9221, character_id="Ironclad")
    mgr.run_state.total_floor = 7
    mgr.run_state.player.deck = [create_card(CardId.STRIKE_IRONCLAD)]
    mgr.run_state.player.current_hp = 3
    mgr._phase = RunManager.PHASE_EVENT
    event = SlipperyBridge()
    mgr._event_model = event
    mgr._event_started = True
    mgr._event_options = event.generate_initial_options(mgr.run_state)

    result = mgr._do_event_choice({"option_id": "hold_on"})

    assert result["phase"] == RunManager.PHASE_RUN_OVER
    assert mgr.run_state.is_over
    assert mgr.run_state.player.current_hp == 0
    assert mgr._event_options[1].description == "Take 3 damage, reroll card"


def test_slippery_bridge_requires_all_players_to_have_removable_cards():
    run_state = _make_run_state(923)
    run_state.total_floor = 7
    ally = run_state.add_player(PlayerState(player_id=2, character_id="Silent"))
    eternal_card = create_card(CardId.STRIKE_IRONCLAD)
    eternal_card.keywords = frozenset({"eternal"})
    ally.deck = [eternal_card]
    event = SlipperyBridge()

    assert event.is_allowed(run_state) is False

    ally.deck = [create_card(CardId.STRIKE_IRONCLAD)]
    assert event.is_allowed(run_state) is True

    run_state.total_floor = 6
    assert event.is_allowed(run_state) is False


def test_symbiote_kill_fire_transforms_selected_card_via_pending_choice():
    run_state = _make_run_state(93)
    target_card = run_state.player.deck[0]
    original_id = target_card.card_id
    event = Symbiote()

    locked_state = _make_run_state(931)
    locked_state.player.deck = [make_spore_mind(), make_spore_mind()]
    locked_options = event.generate_initial_options(locked_state)
    assert [option.enabled for option in locked_options] == [False, True]

    result = event.choose(run_state, "kill_fire")

    assert not result.finished
    assert event.pending_choice is not None
    assert event.pending_choice.options[0].card is target_card

    resolved = event.resolve_pending_choice(0)

    assert resolved.finished
    assert event.pending_choice is None
    assert target_card.card_id != original_id


def test_symbiote_deferred_kill_fire_uses_event_rng_for_transform_result():
    mgr = RunManager(seed=932, character_id="Ironclad")
    first = create_card(CardId.STRIKE_IRONCLAD)
    second = create_card(CardId.DEFEND_IRONCLAD)
    mgr.run_state.player.deck = [first, second]
    mgr._phase = RunManager.PHASE_EVENT
    event = Symbiote()
    event.rng = _LastChoiceRng()
    mgr._event_model = event
    mgr._event_options = event.generate_initial_options(mgr.run_state)
    niche_counter = mgr.run_state.rng.niche.counter

    result = mgr._do_event_choice({"option_id": "kill_fire"})

    assert result["phase"] == RunManager.PHASE_CARD_REWARD
    assert event.rng.choice_calls == 0
    assert mgr.run_state.pending_choice is not None

    final = mgr.take_action({"action": "choose", "index": 0})

    assert final["phase"] == RunManager.PHASE_MAP_CHOICE
    assert event.rng.choice_calls == 1
    assert mgr.run_state.rng.niche.counter == niche_counter
    assert first.card_id != CardId.STRIKE_IRONCLAD
    assert second.card_id == CardId.DEFEND_IRONCLAD


def test_lost_wisp_search_grants_the_rolled_gold_amount():
    run_state = _make_run_state(94)
    event = LostWisp()

    options = event.generate_initial_options(run_state)
    gold_option = next(option for option in options if option.option_id == "search")
    expected_gold = event._gold  # noqa: SLF001
    starting_gold = run_state.player.gold

    result = event.choose(run_state, "search")

    assert gold_option.description == f"Gain {expected_gold} gold"
    assert result.finished
    assert run_state.player.gold == starting_gold + expected_gold


def test_reflections_touch_downgrades_two_and_upgrades_four_cards():
    run_state = _make_run_state(95)
    run_state.player.deck = [
        create_card(CardId.STRIKE_IRONCLAD, upgraded=True),
        create_card(CardId.DEFEND_IRONCLAD, upgraded=True),
        create_card(CardId.BASH),
        create_card(CardId.ANGER),
        create_card(CardId.SHRUG_IT_OFF),
        create_card(CardId.POMMEL_STRIKE),
    ]
    event = Reflections()

    result = event.choose(run_state, "touch")

    assert result.finished
    assert len(run_state.player.deck) == 6
    assert sum(1 for card in run_state.player.deck if card.upgraded) == 4


def test_reflections_touch_uses_event_rng_and_can_reupgrade_downgraded_cards():
    run_state = _make_run_state(951)
    first = create_card(CardId.STRIKE_IRONCLAD, upgraded=True)
    second = create_card(CardId.DEFEND_IRONCLAD, upgraded=True)
    third = create_card(CardId.BASH)
    fourth = create_card(CardId.ANGER)
    run_state.player.deck = [first, second, third, fourth]
    event = Reflections()
    event.rng = _FirstChoiceRng()
    niche_counter = run_state.rng.niche.counter
    rewards_counter = run_state.rng.rewards.counter

    result = event.choose(run_state, "touch")

    assert result.finished
    assert event.rng.choice_calls == 6
    assert run_state.rng.niche.counter == niche_counter
    assert run_state.rng.rewards.counter == rewards_counter
    assert first.upgraded is True
    assert second.upgraded is True
    assert third.upgraded is True
    assert fourth.upgraded is True


def test_reflections_shatter_duplicates_deck_and_adds_bad_luck():
    run_state = _make_run_state(96)
    run_state.player.deck = [
        create_card(CardId.BASH),
        create_card(CardId.ANGER),
    ]
    event = Reflections()

    result = event.choose(run_state, "shatter")

    assert result.finished
    assert len(run_state.player.deck) == 5
    assert sum(1 for card in run_state.player.deck if card.card_id == CardId.BASH) == 2
    assert sum(1 for card in run_state.player.deck if card.card_id == CardId.ANGER) == 2
    assert any(card.card_id == make_bad_luck().card_id for card in run_state.player.deck)
    assert len({card.instance_id for card in run_state.player.deck}) == len(run_state.player.deck)
