from dataclasses import replace

import pytest

from sts2_env.az.boss_cards import CODEC, TOKENS, MAX_CARDS, ACTION_SIZE, card_capacity, single_choice_mask, purity_mask
from sts2_env.az.choice_state import capture_choice
from sts2_env.az.g1 import SUMMON_CODEC
from sts2_env.cards.ironclad import create_ironclad_starter_deck, make_headbutt, make_armaments
from sts2_env.cards.colorless import make_purity
from sts2_env.cards.status import make_burn, make_wound
from sts2_env.core.combat import CombatState
from sts2_env.core.enums import CardId, PowerId
from sts2_env.core.rng import Rng
from sts2_env.monsters.act3 import create_test_subject


def combat():
    world = CombatState(2000, 2000, create_ironclad_starter_deck(), 3, character_id="Ironclad")
    enemy, ai = create_test_subject(Rng(3))
    world.add_enemy(enemy, ai)
    world.start_combat()
    for pile in (world.hand, world.draw_pile, world.discard_pile, world.exhaust_pile):
        pile.clear()
    return world


@pytest.mark.parametrize("factory", [make_burn, make_wound])
def test_status_codec_roundtrip_and_legacy_rejection(factory):
    card = factory()
    state = CODEC.capture(card)
    restored = CODEC.restore(state)
    assert CODEC.capture(restored) == state
    assert restored is not card
    assert "unplayable" in restored.keywords
    assert "ethereal" not in restored.keywords
    assert state.token in TOKENS and state.token + "+" not in TOKENS
    with pytest.raises(ValueError):
        CODEC.validate(replace(state, token=state.token + "+"))
    with pytest.raises(ValueError):
        SUMMON_CODEC.capture(card)


@pytest.mark.parametrize("block,loss", [(0, 2), (1, 1), (2, 0), (10, 0)])
@pytest.mark.parametrize("factory", [make_burn, make_wound])
def test_status_end_of_turn_damage_uses_native_block(factory, block, loss):
    world = combat()
    card = CODEC.restore(CODEC.capture(factory()))
    card.owner = world.player
    world.hand[:] = [card]
    world.player.block = block
    before = world.player.current_hp
    world._execute_turn_end_in_hand_effect(card, 1)
    assert before - world.player.current_hp == (loss if card.card_id == CardId.BURN else 0)


@pytest.mark.parametrize("retain", [False, True])
def test_burn_and_wound_retention_is_not_dazed_ethereal(retain):
    world = combat()
    burn, wound = make_burn(), make_wound()
    for card in (burn, wound):
        card.owner = world.player
    world.hand[:] = [burn, wound]
    world.player.block = 100
    if retain:
        world.player.apply_power(PowerId.RETAIN_HAND, 1)
    world.end_player_turn()
    assert world.player.current_hp == 2000
    assert burn not in world.exhaust_pile and wound not in world.exhaust_pile
    # Without retain both may already have been shuffled and drawn next turn;
    # neither is destroyed by the end-of-turn effect.
    all_cards = world.hand + world.draw_pile + world.discard_pile
    assert burn in all_cards and wound in all_cards
    if retain:
        assert burn in world.hand and wound in world.hand


def test_headbutt_can_choose_last_of_2145_public_candidates():
    world = combat()
    world.hand[:] = [make_headbutt()]
    world.discard_pile[:] = [make_wound() for _ in range(MAX_CARDS - 1)] + [make_burn()]
    last = world.discard_pile[-1]
    assert world.play_card(0, 0)
    choice = world.pending_choice
    assert choice is not None and choice.num_options == MAX_CARDS
    public = capture_choice(choice, {"discard": world.discard_pile}, CODEC,
                            mechanism="HEADBUTT", action_size=ACTION_SIZE)
    assert public.legal_mask(CODEC, ACTION_SIZE) == single_choice_mask(MAX_CARDS)
    assert public.decode_action(MAX_CARDS, CODEC, ACTION_SIZE) == MAX_CARDS - 1
    assert world.resolve_pending_choice(MAX_CARDS - 1)
    assert world.pending_choice is None and world.draw_pile[0] is last


def test_atomic_purity_still_uses_only_low_nine_bits():
    mask = purity_mask(9, 1, 3, False)
    assert len(mask) == ACTION_SIZE
    assert sum(mask) == 129
    assert not any(mask[512:])
    world = combat()
    world.hand[:] = [make_purity(), make_burn(), make_wound()]
    assert world.play_card(0, 0)
    assert world.pending_choice is not None
    assert world.resolve_pending_choice(0)
    assert world.resolve_pending_choice(1)
    assert world.resolve_pending_choice(None)
    assert world.pending_choice is None
    assert {c.card_id for c in world.exhaust_pile} >= {CardId.BURN, CardId.WOUND}


def test_armaments_does_not_create_upgraded_status_cards():
    world = combat()
    world.hand[:] = [make_armaments(upgraded=True), make_burn(), make_wound()]
    assert world.play_card(0, 0)
    assert world.pending_choice is None
    assert [CODEC.capture(c).token for c in world.hand] == ["BURN", "WOUND"]


def test_capacity_derivation_and_overflow_rejection():
    assert MAX_CARDS == 2145 and MAX_CARDS + 1 < ACTION_SIZE
    assert card_capacity(0, 0, 20) == 20
    assert card_capacity(1, 1, 20) == 27
    with pytest.raises(ValueError):
        single_choice_mask(MAX_CARDS + 1)
    with pytest.raises(ValueError):
        single_choice_mask(True)
    with pytest.raises(ValueError):
        card_capacity(True)
