"""Atomic final-set actions for audited Purity choices (selection content v2).

Action bits identify public candidate positions, including duplicate cards.
No engine rule changes: reconcile native toggles, then confirm exactly once.
"""
from .content import BOSS_CONTENT, EXPANSION_CONTENT
from functools import lru_cache

SET_ACTION_SIZE = 512
MAX_SET_OPTIONS = 9  # Purity leaves at most nine cards from the ten-card hand.


@lru_cache(maxsize=32)
def set_mask(option_count, min_choices, max_choices, allow_skip, size=SET_ACTION_SIZE):
    if (type(option_count) is not int or not 1 <= option_count <= MAX_SET_OPTIONS
            or type(min_choices) is not int or type(max_choices) is not int
            or not 0 <= min_choices <= max_choices <= 5 or type(allow_skip) is not bool
            or type(size) is not int or size < (1 << option_count)):
        raise ValueError("Unsupported complete-set choice shape")
    return tuple(a < (1 << option_count)
                 and (min_choices <= a.bit_count() <= max_choices or (a == 0 and allow_skip))
                 for a in range(size))


def public_choice_mask(choice, codec, content):
    from .actions import action_size
    from .content import (SET_CONTENT, MORPH_CONTENT, MULTI_CONTENT, SUMMON_CONTENT,
                          ALL_CONTENT)
    choice.validate(codec, action_size(content))
    if content in (SET_CONTENT, MORPH_CONTENT, MULTI_CONTENT, SUMMON_CONTENT, BOSS_CONTENT, EXPANSION_CONTENT, ALL_CONTENT) and choice.mechanism.removesuffix("+") == "PURITY":
        return set_mask(len(choice.options), choice.min_choices, choice.max_choices, choice.allow_skip,
                        action_size(content))
    return choice.legal_mask(codec, action_size(content))


def is_set_choice(world, content):
    from .content import (SET_CONTENT, MORPH_CONTENT, MULTI_CONTENT, SUMMON_CONTENT,
                          ALL_CONTENT)
    pending = getattr(world, "_pending_play", None)
    return (content in (SET_CONTENT, MORPH_CONTENT, MULTI_CONTENT, SUMMON_CONTENT, BOSS_CONTENT, EXPANSION_CONTENT,
                        ALL_CONTENT) and world.pending_choice is not None
            and pending is not None and pending["card"].card_id.name == "PURITY")


def resolve_choice(world, action, content):
    if not is_set_choice(world, content):
        return world.resolve_pending_choice(None if action == 0 else action - 1)
    from .actions import action_size
    choice = world.pending_choice
    mask = set_mask(choice.num_options, choice.min_choices, choice.max_choices, choice.allow_skip,
                    action_size(content))
    if type(action) is not int or not 0 <= action < len(mask) or not mask[action]:
        raise ValueError("Illegal complete-set action")
    target = {i for i in range(choice.num_options) if action & (1 << i)}
    # Remove before adding so a preselected snapshot can never exceed the cap.
    toggles = sorted(choice.selected_indices - target) + sorted(target - choice.selected_indices)
    for index in toggles:
        if not world.resolve_pending_choice(index) or world.pending_choice is not choice:
            raise ValueError("Native set reconciliation failed")
    if choice.selected_indices != target or not choice.can_confirm():
        raise ValueError("Native complete-set mismatch")
    return world.resolve_pending_choice(None)
