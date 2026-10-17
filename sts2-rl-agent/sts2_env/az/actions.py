"""Versioned AZ actions; normal actions retain native indices, choices do not truncate."""
import numpy as np
from .content import TOP_CONTENT, LIFE_CONTENT, SEL_CONTENT, SET_CONTENT, MORPH_CONTENT, MULTI_CONTENT, SUMMON_CONTENT
from .content import BOSS_CONTENT, EXPANSION_CONTENT
from .config import ACTION_VERSION

MAX_COMBAT_CARDS = 420  # <=20 initial cards + <=400 one-copy Anger decisions
# Summon content: <=20 initial + <=400 Anger + 3 Dazed per performed Eye turn at
# the same decision/turn limits.  Purity keeps its atomic 9-bit set semantics,
# so the wider schema only adds never-legal high bits; nothing is truncated.
MAX_SUMMON_CARDS = 720


def action_size(content):
    if content in (BOSS_CONTENT, EXPANSION_CONTENT):
        return 4096
    if content == SUMMON_CONTENT:
        return 1024
    if content in (SET_CONTENT, MORPH_CONTENT, MULTI_CONTENT):
        return 512
    return MAX_COMBAT_CARDS + 1 if content in (TOP_CONTENT, LIFE_CONTENT, SEL_CONTENT, SET_CONTENT, MORPH_CONTENT, MULTI_CONTENT) else 115


def action_version(content):
    if content in (BOSS_CONTENT, EXPANSION_CONTENT):
        return "combat-boss4096-v1"
    if content == SUMMON_CONTENT:
        return "combat-summon1024-v4"
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
        if content == EXPANSION_CONTENT:
            from sts2_env.core.enums import TargetType
            from sts2_env.core.constants import MAX_HAND_SIZE, MAX_ENEMIES
            for slot, card in enumerate(world.hand):
                if card.target_type == TargetType.RANDOM_ENEMY:
                    aliases = [1 + MAX_HAND_SIZE + slot * MAX_ENEMIES + i for i in range(MAX_ENEMIES)]
                    legal = [i for i in aliases if result[i]]
                    for i in legal[1:]: result[i] = 0
        return result
    choice = world.pending_choice
    from .choice_sets import is_set_choice, set_mask
    if is_set_choice(world, content):
        return np.asarray(set_mask(choice.num_options, choice.min_choices, choice.max_choices, choice.allow_skip, size), dtype=np.int8)
    if choice.num_options >= size:
        raise ValueError("Choice exceeds versioned action capacity; truncation forbidden")
    result = np.zeros(size, dtype=np.int8)
    result[0] = choice.can_confirm()
    for i in range(choice.num_options):
        result[i + 1] = not choice.is_multi or choice.can_toggle(i)
    return result
