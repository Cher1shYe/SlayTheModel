"""Audited native collection backend for the existing ALL lifecycle.

Native rollout teachers have privileged information. This backend owns a distinct
protocol/replay, while ALL continues to own learning, recovery and promotion.
"""
from collections import Counter
import json
import os
from pathlib import Path
import random
import shutil
import subprocess

from .config import atomic_json, content_hash
from .native_pilot import ENCOUNTERS, EXPANDED_CARDS, EXPANDED_FORMAT, validate_raw, to_episode

PROTOCOL = 'native-six-card-validation-v2'
ROOT = Path(__file__).resolve().parents[2]


def validate_settings(config, settings, *, include_test=False, workers=1):
    backend = config['backend']
    if (backend.get('kind') != EXPANDED_FORMAT or type(backend.get('budget_ms')) is not int
            or not 50 <= backend['budget_ms'] <= 1000 or include_test or workers != 1
            or settings['leaf_mode'] != 'heuristic' or settings['budget'] != backend['budget_ms']
            or (settings['max_turns'], settings['max_decisions'], settings['eval_max_turns'], settings['eval_max_decisions']) != (40, 100, 40, 100)):
        raise ValueError('Native v2 requires one worker, rollout heuristic, configured millisecond budget, 40/100 guards and no test split')


def validate_recipe(recipe):
    if set(recipe) != {'scenario_id', 'encounter', 'seed', 'hp', 'deck', 'split'}:
        raise ValueError('Native recipe fields differ')
    if (recipe['encounter'] not in ENCOUNTERS or recipe['split'] not in ('train', 'validation')
            or type(recipe['seed']) is not int or not 0 <= recipe['seed'] < 2_000_000_000
            or type(recipe['hp']) is not int or not 1 <= recipe['hp'] <= 80
            or not isinstance(recipe['deck'], list) or not 6 <= len(recipe['deck']) <= 20
            or any(c not in EXPANDED_CARDS for c in recipe['deck'])):
        raise ValueError('Unsupported native recipe')
    validation_seed = recipe['seed'] >= 1_000_000_000
    if validation_seed != (recipe['split'] == 'validation'):
        raise ValueError('Native train/validation seed domains overlap')
    if recipe['scenario_id'] != content_hash({k: v for k, v in recipe.items() if k != 'scenario_id'}):
        raise ValueError('Native recipe fingerprint differs')
    return recipe


def recipe(seed, encounter, split):
    rng = random.Random(seed)
    deck = list(EXPANDED_CARDS) + rng.choices(list(EXPANDED_CARDS), k=rng.randint(4, 8))
    rng.shuffle(deck)
    row = dict(seed=seed, encounter=encounter, split=split, hp=rng.choice([40, 60, 80]), deck=deck)
    return validate_recipe(dict(row, scenario_id=content_hash(row)))


def training_recipes(iteration, episodes):
    if type(iteration) is not int or not 0 <= iteration < 90000 or type(episodes) is not int or not 1 <= episodes <= 304:
        raise ValueError('Native collection count/iteration out of range')
    return tuple(recipe(1_000_000 + iteration*10000 + i, list(ENCOUNTERS)[i % len(ENCOUNTERS)], 'train')
                 for i in range(episodes))


def frozen_protocol(count=24, seed=1_500_000_000):
    if type(count) is not int or count < 4 or count % len(ENCOUNTERS) or seed < 1_000_000_000:
        raise ValueError('Balanced independent native validation required')
    body = dict(version=PROTOCOL, cards=sorted(EXPANDED_CARDS), encounters=sorted(ENCOUNTERS),
                validation=[recipe(seed+i, list(ENCOUNTERS)[i % len(ENCOUNTERS)], 'validation') for i in range(count)])
    return dict(body, manifest_sha256=content_hash(body))


def validate_protocol(protocol):
    body = {k: v for k, v in protocol.items() if k != 'manifest_sha256'}
    if (set(body) != {'version', 'cards', 'encounters', 'validation'} or body['version'] != PROTOCOL
            or body['cards'] != sorted(EXPANDED_CARDS) or body['encounters'] != sorted(ENCOUNTERS)
            or content_hash(body) != protocol['manifest_sha256']):
        raise ValueError('Native frozen protocol mismatch')
    rows = [validate_recipe(r) for r in body['validation']]
    counts = Counter(r['encounter'] for r in rows)
    if (len(rows) < 4 or any(r['split'] != 'validation' for r in rows)
            or len({r['scenario_id'] for r in rows}) != len(rows) or len({r['seed'] for r in rows}) != len(rows)
            or set(counts) != set(ENCOUNTERS) or len(set(counts.values())) != 1):
        raise ValueError('Native validation duplicates/split/strata mismatch')
    return tuple(rows)


class NativeBackend:
    format = EXPANDED_FORMAT
    recipe_validator = staticmethod(validate_recipe)
    raw_validator = staticmethod(validate_raw)
    episode_converter = staticmethod(to_episode)
    def __init__(self, config, protocol, out):
        from scripts.check_native_collection import provenance
        if config.get('kind') != EXPANDED_FORMAT or not 50 <= config['budget_ms'] <= 1000:
            raise ValueError('Invalid native backend configuration')
        self.repo = Path(config['repo']).resolve()
        self.game = Path(config['game']).resolve()
        self.out = Path(out)
        self.budget = config['budget_ms']
        self.validation = validate_protocol(protocol)
        self.provenance = dict(sources=provenance(self.repo), protocol=protocol['manifest_sha256'],
                               backend=EXPANDED_FORMAT, budget_ms=self.budget)
        self.built = False

    def _execute(self, job, log):
        shell = shutil.which('pwsh') or shutil.which('powershell.exe')
        if not shell:
            raise RuntimeError('Native backend requires PowerShell')
        command = [shell, '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(self.repo/'scripts/native-worker.ps1'),
                   '-GameDir', str(self.game), '-Mode', 'collection-pilot', '-TimeoutSeconds', '120']
        if self.built:
            command.append('-SkipBuild')
        with Path(log).open('a', encoding='utf-8') as stream:
            result = subprocess.run(command, env=dict(os.environ, STS2_COLLECTION_PILOT_JOB=str(job)),
                                    stdout=stream, stderr=subprocess.STDOUT,
                                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if result.returncode:
            raise RuntimeError(f'Native collection failed; completed fights retained; see {log}')
        self.built = True

    def fights(self, checkpoint, recipes, directory, arm):
        from scripts.check_native_collection import sha
        recipes = tuple(self.recipe_validator(r) for r in recipes)
        if not recipes or len({r['scenario_id'] for r in recipes}) != len(recipes):
            raise ValueError('Empty/duplicate native collection recipes')
        if arm not in ('policy', 'puct', 'uct'):
            raise ValueError('Invalid native collection arm')
        checkpoint, directory = Path(checkpoint).resolve(), Path(directory).resolve()
        directory.mkdir(parents=True, exist_ok=True)
        model_sha = sha(checkpoint)
        identity = content_hash(dict(provenance=self.provenance, model=model_sha, arm=arm, recipes=recipes))
        manifest = dict(identity=identity, model_sha256=model_sha, recipes=recipes, arm=arm,
                        provenance=self.provenance)
        manifest = json.loads(json.dumps(manifest))
        path = directory/'manifest.json'
        if path.exists() and json.loads(path.read_text()) != manifest:
            raise ValueError('Native cache source/model/recipe/protocol changed')
        atomic_json(path, manifest)
        specs = [dict(seed=r['seed'], hp=r['hp'], encounter=r['encounter'], deck=r['deck'], split=r['split'],
                      recipe=r, arm=arm, output=str(directory/f"{r['scenario_id']}.json")) for r in recipes]

        validated=set()
        def read(spec):
            raw = json.loads(Path(spec['output']).read_text())
            if (raw['format'] != self.format or raw['identity'] != identity or raw['recipe'] != spec['recipe']
                    or raw['modelSha256'] != model_sha or raw['budgetMs'] != self.budget or raw['arm'] != arm):
                raise ValueError('Cached native fight provenance mismatch')
            self.raw_validator(raw)
            validated.add(spec['recipe']['scenario_id'])
            return raw

        missing = []
        for spec in specs:
            if Path(spec['output']).exists():
                read(spec)
            else:
                missing.append(spec)
        progress = directory/'progress.json'
        cached_at_start=len(specs)-len(missing)
        def save_progress(status,invalid=None):
            completed=len(validated)
            atomic_json(progress, dict(status=status,total=len(specs),completed=completed,
                cached_at_start=cached_at_start,newly_completed=completed-cached_at_start,
                pending=len(specs)-completed,unit='evaluated_fights' if arm=='policy' else 'bounded_episodes' if getattr(self,'supports_cutoff',False) else 'complete_fights',
                invalid=invalid or [],workers=getattr(self,'workers',1),
                fights_per_worker=getattr(self,'native_batch_size',4)))
        save_progress('collecting')
        # Small batches bound failure cost. Each completed fight is atomic even if its batch fails.
        batch_size=getattr(self,'native_batch_size',4)
        workers=getattr(self,'workers',1)
        if missing and workers > 1:
            from concurrent.futures import ThreadPoolExecutor, as_completed
            try: self._prepare_parallel(directory)
            except Exception:
                save_progress('failed')
                raise
            batches=[missing[i:i+batch_size] for i in range(0,len(missing),batch_size)]
            # Bounded waves: after a failure drain active workers, validate their
            # durable outputs, and stop before submitting any subsequent wave.
            with ThreadPoolExecutor(max_workers=workers) as pool:
                for start in range(0,len(batches),workers):
                    futures={}
                    for index,batch in enumerate(batches[start:start+workers],start):
                        task=directory/'workers'/f'batch-{index:05d}'
                        task.mkdir(parents=True,exist_ok=True)
                        job=task/'job.json'
                        atomic_json(job,dict(format=self.format,source=str(ROOT),checkpoint=str(checkpoint),
                            identity=identity,modelSha256=model_sha,budgetMs=self.budget,cases=batch,
                            **getattr(self,'search_job',{})))
                        futures[pool.submit(self._execute_parallel,job,task/'worker.log')]=batch
                    failure=None
                    invalid=[]
                    for future in as_completed(futures):
                        try: future.result()
                        except Exception as error:
                            if failure is None: failure=error
                        for spec in futures[future]:
                            try: read(spec)
                            except (ValueError,KeyError,TypeError,OSError) as error:
                                if failure is None: failure=error
                                invalid.append(dict(scenario_id=spec['recipe']['scenario_id'],error=str(error)))
                        save_progress('failed' if failure else 'collecting',invalid)
                    if failure: raise failure
            missing=[]
        for start in range(0, len(missing), batch_size):
            job = directory/'job.json'
            atomic_json(job, dict(format=self.format, source=str(ROOT), checkpoint=str(checkpoint),
                identity=identity, modelSha256=model_sha, budgetMs=self.budget, cases=missing[start:start+batch_size],
                **getattr(self,'search_job',{})))
            try:
                self._execute(job, directory/'worker.log')
                for spec in missing[start:start+batch_size]:
                    read(spec)
            except (RuntimeError, OSError, ValueError, KeyError):
                invalid=[]
                for spec in missing[start:start+batch_size]:
                    if spec['recipe']['scenario_id'] in validated or not Path(spec['output']).exists(): continue
                    try: read(spec)
                    except (ValueError,KeyError,TypeError,OSError) as error:
                        invalid.append(dict(scenario_id=spec['recipe']['scenario_id'],error=str(error)))
                save_progress('failed',invalid)
                raise
            save_progress('collecting')
        raws = [read(s) for s in specs]
        save_progress('completed')
        return raws

    def collect(self, checkpoint, recipes, directory):
        if any(r['split'] != 'train' for r in recipes):
            raise ValueError('Validation recipes cannot enter collection')
        return [self.episode_converter(raw) for raw in self.fights(checkpoint, recipes, directory, 'puct')]

    def evaluate(self, model, recipes, *, version, error_dir, limits=None):
        import torch
        from .all_runner import TIER, ALL_CONTENT, V7
        from .model_factory import save_transformer_checkpoint, load_transformer_checkpoint
        if tuple(recipes) != self.validation:
            raise ValueError('Native evaluation requires the entire frozen validation split')
        directory = self.out/'native-validation'/version
        directory.mkdir(parents=True, exist_ok=True)
        checkpoint = directory/'model.pt'
        if checkpoint.exists():
            frozen, _ = load_transformer_checkpoint(checkpoint, TIER, model.content_version, V7)
            if any(not torch.equal(v.cpu(), frozen.state_dict()[k].cpu()) for k, v in model.state_dict().items()):
                raise ValueError('Cached native validation model differs')
        else:
            save_transformer_checkpoint(checkpoint, model, version, config={'backend': self.format})
        raws = self.fights(checkpoint, recipes, directory/'fights', 'policy')
        rows = [dict(scenario_id=r['recipe']['scenario_id'], encounter_id=r['encounter'],
                    reward=r['outcome']['reward'], termination_reason=r['outcome'].get('terminationReason','win' if r['outcome']['won'] else 'death'),
                    final_hp=r['outcome']['finalHp']) for r in raws]
        return dict(episodes=len(rows), win_rate=sum(r['termination_reason']=='win' for r in rows)/len(rows),
                    mean_utility=sum(r['reward'] for r in rows)/len(rows),
                    time_limit_rate=sum(r['termination_reason']=='time_limit' for r in rows)/len(rows), contract_rejections=0,
                    contract_rejected=[]), rows


def preflight(config, protocol, *, iterations=None, episodes=None, max_turns=None, max_decisions=None):
    from .all_runner import effective_settings
    settings = effective_settings(config, iterations=iterations, episodes=episodes, max_turns=max_turns, max_decisions=max_decisions)
    validate_settings(config, settings)
    validation = validate_protocol(protocol)
    for iteration in range(settings['iterations']):
        for r in training_recipes(iteration, settings['episodes']):
            validate_recipe(r)
    return dict(ready=True, backend=EXPANDED_FORMAT,
                training=dict(planned=settings['iterations']*settings['episodes'], errors=[]),
                validation=dict(checked=len(validation), errors=[]), test=None,
                scope='Recipe validation only; native execution is checked during collection/evaluation')
