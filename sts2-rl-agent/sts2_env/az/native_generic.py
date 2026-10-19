"""Versioned native JSON protocol: no Python card or monster registry lookup."""
from copy import deepcopy
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import re

from .config import content_hash, canonical_json
from .rewards import V7
from .risk_reward import utility
from .entity_replay import EntityReplayBuffer

FORMAT = 'native-generic-collection-v1'
CONTENT = 'native-generic-json-v1'
SCHEMA = dict(version=CONTENT, features='two-hash-field-value-v1', buckets=8192,
              max_entities=512, max_actions=512, max_leaves=2048,
              teacher='native_checkpoint_privileged', search='root-prior-uniform-tree-rollout-v1')
SCHEMA_HASH = content_hash(SCHEMA)
VALUE_SEARCH = 'root-prior-uniform-tree-leaf-v1'


def raw_leaf_settings(raw):
    from .search_config import leaf_settings
    mode,mix=raw.get('leafMode','heuristic'),raw.get('valueMix',.5)
    leaf_settings(mode,mix)
    expected=SCHEMA['search'] if mode=='heuristic' else VALUE_SEARCH
    if raw['searchMode']!=expected: raise ValueError('Native leaf mode/search contract mismatch')
    return mode,mix


def validate_recipe(r):
    if set(r) != {'scenario_id', 'encounter', 'seed', 'hp', 'deck', 'split'}:
        raise ValueError('Generic recipe fields differ')
    if (not isinstance(r['encounter'], str) or not re.fullmatch(r'[A-Z][A-Z0-9_]{0,99}', r['encounter'])
            or r['split'] not in ('train', 'validation') or type(r['seed']) is not int
            or not 0 <= r['seed'] < 2_000_000_000 or type(r['hp']) is not int or not 1 <= r['hp'] <= 80
            or not isinstance(r['deck'], list) or not 1 <= len(r['deck']) <= 60
            or any(not isinstance(c,str) or not re.fullmatch(r'[A-Z][A-Z0-9_]{0,99}\+?',c) for c in r['deck'])):
        raise ValueError('Malformed generic recipe')
    if (r['seed'] >= 1_000_000_000) != (r['split']=='validation'):
        raise ValueError('Generic train/validation seed domain mismatch')
    if r['scenario_id'] != content_hash({k:v for k,v in r.items() if k!='scenario_id'}):
        raise ValueError('Generic recipe fingerprint mismatch')
    return r


def leaves(value, path=''):
    if isinstance(value, dict):
        for key in sorted(value):
            if not isinstance(key, str):
                raise ValueError('JSON keys must be strings')
            yield from leaves(value[key], path+'/'+key)
    elif isinstance(value, list):
        for i, v in enumerate(value):
            yield from leaves(v, path+'/'+str(i))
        if not value:
            yield path, 'empty-list'
    elif value is None or isinstance(value, (str,bool,int,float)):
        if isinstance(value,(int,float)) and not math.isfinite(value):
            raise ValueError('Nonfinite native feature')
        if isinstance(value,str) and len(value)>8192:
            raise ValueError('Native text too long')
        yield path, value
    else:
        raise ValueError('Non-JSON native feature')


def encode(frame, *, value_only=False):
    if set(frame) != {'version','initialHp','decisions','observation','cards','intents','choice','actions'} or frame['version']!='native-generic-observation-v1':
        raise ValueError('Unknown native generic frame')
    o = deepcopy(frame['observation'])
    if o['SchemaVersion'] != 5 or len(o['Players']) != 1:
        raise ValueError('Native collector schema/single-player mismatch')
    if set(o) != {'SchemaVersion','RoundNumber','CurrentSide','Players','Creatures',
                  'EnemyIntents','Companions','ActiveChoice','PendingManualActions'}:
        raise ValueError('Unknown collector observation fields')
    if o['Companions'] or o['PendingManualActions'] or o['ActiveChoice'] or o['EnemyIntents']:
        raise ValueError('Unprojected collector extension; refusing silent feature loss')
    card_data = {c['index']: c['data'] for c in frame['cards']}
    if len(card_data)!=len(frame['cards']):
        raise ValueError('Duplicate native card index')
    creature_data = {c['CombatId']: c for c in o['Creatures']}
    if len(creature_data)!=len(o['Creatures']):
        raise ValueError('Duplicate creature index')
    entities = [dict(kind='state', turn=o['RoundNumber'], side=o['CurrentSide'], initial_hp=frame['initialHp'], decisions=frame['decisions'])]
    player = o['Players'][0]
    player_id = player['PlayerId']
    for c in o['Creatures']:
        c['role'] = 'player' if c['PlayerId']==player_id else 'enemy'
        del c['PlayerId']
        del c['CombatId']
        entities.append(dict(kind='creature', **c))
    seen = set()
    for pile in player.pop('Piles'):
        zone = pile['PileType']
        cards = []
        for c in pile['Cards']:
            index = c.pop('CombatCardIndex')
            if index not in card_data or index in seen:
                raise ValueError('Missing/duplicate native pile card')
            seen.add(index)
            cards.append(dict(c, native=card_data[index]))
        # Collector snapshots contain exact draw order; the student must not receive it.
        if 'draw' in str(zone).lower():
            cards.sort(key=canonical_json)
        for i,c in enumerate(cards):
            entities.append(dict(kind='card', zone=zone, slot=i if 'draw' not in str(zone).lower() else 0, **c))
    if seen != set(card_data):
        raise ValueError('Native card projection mismatch')
    player.pop('PlayerId')
    entities.append(dict(kind='player', **player))
    for intent in frame['intents']:
        if intent['target'] not in creature_data:
            raise ValueError('Unknown intent creature')
        entities.append(dict(kind='intent', creature=creature_data[intent['target']], intents=intent['intents']))
    if frame['choice'] is not None:
        choice=frame['choice']
        if not 0 <= choice['min'] <= choice['max'] <= len(choice['options']):
            raise ValueError('Invalid native choice bounds')
        entities.append(dict(kind='choice', **choice))
    actions=[]
    for action in frame['actions']:
        f=deepcopy(action['features'])
        if f.get('target') is not None:
            if f['target'] not in creature_data:
                raise ValueError('Unknown action target')
            f['target']=creature_data[f['target']]
        if f['kind']=='Choose':
            if frame['choice'] is None:
                raise ValueError('Choice action without selector')
            indices=[s['index'] for s in f['selected']]
            if (len(set(indices))!=len(indices) or not frame['choice']['min']<=len(indices)<=frame['choice']['max']
                    or any(type(i) is not int or not 0<=i<len(frame['choice']['options']) for i in indices)
                    or any(s['card']!=frame['choice']['options'][s['index']] for s in f['selected'])):
                raise ValueError('Invalid native selected options')
        actions.append(dict(key=action['Key'], features=f))
    packed=dict(schema=SCHEMA_HASH, entities=entities, actions=actions)
    validate_packed(packed, value_only=value_only)
    return packed


def validate_packed(p, *, value_only=False):
    if set(p)!={'schema','entities','actions'} or p['schema']!=SCHEMA_HASH:
        raise ValueError('Generic packed schema mismatch')
    if not 1<=len(p['entities'])<=SCHEMA['max_entities'] or not (0 if value_only else 1)<=len(p['actions'])<=SCHEMA['max_actions']:
        raise ValueError('Generic frame exceeds bounds; truncation forbidden')
    keys=[a['key'] for a in p['actions']]
    if any(not isinstance(k,str) or not k for k in keys) or len(set(keys))!=len(keys):
        raise ValueError('Invalid/duplicate native action key')
    for e in p['entities']+[a['features'] for a in p['actions']]:
        if not isinstance(e,dict) or not e or len(list(leaves(e)))>SCHEMA['max_leaves']:
            raise ValueError('Invalid/oversized generic feature object')


def validate_raw(raw, *, allow_validation_cutoff=False, allow_training_cutoff=False):
    mode,mix=raw_leaf_settings(raw)
    truncated=raw.get('complete') is False
    permitted_cutoff=(allow_validation_cutoff and raw.get('arm')=='policy' and raw.get('split')=='validation'
                      or allow_training_cutoff and raw.get('arm') in ('puct','uct') and raw.get('split')=='train')
    if truncated and not permitted_cutoff:
        raise ValueError('Truncated trajectory requires explicit split/arm admission')
    if (raw['format']!=FORMAT or raw['teacherInformation']!='native_checkpoint_privileged'
            or type(raw['complete']) is not bool
            or raw['arm'] not in ('policy','puct','uct') or not raw['steps']):
        raise ValueError('Generic trajectory contract mismatch')
    r=validate_recipe(raw['recipe'])
    if any(raw[k]!=r[k] for k in ('seed','encounter','split')) or raw['initialHp']!=r['hp']:
        raise ValueError('Generic recipe/trajectory mismatch')
    for k in ('identity','modelSha256'):
        if not re.fullmatch('[0-9a-f]{64}',raw[k]):
            raise ValueError('Generic provenance missing')
    if type(raw['budgetMs']) is not int or not 50<=raw['budgetMs']<=1000:
        raise ValueError('Invalid native budget')
    end=raw['outcome']
    if not math.isfinite(raw['wallSeconds']) or raw['wallSeconds'] < 0:
        raise ValueError('Invalid native wall time')
    if type(end['won']) is not bool or end['decisions']!=len(raw['steps']):
        raise ValueError('Generic endpoint mismatch')
    if truncated:
        cutoff=end['cutoff']
        if (end.get('terminationReason')!='time_limit' or end['won'] or end['finalHp']<=0
                or not (end['decisions']==100 or end['turns']>40) or type(cutoff['pendingChoice']) is not bool
                or (cutoff['pendingChoice'] and cutoff['risk']!=1)):
            raise ValueError('Invalid cutoff boundary')
        z=utility('time_limit',end['finalHp'],r['hp'],end['maxHp'],cutoff['damage'],cutoff['risk'])
    else:
        z=utility('win' if end['won'] else 'death',end['finalHp'],r['hp'],end['maxHp'],1.,0.)
    if not math.isfinite(end['reward']) or abs(end['reward']-z)>1e-15 or not math.isfinite(end['searchReward']) or abs(end['searchReward']-z)>1e-15:
        raise ValueError('Generic terminal reward mismatch')
    encoded=[]
    for i,s in enumerate(raw['steps']):
        f=s['observation']
        if 'successorParityScope' in s:
            scope=s['successorParityScope']
            pending_after=(i+1<len(raw['steps']) and raw['steps'][i+1]['observation']['choice'] is not None)
            if truncated and i==len(raw['steps'])-1: pending_after=end['cutoff']['pendingChoice']
            if scope not in ('selector_boundary','complete_continuation') or (scope=='selector_boundary') != pending_after:
                raise ValueError('Native successor parity boundary mismatch')
        if mode!='heuristic':
            d=s['leafDiagnostics']
            if type(d['valueCalls']) is not int or d['valueCalls']<0: raise ValueError('Invalid leaf diagnostics')
            if any(not math.isfinite(d[k]) or abs(d[k])>d['valueCalls']+1e-8 for k in ('valueSum','heuristicSum','evaluatedValueSum')):
                raise ValueError('Invalid leaf value totals')
            expected=d['valueSum'] if mode=='learned' else (1-mix)*d['heuristicSum']+mix*d['valueSum']
            if abs(expected-d['evaluatedValueSum'])>1e-7*max(1,d['valueCalls']): raise ValueError('Leaf mixture mismatch')
            if (any(type(d[k]) is not int or d[k]<0 for k in ('leafBackups','terminalBackups'))
                    or d['leafBackups']+d['terminalBackups']!=s['simulations'] or d['leafBackups']>d['valueCalls']
                    or not math.isfinite(d['meanBackupDepth']) or d['meanBackupDepth']<0):
                raise ValueError('Native leaf backup accounting mismatch')
        if (s['featureParity'] is not True or s['successorParity'] is not True or f['decisions']!=i
                or f['initialHp']!=r['hp'] or s['terminalAfter']!=(not truncated and i==len(raw['steps'])-1)):
            raise ValueError('Generic state parity missing')
        o=f['observation']; pid=o['Players'][0]['PlayerId']
        if i == 0:
            actual=Counter(c['data']['model'] + '+'*c['data']['upgrade'] for c in f['cards'])
            if actual != Counter(r['deck']):
                raise ValueError('Generic initial deck/upgrade mismatch')
        player=next(c for c in o['Creatures'] if c['PlayerId']==pid)
        if player['CurrentHp']!=(r['hp'] if i==0 else raw['steps'][i-1]['hpAfter']):
            raise ValueError('Generic HP continuity mismatch')
        if i==len(raw['steps'])-1 and s['hpAfter']!=end['finalHp']:
            raise ValueError('Generic final HP mismatch')
        packed=encode(f); keys={a['key'] for a in packed['actions']}
        if (set(s['visits'])!=keys or s['action'] not in keys or type(s['simulations']) is not int
                or s['simulations']<0 or any(type(v) is not int or v<0 for v in s['visits'].values())
                or sum(s['visits'].values())!=s['simulations'] or s['forced']!=(len(keys)==1)
                or not math.isfinite(s['seconds']) or s['seconds']<0):
            raise ValueError('Generic policy target mismatch')
        if (s['simulations']==0)!=(s['forced'] or raw['arm']=='policy'):
            raise ValueError('Missing native visit labels')
        encoded.append(packed)
    return encoded


def to_episode(raw):
    encoded=validate_raw(raw,allow_training_cutoff=True)
    if raw['split']!='train' or raw['arm']=='policy':
        raise ValueError('Only training search trajectories may enter generic replay')
    identity=content_hash([raw['identity'],raw['recipe'],raw['arm']])
    rows=[]
    for i,(s,o) in enumerate(zip(raw['steps'],encoded)):
        pi={k:1. if s['forced'] else v/s['simulations'] for k,v in s['visits'].items()}
        rows.append(dict(episode_id=identity,step_index=i,observation=o,policy_target=pi,z=raw['outcome']['reward'],
            family_id='native-generic/'+raw['encounter'],encounter_id=raw['encounter'],scenario_id=raw['recipe']['scenario_id'],
            root_visits=s['visits'],chosen_action=s['action'],forced_action=s['forced'],search_seconds=s['seconds']))
    return dict(episode_id=identity,complete=True,split='train',rows=rows,native_audit=raw,
                compatibility=GenericReplay.compatibility_for(*raw_leaf_settings(raw)),
                outcome=dict(raw['outcome'],termination_reason='time_limit' if not raw['complete'] else 'win' if raw['outcome']['won'] else 'death',truncated=not raw['complete']))


class GenericReplay(EntityReplayBuffer):
    @staticmethod
    def compatibility_for(leaf_mode='heuristic',value_mix=.5):
        from .search_config import leaf_settings
        leaf_settings(leaf_mode,value_mix)
        result=dict(information_mode='observable',content_version=CONTENT,reward_version=V7,schema_hash=SCHEMA_HASH,
                    native_adapter=FORMAT,teacher_information=SCHEMA['teacher'],search_version=SCHEMA['search'],
                    truncation_policy='v7-bounded-episode-v1')
        if leaf_mode!='heuristic': result.update(search_version=VALUE_SEARCH,leaf_mode=leaf_mode,value_mix=value_mix)
        return result

    def __init__(self,directory,capacity=50000,*,leaf_mode='heuristic',value_mix=.5):
        self.directory,self.capacity=Path(directory),capacity
        if type(capacity) is not int or capacity<1: raise ValueError('Invalid replay capacity')
        self.content_version=CONTENT; self.compatibility=self.compatibility_for(leaf_mode,value_mix)
        self.episodes=[]; self.committed={}
        p=self.directory/'manifest.json'
        if p.exists():
            m=json.loads(p.read_text())
            if m['compatibility']!=self.compatibility or m['capacity']!=capacity: raise ValueError('Generic replay mismatch')
            self.committed=m['committed']
            for identity in m['active']:
                e=self.read_episode(identity); self.validate(e)
                if self.digest(e)!=self.committed[identity]: raise ValueError('Generic replay checksum mismatch')
                self.episodes.append(e)

    def validate(self,e):
        if e['compatibility']!=self.compatibility: raise ValueError('Generic replay leaf settings mismatch')
        if e!=to_episode(e['native_audit']): raise ValueError('Generic replay/audit mismatch')
