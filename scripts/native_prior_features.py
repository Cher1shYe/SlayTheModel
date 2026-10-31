"""Shared strict feature projection for native inference and training."""
from collections import Counter
from types import SimpleNamespace as NS
from sts2_env.az.entity_encoder import Entity, EntityObservation, ActionCandidate, numeric
from sts2_env.az.expanded_entities import card_entity, pile_state
from sts2_env.az.all_entities import enemy_entities
from sts2_env.az.monster_registry import info_for
from sts2_env.az.content import ALL_CONTENT
from sts2_env.az.rewards import V7


def encode_native(d):
    if d['version'] != 'native-starter-prior-v1':
        raise ValueError('Unknown native feature schema')
    entities = [Entity('state', 'state', 'none', None, numeric(
        turn=d['turn'], decisions=d['decisions'], max_decisions=400, max_turns=40,
        initial_hp=d['initialHp'], played_this_turn=d['played'], completed_plays=d['played'],
        attack_count=d['attacks'], enemy_rounds=d['turn']-1,
        received_unblocked_hits=d['unblockedHits'])),
        Entity('player', 'player', 'none', None, numeric(hp=d['hp'], max_hp=d['maxHp'],
            block=d['block'], energy=d['energy'], max_energy=3))]
    slots, target_refs = [], {}
    for index, enemy in enumerate(d['enemies']):
        if enemy['id'] != 'BYRDONIS':
            raise ValueError('Unaudited monster: '+enemy['id'])
        script = info_for(enemy['id'])
        move = enemy['move']
        if move not in script.moves:
            raise ValueError('Unknown native move: '+str(move))
        intents = dict(script.intent_signatures)[move]
        expected_hits = [damage for kind, damage, hits in intents
                         if kind in ('ATTACK', 'MULTI_ATTACK') for _ in range(hits)]
        if len(expected_hits) != len(enemy['hits']) or len(set(enemy['hits'])) > 1:
            raise ValueError('Native/Python intent shape mismatch')
        # The old simulator has Byrdonis swoop=16; native v0.111.0 is 17.
        # Keep static operation structure, always use native numerical damage.
        intents = tuple((kind, enemy['hits'][0], hits) if kind in ('ATTACK','MULTI_ATTACK')
                        else (kind, damage, hits) for kind, damage, hits in intents)
        powers = tuple((p['id'].removesuffix('_POWER'), p['amount']) for p in enemy['powers'])
        amounts = dict(powers)
        previous = script.initial_moves[0]
        for _ in range(max(0, d['turn']-2)):
            follow = dict(script.successors).get(previous, ())
            if len(follow) != 1: raise ValueError('Ambiguous public history')
            previous = follow[0]
        values = dict(slot=index, monster_id=enemy['id'], hp=enemy['hp'], max_hp=enemy['maxHp'],
            initial_hp=enemy['maxHp'], block=enemy['block'], move=move,
            moves=(previous,)*(d['turn']-1), intents=intents, powers=powers,
            primary=True, spawned=False, reviving=False)
        for field in ('vulnerable','strength','slow','territorial','artifact','illusion','minion'):
            values[field] = amounts.get(field.upper(), 0)
        slots.append(NS(**values))
        target_refs[enemy['combatId']] = f'enemy/{index}'
    entities.extend(enemy_entities(NS(enemies=slots, history=NS(pending_target=None))))
    for zone in ('hand', 'discard', 'draw'):
        tokens = [c['id'] for c in d[zone]]
        rows = list(enumerate((token, 1) for token in tokens)) if zone != 'draw' else list(enumerate(sorted(Counter(tokens).items())))
        for index, (token, count) in rows:
            if token not in ('STRIKE_IRONCLAD', 'DEFEND_IRONCLAD', 'BASH'):
                raise ValueError('Unsupported card')
            entities.append(card_entity(f'{zone}/{index}', pile_state(token, 0), zone,
                                        count=count, slot=index+1 if zone=='hand' else 0))
    actions = []
    for a in d['actions']:
        if a['Kind'] == 'EndTurn':
            actions.append(ActionCandidate(a['Key'], 'end_turn'))
            continue
        matches = [i for i, c in enumerate(d['hand']) if c['stateKey']==a['CardStateKey']]
        index = matches[a['CardStateOccurrence']]
        refs = (target_refs[a['TargetCombatId']],) if a['TargetCombatId'] is not None else ('player',)
        actions.append(ActionCandidate(a['Key'], 'play', f'hand/{index}', refs))
    obs = EntityObservation(tuple(entities), tuple(actions), content_version=ALL_CONTENT, reward_version=V7).validate()
    return obs
