"""Public nested play frames. JSON contains data only, never native callbacks."""
import json
from dataclasses import asdict,replace
from collections import Counter
from .config import canonical_json
from .card_state import PublicCardState
from sts2_env.cards import ironclad,colorless
from .mechanic_registry import Operation as O,MechanicDescriptor
TURN_STAGES=('block','before_hand_draw','card_before_hand_draw','before_hand_draw_late','draw','after_player_turn_start','post_after_player_turn_start')
FACTORIES={'HAVOC':ironclad.make_havoc,'CASCADE':ironclad.make_cascade,'HOWL_FROM_BEYOND':ironclad.make_howl_from_beyond,
    'CATASTROPHE':colorless.make_catastrophe,'BEAT_DOWN':colorless.make_beat_down}

def descriptor(c):
    n=c.card_id.name
    if n=='HOWL_FROM_BEYOND':
        ops=[O('damage','all_enemies','on_play',c.base_damage),O('auto_play_self','exhaust','before_hand_draw',1)]
    elif n=='CATASTROPHE':ops=[O('auto_play_random_draw','draw','on_play',c.effect_vars.get('cards',3))]
    elif n=='BEAT_DOWN':ops=[O('auto_play_discard_attacks','discard','on_play',c.effect_vars.get('cards',3)),O('random_target','enemy','on_play',1)]
    else:
        ops=[O('auto_play_draw','draw','on_play',1 if n=='HAVOC' else int(c.upgraded),coefficient=0 if n=='HAVOC' else 1)]
        if n=='HAVOC':ops.append(O('force_exhaust_played','generated','after_play',1))
    ops += [O(k,'self','after_play',1) for k in sorted(c.keywords)]
    return MechanicDescriptor(c.card_type.value,c.cost,'all_enemies' if n=='HOWL_FROM_BEYOND' else 'self',tuple(o.validate() for o in ops))

def inventory(deck,events,codec):
    counts=Counter(deck)
    for e in events:
        if type(e)is not tuple or not e:raise ValueError('Invalid visible event')
        if e[0]=='steal':
            if len(e)!=3 or type(e[1])is not str or type(e[2])is not int:raise ValueError('Invalid steal event')
            from .card_memory import parse
            state=parse(e[1],codec)
            if counts[state.token]<=0:raise ValueError('Stolen card absent from the public inventory')
            counts[state.token]-=1
        elif e[0]=='generated':
            if len(e)!=4 or e[1] not in codec.factories:raise ValueError('Unadmitted generation')
            counts[e[1]]+=1
        elif e[0] in ('upgrade','transform'):
            if len(e)!=4 or e[1] not in codec.factories or e[2] not in codec.factories or counts[e[1]]<=0:raise ValueError('Invalid public card change')
            counts[e[1]]-=1;counts[e[2]]+=1
        elif e[0]=='start':
            if len(e)!=6 or e[1] not in codec.factories or type(e[2])is not int or type(e[3])is not int or e[3]<0 or type(e[5])is not bool:raise ValueError('Invalid play start')
        elif e[0]=='finish':
            if len(e)!=4 or e[1] not in codec.factories or type(e[3])is not bool:raise ValueError('Invalid play finish')
        elif e[0]=='play_start_meta':
            if len(e)!=4 or type(e[1])is not int or type(e[2])is not bool or type(e[3])is not int or e[3]<0:raise ValueError('Invalid public play metadata')
        elif e[0] in ('draw_remove','draw_insert'):
            if len(e)!=5 or e[1] not in codec.factories or e[2] not in ('top','bottom','unknown') or type(e[3])is not int or type(e[4])is not str:raise ValueError('Invalid public draw movement')
        elif e[0] == 'enemy_intent_action':
            from .roster import INTENT_NAMES
            if (len(e) != 5 or type(e[1]) is not int or e[1] < 0 or type(e[2]) is not str
                    or type(e[3]) is not tuple or not e[3] or type(e[4]) is not int
                    or any(type(i) is not tuple or len(i) != 3 or i[0] not in INTENT_NAMES
                           or any(type(n) is not int or n < 0 for n in i[1:]) for i in e[3])):
                raise ValueError('Invalid performed public intent')
        elif e[0] in ('enemy_action','enemy_knockout'):
            if len(e)!=(3 if e[0]=='enemy_action' else 4) or any(type(v)is not int or v<0 for v in e[1:]):raise ValueError('Invalid public enemy event')
        elif e[0]=='player_damage':
            if len(e)!=4 or any(type(v)is not int or v<0 for v in e[1:]):raise ValueError('Invalid player damage event')
        elif e[0]=='card_state_change':
            if len(e)!=4 or any(type(v)is not str for v in e[1:3]) or type(e[3])is not int:raise ValueError('Invalid card state change')
        elif e[0] in ('generated_state','power_removed_state'):
            if len(e)!=3 or type(e[1])is not str or type(e[2])is not int:raise ValueError('Invalid public card state event')
        elif e[0] in ('dominate_strength','rupture_strength','brand_strength'):
            if len(e)!=3 or type(e[1])is not int or e[1]<0 or type(e[2])is not int:raise ValueError('Invalid Dominate event')
        elif e[0]=='shuffle':
            if len(e)!=3 or type(e[1])is not int or e[1]<0 or type(e[2])is not int:raise ValueError('Invalid shuffle event')
        elif e[0]=='steal':
            if len(e)!=3 or type(e[1])is not str or type(e[2])is not int:raise ValueError('Invalid steal event')
        elif e[0]=='exhaust':
            if len(e)!=3 or e[1] not in codec.factories or type(e[2])is not int:raise ValueError('Invalid exhaust event')
        else:raise ValueError('Unknown public event')
    return +counts

def active(world):
    return world._pending_play['card'] if world._pending_play else None

def capture(world,codec):
    if not world.pending_choice and not (world.is_over and world.play_pile):return ''
    if world._pending_turn_setup is not None and world._pending_turn_cursor is None:
        raise ValueError('Unadmitted turn continuation')
    if any(owner is not world.player or not hasattr(listener,'power_id') for owner,listener in world._pending_hand_draw_hooks):raise ValueError('Unsupported turn hook owner/source')
    cards=list(world.play_pile)
    def public_ref(card):
        for zone in ('hand','discard','exhaust','play'):
            pile=world.hand if zone=='hand' else getattr(world,zone+'_pile')
            if card in pile:return dict(zone=zone,index=pile.index(card))
        # A candidate moved back to draw is identified by its previously public
        # face; neither its hidden position nor the shuffled batch order escapes.
        return dict(zone='draw',state=asdict(codec.capture(card)))
    def ctx(c):
        effects=[['exhaust_card',public_ref(e[1])] if e[0]=='exhaust_card' else e for e in c.get('post_draw_effects',[])]
        return dict(post_draw_effects=effects,card=cards.index(c['card']),target=world.enemies.index(c['target']) if c['target'] in world.enemies else -1,
            **{k:c[k] for k in ('remaining_plays','play_count','energy_spent','energy_value','force_exhaust','is_auto_play','awaiting_after_hook')})
    frames=[]
    for f in world._play_continuations:
        if f['kind']=='play':frames.append(dict(kind='play',context=ctx(f['context'])))
        elif f['kind']=='hooks':
            tasks=[]
            for owner,listener,method,args in f['tasks']:
                if not hasattr(listener,'power_id'):raise ValueError('Unadmitted relic continuation')
                tasks.append(dict(owner=-1 if owner is world.player else world.enemies.index(owner),power=listener.power_id.name,
                    amount=listener.amount,method=method,arg=public_ref(args[0]) if method=='after_card_exhausted' else args[0].value))
            frames.append(dict(kind='hooks',tasks=tasks))
        elif f['kind']=='random_batch':frames.append(dict(kind='random_batch',remaining=f['remaining'],pool=sorted((public_ref(c) for c in f['cards']),key=canonical_json)))
        elif f['kind']=='auto_batch':frames.append(dict(kind='auto_batch',cards=[cards.index(c) for c in f['cards']],force_exhaust=f['force_exhaust'],random_targets=f['random_targets']))
        elif f['kind']=='draw':frames.append(dict(kind='draw',remaining=f['remaining'],from_hand_draw=f['from_hand_draw']))
        elif f['kind'] in ('random_draw','random_hand_attack'):frames.append(dict(kind=f['kind'],remaining=f['remaining']))
        else:raise ValueError('Unadmitted execution frame')
    return canonical_json(dict(version='public-play-stack-v2',cards=[asdict(codec.capture(c)) for c in cards],active=ctx(world._pending_play) if world._pending_play else None,frames=frames,
        draw=({k:world._pending_draw[k] for k in ('remaining','from_hand_draw')} if world._pending_draw else None),
        turn=world._pending_turn_cursor,end_turn=world._pending_end_turn,end_stage=world._pending_end_turn_stage,
        hooks=[listener.power_id.name for owner,listener in world._pending_hand_draw_hooks],
        pile=({**{k:world._pending_pile_operation[k] for k in ('kind','remaining','force_exhaust')},
               'cards':[cards.index(c) for c in world._pending_pile_operation['cards']]} if world._pending_pile_operation else None)))

def states(data,codec):
    d=json.loads(data)
    if set(d)!={'version','cards','active','frames','draw','turn','end_turn','end_stage','pile','hooks'} or d['version']!='public-play-stack-v2':raise ValueError('Invalid execution schema')
    return d,tuple(codec.validate(PublicCardState(**{**c,'effect_vars':tuple(tuple(p) for p in c['effect_vars'])})) for c in d['cards'])

def validate(info,codec):
    if not info.execution:return
    d,cards=states(info.execution,codec)
    keys={'card','target','remaining_plays','play_count','energy_spent','energy_value','force_exhaust','is_auto_play','awaiting_after_hook','post_draw_effects'}
    def ctx(c):
        if set(c)!=keys or any(type(c[k])is not int for k in keys-{'force_exhaust','is_auto_play','awaiting_after_hook','post_draw_effects'}):raise ValueError('Invalid play frame')
        if type(c['post_draw_effects'])is not list:raise ValueError('Invalid effect sequence')
        for e in c['post_draw_effects']:
            if e in (["power","NO_DRAW",1],["power","DRUM_OF_BATTLE",1],["topdeck_hand"]):continue
            if type(e)is not list or not e:raise ValueError('Invalid queued effect')
            if e[0]=='exhaust_card' and len(e)==2 and type(e[1])is dict:continue
            if e[0] in ('draw','energy','block') and len(e)==2 and type(e[1])is int and 0<=e[1]<=100000:continue
            if e[0]=='power_target' and len(e)==4 and type(e[1])is int and -1<=e[1]<len(info.enemies) and e[2] in ('STRENGTH','VULNERABLE','WEAK') and type(e[3])is int and 0<=e[3]<=100000:continue
            if e[0]=='damage' and len(e)==3 and type(e[1])is int and 0<=e[1]<len(info.enemies) and type(e[2])is int and 0<=e[2]<=1000000:continue
            raise ValueError('Invalid post-draw effect')
        if not 0<=c['card']<len(cards) or not -1<=c['target']<len(info.enemies) or not 0<=c['remaining_plays']<c['play_count'] or c['play_count']>1000:raise ValueError('Invalid play cursor')
        if any(type(c[k])is not bool for k in ('force_exhaust','is_auto_play','awaiting_after_hook')):raise ValueError('Invalid execution flag')
    if d['active'] is not None:
        ctx(d['active'])
        if cards[d['active']['card']]!=info.pending_card:raise ValueError('Pending card disagrees with execution stack')
    elif info.pending_card is not None:raise ValueError('Pending card without active execution')
    if type(d['end_turn'])is not bool:raise ValueError('Invalid end turn continuation')
    if d['end_stage'] not in ('cleanup','finish'):raise ValueError('Invalid end turn stage')
    if d['draw'] is not None and (set(d['draw'])!={'remaining','from_hand_draw'} or
        type(d['draw']['remaining'])is not int or not 1<=d['draw']['remaining']<=100000 or
        type(d['draw']['from_hand_draw'])is not bool):raise ValueError('Invalid draw continuation')
    if d['turn'] is not None and (type(d['turn'])is not list or len(d['turn'])!=2 or d['turn'][0]!=0 or
        d['turn'][1] not in TURN_STAGES):raise ValueError('Invalid turn cursor')
    from sts2_env.core.enums import PowerId
    if type(d['hooks'])is not list or any(type(n)is not str or n not in PowerId.__members__ for n in d['hooks']):raise ValueError('Invalid hook continuation')
    if d['pile'] is not None:
        f=d['pile']
        if (set(f)!={'kind','remaining','force_exhaust','cards'} or f['kind'] not in ('auto_draw','exhaust_draw')
            or type(f['remaining'])is not int or not 0<=f['remaining']<=100000 or type(f['force_exhaust'])is not bool
            or any(type(i)is not int or not 0<=i<len(cards) for i in f['cards'])):raise ValueError('Invalid pile continuation')
    for f in d['frames']:
        if f['kind']=='play' and set(f)=={'kind','context'}:ctx(f['context'])
        elif f['kind']=='hooks' and set(f)=={'kind','tasks'}:
            for t in f['tasks']:
                if set(t)!={'owner','power','amount','method','arg'} or type(t['owner'])is not int or not -1<=t['owner']<len(info.enemies) or t['power'] not in PowerId.__members__ or type(t['amount'])is not int:raise ValueError('Invalid hook task')
                if t['method'] not in ('after_card_exhausted','after_turn_end','after_turn_end_late'):raise ValueError('Unknown hook task')
        elif f['kind']=='random_batch' and set(f)=={'kind','remaining','pool'}:
            if type(f['remaining'])is not int or not 1<=f['remaining']<=len(f['pool']):raise ValueError('Invalid random batch count')
            for ref in f['pool']:
                if ref.get('zone')=='draw' and set(ref)=={'zone','state'}:
                    from .card_memory import parse
                    parse(ref['state'],codec)
                elif ref.get('zone') in ('hand','discard','exhaust','play') and set(ref)=={'zone','index'}:
                    if type(ref['index'])is not int or ref['index']<0:raise ValueError('Invalid public batch reference')
                else:raise ValueError('Invalid public batch source')
        elif f['kind']=='auto_batch' and set(f)=={'kind','cards','force_exhaust','random_targets'}:
            if type(f['force_exhaust'])is not bool or type(f['random_targets'])is not bool or any(type(i)is not int or not 0<=i<len(cards) for i in f['cards']):raise ValueError('Invalid auto queue')
        elif f['kind']=='draw' and set(f)=={'kind','remaining','from_hand_draw'}:
            if type(f['remaining'])is not int or not 1<=f['remaining']<=100000 or type(f['from_hand_draw'])is not bool:raise ValueError('Invalid draw frame')
        elif f['kind'] in ('random_draw','random_hand_attack') and set(f)=={'kind','remaining'}:
            if type(f['remaining'])is not int or not 1<=f['remaining']<=100000:raise ValueError('Invalid random auto count')
        else:raise ValueError('Unknown execution frame')

def restore_hand_draw_listener(owner, name):
    from sts2_env.core.enums import PowerId
    from sts2_env.core.creature import get_power_class
    from sts2_env.powers.base import PowerInstance
    power_id = PowerId[name]
    if power_id in owner.powers:
        return owner.powers[power_id]
    cls = get_power_class(power_id)
    # The native queue snapshots listeners before earlier hooks can consume
    # powers. A removed listener with the inherited no-op is safe to recreate
    # only in the queue, never as an active power or an extra damage bonus.
    if cls is not None and cls.before_hand_draw_late is PowerInstance.before_hand_draw_late:
        return cls(0)
    raise ValueError(f'Missing stateful hand-draw listener: {name}')


def restore(world,info,codec):
    world.visible_card_events=list(info.history.public_events)
    from sts2_env.core.enums import ValueProp
    world._damage_events_combat=[(None,world.player,ValueProp(e[2]),e[3]) for e in info.history.public_events if e[0]=="player_damage"]
    world._damage_events_this_turn=[(None,world.player,ValueProp(e[2])) for e in info.history.public_events if e[0]=="player_damage" and e[1]==info.turn]
    if info.history.public_events:
        from .decks import make_any_token
        world._played_cards_this_turn=[]
        for e in info.history.public_events:
            if e[0]=='finish' and e[2]==info.turn:
                c=make_any_token(e[1]);c.owner=world.player;world._played_cards_this_turn.append(c)
        from sts2_env.core.enums import PowerId
        for enemy in world.enemies:
            if PowerId.SLOW in enemy.powers:enemy.powers[PowerId.SLOW]._slow_amount=len(world._played_cards_this_turn)
        from sts2_env.core.combat import CardPlayStartedEntry
        world._card_play_starts_this_turn=[]
        last=None
        for e in info.history.public_events:
            if e[0]=='start':last=e
            elif e[0]=='play_start_meta' and e[1]==info.turn:
                if last is None or last[2]!=e[1]:raise ValueError('Play metadata without start')
                c=make_any_token(last[1]);c.owner=world.player
                world._card_play_starts_this_turn.append(CardPlayStartedEntry(c,e[2],e[3]))
    if not info.execution:return
    d,states_=states(info.execution,codec)
    leaf=world.play_pile[-1] if world.play_pile else None
    cards=[leaf if d['active'] is not None and i==d['active']['card'] else codec.restore(c) for i,c in enumerate(states_)]
    for c in cards:c.owner=world.player
    world.play_pile=cards
    def resolve_ref(ref):
        if ref.get('zone')=='draw' and set(ref)=={'zone','state'}:
            from .card_memory import parse
            state=parse(ref['state'],codec)
            candidates=[c for c in world.draw_pile if codec.capture(c)==state]
            if not candidates:raise ValueError('Queued card face absent')
            return world.shuffle_rng.choice(candidates)
        if ref.get('zone') not in ('hand','discard','exhaust','play') or set(ref)!={'zone','index'}:raise ValueError('Invalid queued card reference')
        pile=world.hand if ref['zone']=='hand' else getattr(world,ref['zone']+'_pile')
        if type(ref['index'])is not int or not 0<=ref['index']<len(pile):raise ValueError('Queued card reference absent')
        return pile[ref['index']]
    def ctx(c):
        result={**c,'card':cards[c['card']],'target':world.enemies[c['target']] if c['target']>=0 else None,'owner':world.player}
        result['post_draw_effects']=[['exhaust_card',resolve_ref(e[1])] if e[0]=='exhaust_card' else e for e in c['post_draw_effects']]
        result['card'].energy_spent=c['energy_spent'];return result
    world._pending_play=ctx(d['active']) if d['active'] is not None else None
    world._pending_draw={**d['draw'],'owner':world.player} if d['draw'] else None
    from sts2_env.core.enums import PowerId
    world._pending_hand_draw_hooks=[(world.player,restore_hand_draw_listener(world.player,n)) for n in d['hooks']]
    world._pending_end_turn=d['end_turn']
    world._pending_end_turn_stage=d['end_stage']
    world._pending_pile_operation=({**d['pile'],'cards':[cards[i] for i in d['pile']['cards']],'owner':world.player} if d['pile'] else None)
    if d['turn'] is not None:world._set_pending_turn_setup(*d['turn'])
    def frame(f):
        if f['kind']=='play':return dict(kind='play',context=ctx(f['context']))
        if f['kind']=='hooks':
            from sts2_env.core.creature import get_power_class
            from sts2_env.core.enums import CombatSide
            tasks=[]
            for t in f['tasks']:
                owner=world.player if t['owner']==-1 else world.enemies[t['owner']]
                power=owner.powers.get(PowerId[t['power']]) or get_power_class(PowerId[t['power']])(t['amount'])
                if power.amount!=t['amount']:raise ValueError('Hook power amount disagrees')
                arg=resolve_ref(t['arg']) if t['method']=='after_card_exhausted' else CombatSide(t['arg'])
                tasks.append((owner,power,t['method'],(arg,)))
            return dict(kind='hooks',tasks=tasks)
        if f['kind']=='draw':return dict(f,owner=world.player)
        if f['kind'] in ('random_draw','random_hand_attack'):return dict(f)
        if f['kind']=='random_batch':
            from .card_memory import parse
            pool=[];available=list(world.draw_pile)
            for ref in f['pool']:
                if ref['zone']=='draw':
                    state=parse(ref['state'],codec)
                    candidates=[c for c in available if codec.capture(c)==state]
                    if not candidates:raise ValueError('Random batch face absent')
                    card=world.shuffle_rng.choice(candidates);available.remove(card)
                else:
                    pile=world.hand if ref['zone']=='hand' else getattr(world,ref['zone']+'_pile')
                    if ref['index']>=len(pile):raise ValueError('Random batch reference absent')
                    card=pile[ref['index']]
                if card in pool:raise ValueError('Repeated random batch candidate')
                pool.append(card)
            world.shuffle_rng.shuffle(pool)
            return dict(kind='random_batch',cards=pool,remaining=f['remaining'])
        return dict(kind='auto_batch',cards=[cards[i] for i in f['cards']],force_exhaust=f['force_exhaust'],random_targets=f['random_targets'])
    world._play_continuations=[frame(f) for f in d['frames']]

def validate_play_finish(events, started, finished):
    """Allow a resolving card's witnessed upgrade, retaining strict nesting."""
    start, finish = events[started], events[finished]
    if start[2] != finish[2]:
        raise ValueError('Mismatched public play turn')
    if start[1] == finish[1]:
        return
    # Dampen removal may restore an upgrade while an outer Havoc is still
    # resolving an automatic play. Do not accept arbitrary face mismatches.
    if (not start[1].endswith('+') and finish[1] == start[1] + '+'
            and ('upgrade', start[1], finish[1], start[2])
            in events[started + 1:finished]):
        return
    raise ValueError('Mismatched public play finish')


def finish_history(before,world,history):
    events=tuple(world.visible_card_events)
    if events[:len(before.history.public_events)]!=before.history.public_events:raise ValueError('Public event journal prefix changed')
    from .deck_observation import prototype
    removed=tuple(e[1] for e in events if e[0]=='finish' and prototype(e[1]).is_power)
    from .player_abilities import CARD_POWER
    abilities=tuple((e[1],e[2]) for e in events if e[0]=='finish' and e[1].removesuffix('+') in CARD_POWER)
    top,bottom,position_states=positions(before,events[len(before.history.public_events):])
    history=replace(history,known_top=top,known_bottom=bottom,position_states=position_states,removed_powers=removed,ability_plays=abilities,
        exhausted_this_turn=tuple(e[1] for e in events if e[0]=='exhaust' and e[2]==world.turn_count))
    from .selection_batch import TurnPayment
    starts=[e for e in events if e[0]=='start' and e[2]==world.turn_count]
    from .deck_observation import prototype
    from .player_abilities import CARD_POWER
    from .foundation import FACTORIES as BASIC
    all_starts=[e for e in events if e[0]=='start']
    from sts2_env.core.enums import PowerId
    # Pair starts/finishes by nesting, including killing blows whose post-damage
    # strength application is suppressed by the native combat-ended guard.
    stack=[];suppressed=set()
    for index,event in enumerate(events):
        if event[0]=='start':stack.append(index)
        elif event[0]=='finish':
            if not stack:raise ValueError('Finish without public start')
            started=stack.pop()
            validate_play_finish(events, started, index)
            if event[3]:suppressed.add(started)
    basic=tuple((e[1],e[2]) for i,e in enumerate(events) if e[0]=='start'
        and e[1].removesuffix('+') in (*BASIC,'BRAND') and i not in suppressed)
    # Engine journal is the visible played-card sequence, including automatic plays.
    return replace(history,public_events=events,played_this_turn=tuple(e[1] for e in starts),
        payments=tuple(TurnPayment(e[1],e[3]) for e in starts),
        removed_powers=removed,
        ability_plays=abilities,
        basic_plays=basic,dominate_strength=sum(e[1] for e in events if e[0]=='dominate_strength'),
        retain_turns=world.player.get_power_amount(PowerId.RETAIN_HAND),
        pending_target=(world.enemies.index(world._pending_play['target']) if world.pending_choice and active(world) is not None and active(world).card_id.name in ('HEADBUTT','SEEKER_STRIKE') else None))


def positions(before,events):
    """Conservative public face-aware prefix/suffix; no hidden card indices."""
    from .content_expansion import CODEC
    from .card_memory import known_states
    top,bottom=known_states(before,CODEC)
    top,bottom=list(top),list(bottom)
    total=len(before.draw_composition)
    from .card_memory import parse
    for e in events:
        if e[0]=='shuffle':
            # The native rule only shuffles when the real draw pile is empty; a
            # revealed steal may have left our tracked count stale, so the
            # public shuffle event itself is authoritative and resets positions.
            top,bottom,total=[],[],e[1]
        elif e[0]=='steal':
            # A revealed card left the combat piles (draw or discard). Forget
            # any known position that could be this face; the exact count stays
            # an upper bound until the next public shuffle.
            state=parse(e[1],CODEC)
            if state in top:top=top[:top.index(state)]
            if state in bottom:bottom=bottom[bottom.index(state)+1:]
        elif e[0]=='draw_remove':
            if total<=0:raise ValueError('Public draw removal underflow')
            state=parse(e[4],CODEC)
            if e[2]=='top':
                expected=top[0] if top else bottom[0] if total==len(bottom) else None
                if expected is not None and expected!=state:raise ValueError('Draw contradicts known face')
                if top:top.pop(0)
                elif total==len(bottom):bottom.pop(0)
            elif e[2]=='unknown':
                if state in top:top=top[:top.index(state)]
                if state in bottom:bottom=bottom[bottom.index(state)+1:]
            else:raise ValueError('Unsupported removal location')
            total-=1
        elif e[0]=='draw_insert':
            state=parse(e[4],CODEC)
            if e[2]=='top':top.insert(0,state)
            elif e[2]=='bottom':bottom.append(state)
            else:top,bottom=[],[]
            total+=1
        elif e[0]=='card_state_change':
            old=parse(e[1],CODEC)
            # An identical face may exist in several zones. Forget ambiguous
            # positions rather than identifying a hidden instance by native ID.
            if old in top:top=top[:top.index(old)]
            if old in bottom:bottom=bottom[bottom.index(old)+1:]
        if len(top)+len(bottom)==total:top,bottom=top+bottom,[]
    return tuple(s.token for s in top),tuple(s.token for s in bottom),canonical_json(
        dict(top=[asdict(s) for s in top],bottom=[asdict(s) for s in bottom]))

