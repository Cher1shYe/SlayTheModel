"""Audited lifecycle derivation from public turn history, never hidden piles.

Remaining Stomp copies are present from combat start; no admitted effect creates
new Stomps. Primal Force may replace copies with Giant Rocks. Every attack updates
remaining Stomps in ALL zones (including exhaust/play).
Thus all copies share the same turn cost, independent of unknown draw order.
"""
from .decks import make_token
from .deck_observation import prototype


def attack_count(history):
    # Includes the attack that is currently paused at a Headbutt choice: its
    # before-play hook already ran even though its after-play hook has not.
    return sum(prototype(t).is_attack for t in history.played_this_turn)


def restore_token(token, history):
    if token in ("DAZED", "BURN", "WOUND", "SLIMED"):
        from sts2_env.cards import status
        return getattr(status, "make_" + token.lower())()
    card = make_token(token)
    count = attack_count(history)
    if token.removesuffix("+") == "STOMP" and count:
        card.set_temporary_cost_for_turn(max(0, 3 - count))
    return card


def validate_state(state, history):
    if state.version=='az-public-card-state-v2':
        # V4 individual faces, including generated Stomps, are verified against
        # the full public event inventory by card_memory.validate.
        if state.single_turn_retain:raise ValueError('Granted retain is not admitted')
        return state
    expected = max(0, 3 - attack_count(history)) if attack_count(history) else None
    if state.token.removesuffix("+") != "STOMP":
        expected = None
    if state.turn_cost != expected:
        raise ValueError("Card temporary cost disagrees with public attack history")
    if state.single_turn_retain:
        raise ValueError("Granted retain is not admitted")
    return state
