"""Public upgrade events and chronological inventory accounting."""
from collections import Counter
from dataclasses import dataclass

from .card_generation import generated_tokens


@dataclass(frozen=True)
class CardUpgrade:
    decision: int
    hand_index: int
    source_token: str
    result_token: str
    cause: str


def upgrades_after(info, action, combat_ended):
    if combat_ended:
        return ()
    if info.choice is not None:
        if info.pending_card.token != "ARMAMENTS":
            return ()
        option = info.choice.options[action - 1]
        pairs, cause = [(option.index, option.card.token)], "ARMAMENTS"
    elif action:
        from sts2_env.gym_env.action_space import action_to_card_and_target
        index, _ = action_to_card_and_target(action)
        cause = info.hand[index]
        if cause not in ("ARMAMENTS", "ARMAMENTS+"):
            return ()
        pairs = [(i - int(i > index), token) for i,token in enumerate(info.hand)
                 if i != index and not token.endswith("+")]
        if cause == "ARMAMENTS" and len(pairs) != 1:
            return ()  # zero candidates or a pending explicit choice
    else:
        return ()
    return tuple(CardUpgrade(info.history.decisions + 1, i, token, token + "+", cause) for i,token in pairs)


def inventory(known_deck, generated, upgraded, decisions, content_version=None, transformed=()):
    generated_tokens(generated, decisions, content_version)
    if type(upgraded) is not tuple:
        raise ValueError("Upgrade ledger must be immutable")
    from .g1 import UP_TOKENS, TOP_TOKENS, LIFE_TOKENS, SEL_TOKENS, MORPH_TOKENS
    from .content import TOP_CONTENT, LIFE_CONTENT, SEL_CONTENT, SET_CONTENT, MORPH_CONTENT, MULTI_CONTENT
    tokens = MORPH_TOKENS if content_version in (MORPH_CONTENT, MULTI_CONTENT) else SEL_TOKENS if content_version in (SEL_CONTENT, SET_CONTENT, MORPH_CONTENT, MULTI_CONTENT) else LIFE_TOKENS if content_version == LIFE_CONTENT else TOP_TOKENS if content_version == TOP_CONTENT else UP_TOKENS
    last = (0, -1)
    for event in upgraded:
        if (type(event) is not CardUpgrade or type(event.decision) is not int
                or not 1 <= event.decision <= decisions or type(event.hand_index) is not int
                or not 0 <= event.hand_index < 10 or (event.decision, event.hand_index) <= last
                or event.source_token not in tokens or event.source_token.endswith("+")
                or event.result_token != event.source_token + "+"
                or event.cause not in ("ARMAMENTS", "ARMAMENTS+")):
            raise ValueError("Invalid upgrade event")
        last = (event.decision, event.hand_index)
    from .morph import validate_transformations
    if transformed and content_version not in (MORPH_CONTENT, MULTI_CONTENT):
        raise ValueError("Transformations in legacy content")
    validate_transformations(transformed, decisions, tokens)
    counts = Counter(known_deck)
    events = sorted([(e.decision, 0, e) for e in generated] +
                    [(e.decision, 1, e) for e in upgraded] + [(e.decision, 2, e) for e in transformed], key=lambda x: (x[0], x[1]))
    kinds = {}
    single_choices = set()
    for decision, kind, event in events:
        if decision in kinds and kinds[decision] != kind:
            raise ValueError("Generation and upgrade cannot share a decision")
        kinds[decision] = kind
        if counts[event.source_token] < 1:
            raise ValueError("Card event has no public source")
        if kind == 1:
            if counts[event.cause] < 1:
                raise ValueError("Upgrade has no public Armaments source")
            if event.cause == "ARMAMENTS":
                if decision in single_choices:
                    raise ValueError("Single upgrade changed multiple cards")
                single_choices.add(decision)
            counts[event.source_token] -= 1
        elif kind == 2:
            if counts[event.cause] < 1:
                raise ValueError("Transformation has no public cause")
            counts[event.source_token] -= 1
        counts[event.result_token] += 1
    return +counts
