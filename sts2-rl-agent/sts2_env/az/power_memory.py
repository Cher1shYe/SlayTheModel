"""Visible power order, secondary counters and public per-power bookkeeping.

Every value stored here is a function of public history: visible power order,
displayed amounts, per-turn play counts and draw counts.  Nothing reads a
hidden card index or the simulator RNG.
"""
import json
from .config import canonical_json

COUNTERS={'DARK_EMBRACE':'_ethereal_exhaust_count','CRIMSON_MANTLE':'self_damage','INFERNO':'self_damage',
          'JUGGLING':'_attacks_played_this_turn',
          'AUTOMATION':'cards_left','PANACHE':'_cards_left','THE_BOMB':'damage',
          'CHAINS_OF_BINDING':'_bound_cards_this_turn','TENDER':'_cards_played_this_turn'}
# Compound public bookkeeping.  Each attribute is still derived from visible
# plays/draws/turns; only its representation differs from a single integer.
#   pairs   : list[[int, int]]
#   triples : list[[int, int, bool]]
#   ints    : list[int]
EXTRAS={'AUTOMATION':{'_instances':'pairs'},'PANACHE':{'_started':'bool','_instances':'triples'},
        'ROLLING_BOULDER':{'_instances':'ints'},'THE_BOMB':{'_instances':'pairs'},
        'CHAINS_OF_BINDING':{'_bound_card_played':'bool'},
        # Per-turn trigger sets: the player can see whether the spark already paid
        # out this turn (their own energy), so only the count is public.
        'VITAL_SPARK':{'_triggered_players_this_turn':'count'}}


def _check(value, shape):
    if shape == 'bool':
        return type(value) is bool
    if shape == 'count':
        return type(value) is int and 0 <= value <= 8
    if not isinstance(value, list) or not 0 <= len(value) <= 64:
        return False
    if shape == 'ints':
        return all(type(v) is int and 0 <= v <= 100000 for v in value)
    if shape == 'pairs':
        return all(isinstance(v, list) and len(v) == 2
                   and all(type(n) is int and 0 <= n <= 100000 for n in v) for v in value)
    if shape == 'triples':
        return all(isinstance(v, list) and len(v) == 3 and type(v[0]) is int and type(v[1]) is int
                   and type(v[2]) is bool and 0 <= v[1] <= 100000 for v in value)
    return False

def capture_creature(creature):
    """Per-power public bookkeeping for one creature (enemy or player)."""
    rows = {}
    for power, obj in creature.powers.items():
        if power.name not in EXTRAS:
            continue
        entry = {}
        for attr in EXTRAS[power.name]:
            value = getattr(obj, attr)
            if isinstance(value, bool):
                entry[attr] = value
            elif isinstance(value, (set, frozenset)):
                entry[attr] = len(value)
            elif isinstance(value, int):
                entry[attr] = int(value)
            elif isinstance(value, list):
                entry[attr] = [[int(x) if not isinstance(x, bool) else x for x in row]
                               if isinstance(row, (list, tuple)) else int(row) for row in value]
        rows[power.name] = entry
    return canonical_json(rows)


def read_creature(blob):
    data = json.loads(blob)
    if type(data) is not dict or any(name not in EXTRAS for name in data):
        raise ValueError('Invalid creature power bookkeeping')
    for name, attrs in data.items():
        if set(attrs) != set(EXTRAS[name]) or not all(
                _check(value, EXTRAS[name][attr]) for attr, value in attrs.items()):
            raise ValueError('Invalid creature power bookkeeping')
    return data


def restore_creature(creature, blob, player=None):
    from sts2_env.core.enums import PowerId
    for name, attrs in read_creature(blob).items():
        power = creature.powers.get(PowerId[name])
        if power is None:
            raise ValueError('Creature power bookkeeping without its power')
        for attr, value in attrs.items():
            if attr == '_triggered_players_this_turn':
                power._triggered_players_this_turn = {player} if value else set()
                continue
            setattr(power, attr, [tuple(row) if isinstance(row, list) else row for row in value]
                    if isinstance(value, list) else value)


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
    extras={}
    for power, obj in world.player.powers.items():
        if power.name not in EXTRAS:
            continue
        rows = {}
        for attr in EXTRAS[power.name]:
            value = getattr(obj, attr)
            if isinstance(value, bool):
                rows[attr] = value
            elif isinstance(value, (set, frozenset)):
                rows[attr] = len(value)
            elif isinstance(value, int):
                rows[attr] = int(value)
            elif isinstance(value, list):
                rows[attr] = [[int(x) if not isinstance(x, bool) else x for x in row]
                              if isinstance(row, (list, tuple)) else int(row) for row in value]
            else:
                rows[attr] = int(value)
        extras[power.name] = rows
    visible = [p for p in world.player.powers
               if not (p.name in ('STRENGTH', 'DEXTERITY')
                       and world.player.powers[p].amount == 0)]
    return canonical_json(dict(order=[p.name for p in visible],
        calamity=sorted(attack_sources),blocks=blocks,rupture=sorted(pending),
        counters={p.name:getattr(world.player.powers[p],COUNTERS[p.name]) for p in visible if p.name in COUNTERS},
        extras={p.name: extras[p.name] for p in visible if p.name in extras}))

def read(info):
    data=json.loads(info.power_memory)
    if set(data)!={'order','counters','extras','rupture','blocks','calamity'} or type(data['order'])is not list or len(set(data['order']))!=len(data['order']):raise ValueError('Invalid public power order')
    from sts2_env.core.enums import PowerId
    if any(n not in PowerId.__members__ for n in data['order']):raise ValueError('Unknown ordered power')
    expected={n for n in data['order'] if n in COUNTERS}
    if set(data['counters'])!=expected or any(type(v)is not int or not 0<=v<=100000 for v in data['counters'].values()):raise ValueError('Invalid secondary power counter')
    expected_extras={n for n in data['order'] if n in EXTRAS}
    if type(data['extras']) is not dict or set(data['extras'])!=expected_extras:raise ValueError('Invalid public power extras')
    for name,attrs in data['extras'].items():
        if set(attrs)!=set(EXTRAS[name]) or not all(_check(value,EXTRAS[name][attr]) for attr,value in attrs.items()):
            raise ValueError('Invalid public power bookkeeping')
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
    for name,attrs in data['extras'].items():
        power=world.player.powers[PowerId[name]]
        for attr,value in attrs.items():
            if name == 'VITAL_SPARK' and attr == '_triggered_players_this_turn':
                power._triggered_players_this_turn = {world.player} if value else set()
                continue
            setattr(power,attr,[tuple(row) if isinstance(row,list) else row for row in value]
                    if isinstance(value,list) else value)
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
