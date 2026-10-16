"""Audited Boss status cards and capacity for the isolated g2-boss-v1 contract."""
from functools import lru_cache

from sts2_env.cards.status import make_burn, make_wound
from .card_state import CardStateCodec
from .g1 import SUMMON_CODEC, SUMMON_TOKENS
from .choice_sets import set_mask

VERSION = "boss-status-cards-v1"
ACTION_VERSION = "combat-boss4096-v1"
ACTION_SIZE = 4096
TOKENS = (*SUMMON_TOKENS, "BURN", "WOUND")
CODEC = CardStateCodec({**SUMMON_CODEC.factories, "BURN": make_burn, "WOUND": make_wound}, SUMMON_CODEC.policy)


def card_capacity(max_turns=100, max_decisions=400, initial_cards=20):
    """Conservative bound under the audited TestSubject + previous pool rules.

    At most ceil(T/2) claws (3,4,... hits), floor(T/2) pounces in phase 2.
    Each unblocked hit adds one Wound. At most 3*T Burn (or Dazed), at most
    one Anger/Reave generated card per decision. Reave transforms no extras.
    The phases share T, but this loose sum does not rely on subtracting their
    turns. Arbitrary added generators or another player invalidate the bound.
    """
    if any(type(n) is not int or n < 0 for n in (max_turns, max_decisions, initial_cards)):
        raise ValueError("Nonnegative integer budgets required")
    claws = (max_turns + 1) // 2
    wounds = 3 * claws + claws * (claws - 1) // 2 + max_turns // 2
    return initial_cards + max_decisions + wounds + 3 * max_turns


MAX_CARDS = card_capacity()


def single_choice_mask(options, can_confirm=False):
    """Every candidate has a distinct action, including duplicate status cards."""
    if (type(options) is not int or not 0 <= options <= MAX_CARDS
            or options >= ACTION_SIZE or type(can_confirm) is not bool):
        raise ValueError("Boss choice exceeds proven capacity; no truncation")
    return (can_confirm,) + (True,) * options + (False,) * (ACTION_SIZE - options - 1)


@lru_cache(maxsize=32)
def purity_mask(options, min_choices, max_choices, allow_skip):
    # High action indices remain invalid for atomic hand subsets.
    return set_mask(options, min_choices, max_choices, allow_skip, ACTION_SIZE)
