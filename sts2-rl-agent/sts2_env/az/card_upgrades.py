"""Public upgrade events and chronological inventory accounting."""
from .content import BOSS_CONTENT, EXPANSION_CONTENT
from collections import Counter
from dataclasses import dataclass

from .card_generation import CardGeneration, generated_tokens


@dataclass(frozen=True)
class CardUpgrade:
    decision: int
    hand_index: int
    source_token: str
    result_token: str
    cause: str


NON_UPGRADABLE_TOKENS = ("DAZED", "BURN", "WOUND")  # native status factories cannot upgrade


def upgradable(token):
    """Publicly upgradable card tokens; an engine no-op is not a public upgrade."""
    return token not in NON_UPGRADABLE_TOKENS


def upgrades_after(info, action, combat_ended):
    if combat_ended:
        return ()
    if info.choice is not None:
        if info.pending_card is None or info.pending_card.token != "ARMAMENTS":
            return ()
        option = info.choice.options[action - 1]
        if not upgradable(option.card.token):
            return ()  # native upgrade_card returns the card unchanged
        pairs, cause = [(option.index, option.card.token)], "ARMAMENTS"
    elif action:
        from sts2_env.gym_env.action_space import action_to_card_and_target
        index, _ = action_to_card_and_target(action)
        cause = info.hand[index]
        if cause not in ("ARMAMENTS", "ARMAMENTS+"):
            return ()
        pairs = [(i - int(i > index), token) for i,token in enumerate(info.hand)
                 if i != index and not token.endswith("+") ]
        if cause == "ARMAMENTS" and len(pairs) != 1:
            return ()  # zero candidates or a pending explicit choice
    else:
        return ()
    return tuple(CardUpgrade(info.history.decisions + 1, i, token, token + "+", cause) for i,token in pairs if upgradable(token))


def inventory(known_deck, generated, upgraded, decisions, content_version=None, transformed=()):
    generated_tokens(generated, decisions, content_version)
    if type(upgraded) is not tuple:
        raise ValueError("Upgrade ledger must be immutable")
    from .g1 import UP_TOKENS, TOP_TOKENS, LIFE_TOKENS, SEL_TOKENS, MORPH_TOKENS
    from .content import TOP_CONTENT, LIFE_CONTENT, SEL_CONTENT, SET_CONTENT, MORPH_CONTENT, MULTI_CONTENT
    from .summon import DAZED_MECHANISM, SUMMON_CONTENT
    tokens = MORPH_TOKENS if content_version in (MORPH_CONTENT, MULTI_CONTENT, SUMMON_CONTENT, BOSS_CONTENT, EXPANSION_CONTENT) else SEL_TOKENS if content_version in (SEL_CONTENT, SET_CONTENT, MORPH_CONTENT, MULTI_CONTENT) else LIFE_TOKENS if content_version == LIFE_CONTENT else TOP_TOKENS if content_version == TOP_CONTENT else UP_TOKENS
    if content_version == EXPANSION_CONTENT:
        from .content_expansion import TOKENS as tokens
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
    if transformed and content_version not in (MORPH_CONTENT, MULTI_CONTENT, SUMMON_CONTENT, BOSS_CONTENT, EXPANSION_CONTENT):
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
        if kind == 0 and type(event) is CardGeneration and event.mechanism in (DAZED_MECHANISM, "boss-wound-v1", "boss-burn-v1"):
            # An audited enemy move has no deck source: it adds its own copies.
            if content_version not in (SUMMON_CONTENT, BOSS_CONTENT, EXPANSION_CONTENT):
                raise ValueError("Enemy-generated cards require the summon content")
            counts[event.result_token] += event.count
            continue
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
