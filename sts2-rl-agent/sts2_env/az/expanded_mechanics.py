"""G2.3e audited semantics, sourced from explicit native factories/effect functions.

No content ID is a learned feature. Unknown tokens/fields/keywords fail closed.
The registered program describes mechanics; the existing engine executes them.
"""
from functools import lru_cache
from .mechanic_registry import Operation as O, MechanicDescriptor

# Each entry lists every effect variable consumed or deliberately derived by the
# effect (Body Slam's calc_base/extra_damage are display metadata, not its rule).
VARIABLES = {
 'STRIKE_IRONCLAD': (), 'DEFEND_IRONCLAD': (), 'BASH': ('vulnerable',),
 'POMMEL_STRIKE': ('cards',), 'SHRUG_IT_OFF': ('cards',), 'BLOODLETTING': ('hp_loss','energy'),
 'INFLAME': ('strength',), 'OFFERING': ('hp_loss','energy','cards'),
 'BODY_SLAM': ('calc_base','extra_damage'), 'IRON_WAVE': (), 'TWIN_STRIKE': (),
 'ASHEN_STRIKE': ('calc_base','extra_damage'), 'BLUDGEON': (), 'HEMOKINESIS': ('hp_loss',),
 'IMPERVIOUS': (), 'THUNDERCLAP': ('vulnerable',), 'TRUE_GRIT': (), 'BURNING_PACT': ('cards',),
 'ANGER': (), 'ARMAMENTS': (), 'HEADBUTT': (), 'STOMP': (),
 'RESTLESSNESS': ('cards','energy'), 'WHIRLWIND': (), 'PURITY': ('cards',),
 'EQUILIBRIUM': ('equilibrium',), 'PRIMAL_FORCE': (), 'REAVE': ('cards',),
 'GIANT_ROCK': (), 'SOUL': ('cards',), 'DAZED': (), 'BURN': ('damage',), 'WOUND': (), 'SLIMED': ('cards',),
}


@lru_cache(maxsize=128)
def describe_card(token):
    from .content_expansion import FACTORIES, descriptor
    if token.removesuffix('+') in FACTORIES:
        return descriptor(token)
    if token.removesuffix('+') == 'SLIMED':
        # Inherited status dependency admitted by the V4/V5 card codec (slimes).
        from .content_expansion import CODEC as EXPANSION_CODEC
        c = EXPANSION_CODEC._reference(token)
        return MechanicDescriptor(c.card_type.value, c.cost, 'none', (
            O('draw', 'self', 'on_play', c.effect_vars['cards']).validate(),
            O('exhaust', 'self', 'after_play', 1).validate()))
    from .boss_cards import CODEC
    if token not in CODEC.factories:
        raise ValueError(f'Unsupported mechanic path: cards/{token}')
    c = CODEC._reference(token)
    name, v = token.removesuffix('+'), c.effect_vars
    if name not in VARIABLES or set(v) != set(VARIABLES[name]):
        raise ValueError(f'Unaudited effect variables: cards/{token}/{sorted(v)}')
    if set(c.keywords) - {'exhaust','retain','ethereal','unplayable'} or c.enchantments or c.bound or c.base_replay_count or c.star_cost or c.has_star_cost_x:
        raise ValueError(f'Unaudited card dependency: {token}')
    target = {'ANY_ENEMY':'enemy','ALL_ENEMIES':'all_enemies','SELF':'self','NONE':'none'}[c.target_type.name]
    def op(kind, amount, where=target, timing='on_play', **kw):
        return O(kind, where, timing, amount, **kw)
    damage = op('damage', c.base_damage or 0)
    block = op('block', c.base_block or 0, 'self')
    draw = op('draw', v.get('cards',0), 'self')
    hp = op('hp_loss', v.get('hp_loss',0), 'self')
    energy = op('energy', v.get('energy',0), 'self')
    if name in ('STRIKE_IRONCLAD','BLUDGEON','GIANT_ROCK'): effects = [damage]
    elif name in ('DEFEND_IRONCLAD','IMPERVIOUS'): effects = [block]
    elif name in ('BASH','THUNDERCLAP'): effects = [damage,op('vulnerable',v['vulnerable'])]
    elif name == 'POMMEL_STRIKE': effects = [damage,draw]
    elif name == 'SHRUG_IT_OFF': effects = [block,draw]
    elif name == 'BLOODLETTING': effects = [hp,energy]
    elif name == 'INFLAME': effects = [op('strength',v['strength'],'self')]
    elif name == 'OFFERING': effects = [hp,energy,draw]
    elif name == 'BODY_SLAM': effects = [op('damage_from_block',1)]
    elif name == 'IRON_WAVE': effects = [block,damage]
    elif name == 'TWIN_STRIKE': effects = [op('damage',c.base_damage,hits=2)]
    elif name == 'ASHEN_STRIKE': effects = [op('damage_per_exhaust',v['calc_base'],coefficient=v['extra_damage'])]
    elif name == 'HEMOKINESIS': effects = [hp,damage]
    elif name == 'TRUE_GRIT': effects = [block,op('choose_exhaust' if c.upgraded else 'random_exhaust',1,'hand',condition='if_hand_nonempty')]
    elif name == 'BURNING_PACT': effects = [op('choose_exhaust',1,'hand',condition='if_hand_nonempty'),draw]
    elif name == 'ANGER': effects = [damage,op('generate_copy',1,'discard')]
    elif name == 'ARMAMENTS': effects = [block,op('upgrade_hand' if c.upgraded else 'choose_upgrade',1,'hand',condition='unupgraded')]
    elif name == 'HEADBUTT': effects = [damage,op('choose_topdeck',1,'discard')]
    elif name == 'STOMP': effects = [damage,op('cost_per_attack',-1,'self','before_attack_play')]
    elif name == 'RESTLESSNESS': effects = [op('draw',v['cards'],'self',condition='hand_empty'),op('energy',v['energy'],'self',condition='hand_empty')]
    elif name == 'WHIRLWIND': effects = [op('damage_per_energy',c.base_damage)]
    elif name == 'PURITY': effects = [op('choose_exhaust',v['cards'],'hand',coefficient=0)]
    elif name == 'EQUILIBRIUM': effects = [block,op('retain_hand',v['equilibrium'],'self')]
    elif name == 'PRIMAL_FORCE':
        rock = CODEC._reference('GIANT_ROCK+' if c.upgraded else 'GIANT_ROCK')
        effects = [op('transform_attacks',1,'hand'),op('cost',rock.cost,'generated','generated_card'),op('damage',rock.base_damage,'enemy','generated_on_play')]
    elif name == 'REAVE':
        soul = CODEC._reference('SOUL+' if c.upgraded else 'SOUL')
        effects = [damage,op('generate',v['cards'],'draw_bottom'),op('cost',soul.cost,'generated','generated_card'),
                   op('draw',soul.effect_vars['cards'],'self','generated_on_play'),op('exhaust',1,'generated','generated_after_play')]
    elif name == 'SOUL': effects = [draw]
    elif name == 'BURN': effects = [op('damage_unpowered',v['damage'],'self','turn_end_hand')]
    elif name == 'SLIMED': effects = [op('draw',v['cards'],'self')]
    elif name in ('DAZED','WOUND'): effects = []
    else: raise ValueError(f'Unimplemented descriptor: {token}')
    for keyword in sorted(c.keywords):
        effects.append(op(keyword,1,'self','after_play' if keyword=='exhaust' else 'turn_end_hand'))
    for effect in effects: effect.validate()
    return MechanicDescriptor(c.card_type.value,c.cost,target,tuple(effects))


def monster_program(name, history=()):
    """Public finite state programs. stage/next_stage form a directed sequence.

    Amounts denote stage indices, never monster/content IDs. Branch coefficient
    is the audited probability; current public stage is an entity feature.
    """
    def damage(n,hits=1): return O('damage','player','on_play',n,hits)
    def strength(n): return O('strength','self','on_play',n)
    def vuln(n): return O('vulnerable','player','on_play',n)
    from sts2_env.monsters import act3 as native
    tables = {
      'SHRINKER_BEETLE': ([O('shrink','player','on_play',-1)], [damage(7)], [damage(13)]),
      'FUZZY_WURM_CRAWLER': ([damage(4)], [strength(7)], [damage(4)]),
      'NIBBIT': ([damage(12)], [damage(6)], [strength(2)]),
      'BYGONE_EFFIGY': ([], [strength(10)], [damage(15)]),
      'BYRDONIS': ([damage(16)], [damage(3,3)]),
      'CUBEX_CONSTRUCT': ([strength(2)], [damage(7),strength(2)], [damage(7),strength(2)], [damage(5,2)]),
      'MAWLER': ([damage(4,2)], [damage(14)], [vuln(3)]),
      'FOGMOG': ([O('summon','self','on_play',6)], [damage(8),strength(1)], [damage(14)], [damage(8),strength(1)]),
      'EYE_WITH_TEETH': ([O('generate','discard','on_play',3),O('unplayable','generated','generated_card',1),O('ethereal','generated','turn_end_hand',1)], [O('revive','self','on_play',6)]),
      'TEST_SUBJECT': ([damage(native.TEST_SUBJECT_BASE_BITE_DAMAGE)],
                      [damage(native.TEST_SUBJECT_BASE_SKULL_BASH_DAMAGE),vuln(native.TEST_SUBJECT_SKULL_BASH_VULNERABLE)],
                      [O('hits_per_claw','player','on_play',native.TEST_SUBJECT_BASE_MULTI_CLAW_DAMAGE,3,coefficient=1)],
                      [damage(native.TEST_SUBJECT_BASE_POUNCE_DAMAGE)],
                      [damage(native.TEST_SUBJECT_BASE_MULTI_CLAW_DAMAGE,native.TEST_SUBJECT_PHASE3_LACERATE_REPEAT)],
                      [damage(native.TEST_SUBJECT_BIG_POUNCE_DAMAGE)],
                      [O('generate','discard','on_play',native.TEST_SUBJECT_BASE_BURNING_GROWL_BURNS),O('unplayable','generated','generated_card',1),O('damage_unpowered','generated','turn_end_hand',2),strength(native.TEST_SUBJECT_BASE_BURNING_GROWL_STRENGTH)],
                      [O('revive','self','on_play',200,condition='phase0'),
                       O('revive','self','on_play',300,condition='phase1'),
                       O('wound_per_unblocked_hit','discard','on_unblocked_hit',1,condition='phase0'),
                       O('alternate_intangible','self','enemy_turn_end',1,condition='phase1'),
                       O('advance_phase','self','on_play',1)]),
    }
    if name not in tables: raise ValueError(f'Unsupported mechanic path: monsters/{name}')
    nexts = {'SHRINKER_BEETLE':(1,2,1), 'FUZZY_WURM_CRAWLER':(1,2,0), 'NIBBIT':(1,2,0),
             'BYGONE_EFFIGY':(1,2,2), 'BYRDONIS':(1,0), 'CUBEX_CONSTRUCT':(1,2,3,1),
             'MAWLER':(1,0,0), 'FOGMOG':(1,2,1,2), 'EYE_WITH_TEETH':(0,0), 'TEST_SUBJECT':(1,0,3,2,5,6,4,2)}
    result=[]
    for i, effects in enumerate(tables[name]):
        result += [O('stage','self','on_play',i), *effects]
        if name == 'MAWLER':
            choices = [j for j in range(3) if j != i and not (j == 2 and 'ROAR_MOVE' in history)]
            result += [O('random_branch','self','on_play',j,coefficient=1/len(choices)) for j in choices]
        elif name == 'FOGMOG' and i == 1:
            result += [O('random_branch','self','on_play',3,coefficient=.4),O('random_branch','self','on_play',2,coefficient=.6)]
        elif name == 'TEST_SUBJECT' and i == 7:
            result += [O('next_stage','self','on_play',2,condition='phase0'),O('next_stage','self','on_play',4,condition='phase1')]
        else: result += [O('next_stage','self','on_play',nexts[name][i])]
    if name == 'TEST_SUBJECT':
        result += [O('finite_forms','self','on_death',100,coefficient=200),O('clear_form_powers','self','on_death',1),
                   O('next_stage','self','on_death',7,condition='phase0'),O('next_stage','self','on_death',7,condition='phase1')]
    return tuple(result)


def registry_manifest():
    from dataclasses import asdict
    from .content_expansion import CODEC
    from .content import profiles, BOSS_CONTENT
    from pathlib import Path
    return {'cards': {t:asdict(describe_card(t)) for t in CODEC.factories},
            'monsters': {n:[asdict(o) for o in monster_program(n)] for n in
                [k for k,v in profiles(BOSS_CONTENT).items() if 'members' not in v]+['EYE_WITH_TEETH']},
            'program_source': Path(__file__).read_text(encoding='utf-8')}
