"""Explicit Ironclad/colorless admission; factories alone never grant support.

The original Boss registry remains frozen. This version adds no relic, potion,
character-resource or multiplayer capability and has no training manifest.
"""
from functools import partial

from sts2_env.cards import ironclad, colorless
from .card_state import CardStateCodec
from .boss_cards import CODEC as BASE_CODEC

POWER_FACTORIES = {
    'BARRICADE_CARD': ironclad.make_barricade, 'RAGE_CARD': ironclad.make_rage,
    'FEEL_NO_PAIN_CARD': ironclad.make_feel_no_pain, 'DEMON_FORM_CARD': ironclad.make_demon_form,
    'FASTEN': colorless.make_fasten, 'ETERNAL_ARMOR': colorless.make_eternal_armor,
}
FACTORIES = {**POWER_FACTORIES,
    'BLOOD_WALL': ironclad.make_blood_wall,
    'BREAKTHROUGH': ironclad.make_breakthrough,
    'TREMBLE': ironclad.make_tremble,
    'TAUNT': ironclad.make_taunt,
    'FINESSE': colorless.make_finesse,
    'FLASH_OF_STEEL': colorless.make_flash_of_steel,
    'MASTER_OF_STRATEGY': colorless.make_master_of_strategy,
    'PRODUCTION': colorless.make_production,
    'ULTIMATE_DEFEND': colorless.make_ultimate_defend,
    'ULTIMATE_STRIKE': colorless.make_ultimate_strike,
    'SALVO': colorless.make_salvo,
    'SCRAWL': colorless.make_scrawl,
    'BREAK': ironclad.make_break,
    'BULLY': ironclad.make_bully,
    'DISMANTLE': ironclad.make_dismantle,
    'DOMINATE': ironclad.make_dominate,
    'MOLTEN_FIST': ironclad.make_molten_fist,
}
CODEC = CardStateCodec({**BASE_CODEC.factories, **{
    name + suffix: partial(factory, upgraded=bool(suffix))
    for name, factory in FACTORIES.items() for suffix in ('', '+')
}}, BASE_CODEC.policy)
TOKENS = tuple(CODEC.factories)


def initial_factories():
    """Only scoped player cards; inherited status/token factories are dependencies."""
    from sts2_env.core.card_pools import CardPoolId, CHARACTER_CARD_POOLS_BY_ID, COLORLESS_CARD_POOL
    from .decks import MORPH_FACTORIES
    scope = {c.name for c in (*CHARACTER_CARD_POOLS_BY_ID[CardPoolId.IRONCLAD], *COLORLESS_CARD_POOL)}
    return {k: v for k, v in {**MORPH_FACTORIES, **FACTORIES}.items() if k in scope}


def descriptor(token):
    from .mechanic_registry import Operation as O, MechanicDescriptor
    c = CODEC._reference(token)
    name, v = token.removesuffix('+'), c.effect_vars
    variables = {'BLOOD_WALL': ('hp_loss',), 'BREAKTHROUGH': ('hp_loss',),
        'TREMBLE': ('vulnerable',), 'TAUNT': ('vulnerable',),
        'FINESSE': ('cards',), 'FLASH_OF_STEEL': ('cards',),
        'MASTER_OF_STRATEGY': ('cards',), 'PRODUCTION': ('energy',),
        'ULTIMATE_DEFEND': (), 'ULTIMATE_STRIKE': (), 'SALVO': ('damage',), 'SCRAWL': (),
        'BREAK': ('vulnerable',), 'BULLY': ('calc_base', 'extra_damage'), 'DISMANTLE': ('hits',),
        'DOMINATE': ('strength_per_vulnerable',), 'MOLTEN_FIST': (),
        'BARRICADE_CARD': (), 'RAGE_CARD': ('power',), 'FEEL_NO_PAIN_CARD': ('power',),
        'DEMON_FORM_CARD': ('strength',), 'FASTEN': ('extra_block',), 'ETERNAL_ARMOR': ('plating',)}
    if name not in variables or set(v) != set(variables[name]):
        raise ValueError(f'Unaudited expansion variables: cards/{token}')
    if set(c.keywords) - {'exhaust', 'retain'} or c.enchantments or c.bound or c.base_replay_count or c.star_cost or c.has_star_cost_x:
        raise ValueError(f'Unaudited expansion dependencies: cards/{token}')
    target = {'ANY_ENEMY': 'enemy', 'ALL_ENEMIES': 'all_enemies', 'SELF': 'self'}[c.target_type.name]
    damage = O('damage', target, 'on_play', c.base_damage or 0)
    block = O('block', 'self', 'on_play', c.base_block or 0)
    draw = O('draw', 'self', 'on_play', v.get('cards', 0))
    hp = O('hp_loss', 'self', 'on_play', v.get('hp_loss', 0))
    vuln = O('vulnerable', target, 'on_play', v.get('vulnerable', 0))
    if name in POWER_FACTORIES:
        from .player_abilities import card_effects
        effects = list(card_effects(name, v))
    elif name == 'BLOOD_WALL': effects = [hp, O('block', 'self', 'on_play', c.base_block, condition='alive')]
    elif name == 'BREAKTHROUGH': effects = [hp, O('damage', target, 'on_play', c.base_damage, condition='alive')]
    elif name == 'TREMBLE': effects = [vuln]
    elif name == 'TAUNT': effects = [block, vuln]
    elif name == 'FINESSE': effects = [block, draw]
    elif name == 'FLASH_OF_STEEL': effects = [damage, draw]
    elif name == 'MASTER_OF_STRATEGY': effects = [draw]
    elif name == 'PRODUCTION': effects = [O('energy', 'self', 'on_play', v['energy'])]
    elif name == 'ULTIMATE_DEFEND': effects = [block]
    elif name == 'ULTIMATE_STRIKE': effects = [damage]
    elif name == 'SALVO': effects = [damage, O('retain_hand', 'self', 'on_play', 1)]
    elif name == 'SCRAWL': effects = [O('draw_to_hand_limit', 'self', 'on_play', 10)]
    elif name == 'BREAK': effects = [damage, vuln]
    elif name == 'BULLY': effects = [O('damage_per_vulnerable', target, 'on_play', v['calc_base'], coefficient=v['extra_damage'])]
    elif name == 'DISMANTLE':
        effects = [O('damage_conditional_hits', target, 'on_play', c.base_damage,
                     hits=2, condition='target_vulnerable', coefficient=1)]
    elif name == 'DOMINATE':
        effects = [O('strength_from_target_vulnerable', target, 'on_play', v['strength_per_vulnerable'])]
    elif name == 'MOLTEN_FIST':
        effects = [damage, O('multiply_vulnerable', target, 'on_play', 2, condition='target_alive')]
    else: raise ValueError(f'Unsupported expansion card: {token}')
    if 'exhaust' in c.keywords: effects.append(O('exhaust', 'self', 'after_play', 1))
    if 'retain' in c.keywords: effects.append(O('retain', 'self', 'turn_end_hand', 1))
    return MechanicDescriptor(c.card_type.value, c.cost, target, tuple(o.validate() for o in effects))
