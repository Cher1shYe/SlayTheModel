"""Public multiset of individual card faces, reconstructed from visible events."""
import json
from dataclasses import asdict
from collections import Counter
from .config import canonical_json
from .card_state import PublicCardState


def parse(data,codec):
    if isinstance(data,str):data=json.loads(data)
    return codec.validate(PublicCardState(**{'version':codec.policy.state_version,**data,'effect_vars':tuple(tuple(p) for p in data['effect_vars'])}))


def inventory(deck,events,codec):
    cards=Counter(codec.capture(codec._reference(t)) for t in deck)
    for e in events:
        if e[0]=='generated_state':cards[parse(e[1],codec)]+=1
        elif e[0]=='power_removed_state':
            state=parse(e[1],codec)
            if cards[state]<=0:raise ValueError('Removed power state absent from public inventory')
            cards[state]-=1
        elif e[0]=='steal':
            # A revealed stolen card leaves the combat piles for good; a death
            # return happens outside combat and never re-enters a pile.
            state=parse(e[1],codec)
            if cards[state]<=0:raise ValueError('Stolen card state absent from public inventory')
            cards[state]-=1
        elif e[0]=='card_state_change':
            old,new=parse(e[1],codec),parse(e[2],codec)
            if cards[old]<=0:raise ValueError('Changed card state absent from public inventory')
            cards[old]-=1;cards[new]+=1
    return +cards


def read(blob,codec):
    data=json.loads(blob)
    if set(data)!={'draw','discard','exhaust'}:raise ValueError('Invalid public card memory')
    return {k:tuple(parse(s,codec) for s in values) for k,values in data.items()}


def capture(world,history,deck,codec,execution):
    visible={k:tuple(codec.capture(c) for c in getattr(world,k+'_pile')) for k in ('discard','exhaust')}
    remaining=inventory(deck,history.public_events,codec)
    remaining.subtract(codec.capture(c) for c in world.hand)
    for values in visible.values():remaining.subtract(values)
    if execution:
        from .execution import states
        remaining.subtract(states(execution,codec)[1])
    if any(n<0 for n in remaining.values()):raise ValueError('Visible card states exceed public inventory')
    visible['draw']=tuple(sorted(remaining.elements(),key=lambda s:canonical_json(asdict(s))))
    visible['exhaust']=tuple(sorted(visible['exhaust'],key=lambda s:canonical_json(asdict(s))))
    return canonical_json({k:[asdict(s) for s in values] for k,values in visible.items()})


def validate(info,codec):
    data=read(info.card_memory,codec)
    for k,names in [('draw',info.draw_composition),('discard',info.discard),('exhaust',info.exhaust)]:
        if Counter(s.token for s in data[k])!=Counter(names):raise ValueError('Card memory/token mismatch')
    top,bottom=known_states(info,codec)
    if Counter(top+bottom)-Counter(data['draw']):raise ValueError('Known face absent from draw')
    visible=Counter(info.hand_states)
    for values in data.values():visible.update(values)
    if info.execution:
        from .execution import states
        visible.update(states(info.execution,codec)[1])
    if visible!=inventory(info.known_deck,info.history.public_events,codec):raise ValueError('Public card state conservation failed')
    return data


def known_states(info,codec):
    if not info.history.position_states:
        return tuple(codec.capture(codec._reference(t)) for t in info.known_top),tuple(codec.capture(codec._reference(t)) for t in info.known_bottom)
    data=json.loads(info.history.position_states)
    if set(data)!={'top','bottom'}:raise ValueError('Invalid known-position faces')
    top,bottom=tuple(parse(v,codec) for v in data['top']),tuple(parse(v,codec) for v in data['bottom'])
    if tuple(s.token for s in top)!=info.known_top or tuple(s.token for s in bottom)!=info.known_bottom:raise ValueError('Known face/token mismatch')
    return top,bottom


def restore(world,info,codec):
    data=validate(info,codec)
    top,bottom=known_states(info,codec)
    pool=list(data['draw'])
    for state in top+bottom:pool.remove(state)
    world.shuffle_rng.shuffle(pool)
    world.draw_pile=[codec.restore(s) for s in (*top,*pool,*bottom)]
    world.discard_pile=[codec.restore(s) for s in data['discard']]
    world.exhaust_pile=[codec.restore(s) for s in data['exhaust']]
    for c in world.draw_pile+world.discard_pile+world.exhaust_pile:c.owner=world.player
