"""Visible power order and explicitly audited secondary counters."""
import json
from .config import canonical_json

COUNTERS={'DARK_EMBRACE':'_ethereal_exhaust_count','CRIMSON_MANTLE':'self_damage','INFERNO':'self_damage',
          'JUGGLING':'_attacks_played_this_turn'}

def capture(world):
    from sts2_env.core.enums import PowerId
    rupture=world.player.powers.get(PowerId.RUPTURE)
    calamity=world.player.powers.get(PowerId.CALAMITY)
    attack_sources=[]
    if calamity:
        for key in calamity._played_attack_ids:
            index=next((i for i,c in enumerate(world.play_pile) if c.instance_id==key),None)
            if index is None:raise ValueError('Calamity source outside public play stack')
            attack_sources.append(index)
    contexts=[f['context'] for f in world._play_continuations if f['kind']=='play']+([world._pending_play] if world._pending_play else [])
    blocks=[]
    for target,props,play in world._block_events_this_turn:
        if target is not world.player:continue
        index=next((world.play_pile.index(c['card']) for c in contexts if play is c and c['card'] in world.play_pile),-1)
        blocks.append([int(props),index])
    pending=[]
    if rupture:
        for key,value in rupture._pending_by_card.items():
            index=next((i for i,c in enumerate(world.play_pile) if id(c)==key),None)
            if index is None:raise ValueError('Rupture source outside public play stack')
            pending.append([index,value])
    return canonical_json(dict(order=[p.name for p in world.player.powers],
        calamity=sorted(attack_sources),blocks=blocks,rupture=sorted(pending),counters={p.name:getattr(v,COUNTERS[p.name]) for p,v in world.player.powers.items() if p.name in COUNTERS}))

def read(info):
    data=json.loads(info.power_memory)
    if set(data)!={'order','counters','rupture','blocks','calamity'} or type(data['order'])is not list or len(set(data['order']))!=len(data['order']):raise ValueError('Invalid public power order')
    from sts2_env.core.enums import PowerId
    if any(n not in PowerId.__members__ for n in data['order']):raise ValueError('Unknown ordered power')
    expected={n for n in data['order'] if n in COUNTERS}
    if set(data['counters'])!=expected or any(type(v)is not int or not 0<=v<=100000 for v in data['counters'].values()):raise ValueError('Invalid secondary power counter')
    from .execution import states
    from .content_expansion import CODEC
    size=len(states(info.execution,CODEC)[1]) if info.execution else 0
    if any(type(i)is not int or not 0<=i<size for i in data['calamity']) or (data['calamity'] and 'CALAMITY' not in data['order']):raise ValueError('Invalid Calamity pending attacks')
    for r in data['blocks']:
        if type(r)is not list or len(r)!=2 or any(type(v)is not int for v in r) or r[0]<0 or not -1<=r[1]<size:raise ValueError('Invalid block history')
    if data['rupture']:
        from .execution import states
        from .content_expansion import CODEC
        if 'RUPTURE' not in data['order'] or not info.execution:raise ValueError('Rupture without pending execution')
        size=len(states(info.execution,CODEC)[1]);seen=set()
        for r in data['rupture']:
            if type(r)is not list or len(r)!=2 or any(type(v)is not int for v in r) or not 0<=r[0]<size or not 0<=r[1]<=100000 or r[0] in seen:raise ValueError('Invalid deferred Rupture')
            seen.add(r[0])
    return data

def restore(world,info):
    from sts2_env.core.enums import PowerId
    data=read(info)
    if set(data['order'])!={p.name for p in world.player.powers}:raise ValueError('Public power order disagrees with powers')
    world.player.powers={PowerId[n]:world.player.powers[PowerId[n]] for n in data['order']}
    for n,v in data['counters'].items():setattr(world.player.powers[PowerId[n]],COUNTERS[n],v)
    if PowerId.RUPTURE in world.player.powers:
        world.player.powers[PowerId.RUPTURE]._pending_by_card={id(world.play_pile[i]):v for i,v in data['rupture']}
    if PowerId.CALAMITY in world.player.powers:
        world.player.powers[PowerId.CALAMITY]._played_attack_ids={world.play_pile[i].instance_id for i in data['calamity']}
    contexts=[f['context'] for f in world._play_continuations if f['kind']=='play']+([world._pending_play] if world._pending_play else [])
    from sts2_env.core.enums import ValueProp
    world._block_events_this_turn=[]
    for props,index in data['blocks']:
        play=next((c for c in contexts if c['card'] is world.play_pile[index]),None) if index>=0 else object()
        if index>=0 and play is None:raise ValueError('Block source is not an active frame')
        world._block_events_this_turn.append((world.player,ValueProp(props),play))
