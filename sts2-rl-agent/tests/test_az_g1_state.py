"""G1 foundation tests; these do not claim complete planner admission."""
from dataclasses import asdict, replace
from functools import partial
import json

import pytest

from sts2_env.az.card_state import CardStateCodec, CardStatePolicy
from sts2_env.az.choice_state import capture_choice
from sts2_env.az.decks import EXPANDED_FACTORIES
from sts2_env.cards import base
from sts2_env.cards.ironclad import make_true_grit, make_burning_pact
from sts2_env.core.combat import CombatState
from sts2_env.core.rng import Rng
from sts2_env.core.selection import CardChoiceOption, PendingCardChoice
from sts2_env.gym_env.action_space import get_action_mask
from sts2_env.monsters.act1_weak import create_shrinker_beetle


FACTORIES = {name + suffix: partial(factory, upgraded=bool(suffix))
             for name, factory in EXPANDED_FACTORIES.items() for suffix in ("", "+")}
CODEC = CardStateCodec(FACTORIES)
MUTABLE = CardStateCodec(FACTORIES, CardStatePolicy(temporary_cost=True, combat_cost=True, retain=True))


@pytest.mark.parametrize("token", FACTORIES)
def test_card_roundtrip_and_id_isolation(token):
    card = FACTORIES[token]()
    saved = base._next_instance_id
    state = CODEC.capture(card)
    assert base._next_instance_id == saved
    card.instance_id += 100000
    assert CODEC.capture(card) == state
    restored = CODEC.restore(state)
    assert CODEC.capture(restored) == state
    assert restored is not card and restored.instance_id != card.instance_id
    assert "instance_id" not in json.dumps(asdict(state))
    restored.effect_vars["new"] = 1
    assert "new" not in card.effect_vars and "new" not in dict(state.effect_vars)


@pytest.mark.parametrize("token", ["BASH", "BLUDGEON", "BODY_SLAM+"])
def test_temporary_cost_and_retain_lifecycle(token):
    card = FACTORIES[token]()
    card.set_temporary_cost_for_turn(0)
    card.single_turn_retain = True
    with pytest.raises(ValueError):
        CODEC.capture(card)
    state = MUTABLE.capture(card)
    hypothetical = MUTABLE.restore(state)
    card.end_of_turn_cleanup()
    hypothetical.end_of_turn_cleanup()
    assert MUTABLE.capture(card) == MUTABLE.capture(hypothetical)
    assert hypothetical.cost == hypothetical.original_cost
    assert not hypothetical.single_turn_retain
    assert state.turn_cost == 0 and state.single_turn_retain


def test_cost_cleanup_follows_engine_even_after_combat_cost_change():
    card = FACTORIES["BLUDGEON"]()
    card.set_combat_cost(2)
    state = MUTABLE.capture(card)
    restored = MUTABLE.restore(state)
    restored.end_of_turn_cleanup()
    assert restored.cost == 2
    card.set_temporary_cost_for_turn(0)
    restored = MUTABLE.restore(MUTABLE.capture(card))
    card.end_of_turn_cleanup()
    restored.end_of_turn_cleanup()
    assert card.cost == restored.cost == 3  # actual engine lifecycle, not invented stacking


@pytest.mark.parametrize("mutation", [
    lambda c: c.combat_vars.update(secret_future_rng=3),
    lambda c: c.combat_vars.update(_stars_spent_for_play=1),
    lambda c: setattr(c, "bound", True),
    lambda c: setattr(c, "base_damage", 999),
    lambda c: setattr(c, "unregistered_counter", 1),
])
def test_unknown_mutations_rejected(mutation):
    card = FACTORIES["BASH"]()
    mutation(card)
    with pytest.raises(ValueError):
        MUTABLE.capture(card)


def test_bad_state_and_schema_rejected():
    state = MUTABLE.capture(FACTORIES["BASH"]())
    for changed in (replace(state, version="future"), replace(state, token="UNKNOWN"),
                    replace(state, cost=True), replace(state, turn_cost=0),
                    replace(state, effect_vars=(("vulnerable", 2), ("vulnerable", 2)))):
        with pytest.raises(ValueError):
            MUTABLE.restore(changed)


def world():
    combat = CombatState(80, 80, [], 0, character_id="Ironclad")
    enemy, ai = create_shrinker_beetle(Rng(0))
    combat.add_enemy(enemy, ai)
    combat.start_combat()
    return combat


def piles(combat):
    return dict(hand=combat.hand, discard=combat.discard_pile, exhaust=combat.exhaust_pile)


@pytest.mark.parametrize("factory", [partial(make_true_grit, upgraded=True), make_burning_pact])
def test_native_card_choice_capture_matches_engine_and_continues(factory):
    combat = world()
    combat.hand = [factory(), FACTORIES["STRIKE_IRONCLAD"](), FACTORIES["DEFEND_IRONCLAD"]()]
    combat.draw_pile = [FACTORIES["BASH"](), FACTORIES["IRON_WAVE"]()]
    assert combat.play_card(0)
    choice = capture_choice(combat.pending_choice, piles(combat), CODEC, mechanism="exhaust-hand")
    assert choice.legal_mask(CODEC) == tuple(bool(x) for x in get_action_mask(combat))
    assert not choice.legal_mask(CODEC)[0]
    assert combat.resolve_pending_choice(choice.decode_action(2, CODEC))
    assert combat.pending_choice is None
    assert combat.exhaust_pile[0].card_id.name == "DEFEND_IRONCLAD"
    assert not combat.play_pile  # native pending play has resumed


def test_multiselect_toggle_confirm_order_and_duplicate_cards():
    combat = world()
    combat.hand = [FACTORIES["BASH"]() for _ in range(3)]
    selected = []
    combat.request_multi_card_choice(prompt="test", cards=list(reversed(combat.hand)), source_pile="hand",
                                     resolver=selected.extend, min_count=1, max_count=2)
    for action in (1, 2, 1, 3, 0):
        state = capture_choice(combat.pending_choice, piles(combat), CODEC, mechanism="test-selection")
        assert state.legal_mask(CODEC) == tuple(bool(x) for x in get_action_mask(combat))
        if action == 0:
            assert state.selected == (1, 2)
            assert not state.legal_mask(CODEC)[1]
        assert combat.resolve_pending_choice(state.decode_action(action, CODEC))
    assert selected == [combat.hand[1], combat.hand[0]]


def test_public_refs_bind_to_independent_cards_without_resolver_or_rng():
    hand = [FACTORIES["BASH"](), FACTORIES["BASH"]()]
    choice = PendingCardChoice("private prompt is not a feature", [CardChoiceOption(c, "hand") for c in hand],
                               lambda _: (_ for _ in ()).throw(AssertionError("real resolver invoked")))
    state = capture_choice(choice, {"hand": hand}, CODEC, mechanism="test")
    cloned = [CODEC.restore(CODEC.capture(c)) for c in hand]
    bound = state.bind_options({"hand": cloned}, CODEC)
    assert bound[0] is cloned[0] and bound[1] is cloned[1]
    assert all(c is not hand[i] for i, c in enumerate(bound))
    with pytest.raises(ValueError, match="alias"):
        state.bind_options({"hand": [cloned[0], cloned[0]]}, CODEC)
    assert "resolver" not in json.dumps(asdict(state))
    hand[0].instance_id += 9999
    assert capture_choice(choice, {"hand": hand}, CODEC, mechanism="test") == state
    cloned[0].set_combat_cost(0)
    with pytest.raises(ValueError):
        state.bind_options({"hand": cloned}, CODEC)


def test_skip_and_capacity_are_explicit():
    cards = [FACTORIES["BASH"]() for _ in range(115)]
    choice = PendingCardChoice("test", [CardChoiceOption(c, "hand") for c in cards], lambda _: None, allow_skip=True)
    with pytest.raises(ValueError, match="truncation"):
        capture_choice(choice, {"hand": cards}, CODEC, mechanism="test")
    choice.options.pop()
    state = capture_choice(choice, {"hand": cards}, CODEC, mechanism="test")
    assert len(state.legal_mask(CODEC)) == 115 and all(state.legal_mask(CODEC))
    assert state.decode_action(0, CODEC) is None
    with pytest.raises(ValueError):
        state.decode_action(True, CODEC)
    choice.options[0].source_pile = "draw_pile"
    with pytest.raises(ValueError, match="reveal"):
        capture_choice(choice, {"draw_pile": cards}, CODEC, mechanism="test")


def test_up_to_three_with_only_two_options_matches_engine():
    combat = world()
    combat.hand = [FACTORIES["BASH"](), FACTORIES["BASH"]()]
    combat.request_multi_card_choice(prompt="up to three", cards=list(combat.hand), source_pile="hand",
                                     resolver=lambda _: None, min_count=0, max_count=3, allow_skip=True)
    state = capture_choice(combat.pending_choice, piles(combat), CODEC, mechanism="test")
    assert state.max_choices == 3
    assert state.legal_mask(CODEC) == tuple(bool(x) for x in get_action_mask(combat))
