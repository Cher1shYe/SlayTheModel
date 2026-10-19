"""Fixed failure regressions plus upgraded and fresh native fights; no training."""
import argparse
import json
import random
import shutil
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def repair_plan(previous, catalog, *, fresh_count=8):
    from sts2_env.az.config import content_hash
    from sts2_env.az.native_generic import validate_recipe
    from sts2_env.az.native_generic_backend import single_player_card_tokens, make_recipe
    tokens = single_player_card_tokens(catalog)
    allowed = set(tokens)
    plan = []
    for result in previous['collection']:
        if result['ok']:
            continue
        original = result['recipe']
        body = {k:v for k,v in original.items() if k != 'scenario_id'}
        removed = [c for c in body['deck'] if c not in allowed]
        body['deck'] = [c for c in body['deck'] if c in allowed]
        if not body['deck']:
            raise ValueError('Fixed fixture has no single-player cards')
        recipe = validate_recipe(dict(body, scenario_id=content_hash(body)))
        plan.append(dict(group='fixed', original=original, removed_multiplayer=removed, recipe=recipe))
    fixed = list(plan)
    for case in fixed:
        body = {k:v for k,v in case['recipe'].items() if k != 'scenario_id'}
        body['deck'] = [c+'+' if not c.endswith('+') and c+'+' in allowed else c for c in body['deck']]
        plan.append(dict(group='upgraded', original=case['original'], removed_multiplayer=case['removed_multiplayer'],
                         recipe=validate_recipe(dict(body, scenario_id=content_hash(body)))))
    encounters = sorted({r['recipe']['encounter'] for r in previous['preflight'] if r['ok']})
    for i,e in enumerate(random.Random(1919).sample(encounters, fresh_count)):
        plan.append(dict(group='fresh', recipe=make_recipe(19190000+i, e, tokens, 'train')))
    return plan


def main():
    import torch
    from sts2_env.az.config import atomic_json
    from sts2_env.az.native_generic import GenericReplay
    from sts2_env.az.native_generic_backend import NativeBackend, frozen_protocol, single_player_card_tokens
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--previous', type=Path, default=Path('output/native_scope_audit_20261019'))
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--only', choices=['fixed','upgraded','fresh'], nargs='+')
    p.add_argument('--index', type=int)
    p.add_argument('--failed-from', type=Path)
    args=p.parse_args(); torch.set_num_threads(1)
    out=args.out.resolve(); out.mkdir(parents=True, exist_ok=True)
    if (out/'report.json').exists(): raise ValueError('Fresh audit directory required')
    previous=json.loads((args.previous/'report.json').read_text())
    catalog=json.loads((out/'catalog.json').read_text())
    plan=repair_plan(previous,catalog)
    if args.failed_from:
        plan=[{k:r[k] for k in ('group','original','removed_multiplayer','recipe') if k in r}
              for r in json.loads(args.failed_from.read_text())['cases'] if not r['ok']]
    if args.only: plan=[x for x in plan if x['group'] in args.only]
    if args.index is not None: plan=[plan[args.index]]
    atomic_json(out/'plan.json',plan)
    encounters=sorted({r['recipe']['encounter'] for r in previous['preflight'] if r['ok']})
    protocol=frozen_protocol(single_player_card_tokens(catalog),encounters,len(encounters))
    atomic_json(out/'protocol.json',protocol)
    config=json.loads((args.previous/'config.json').read_text())
    atomic_json(out/'config.json',config)
    checkpoint=out/'initial.pt'; shutil.copyfile(args.previous/'initial.pt',checkpoint)
    backend=NativeBackend(config['backend'],protocol,out); backend.configure_search('mixed',.5)
    backend.built=True
    replay=GenericReplay(out/'replay',leaf_mode='mixed',value_mix=.5)
    report=dict(formal_training_started=False,updates=0,provenance=backend.provenance,
                excluded_multiplayer=[c['id'] for c in catalog['cards'] if c['multiplayerOnly']],cases=[])
    for i,case in enumerate(plan):
        directory=out/'fights'/f'{i:03d}'
        row=dict(case,log=str(directory/'worker.log'))
        try:
            for episode in backend.collect(checkpoint,[case['recipe']],directory): replay.commit(episode)
            raw=json.loads((directory/f"{case['recipe']['scenario_id']}.json").read_text())
            row.update(ok=True,outcome=raw['outcome'])
        except (RuntimeError,OSError,ValueError,KeyError) as error:
            row.update(ok=False,error=f'{type(error).__name__}: {error}')
            log=directory/'worker.log'
            if log.exists(): row['native_error']=log.read_text(encoding='utf-8').split('SLAY_WORKER_FAILED')[-1].split('\n   at ')[0]
        report['cases'].append(row); report['replay_rows']=replay.size
        atomic_json(out/'partial-report.json',report)
        atomic_json(out/'progress.json',dict(completed=i+1,total=len(plan),status='running',last_ok=row['ok']))
        print(case['group'],case['recipe']['encounter'],row['ok'],row.get('native_error',''),flush=True)
    atomic_json(out/'report.json',report)
    atomic_json(out/'progress.json',dict(completed=len(plan),total=len(plan),status='completed'))


if __name__=='__main__': main()
