"""Frozen, resumable five-arm diagnostic; no optimizer or training runner."""
import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict
from datetime import datetime
import hashlib
import json
import multiprocessing
from pathlib import Path
import sys
import traceback
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from sts2_env.az.config import atomic_json, content_hash, derive_seed, EpisodeLimits

ARMS = [('network', 0, 'learned'), ('learned8', 8, 'learned'),
        ('learned32', 32, 'learned'), ('mixed8', 8, 'mixed'), ('mixed32', 32, 'mixed')]
_model = None


def initialize(checkpoint):
    global _model
    import torch
    from sts2_env.az.model_factory import load_transformer_checkpoint
    from sts2_env.az.all_runner import TIER, ALL_CONTENT, V7
    torch.set_num_threads(1)
    torch.use_deterministic_algorithms(True)
    _model, _ = load_transformer_checkpoint(checkpoint, TIER, ALL_CONTENT, V7)
    _model.eval().requires_grad_(False)


def fight(manifest, index, arm, output):
    from sts2_env.az.scenarios import CombatScenario
    from sts2_env.az.adapter import ObservableCombatAdapter
    from sts2_env.az.entity_encoder import encode_entities
    from sts2_env.az.action_candidates import action_candidates
    from sts2_env.az.dynamic_search import plan_dynamic
    from sts2_env.az.all_runner import SEARCH, V7
    name, budget, mode = arm[:3]
    depth_limit = arm[3] if len(arm) == 4 else manifest.get('max_depth', 128)
    recipe = CombatScenario.from_dict(manifest['recipes'][index])
    env = ObservableCombatAdapter(recipe, EpisodeLimits(**manifest['limits']),
                                  str(Path(output)/'errors'/name), V7)
    latencies, coverage = [], []
    while not env.outcome().done:
        started = perf_counter()
        info = env.information
        if budget:
            result = plan_dynamic(info, _model, model_version='paired-value-diagnostic',
                budget=budget, training=False, temperature=0, search_version=SEARCH,
                leaf_mode=mode, value_mix=manifest['value_mix'],
                max_depth=depth_limit,
                search_seed=derive_seed(manifest['seed'], 0, index, f'diagnostic-{len(latencies)}'))
            key = result.action
            if not result.forced_action:
                coverage.append(dict(legal=len(result.root_visits),
                    visited=sum(v > 0 for v in result.root_visits.values()),
                    mean_depth=result.mean_depth, max_depth=result.max_depth_reached))
        else:
            priors, _ = _model.predict(encode_entities(info))
            key = max(sorted(priors), key=priors.get)
        _, mapping = action_candidates(info)
        latencies.append(perf_counter()-started)
        env.step(mapping[key])
    return dict(asdict(env.outcome()), scenario_id=recipe.scenario_id,
                encounter_id=recipe.encounter_id, decision_seconds=latencies,
                action_coverage=coverage, errors=0, illegal_actions=0)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', required=True)
    parser.add_argument('--out', required=True)
    parser.add_argument('--workers', type=int, default=2)
    args = parser.parse_args()
    from sts2_env.az.network import code_digest
    from sts2_env.az.all_runner import paired_gain
    from sts2_env.az.evaluation import summarize
    manifest = json.loads(Path(args.manifest).read_text(encoding='utf-8'))
    if manifest['source_digest'] != code_digest():
        raise ValueError('Source differs from frozen diagnostic manifest')
    if manifest.get('driver_sha256') and manifest['driver_sha256'] != hashlib.sha256(Path(__file__).read_bytes()).hexdigest():
        raise ValueError('Diagnostic driver changed')
    if hashlib.sha256(Path(manifest['checkpoint']).read_bytes()).hexdigest() != manifest['checkpoint_sha256']:
        raise ValueError('Checkpoint changed')
    recipes = manifest['recipes']
    arms = manifest.get('arms', ARMS)
    if (not arms or arms[0] != ['network', 0, 'learned'] and arms[0] != ('network', 0, 'learned')
            or len({a[0] for a in arms}) != len(arms)):
        raise ValueError('Unique arms must start with pure network')
    if (not recipes or any(r['split'] != 'train' for r in recipes)
            or len({r['scenario_id'] for r in recipes}) != len(recipes)):
        raise ValueError('Require unique frozen training-side recipes')
    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)
    identity = content_hash(manifest)
    results = {a[0]: {} for a in arms}; failures = []
    total = len(recipes)*len(arms)

    def progress(status, latest):
        doc = dict(status=status, updated=datetime.now().isoformat(timespec='seconds'),
            complete=sum(len(v) for v in results.values()), total=total,
            failures=len(failures), by_arm={k:len(v) for k,v in results.items()}, latest=latest)
        atomic_json(out/'progress.json', doc)
        with (out/'progress.log').open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(doc, ensure_ascii=False)+'\n')

    progress('starting', 'Loading cached complete fights')
    tasks = []
    for index in range(len(recipes)):
        for arm in arms:
            path = out/'fights'/f'{arm[0]}-{index:03d}.json'
            if path.exists():
                doc = json.loads(path.read_text())
                if doc['identity'] != identity or doc['sha256'] != content_hash(doc['row']):
                    raise ValueError(f'Incompatible or corrupt fight: {path}')
                results[arm[0]][index] = doc['row']
            else:
                tasks.append((index, arm, path))
    progress('running', 'Fixed model; exploration disabled')
    with ProcessPoolExecutor(args.workers, mp_context=multiprocessing.get_context('spawn'),
            initializer=initialize, initargs=(manifest['checkpoint'],)) as pool:
        futures = {pool.submit(fight, manifest, i, arm, str(out)):(i,arm,path) for i,arm,path in tasks}
        for future in as_completed(futures):
            index, arm, path = futures[future]
            try:
                row = future.result()
            except Exception:
                failure = dict(index=index, arm=arm[0], error=traceback.format_exc())
                failures.append(failure)
                atomic_json(out/'errors'/f'{arm[0]}-{index:03d}.json', failure)
            else:
                atomic_json(path, dict(identity=identity, row=row, sha256=content_hash(row)))
                results[arm[0]][index] = row
            progress('running', f'{arm[0]} recipe {index+1}/{len(recipes)}')
    report = dict(manifest=manifest, identity=identity, failures=failures, results={})
    for arm, values in results.items():
        rows = [values[i] for i in sorted(values)]
        report['results'][arm] = dict(rows=rows, summary=summarize(rows) if rows else None)
        if arm != 'network' and len(values)==len(recipes) and len(results['network'])==len(recipes):
            report['results'][arm]['paired_vs_network'] = paired_gain(
                [results['network'][i] for i in range(len(recipes))], rows)
    report['paired_comparisons'] = {}
    for baseline, candidate in [('learned8', 'learned32'), ('mixed8', 'mixed32'),
                                 ('learned8', 'mixed8'), ('learned32', 'mixed32'),
                                 ('learned32', 'learned256'), ('mixed8', 'learned256'),
                                 ('heuristic256', 'learned256'),
                                 ('learned32', 'learned32_depth256')]:
        if (baseline in results and candidate in results
                and len(results[baseline]) == len(recipes) and len(results[candidate]) == len(recipes)):
            report['paired_comparisons'][candidate+'_vs_'+baseline] = paired_gain(
                [results[baseline][i] for i in range(len(recipes))],
                [results[candidate][i] for i in range(len(recipes))])
    atomic_json(out/'report.json', report)
    progress('failed' if failures else 'completed', 'Report saved; no training was performed')
    if failures:
        raise SystemExit(1)


if __name__ == '__main__':
    try:
        main()
    except Exception:
        if '--out' in sys.argv:
            output = Path(sys.argv[sys.argv.index('--out')+1])
            atomic_json(output/'fatal_error.json', dict(error=traceback.format_exc()))
            atomic_json(output/'progress.json', dict(status='failed',
                updated=datetime.now().isoformat(timespec='seconds'), details='fatal_error.json'))
        raise
