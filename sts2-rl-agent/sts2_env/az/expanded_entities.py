"""Complete public entity projection for the frozen G2.3e content contract."""
from collections import Counter
from dataclasses import replace
from functools import lru_cache

from .entity_encoder import Entity, EntityObservation, numeric
from .expanded_mechanics import describe_card, monster_program
from .mechanic_registry import Operation as O, POWER_RULES
from .content_expansion import CODEC
from .lifecycle import attack_count
from .rewards import V6, V7

STAGES = {
 'SHRINKER_BEETLE': ('SHRINKER_MOVE','CHOMP_MOVE','STOMP_MOVE'),
 'FUZZY_WURM_CRAWLER': ('FIRST_ACID_GOOP','INHALE','ACID_GOOP'),
 'NIBBIT': ('BUTT_MOVE','SLICE_MOVE','HISS_MOVE'),
 'BYGONE_EFFIGY': ('INITIAL_SLEEP_MOVE','WAKE_MOVE','SLASHES_MOVE'),
 'BYRDONIS': ('SWOOP_MOVE','PECK_MOVE'),
 'CUBEX_CONSTRUCT': ('CHARGE_UP_MOVE','REPEATER_MOVE','REPEATER_MOVE_2','EXPEL_BLAST'),
 'MAWLER': ('CLAW_MOVE','RIP_AND_TEAR_MOVE','ROAR_MOVE'),
 'FOGMOG': ('ILLUSION_MOVE','SWIPE_MOVE','HEADBUTT_MOVE','SWIPE_RANDOM_MOVE'),
 'EYE_WITH_TEETH': ('DISTRACT_MOVE','REVIVE_MOVE'),
 'TEST_SUBJECT': ('BITE_MOVE','SKULL_BASH_MOVE','MULTI_CLAW_MOVE','POUNCE_MOVE','PHASE3_LACERATE_MOVE','BIG_POUNCE_MOVE','BURNING_GROWL_MOVE','RESPAWN_MOVE')}


@lru_cache(maxsize=512)
def pile_state(token, attacks):
    state = CODEC.capture(CODEC._reference(token))
    if token.removesuffix('+') == 'STOMP' and attacks:
        state = replace(state, cost=max(0,3-attacks), turn_cost=max(0,3-attacks))
    return CODEC.validate(state)


def card_entity(ref, state, zone, count=1, slot=0, position=0, selected=False, option=False):
    CODEC.validate(state)
    d = describe_card(state.token)
    from sts2_env.core.enums import CardTag
    tags = (O('defend_tag','self','powered_card_block',1),) if CardTag.DEFEND in CODEC._reference(state.token).tags else ()
    return Entity(ref,'card',zone,'player',numeric(count=count,hand_slot=slot,known_position=position,
        base_cost=d.cost,current_cost=state.cost,original_cost=state.original_cost,card_type=d.card_type,
        upgraded=int(state.token.endswith('+')),turn_cost=state.turn_cost or 0,has_turn_cost=int(state.turn_cost is not None),
        choice_selected=int(selected),choice_option=int(option)),d.effects + tags)


def encode_expanded(info):
    if info.reward_version not in (V6, V7): raise ValueError('G2.3e requires frozen V6 reward')
    info.validate()
    if info.terminal_value() is not None: raise ValueError('Terminal state has no decision policy')
    attacks = attack_count(info.history)
    completed = len(info.history.played_this_turn) - int(info.choice is not None)
    entities = [Entity('state','state','none',None,numeric(turn=info.turn,decisions=info.history.decisions,
        max_decisions=info.limits.max_decisions,max_turns=info.limits.max_turns,initial_hp=info.initial_hp,
        played_this_turn=len(info.history.played_this_turn),attack_count=attacks,completed_plays=completed,
        enemy_rounds=len(info.history.enemy_moves),
        pending_energy=info.history.payments[-1].energy if info.choice and info.history.payments else 0))]
    peffects = ((POWER_RULES['shrink'] if info.shrink else ()) + (POWER_RULES['vulnerable'] if info.player_vulnerable else ())
        + ((O('strength','self','outgoing_powered_attack',info.player_strength),) if info.player_strength else ())
        + ((O('retain_hand','self','turn_end_hand',info.retain_hand),) if info.retain_hand else ()))
    from .player_abilities import active_effects
    peffects += active_effects(info.player_abilities)
    entities.append(Entity('player','player','none',None,numeric(hp=info.player_hp,max_hp=info.player_max_hp,
        block=info.player_block,energy=info.energy,max_energy=info.max_energy,shrink=info.shrink,
        vulnerable=info.player_vulnerable,strength=info.player_strength,retain_turns=info.retain_hand),peffects))
    from .summon import public_move
    for enemy in info.enemies:
        name = enemy.monster_id
        powers = dict(info.boss.powers) if info.boss is not None else {}
        phase, claws, remaining = 0,0,0
        if info.boss:
            phase, _, move, claws = info.boss.phase.cursor
            from .boss_phases import FORM_HP
            remaining = sum(FORM_HP[phase+1:])
        elif enemy.hp <= 0 and not enemy.reviving:
            move = None
        else:
            move = public_move(enemy,len(info.enemies))
        stage = STAGES[name].index(move) if move is not None else -1
        effects = list(monster_program(name,enemy.moves))
        if enemy.vulnerable: effects += POWER_RULES['vulnerable']
        if enemy.strength: effects.append(O('strength','self','outgoing_powered_attack',enemy.strength))
        if enemy.slow: effects += [O('damage_per_play','self','incoming_powered_attack',.1),O('clear_turn','self','turn_start',1)]
        if enemy.territorial: effects.append(O('strength_per_turn','self','enemy_turn_end',enemy.territorial))
        if enemy.artifact: effects.append(O('artifact','self','on_play',enemy.artifact))
        if enemy.illusion: effects += [O('revive','self','on_death',6),O('clear_debuffs','self','on_death',1)]
        if enemy.illusion or powers.get('ADAPTABLE'):
            effects.append(O('untargetable','self','on_play',1,condition='reviving'))
        if powers.get('ADAPTABLE'): effects.append(O('prevent_combat_end','self','on_death',1))
        if enemy.minion: effects.append(O('secondary','self','applier_death',1))
        if powers.get('ENRAGE'): effects.append(O('strength_per_skill','self','on_skill_play',powers['ENRAGE']))
        if powers.get('INTANGIBLE'): effects.append(O('damage_cap','self','incoming_powered_attack',1))
        if powers.get('NEMESIS'): effects.append(O('alternate_intangible','self','enemy_turn_end',1))
        if powers.get('PAINFUL_STABS'): effects += [O('wound_per_unblocked_hit','discard','on_unblocked_hit',1),O('unplayable','generated','generated_card',1)]
        entities.append(Entity(f'enemy/{enemy.slot}','enemy','none',None,numeric(hp=enemy.hp,max_hp=enemy.max_hp,
            initial_hp=enemy.initial_hp,block=enemy.block,vulnerable=enemy.vulnerable,strength=enemy.strength,
            slow=completed if enemy.slow else 0,territorial=enemy.territorial,artifact=enemy.artifact,
            illusion=enemy.illusion,minion=enemy.minion,primary=int(enemy.primary),spawned=int(enemy.spawned),
            reviving=int(enemy.reviving),intent_damage=enemy.intent[1],intent_hits=enemy.intent[2],
            enemy_rounds=len(enemy.moves),cycle_step=stage,last_stage=STAGES[name].index(enemy.moves[-1]) if enemy.moves else -1,
            roar_used=int('ROAR_MOVE' in enemy.moves),pending_target=int(info.history.pending_target==enemy.slot),
            phase=phase,claws=claws,remaining_forms_hp=remaining,
            intangible=powers.get('INTANGIBLE',0),nemesis=powers.get('NEMESIS',0),enrage=powers.get('ENRAGE',0),
            adaptable=powers.get('ADAPTABLE',0),painful_stabs=powers.get('PAINFUL_STABS',0)),tuple(effects)))
    options = {(o.pile,o.index):i for i,o in enumerate(info.choice.options)} if info.choice else {}
    selected = set(info.choice.selected) if info.choice else set()
    for i,state in enumerate(info.hand_states):
        entities.append(card_entity(f'hand/{i}',state,'hand',slot=i+1,option=('hand',i) in options,selected=options.get(('hand',i),-1) in selected))
    # Discard instances stay distinct because Headbutt refers to each position;
    # position is NOT learned. Relations carry option identity.
    for i,token in enumerate(info.discard):
        entities.append(card_entity(f'discard/{i}',pile_state(token,attacks),'discard',option=('discard',i) in options,selected=options.get(('discard',i),-1) in selected))
    for zone,pile in (('draw_top',info.known_top),('draw_bottom',info.known_bottom)):
        for i,token in enumerate(pile):
            entities.append(card_entity(f'{zone}/{i}',pile_state(token,attacks),zone,position=i+1))
    unknown = Counter(info.draw_composition)-Counter(info.known_top)-Counter(info.known_bottom)
    for zone,counts in (('draw',unknown),('exhaust',Counter(info.exhaust))):
        for i,(token,count) in enumerate(sorted(counts.items())):
            entities.append(card_entity(f'{zone}/{i}',pile_state(token,attacks),zone,count=count))
    if info.choice:
        entities.append(card_entity('pending',info.pending_card,'pending'))
        entities.append(Entity('choice','choice','none','pending',numeric(choice_min=info.choice.min_choices,
            choice_max=info.choice.max_choices,choice_skip=int(info.choice.allow_skip),choice_selected=len(selected))))
    from .action_candidates import action_candidates
    actions,_ = action_candidates(info)
    return EntityObservation(tuple(entities),actions,content_version=info.content_version,reward_version=info.reward_version).validate()
