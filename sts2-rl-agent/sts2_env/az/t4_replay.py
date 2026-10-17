"""Two explicit pools, atomic whole-episode commit, immutable source binding."""
import gzip
import json
from pathlib import Path
from copy import deepcopy
from .config import atomic_json,canonical_json,content_hash,atomic_replace
from .entity_replay import EntityReplayBuffer
from .natural_course import validate_suffix,checked
from .t4_protocol import validate_protocol,signature,training_recipes,HELDOUT_ID
from .scenarios import CombatScenario
from .content import BOSS_CONTENT
from .rewards import V7


def stable(record):
    value=deepcopy(record)
    for row in value['rows']:row.pop('search_seconds',None)
    return value


class MixedReplay:
    def __init__(self,root,binding,protocol,course,capacities=None):
        self.root=Path(root);self.root.mkdir(parents=True,exist_ok=True)
        validate_protocol(protocol,course['entries']);checked(course)
        self.protocol,self.course=protocol,course
        self.capacities=capacities or {'full':150000,'late':50000}
        if set(self.capacities)!={'full','late'} or any(type(v)!=int or v<1 for v in self.capacities.values()):
            raise ValueError('Invalid replay capacities')
        self.binding=binding;self.cache={}
        self.full_validator=EntityReplayBuffer(self.root/'full-validator',content_version=BOSS_CONTENT,reward_version=V7)
        self.manifest=dict(version='t4-mixed-replay-v1',binding=binding,capacities=self.capacities,
                           committed={},row_counts={},active={'full':[],'late':[]})
        path=self.root/'manifest.json'
        if path.exists():
            value=json.loads(path.read_text(encoding='utf-8'))
            if any(value.get(k)!=self.manifest[k] for k in ('version','binding','capacities')):
                raise ValueError('Replay binding/capacity mismatch')
            self.manifest=value
            if set(value['active'])!={'full','late'}:raise ValueError('Missing Replay pool')
            for kind,ids in value['active'].items():
                if kind not in ('full','late') or len(ids)!=len(set(ids)):raise ValueError('Invalid active pool')
                for identity in ids:
                    item=self.read(identity)
                    if item['kind']!=kind:raise ValueError('Replay pool mismatch')
                    if len(item['record']['rows'])!=value['row_counts'][identity]:raise ValueError('Replay row-count mismatch')
                    self.validate(item)
                if self.size(kind)>self.capacities[kind]:raise ValueError('Replay over capacity')

    def read(self,identity):
        if len(identity)!=64 or any(c not in '0123456789abcdef' for c in identity):raise ValueError('Invalid replay identity')
        if identity not in self.cache:
            path=self.root/'episodes'/f'{identity}.json.gz'
            item=json.loads(gzip.decompress(path.read_bytes()))
            if content_hash(item)!=self.manifest['committed'][identity]:raise ValueError('Replay digest mismatch')
            if len(item['record']['rows'])!=self.manifest['row_counts'][identity]:raise ValueError('Replay row-count mismatch')
            self.cache[identity]=item
            while len(self.cache)>16:self.cache.pop(next(iter(self.cache)))
        return self.cache[identity]

    def validate(self,item):
        kind,record=item['kind'],item['record']
        if kind=='full':
            recipe=CombatScenario.from_dict(item['recipe'])
            if recipe.split!='train' or signature(recipe) not in {signature(r) for r in training_recipes(self.protocol)}:
                raise ValueError('Full episode outside training combos')
            self.full_validator.validate(record)
            from .adapter import ObservableCombatAdapter
            from .entity_transition import public_from_dict
            if (record['rows'][0]['scenario_id']!=recipe.scenario_id or
                public_from_dict(record['rows'][0]['public_information'])!=ObservableCombatAdapter(recipe,reward_version=V7).information):
                raise ValueError('Full episode must start at original battle boundary')
            if any(HELDOUT_ID in r['public_information']['known_deck'] or HELDOUT_ID+'+' in r['public_information']['known_deck'] for r in record['rows']):
                raise ValueError('Heldout ID in Replay')
        elif kind=='late':
            if record['start'] not in self.course['entries']:raise ValueError('Unknown late start')
            validate_suffix(record)
        else:raise ValueError('Unknown Replay kind')

    def size(self,kind):
        return sum(self.manifest['row_counts'][i] for i in self.manifest['active'][kind])

    def commit(self,identity,kind,record,recipe=None):
        if len(identity)!=64 or any(c not in '0123456789abcdef' for c in identity):raise ValueError('Invalid replay identity')
        item=dict(kind=kind,record=stable(record),recipe=recipe)
        # Entity validation requires the timing field; normalize it deterministically.
        if kind=='full':
            for row in item['record']['rows']:row['search_seconds']=0.
        self.validate(item)
        digest=content_hash(item)
        if identity in self.manifest['committed']:
            if digest!=self.manifest['committed'][identity]:raise ValueError('Conflicting replay retry')
            return False
        if len(record['rows'])>self.capacities[kind]:raise ValueError('Episode exceeds pool capacity')
        import os,tempfile
        directory=self.root/'episodes';directory.mkdir(exist_ok=True)
        fd,temp=tempfile.mkstemp(dir=directory,suffix='.tmp')
        try:
            with os.fdopen(fd,'wb') as f:
                f.write(gzip.compress(canonical_json(item).encode(),mtime=0));f.flush();os.fsync(f.fileno())
            atomic_replace(temp,directory/f'{identity}.json.gz')
        finally:
            if os.path.exists(temp):os.unlink(temp)
        new=deepcopy(self.manifest);new['committed'][identity]=digest;new['active'][kind].append(identity)
        new['row_counts'][identity]=len(record['rows'])
        # Old manifest remains the commit point if publication fails.
        def length(i):return new['row_counts'][i]
        while sum(length(i) for i in new['active'][kind])>self.capacities[kind]:new['active'][kind].pop(0)
        atomic_json(self.root/'manifest.json',new)
        self.manifest=new;self.cache[identity]=item
        active=set(sum(new['active'].values(),[]))
        self.cache={k:v for k,v in self.cache.items() if k in active}
        while len(self.cache)>16:self.cache.pop(next(iter(self.cache)))
        return True

    def sample(self,rng,full=48,late=16):
        samples=[]
        for kind,count in (('full',full),('late',late)):
            ids=self.manifest['active'][kind]
            if not ids or type(count)!=int or count<1:raise ValueError('Both Replay pools required; no ratio fallback')
            for _ in range(count):
                rows=self.read(ids[int(rng.integers(len(ids)))])['record']['rows']
                samples.append(deepcopy(rows[int(rng.integers(len(rows)))]))
        return samples
