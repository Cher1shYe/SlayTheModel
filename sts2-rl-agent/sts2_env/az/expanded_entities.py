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


def card_entity(ref, state, zone, count=1, slot=0, position=0, selected=False, option=False, **execution):
    from .boss_cards import CODEC as LEGACY_CODEC
    (CODEC if state.version==CODEC.policy.state_version else LEGACY_CODEC).validate(state)
    d = describe_card(state.token)
    if state.token.removesuffix("+") in ("RAMPAGE","THRASH"):
        from .foundation import descriptor
        d=descriptor(CODEC.restore(state))
    from sts2_env.core.enums import CardTag
    rarity=(O('rarity','self','on_play',CODEC._reference(state.token).rarity.value),)
    tags = (O('defend_tag','self','powered_card_block',1),) if CardTag.DEFEND in CODEC._reference(state.token).tags else ()
    if CardTag.STRIKE in CODEC._reference(state.token).tags: tags += (O('strike_tag','self','on_play',1),)
    return Entity(ref,'card',zone,'player',numeric(count=count,hand_slot=slot,known_position=position,
        base_cost=d.cost,current_cost=state.cost,original_cost=state.original_cost,card_type=d.card_type,
        upgraded=int(state.token.endswith('+')),turn_cost=state.turn_cost or 0,has_turn_cost=int(state.turn_cost is not None),
        choice_selected=int(selected),choice_option=int(option),is_clone=int(state.is_clone),
        has_turn_star_cost=int(state.turn_star_cost is not None),**execution),d.effects + tags + rarity)


def encode_expanded(info):
    if info.reward_version not in (V6, V7): raise ValueError('G2.3e requires frozen V6 reward')
    info.validate()
    if info.terminal_value() is not None: raise ValueError('Terminal state has no decision policy')
    attacks = attack_count(info.history)
    from .content import EXPANSION_CONTENT, ALL_CONTENT
    completed = (sum(e[0]=="finish" and e[2]==info.turn for e in info.history.public_events)
        if info.content_version in (EXPANSION_CONTENT, ALL_CONTENT) else len(info.history.played_this_turn)-int(info.choice is not None))
    entities = [Entity('state','state','none',None,numeric(received_unblocked_hits=sum(e[0]=='player_damage' and e[3]>0 for e in info.history.public_events),
        player_damaged_this_turn=int(any(e[0]=='player_damage' and e[1]==info.turn and e[3]>0 for e in info.history.public_events)),turn=info.turn,decisions=info.history.decisions,
        max_decisions=info.limits.max_decisions,max_turns=info.limits.max_turns,initial_hp=info.initial_hp,
        played_this_turn=len(info.history.played_this_turn),attack_count=attacks,completed_plays=completed,
        enemy_rounds=len(info.history.enemy_moves),exhausted_this_turn=len(info.history.exhausted_this_turn),
        pending_energy=info.history.payments[-1].energy if info.choice and info.history.payments else 0))]
    peffects = ((POWER_RULES['shrink'] if info.shrink else ()) + (POWER_RULES['vulnerable'] if info.player_vulnerable else ())
        + ((O('strength','self','outgoing_powered_attack',info.player_strength),) if info.player_strength else ())
        + ((O('retain_hand','self','turn_end_hand',info.retain_hand),) if info.retain_hand else ()))
    from .player_abilities import active_effects
    peffects += active_effects(info.player_abilities)
    from .foundation import effects as basic_effects
    peffects += basic_effects(info,-1)
    entities.append(Entity('player','player','none',None,numeric(hp=info.player_hp,max_hp=info.player_max_hp,
        block=info.player_block,energy=info.energy,max_energy=info.max_energy,shrink=info.shrink,
        vulnerable=info.player_vulnerable,strength=info.player_strength,retain_turns=info.retain_hand),peffects))
    if info.power_memory:
        from .power_memory import read
        from .foundation import PLAYER
        from .player_abilities import POWER_IDS,rules
        memory=read(info)
        from sts2_env.core.enums import ValueProp
        for i,(props,index) in enumerate(memory['blocks']):
            entities.append(Entity(f'block_event/{i}','continuation','pending','player',numeric(execution_card_reference=index+1),
                (O('block_gain_event','self','powered_card_block',int(ValueProp(props).is_card_or_monster_move())),)))
        for index,value in memory['rupture']:
            entities.append(Entity(f'rupture/{index}','continuation','pending','player',numeric(execution_card_reference=index+1),
                (O('deferred_strength','self','after_play',value),)))
        for index in memory['calamity']:
            entities.append(Entity(f'calamity/{index}','continuation','pending','player',numeric(execution_card_reference=index+1),
                (O('generate_character_attack','hand','after_attack_play',dict((n,a) for slot,n,a in info.basic_statuses if slot==-1)['CALAMITY']),)))
        for i,name in enumerate(memory['order']):
            if name in PLAYER:
                effects=basic_effects(replace(info,basic_statuses=tuple(r for r in info.basic_statuses if r[1]==name)),-1)
            elif name in POWER_IDS:effects=rules(name,dict(info.player_abilities)[name])
            elif name=='STRENGTH':effects=(O('strength','self','outgoing_powered_attack',info.player_strength),)
            elif name=='RETAIN_HAND':effects=(O('retain_hand','self','turn_end_hand',info.retain_hand),)
            elif name in ('SHRINK','VULNERABLE'):effects=POWER_RULES[name.lower()]
            else:effects=(O('public_power','self','on_play',dict(info.player_abilities).get(name,0)),)
            counter=memory['counters'].get(name,0)
            if name in ('CRIMSON_MANTLE','INFERNO'):effects+=(O('hp_loss','self','turn_start',counter),)
            entities.append(Entity(f'power/{i}','power','none','player',numeric(power_order=i+1,power_counter=counter),effects))
    from .summon import public_move
    if info.content_version == ALL_CONTENT:
        from .all_entities import enemy_entities
        entities.extend(enemy_entities(info))
    for enemy in (() if info.content_version == ALL_CONTENT else info.enemies):
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
        effects = list(monster_program(name,enemy.moves)) + list(basic_effects(info,enemy.slot))
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
    from .content import EXPANSION_CONTENT, ALL_CONTENT
    memory=None
    if info.content_version in (EXPANSION_CONTENT, ALL_CONTENT):
        from .card_memory import read
        memory=read(info.card_memory,CODEC)
    options = {(o.pile,o.index):i for i,o in enumerate(info.choice.options)} if info.choice else {}
    selected = set(info.choice.selected) if info.choice else set()
    for i,state in enumerate(info.hand_states):
        entities.append(card_entity(f'hand/{i}',state,'hand',slot=i+1,option=('hand',i) in options,selected=options.get(('hand',i),-1) in selected))
    # Discard instances stay distinct because Headbutt refers to each position;
    # position is NOT learned. Relations carry option identity.
    for i,token in enumerate(info.discard):
        entities.append(card_entity(f'discard/{i}',memory['discard'][i] if memory else pile_state(token,attacks),'discard',option=('discard',i) in options,selected=options.get(('discard',i),-1) in selected))
    from .card_memory import known_states
    top_states,bottom_states=known_states(info,CODEC) if memory else ((),())
    for zone,pile in (('draw_top',info.known_top),('draw_bottom',info.known_bottom)):
        for i,token in enumerate(pile):
            entities.append(card_entity(f'{zone}/{i}',(top_states if zone=='draw_top' else bottom_states)[i] if memory else pile_state(token,attacks),zone,position=i+1))
    unknown = Counter(info.draw_composition)-Counter(info.known_top)-Counter(info.known_bottom)
    if memory:
        draw=Counter(memory['draw'])
        draw.subtract(top_states+bottom_states)
        for zone,counts in (('draw',+draw),('exhaust',Counter(memory['exhaust']))):
            for i,(state,count) in enumerate(sorted(counts.items(),key=lambda p:str(p[0]))):
                entities.append(card_entity(f'{zone}/{i}',state,zone,count=count))
    else:
        for zone,counts in (('draw',unknown),('exhaust',Counter(info.exhaust))):
            for i,(token,count) in enumerate(sorted(counts.items())):
                entities.append(card_entity(f'{zone}/{i}',pile_state(token,attacks),zone,count=count))
    execution_features={}
    if info.execution:
        from .execution import states
        data,stack_cards=states(info.execution,CODEC)
        def continuation(ref,kind,count=1,depth=0,**values):
            entities.append(Entity(ref,'continuation','pending','player',numeric(execution_depth=depth,
                execution_remaining=count,**values),(O(kind,'self','after_choice',count),)))
        if data['draw']:continuation('continuation/draw','resume_draw',data['draw']['remaining'],from_hand_draw=int(data['draw']['from_hand_draw']))
        if data['end_turn']:continuation('continuation/end_turn','resume_end_turn' if data['end_stage']=='cleanup' else 'finish_end_turn')
        if data['turn']:continuation('continuation/turn','resume_'+data['turn'][1])
        if data['pile']:continuation('continuation/pile','resume_'+data['pile']['kind'],data['pile']['remaining'],execution_force_exhaust=int(data['pile']['force_exhaust']))
        for i,name in enumerate(data['hooks']):
            effects=basic_effects(replace(info,basic_statuses=tuple(r for r in info.basic_statuses if r[1]==name)),-1)
            entities.append(Entity(f'continuation/hook/{i}','continuation','pending','player',numeric(execution_queue_position=i+1),effects))
        for i,frame in enumerate(data['frames'],1):
            kind=frame['kind']
            if kind=='hooks':
                from .foundation import PLAYER,ENEMY
                from .player_abilities import POWER_IDS,rules
                for j,task in enumerate(frame['tasks']):
                    name,amount,slot=task['power'],task['amount'],task['owner']
                    op={'after_card_exhausted':'resume_exhaust_hook','after_turn_end':'resume_turn_end_hook','after_turn_end_late':'resume_turn_end_late_hook'}[task['method']]
                    effects=(O(op,'self','after_choice',amount),)
                    if name in (*PLAYER,*ENEMY):effects+=basic_effects(replace(info,basic_statuses=((slot,name,amount),)),slot)
                    elif name in POWER_IDS:effects+=rules(name,amount)
                    entities.append(Entity(f'continuation/hooks/{i}/{j}','continuation','pending','player' if slot==-1 else f'enemy/{slot}',
                        numeric(execution_depth=i,execution_queue_position=j+1),effects))
            if kind in ('draw','random_draw','random_hand_attack','random_batch'):
                op={'draw':'resume_draw','random_draw':'auto_play_random_draw','random_hand_attack':'auto_play_hand_attack','random_batch':'resume_random_batch'}[kind]
                continuation(f'continuation/frame/{i}',op,frame['remaining'],i,from_hand_draw=int(frame.get('from_hand_draw',False)))
            if kind=='random_batch':
                from .card_memory import parse
                for j,ref in enumerate(frame['pool']):
                    if ref['zone']=='draw':state=parse(ref['state'],CODEC)
                    elif ref['zone']=='play':state=stack_cards[ref['index']]
                    elif ref['zone']=='hand':state=info.hand_states[ref['index']]
                    else:
                        from .card_memory import read
                        state=read(info.card_memory,CODEC)[ref['zone']][ref['index']]
                    entities.append(card_entity(f'continuation/pool/{i}/{j}',state,'pending',execution_depth=i,execution_auto=1))
        contexts=[f['context'] for f in data['frames'] if f['kind']=='play']+([data['active']] if data['active'] is not None else [])
        for depth,ctx in enumerate(contexts,1):
            for j,effect in enumerate(ctx['post_draw_effects']):
                if effect[0]=='power':
                    ops=(O('no_draw' if effect[1]=='NO_DRAW' else 'exhaust_draw_top','self','after_choice',effect[2]),)
                elif effect[0]=='topdeck_hand':ops=(O('choose_topdeck','hand','after_choice',1),)
                elif effect[0] in ('draw','energy','block'):ops=(O(effect[0],'self','after_choice',effect[1]),)
                elif effect[0]=='power_target':ops=(O(effect[2].lower(),'self' if effect[1]<0 else 'enemy','after_choice',effect[3]),)
                elif effect[0]=='damage':ops=(O('damage','enemy','after_choice',effect[2]),)
                elif effect[0]=='exhaust_card':
                    ops=(O('exhaust','self','after_choice',1),)
                    ref=effect[1]
                    from .card_memory import parse,read
                    state=(parse(ref['state'],CODEC) if ref['zone']=='draw' else stack_cards[ref['index']] if ref['zone']=='play' else
                        info.hand_states[ref['index']] if ref['zone']=='hand' else read(info.card_memory,CODEC)[ref['zone']][ref['index']])
                    entities.append(card_entity(f'continuation/exhaust/{depth}/{j}',state,'pending',execution_depth=depth,execution_queue_position=j+1))
                else:raise ValueError('Queued effect lacks encoding')
                entities.append(Entity(f'continuation/post_draw/{depth}/{j}','continuation','pending','player',numeric(execution_depth=depth,execution_queue_position=j+1),ops))
            execution_features[ctx['card']]=dict(execution_depth=depth,
                execution_remaining=ctx['remaining_plays'],execution_total=ctx['play_count'],
                execution_auto=int(ctx['is_auto_play']),execution_force_exhaust=int(ctx['force_exhaust']),
                execution_after_hook=int(ctx['awaiting_after_hook']),execution_target=ctx['target']+1)
        queue_position=0
        for frame in reversed(data['frames']):
            if frame['kind']=='auto_batch':
                for index in frame['cards']:
                    queue_position+=1
                    execution_features.setdefault(index,{}).update(execution_queue_position=queue_position,
                        execution_auto=1,execution_force_exhaust=int(frame['force_exhaust']))
        for i,c in enumerate(stack_cards):
            if data['active'] is None or i!=data['active']['card']:entities.append(card_entity(f'execution/{i}',c,'pending',**execution_features.get(i,{})))
    if info.choice:
        for o in info.choice.options:
            if o.pile=='revealed':entities.append(card_entity(f'revealed/{o.index}',o.card,'revealed',option=True))
        if info.pending_card:
            entities.append(card_entity('pending',info.pending_card,'pending',**(execution_features.get(data['active']['card'],{}) if info.execution else {})))
        else:
            entities.append(Entity('pending','choice','pending','player',numeric(),(O('choose_to_hand','draw','after_shuffle',info.choice.max_choices),)))
        entities.append(Entity('choice','choice','none','pending',numeric(choice_min=info.choice.min_choices,
            choice_max=info.choice.max_choices,choice_skip=int(info.choice.allow_skip),choice_selected=len(selected))))
    from .action_candidates import action_candidates
    actions,_ = action_candidates(info)
    return EntityObservation(tuple(entities),actions,content_version=info.content_version,reward_version=info.reward_version).validate()
