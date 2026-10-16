"""Read-only reproduction of greedy policy and replay supervision from a run."""
import argparse
from collections import Counter
import gzip
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import torch
from sts2_env.az.model_factory import load_transformer_checkpoint
from sts2_env.az.content import BOSS_CONTENT
from sts2_env.az.rewards import V6
from sts2_env.az.scenarios import load_manifest
from sts2_env.az.adapter import ObservableCombatAdapter
from sts2_env.az.entity_encoder import encode_entities
from sts2_env.az.action_candidates import action_candidates
from sts2_env.az.dynamic_search import plan_dynamic


def diagnose(root, count=16):
    torch.set_num_threads(1)
    root = Path(root)
    recipes = [r for r in load_manifest(root / 'manifest.json') if r.split == 'validation'][:count]
    result = {'checkpoints': {}, 'replay': {}}
    for path in sorted((root / 'seed-42').glob('*.pt')):
        if path.name.startswith('training'): continue
        model, payload = load_transformer_checkpoint(path, 'S', BOSS_CONTENT, V6)
        actions, records, roots = Counter(), [], []
        for recipe in recipes:
            env = ObservableCombatAdapter(recipe, reward_version=V6)
            first = True
            while not env.outcome().done:
                info = env.information
                p, v = model.predict(encode_entities(info))
                chosen = max(sorted(p), key=p.get)
                if first:
                    search = plan_dynamic(info, model, model_version=payload['model_version'], budget=4, search_seed=42)
                    roots.append({'scenario': recipe.scenario_id, 'hand': info.hand, 'energy': info.energy,
                                  'priors': p, 'value': v, 'chosen': chosen,
                                  'search_action': search.action,
                                  'search_edges': {k: {'visits': e.visits, 'q': e.q} for k,e in search.root.edges.items()}})
                    first = False
                _, mapping = action_candidates(info)
                actions[chosen.split(':')[0]] += 1
                env.step(mapping[chosen])
            records.append({'reason': env.outcome().termination_reason, 'reward': env.outcome().reward})
        result['checkpoints'][path.name] = {'actions': dict(actions), 'roots': roots, 'outcomes': records,
                                           'history': payload['statistics'].get('history', [])}
    actions, target, zs = Counter(), Counter(), Counter()
    n = 0
    for path in (root / 'seed-42/replay/episodes').glob('*.gz'):
        with gzip.open(path, 'rt', encoding='utf-8') as f: episode = json.load(f)
        if 'episode' in episode: episode = episode['episode']
        for row in episode['rows']:
            n += 1
            actions[row['chosen_action'].split(':')[0]] += 1
            zs[row['z']] += 1
            for k, v in row['policy_target'].items(): target[k.split(':')[0]] += v
    result['replay'] = {'rows': n, 'actions': dict(actions), 'target_mass': dict(target), 'z_counts': dict(zs)}
    return result


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('root'); p.add_argument('--output', required=True); p.add_argument('--count', type=int, default=16)
    a = p.parse_args()
    result = diagnose(a.root, a.count)
    Path(a.output).write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps({'actions': {k:v['actions'] for k,v in result['checkpoints'].items()}, 'replay':result['replay']}))
