"""Native nesting/choice regression fixtures; no training data."""
import sts2_env.powers
from sts2_env.core.combat import CombatState
from sts2_env.core.rng import Rng
from sts2_env.cards import ironclad as cards
from sts2_env.monsters.act1_weak import create_shrinker_beetle


def world(hand,draw):
    w=CombatState(player_hp=80,player_max_hp=80,deck=[],rng_seed=8)
    e,ai=create_shrinker_beetle(Rng(8));w.add_enemy(e,ai);w.start_combat()
    w.hand=hand;w.draw_pile=draw;w.energy=5
    for c in hand+draw:c.owner=w.player
    return w


def test_havoc_returns_outer_card_to_discard():
    w=world([cards.make_havoc()],[cards.make_strike_ironclad()])
    assert w.play_card(0)
    assert not w.play_pile and w._pending_play is None
    assert [c.card_id.name for c in w.exhaust_pile]==['STRIKE_IRONCLAD']
    assert [c.card_id.name for c in w.discard_pile]==['HAVOC']
    assert [c.card_id.name for c in w._played_cards_this_turn]==['STRIKE_IRONCLAD','HAVOC']
    assert not w._play_continuations


def test_cascade_batch_survives_nested_havoc_hand_choice():
    w=world([cards.make_cascade(),cards.make_defend_ironclad(),cards.make_bash()],
            [cards.make_havoc(),cards.make_strike_ironclad(),cards.make_true_grit(upgraded=True)])
    w.energy=2
    assert w.play_card(0)
    assert w.pending_choice is not None
    assert len(w._play_continuations)==3
    assert w.resolve_pending_choice(0)
    assert w.pending_choice is None and w._pending_play is None
    assert not w.play_pile and not w._play_continuations
    assert [c.card_id.name for c in w._played_cards_this_turn]==['TRUE_GRIT','HAVOC','STRIKE_IRONCLAD','CASCADE']


