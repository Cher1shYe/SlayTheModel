"""Audited Primal Force transformations and Reave public draw-suffix memory."""
from dataclasses import dataclass
from sts2_env.gym_env.action_space import action_to_card_and_target


MORPH_EXTRA = tuple(t+s for t in ("PRIMAL_FORCE", "REAVE", "GIANT_ROCK", "SOUL") for s in ("", "+"))


@dataclass(frozen=True)
class CardTransformation:
    decision: int
    hand_index: int
    source_token: str
    result_token: str
    cause: str


def transformations_after(info, action, ended):
    if ended or info.choice is not None or action == 0:
        return ()
    from .deck_observation import prototype
    index, _ = action_to_card_and_target(action)
    cause = info.hand[index]
    if cause.removesuffix("+") != "PRIMAL_FORCE":
        return ()
    result = "GIANT_ROCK" + ("+" if cause.endswith("+") else "")
    return tuple(CardTransformation(info.history.decisions + 1, i - int(i > index), t, result, cause)
                 for i,t in enumerate(info.hand) if i != index and prototype(t).is_attack)


def validate_transformations(events, decisions, tokens):
    from .deck_observation import prototype
    if type(events) is not tuple:
        raise ValueError("Transformation history must be immutable")
    last = (0, -1)
    for e in events:
        if (type(e) is not CardTransformation or type(e.decision) is not int
                or not 1 <= e.decision <= decisions or type(e.hand_index) is not int
                or not 0 <= e.hand_index < 9 or (e.decision, e.hand_index) <= last
                or e.source_token not in tokens or not prototype(e.source_token).is_attack
                or e.cause not in ("PRIMAL_FORCE", "PRIMAL_FORCE+")
                or e.result_token != "GIANT_ROCK" + ("+" if e.cause.endswith("+") else "")):
            raise ValueError("Invalid public transformation")
        last = (e.decision, e.hand_index)


def advance_positions(before, action, after_hand, ended):
    """Track nonoverlapping prefix/suffix; only newly drawn visible cards are read.

The unknown middle's order never enters this function. If all remaining draw
cards are known, normalize them into one prefix. A reshuffle loses old positions.
"""
    if ended:
        return (), ()
    if type(after_hand) is not tuple:
        raise ValueError("Position tracking needs visible post-action hand")
    from .deck_observation import prototype
    top, bottom = before.known_top, before.known_bottom
    total = len(before.draw_composition)
    drawn = 0
    if before.choice is not None:
        if before.pending_card is None:
            # A choice that is not bound to a pending card cannot move known
            # draw positions; keep the visible prefix/suffix unchanged.
            return top, bottom
        token = before.pending_card.token.removesuffix("+")
        if token in ("HEADBUTT","THINKING_AHEAD"):
            top = (before.choice.options[action - 1].card.token,) + top
            total += 1
        elif token == "BURNING_PACT":
            drawn = len(after_hand) - len(before.hand) + 1
    elif action == 0:
        # Burn resolves from hand into discard before the retention/flush hook.
        # It can be drawn again, but is never part of the retained prefix.
        survivors = tuple(t for t in before.hand if t != "BURN" and not prototype(t).is_ethereal)
        retained = tuple(t for t in survivors if prototype(t).is_retain)
        if before.retain_hand:
            retained += tuple(t for t in survivors if not prototype(t).is_retain)
        if after_hand[:len(retained)] != retained:
            raise ValueError("Retained order mismatch")
        drawn = len(after_hand) - len(retained)
    else:
        index, _ = action_to_card_and_target(action)
        token = before.hand[index].removesuffix("+")
        if token == "REAVE":
            bottom += ("SOUL+" if before.hand[index].endswith("+") else "SOUL",)
            total += 1
        elif token == "HEADBUTT" and len(before.discard) == 1:
            top = before.discard + top
            total += 1
        elif token == "STOKE":
            drawn = len(after_hand)
        elif token in ("THINKING_AHEAD","PILLAGE","IMPATIENCE","BATTLE_TRANCE","POMMEL_STRIKE", "SHRUG_IT_OFF", "OFFERING", "BURNING_PACT", "RESTLESSNESS", "FINESSE", "FLASH_OF_STEEL", "MASTER_OF_STRATEGY", "SCRAWL", "SOUL"):
            drawn = len(after_hand) - len(before.hand) + 1
            if token == "BURNING_PACT" and len(before.hand) == 2:
                drawn += 1
    if drawn < 0:
        raise ValueError("Negative visible draw count")
    visible = after_hand[-drawn:] if drawn else ()
    for i in range(min(drawn, total)):
        expected = top[i] if i < len(top) else bottom[i - (total-len(bottom))] if i >= total-len(bottom) else None
        if expected is not None and visible[i] != expected:
            # Hand growth may include a card added to hand rather than drawn, so
            # the visible suffix cannot always be attributed to the known order.
            # Forget the prefix/suffix instead of asserting an unverified order.
            return (), ()
    top = top[drawn:]
    bottom = bottom[max(0, drawn-(total-len(bottom))):]
    remaining = max(0, total-drawn)
    if len(top) + len(bottom) == remaining:
        top, bottom = top + bottom, ()
    return top, bottom
