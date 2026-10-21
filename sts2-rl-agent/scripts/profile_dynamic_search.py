"""Fixed-state search profile and exact before/after tree comparison (no training)."""
import argparse
import cProfile
from dataclasses import asdict
import gzip
import importlib.util
import json
from pathlib import Path
import pstats
import sys
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def normalized(value):
    if isinstance(value, dict):
        return [[normalized(k), normalized(v)] for k, v in value.items()]
    if isinstance(value, (tuple, list)):
        return [normalized(v) for v in value]
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', required=True)
    parser.add_argument('--out', required=True)
    parser.add_argument('--reference')
    parser.add_argument('--profile', action='store_true', help='Also collect cProfile, separately from wall timing')
    parser.add_argument('--budgets', type=int, nargs='+', default=[32, 256])
    parser.add_argument('--states', nargs='+', default=['opening', 'knights', 'vigor'])
    parser.add_argument('--modes', nargs='+', default=['learned', 'heuristic', 'mixed'])
    args = parser.parse_args()
    import torch
    from sts2_env.az import dynamic_search
    from sts2_env.az.all_runner import TIER, ALL_CONTENT, V7, SEARCH
    from sts2_env.az.model_factory import load_transformer_checkpoint
    from sts2_env.az.adapter import ObservableCombatAdapter
    from sts2_env.az.scenarios import CombatScenario
    from sts2_env.az.config import EpisodeLimits, content_hash, atomic_json
    from sts2_env.az.entity_transition import public_from_dict
    torch.set_num_threads(1)
    torch.use_deterministic_algorithms(True)
    manifest = json.loads(Path(args.manifest).read_text(encoding='utf-8-sig'))
    model, _ = load_transformer_checkpoint(manifest['checkpoint'], TIER, ALL_CONTENT, V7)
    model.eval().requires_grad_(False)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    modules = [('current', dynamic_search)]
    if args.reference:
        name = 'sts2_env.az._profile_reference'
        spec = importlib.util.spec_from_file_location(name, args.reference)
        ref = importlib.util.module_from_spec(spec)
        sys.modules[name] = ref
        spec.loader.exec_module(ref)
        modules.insert(0, ('reference', ref))
    rows = []
    for state in args.states:
        if state == 'opening':
            info = ObservableCombatAdapter(CombatScenario.from_dict(manifest['recipes'][0]),
                EpisodeLimits(**manifest['limits']), str(out/'errors'), V7).information
        else:
            filename = {'knights': 'knights_exhaust_upgrade', 'vigor': 'vigor_pending_hook'}[state]
            info = public_from_dict(json.loads(gzip.decompress((ROOT/'tests/fixtures'/f'{filename}.json.gz').read_bytes())))
        for budget in args.budgets:
            for mode in args.modes:
                hashes = []
                for label, module in modules:
                    kwargs = dict(model_version='fixed-profile', search_seed=123, budget=budget,
                        max_depth=128, training=False, temperature=0, search_version=SEARCH, leaf_mode=mode)
                    # Unprofiled timing separately from instrumentation overhead.
                    started = perf_counter()
                    result = module.plan_dynamic(info, model, **kwargs)
                    elapsed = perf_counter()-started
                    doc = asdict(result)
                    del doc['elapsed']
                    signature = content_hash(normalized(doc))
                    hashes.append(signature)
                    if args.profile:
                        profiler = cProfile.Profile()
                        profiler.runcall(module.plan_dynamic, info, model, **kwargs)
                        stem = f'{state}-{budget}-{mode}-{label}'
                        profiler.dump_stats(str(out/f'{stem}.prof'))
                        with (out/f'{stem}.txt').open('w') as stream:
                            pstats.Stats(profiler, stream=stream).strip_dirs().sort_stats('cumulative').print_stats(45)
                    row = dict(state=state, budget=budget, mode=mode, implementation=label,
                        seconds=elapsed, simulations_per_second=budget/elapsed, signature=signature,
                        action=result.action, mean_depth=result.mean_depth)
                    rows.append(row)
                    atomic_json(out/'report.json', {'rows': rows})
                    print(json.dumps(row), flush=True)
                if len(set(hashes)) != 1:
                    raise AssertionError(f'Search tree changed: {state}/{budget}/{mode}')
    atomic_json(out/'report.json', {'rows': rows, 'exact_tree_equivalence': bool(args.reference)})


if __name__ == '__main__':
    main()
