"""V3 explicit admission of immediate effects and observable counters."""
from sts2_env.cards import ironclad, colorless
from .mechanic_registry import Operation as O, MechanicDescriptor

NAMES_IRONCLAD = ('CONFLAGRATION','EXPECT_A_FIGHT','PERFECTED_STRIKE','PILLAGE',
    'FIEND_FIRE','SECOND_WIND','STOKE','STONE_ARMOR','SWORD_BOOMERANG','PACTS_END',
    'EVIL_EYE','FORGOTTEN_RITUAL','BATTLE_TRANCE')
NAMES_COLORLESS = ('DRAMATIC_ENTRANCE','FISTICUFFS','IMPATIENCE','MIND_BLAST','OMNISLICE','REND','VOLLEY')
FACTORIES = {**{n:getattr(ironclad, 'make_'+n.lower()) for n in NAMES_IRONCLAD},
             **{n:getattr(colorless, 'make_'+n.lower()) for n in NAMES_COLORLESS}}
VARIABLES = {'CONFLAGRATION':('calc_base','extra_damage'), 'EXPECT_A_FIGHT':('energy','calc_base','calc_extra'),
 'PERFECTED_STRIKE':('calc_base','extra_damage'), 'PILLAGE':(), 'FIEND_FIRE':(),
 'SECOND_WIND':('block',), 'STOKE':(), 'STONE_ARMOR':('plating',), 'SWORD_BOOMERANG':('repeat',),
 'PACTS_END':('cards',), 'EVIL_EYE':(), 'FORGOTTEN_RITUAL':('energy',), 'BATTLE_TRANCE':('cards',),
 'DRAMATIC_ENTRANCE':(), 'FISTICUFFS':(), 'IMPATIENCE':('cards',), 'MIND_BLAST':('calc_base','extra_damage'),
 'OMNISLICE':('damage',), 'REND':('calc_base','extra_damage'), 'VOLLEY':('damage',)}


def descriptor(card):
    n, v = card.card_id.name, card.effect_vars
    if (n not in VARIABLES or set(v) != set(VARIABLES[n]) or set(card.keywords)-{'exhaust','innate'}
            or card.enchantments or card.bound or card.base_replay_count or card.star_cost or card.has_star_cost_x):
        raise ValueError('Unaudited simple card dependency')
    target = {'SELF':'self','ANY_ENEMY':'enemy','ALL_ENEMIES':'all_enemies','RANDOM_ENEMY':'random_enemy'}[card.target_type.name]
    damage = O('damage',target,'on_play',card.base_damage or 0)
    if n == 'CONFLAGRATION': effects=[O('damage_per_finished_attack',target,'on_play',v['calc_base'],coefficient=v['extra_damage'])]
    elif n == 'EXPECT_A_FIGHT': effects=[O('energy_per_hand_attack','self','on_play',1)]
    elif n == 'PERFECTED_STRIKE': effects=[O('damage_per_strike_card',target,'on_play',v['calc_base'],coefficient=v['extra_damage'])]
    elif n == 'PILLAGE': effects=[damage,O('draw_until_nonattack','self','after_play_damage',10)]
    elif n == 'FIEND_FIRE': effects=[O('exhaust_hand','hand','on_play',1),O('damage_per_exhausted_hand',target,'after_exhaust',card.base_damage)]
    elif n == 'SECOND_WIND': effects=[O('exhaust_nonattacks_with_block','hand','on_play',v['block'])]
    elif n == 'STOKE': effects=[O('exhaust_hand','hand','on_play',1),O('draw_per_exhausted_hand','self','after_exhaust',1)]
    elif n == 'STONE_ARMOR': effects=[O('plating','self','player_turn_end',v['plating']),O('decrement','self','enemy_turn_end',1)]
    elif n == 'SWORD_BOOMERANG': effects=[O('damage','random_enemy','on_play',card.base_damage,hits=v['repeat'])]
    elif n == 'PACTS_END': effects=[O('require_exhaust_count','self','playability',v['cards']),damage]
    elif n == 'EVIL_EYE': effects=[O('block','self','on_play',card.base_block),O('block','self','on_play',card.base_block,condition='exhausted_this_turn')]
    elif n == 'FORGOTTEN_RITUAL': effects=[O('energy','self','on_play',v['energy'],condition='exhausted_this_turn')]
    elif n == 'BATTLE_TRANCE': effects=[O('draw','self','on_play',v['cards']),O('no_draw','self','outside_hand_draw',1),O('remove','self','player_turn_end',1)]
    elif n == 'DRAMATIC_ENTRANCE': effects=[damage]
    elif n == 'FISTICUFFS': effects=[damage,O('block_from_damage_result','self','after_play_damage',1,condition='combat_active')]
    elif n == 'IMPATIENCE': effects=[O('draw','self','on_play',v['cards'],condition='no_attacks_in_hand')]
    elif n == 'MIND_BLAST': effects=[O('damage_per_draw_card',target,'on_play',v['calc_base'],coefficient=v['extra_damage'])]
    elif n == 'OMNISLICE': effects=[damage,O('splash_damage_result','other_enemies','after_play_damage',1)]
    elif n == 'REND': effects=[O('damage_per_debuff_type',target,'on_play',v['calc_base'],coefficient=v['extra_damage'])]
    elif n == 'VOLLEY': effects=[O('damage_per_energy','random_enemy','on_play',card.base_damage)]
    else: raise ValueError(n)
    for keyword in sorted(card.keywords):
        effects.append(O(keyword,'self','opening_hand' if keyword=='innate' else 'after_play',1))
    return MechanicDescriptor(card.card_type.value,card.cost,target,tuple(o.validate() for o in effects))


def finish_history(before, world, history):
    """Only visible exhausted cards; no hidden piles or engine event list."""
    from collections import Counter
    from dataclasses import replace
    from .decks import card_token
    if world.turn_count > before.turn:
        events = ()
    else:
        added = Counter(card_token(c) for c in world.exhaust_pile)-Counter(before.exhaust)
        events = before.history.exhausted_this_turn + tuple(sorted(added.elements()))
    return replace(history, exhausted_this_turn=events)
