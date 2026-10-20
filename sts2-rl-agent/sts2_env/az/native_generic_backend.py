"""Runtime-supplied content manifests, shared native cache and ALL lifecycle."""
import json
from pathlib import Path
import random
from .config import content_hash
from .native_generic import FORMAT, CONTENT, SCHEMA_HASH, validate_recipe, validate_raw, to_episode
from .native_backend import NativeBackend as BaseBackend


def single_player_card_tokens(catalog, *, include_upgrades=True):
    """Use native eligibility metadata; never infer multiplayer cards from names."""
    tokens = []
    for card in catalog['cards']:
        if (card['pool'] not in ('IroncladCardPool', 'ColorlessCardPool')
                or type(card['multiplayerOnly']) is not bool
                or type(card['maxUpgradeLevel']) is not int or card['maxUpgradeLevel'] < 0):
            raise ValueError('Invalid native card eligibility metadata')
        if card['multiplayerOnly']:
            continue
        tokens.append(card['id'])
        if include_upgrades and card['maxUpgradeLevel'] > 0:
            tokens.append(card['id'] + '+')
    if not tokens or len(tokens) != len(set(tokens)):
        raise ValueError('Empty or duplicate native single-player card pool')
    return tokens


def validate_protocol(p):
    body={k:v for k,v in p.items() if k!='manifest_sha256'}
    if (set(body)!={'version','cards','encounters','validation'} or p['version']!='native-generic-protocol-v1'
            or p['manifest_sha256']!=content_hash(body) or not p['cards'] or not p['encounters']
            or len(set(p['cards']))!=len(p['cards']) or len(set(p['encounters']))!=len(p['encounters'])):
        raise ValueError('Generic protocol identity mismatch')
    rows=tuple(validate_recipe(r) for r in p['validation'])
    if (not rows or any(r['split']!='validation' or r['encounter'] not in p['encounters']
                       or any(c not in p['cards'] for c in r['deck']) for r in rows)
            or len({r['seed'] for r in rows})!=len(rows) or len({r['scenario_id'] for r in rows})!=len(rows)):
        raise ValueError('Generic held-out split mismatch')
    return rows


def make_recipe(seed, encounter, cards, split):
    rng=random.Random(seed)
    # The manifest is a curriculum, not a Python implementation whitelist.
    deck=rng.choices(cards,k=10)
    r=dict(seed=seed,encounter=encounter,deck=deck,hp=rng.choice([40,60,80]),split=split)
    return validate_recipe(dict(r,scenario_id=content_hash(r)))


def frozen_protocol(cards,encounters,count=24):
    if count<len(encounters) or count%len(encounters): raise ValueError('Balanced validation required')
    body=dict(version='native-generic-protocol-v1',cards=cards,encounters=encounters,
              validation=[make_recipe(1_600_000_000+i,encounters[i%len(encounters)],cards,'validation') for i in range(count)])
    result=dict(body,manifest_sha256=content_hash(body)); validate_protocol(result); return result


def restrict_protocol_cards(protocol, excluded_base_ids):
    """Freeze a narrower pool; preserve unaffected held-out recipes exactly."""
    validate_protocol(protocol)
    excluded=set(excluded_base_ids)
    cards=[c for c in protocol['cards'] if c.rstrip('+') not in excluded]
    if not cards: raise ValueError('Cannot exclude the entire card pool')
    allowed=set(cards)
    validation=[r if set(r['deck'])<=allowed else make_recipe(r['seed'],r['encounter'],cards,'validation')
                for r in protocol['validation']]
    body=dict(version=protocol['version'],cards=cards,encounters=protocol['encounters'],validation=validation)
    result=dict(body,manifest_sha256=content_hash(body));validate_protocol(result)
    return result


def validate_settings(config,settings,*,include_test=False,workers=1):
    from .dynamic_search import leaf_settings
    leaf_settings(settings['leaf_mode'],settings['value_mix'])
    if (config['backend'].get('kind')!=FORMAT or include_test or type(workers) is not int or not 1<=workers<=4
            or settings['budget']!=config['backend']['budget_ms']
            or not 50<=settings['budget']<=1000
            or (settings['max_turns'],settings['max_decisions'],settings['eval_max_turns'],settings['eval_max_decisions'])!=(40,100,40,100)):
        raise ValueError('Generic native requires 1-4 workers, 40/100 guards, millisecond budget; no test split')


class NativeBackend(BaseBackend):
    supports_cutoff=True
    native_batch_size=1  # Each search fight has its own bounded worker timeout.
    format=FORMAT
    recipe_validator=staticmethod(validate_recipe)
    episode_converter=staticmethod(to_episode)

    def __init__(self,config,protocol,out):
        from scripts.check_native_collection import provenance, sha
        if config['kind']!=FORMAT: raise ValueError('Generic native backend required')
        self.repo=Path(config['repo']).resolve(); self.game=Path(config['game']).resolve(); self.out=Path(out)
        self.budget=config['budget_ms']; self.validation=validate_protocol(protocol); self.protocol=protocol
        self.native_batch_size=config.get('fights_per_worker',1)
        # Keep the existing 120-second watchdog. Reserve time for reset, inference
        # startup and JSON I/O, even if every fight reaches the 100-decision guard.
        if (type(self.native_batch_size) is not int or not 1<=self.native_batch_size<=4
                or self.native_batch_size*(100*self.budget+5000)>110000):
            raise ValueError('fights_per_worker exceeds bounded native worker budget')
        self.provenance=dict(sources=provenance(self.repo),protocol=protocol['manifest_sha256'],backend=FORMAT,
                            schema=SCHEMA_HASH,budget_ms=self.budget)
        # The generic input now depends directly on the collector and shared DTOs.
        # Include them even though the legacy pilot did not consume this projection.
        files=[p for name in ('SlayTheModel.Sts2.ModAdapter','SlayTheModel.Sts2.Protocol')
               for p in (self.repo/'src'/name).rglob('*.cs') if not {'bin','obj'} & set(p.parts)]
        if not files: raise ValueError('Native collector/protocol sources unavailable')
        self.provenance['collector_sha256']=content_hash({str(p.relative_to(self.repo)):sha(p) for p in sorted(files)})
        self.built=False
        self.workers=1
        self.configure_search(config.get('leaf_mode','heuristic'),config.get('value_mix',.5))

    def configure_workers(self,workers):
        if type(workers) is not int or not 1<=workers<=8:
            raise ValueError('Native collection supports 1-8 workers')
        self.workers=workers

    def _prepare_parallel(self,directory):
        from .config import atomic_json
        if not self.built:
            job=directory/'build-job.json'
            atomic_json(job,dict(format=self.format,catalogOutput=str(directory/'catalog.json')))
            self._execute(job,directory/'build.log')

    def _execute_parallel(self,job,log):
        import os
        import shutil
        import subprocess
        import uuid
        import sys
        from .native_platform import worker_executable, stop_process_tree
        directory=job.parent
        project=directory/'project'
        project.mkdir(exist_ok=True)
        source=self.repo/'tools/Sts2.NativeWorker'
        for name in ('Worker.tscn','Worker.cs'):
            shutil.copyfile(source/name,project/name)
        settings=(source/'project.godot').read_text()
        marker='config/custom_user_dir_name="SlayTheModelWorker"'
        if marker not in settings:
            raise ValueError('Native worker user directory isolation contract changed')
        (project/'project.godot').write_text(settings.replace(marker,
            f'config/custom_user_dir_name="SlayTheModelCollection/{uuid.uuid4().hex}"'))
        (project/'.godot').mkdir(exist_ok=True)
        (project/'.godot/global_script_class_cache.cfg').write_text('list=Array[Dictionary]([])')
        env=dict(os.environ,STS2_COLLECTION_PILOT_JOB=str(job),
                 STS2_GAME_PACK=str(self.game/'SlayTheSpire2.pck'),STS2_WORKER_MODE='collection-pilot',
                 STS2_PYTHON_EXECUTABLE=sys.executable)
        command=[str(worker_executable(self.repo)),'--headless',
                 '--path',str(project),'--log-file',str(directory/'godot.log')]
        with Path(log).open('a',encoding='utf-8') as stream:
            process=subprocess.Popen(command,env=env,stdout=stream,stderr=subprocess.STDOUT,
                creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0), start_new_session=os.name != 'nt')
            try: code=process.wait(timeout=120)
            except BaseException:
                stop_process_tree(process)
                raise
            if code: raise RuntimeError(f'Native worker exit {code}; completed fights retained; see {log}')

    def configure_search(self,mode,mix):
        from .dynamic_search import leaf_settings
        leaf_settings(mode,mix)
        self.search_job=dict(leafMode=mode,valueMix=mix)
        self.provenance['leaf_settings']=self.search_job

    def raw_validator(self,raw):
        from .native_generic import raw_leaf_settings
        if raw_leaf_settings(raw)!=(self.search_job['leafMode'],self.search_job['valueMix']):
            raise ValueError('Native cache leaf configuration mismatch')
        return validate_raw(raw,allow_validation_cutoff=True,allow_training_cutoff=True)

    def training_recipes(self,iteration,episodes):
        if not 0<=iteration<90000 or not 1<=episodes<=304: raise ValueError('Generic recipe coordinates out of bounds')
        return tuple(make_recipe(2_000_000+iteration*10000+i,self.protocol['encounters'][i%len(self.protocol['encounters'])],
                                 self.protocol['cards'],'train') for i in range(episodes))


def preflight(config,protocol,**kwargs):
    from .all_runner import effective_settings
    settings=effective_settings(config,**kwargs); validate_settings(config,settings)
    validation=validate_protocol(protocol)
    return dict(ready=True,backend=FORMAT,validation=dict(checked=len(validation),errors=[]),test=None,
                scope='Protocol/schema only; native simulator capability must pass execution audit')
