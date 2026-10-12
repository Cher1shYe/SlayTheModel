"""Versioned AZ actions; normal actions retain native indices, choices do not truncate."""
import numpy as np
from .content import TOP_CONTENT, LIFE_CONTENT, SEL_CONTENT, SET_CONTENT, MORPH_CONTENT, MULTI_CONTENT
from .config import ACTION_VERSION

MAX_COMBAT_CARDS = 420  # <=20 initial cards + <=400 one-copy Anger decisions


def action_size(content):
    if content in (SET_CONTENT, MORPH_CONTENT, MULTI_CONTENT):
        return 512
    return MAX_COMBAT_CARDS + 1 if content in (TOP_CONTENT, LIFE_CONTENT, SEL_CONTENT, SET_CONTENT, MORPH_CONTENT, MULTI_CONTENT) else 115


def action_version(content):
    if content == MULTI_CONTENT:
        return "combat-multi512-v3"
    if content in (SET_CONTENT, MORPH_CONTENT, MULTI_CONTENT):
        return "combat-set512-v2"
    return "combat-421-v1" if content in (TOP_CONTENT, LIFE_CONTENT, SEL_CONTENT, SET_CONTENT, MORPH_CONTENT, MULTI_CONTENT) else ACTION_VERSION


def public_mask(world, content):
    from sts2_env.gym_env.action_space import get_action_mask
    size = action_size(content)
    if world.pending_choice is None:
        result = np.zeros(size, dtype=np.int8)
        result[:115] = get_action_mask(world)
        return result
    choice = world.pending_choice
    from .choice_sets import is_set_choice, set_mask
    if is_set_choice(world, content):
        return np.asarray(set_mask(choice.num_options, choice.min_choices, choice.max_choices, choice.allow_skip), dtype=np.int8)
    if choice.num_options >= size:
        raise ValueError("Choice exceeds versioned action capacity; truncation forbidden")
    result = np.zeros(size, dtype=np.int8)
    result[0] = choice.can_confirm()
    for i in range(choice.num_options):
        result[i + 1] = not choice.is_multi or choice.can_toggle(i)
    return result
