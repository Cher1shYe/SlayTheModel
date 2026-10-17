"""Update known draw prefix using public actions and visible post-action hand only."""
from .content import BOSS_CONTENT, EXPANSION_CONTENT
from sts2_env.gym_env.action_space import action_to_card_and_target


def advance_top(before, action, after_hand, combat_ended):
    if combat_ended:
        return ()  # no subsequent decisions; terminal engine short-circuits effects
    if type(after_hand) is not tuple:
        raise ValueError("Known-draw tracking needs the visible post-action hand")
    top = before.known_top
    if before.choice is not None:
        token = before.pending_card.token.removesuffix("+")
        if token == "HEADBUTT":
            return (before.choice.options[action - 1].card.token,) + top
        baseline = len(before.hand) - int(token in ("BURNING_PACT", "TRUE_GRIT"))
        drawn = len(after_hand) - baseline if token == "BURNING_PACT" else 0
    elif action == 0:
        from .content import LIFE_CONTENT, SEL_CONTENT, SET_CONTENT, MORPH_CONTENT, MULTI_CONTENT, SUMMON_CONTENT
        from .deck_observation import prototype
        retained = tuple(t for t in before.hand if prototype(t).is_retain) if before.content_version in (LIFE_CONTENT, SEL_CONTENT, SET_CONTENT, MORPH_CONTENT, MULTI_CONTENT, SUMMON_CONTENT, BOSS_CONTENT, EXPANSION_CONTENT) else ()
        if before.content_version in (SEL_CONTENT, SET_CONTENT, MORPH_CONTENT, MULTI_CONTENT, SUMMON_CONTENT, BOSS_CONTENT, EXPANSION_CONTENT) and before.retain_hand:
            # Native flush implementation keeps static retain cards first, then
            # all remaining cards in their prior relative order when flush is off.
            retained += tuple(t for t in before.hand if not prototype(t).is_retain)
        if after_hand[:len(retained)] != retained:
            raise ValueError("Retained cards changed order across turn boundary")
        drawn = len(after_hand) - len(retained)
    else:
        index, _ = action_to_card_and_target(action)
        token = before.hand[index].removesuffix("+")
        if token == "HEADBUTT" and len(before.discard) == 1:
            return before.discard + top  # engine auto-resolves one candidate
        drawn = (len(after_hand) - len(before.hand) + 1
                 if token in ("POMMEL_STRIKE", "SHRUG_IT_OFF", "OFFERING", "BURNING_PACT", "RESTLESSNESS", "FINESSE", "FLASH_OF_STEEL", "MASTER_OF_STRATEGY", "SCRAWL") else 0)
        # Burning Pact with one remaining hand card auto-exhausts it before drawing.
        if token == "BURNING_PACT" and len(before.hand) == 2:
            drawn += 1
    if drawn < 0:
        raise ValueError("Unexpected visible draw transition")
    visible_draws = after_hand[-drawn:] if drawn else ()
    expected = top[:drawn]
    if visible_draws[:len(expected)] != expected:
        raise ValueError("Visible draws contradict the public known prefix")
    # Draws consume the prefix first, including when a later draw reshuffles.
    return top[drawn:]
