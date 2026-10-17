"""Freeze T4 pilot contracts and run bounded diagnostics; never train or test heldouts."""
import json
import hashlib
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import torch
from sts2_env.az.natural_course import export_witness,validate_course,restore,seal,advance
from sts2_env.az.t4_protocol import generate_protocol,validate_protocol,HELDOUT_ID
from sts2_env.az.combo_diagnostic import sequence,probe
from sts2_env.az.scenarios import CombatScenario
from sts2_env.az.adapter import ObservableCombatAdapter
from sts2_env.az.rewards import V7
from sts2_env.az.content import BOSS_CONTENT
from sts2_env.az.model_factory import load_transformer_checkpoint
from sts2_env.az.config import content_hash
from sts2_env.az.network import code_digest


def read(path): return json.loads(path.read_text(encoding='utf-8'))


def freeze(path,data):
    path.parent.mkdir(parents=True,exist_ok=True)
    if path.exists() and read(path)!=json.loads(json.dumps(data)):
        raise ValueError(f'Frozen document changed: {path}; use a new version')
    path.write_text(json.dumps(data,indent=2),encoding='utf-8')


def main():
    torch.set_num_threads(1)
    source=Path('docs/g23f_audit'); destination=Path('configs/az_transformer_t4_v1')
    sources=[]; entries=[]; source_hashes={}
    for path in sorted(source.glob('*.json')):
        if not path.name.startswith(('rule-win-','replay-phase-')): continue
        witness=read(path)
        if any(c['card_id']==HELDOUT_ID for c in witness['recipe']['deck']): continue
        sources.append(witness); entries.extend(export_witness(witness))
        source_hashes[str(path)]=hashlib.sha256(path.read_bytes()).hexdigest()
    course=seal(dict(version='natural-late-course-v1',entries=entries,source_sha256=source_hashes))
    validate_course(course,sources)
    protocol=generate_protocol()
    counts=validate_protocol(protocol,entries)
    freeze(destination/'natural_course.json',course)
    freeze(destination/'protocol.json',protocol)
    # Start from a legal full winning trajectory, never fabricate a hand or HP.
    witness=read(next(source.glob('rule-win-*.json')))
    recipe=CombatScenario.from_dict(witness['recipe'])
    def factory(): return ObservableCombatAdapter(recipe,reward_version=V7)
    orders={name:sequence(factory,tokens) for name,tokens in (
        ('block_then_slam',['ARMAMENTS+','BODY_SLAM+']),
        ('slam_then_block',['BODY_SLAM+','ARMAMENTS+']))}
    # A second predeclared combo: Iron Wave's block+attack before Body Slam.
    scout=factory(); prefix=[]; iron_wave=None
    for key in witness['actions']:
        i=scout.information
        if ('IRON_WAVE+' in i.hand and 'BODY_SLAM+' in i.hand and i.energy>=1
                and i.player_block==0 and i.enemy_hp>20
                and not dict(i.boss.powers).get('INTANGIBLE')):
            frozen_prefix=list(prefix)
            def pair_factory():
                env=factory()
                for action in frozen_prefix: advance(env,action)
                return env
            iron_wave=dict(prefix=frozen_prefix,
                block_then_slam=sequence(pair_factory,['IRON_WAVE+','BODY_SLAM+']),
                slam_then_block=sequence(pair_factory,['BODY_SLAM+','IRON_WAVE+']))
            break
        advance(scout,key);prefix.append(key)
    if iron_wave is None: raise ValueError('No natural Iron Wave combo fixture found')
    public=factory().information
    models={'uniform':None}; checkpoint_hashes={}
    root=Path('output/az_transformer_t3_v7_formal_20261016')
    for seed,index in ((42,1),(43,2)):
        path=root/f'seed-{seed}/candidate-{index}.pt'
        models[str(seed)]=load_transformer_checkpoint(path,'S',BOSS_CONTENT,V7)[0]
        checkpoint_hashes[str(path)]=hashlib.sha256(path.read_bytes()).hexdigest()
    probes={name:{str(b):probe(public,model,b) for b in (8,32,128)} for name,model in models.items()}
    report=dict(version='t4-preparation-diagnostic-v1',training_started=False,
        heldout_battles_executed=False,network_quality_accepted=False,
        acceptance_status='not-evaluated-no-new-trained-model',code_digest=code_digest(),
        course_sha256=course['sha256'],protocol_sha256=protocol['sha256'],
        counts=counts,natural_snapshots=len(entries),categories=sorted({e['category'] for e in entries}),
        source_sha256=source_hashes,checkpoint_sha256=checkpoint_hashes,
        orders=orders,iron_wave_order=iron_wave,probes=probes,
        note='Frozen old models diagnose a known training witness only; these weights cannot initialize the ID-holdout experiment.')
    for path,digest in {**source_hashes,**checkpoint_hashes}.items():
        if hashlib.sha256(Path(path).read_bytes()).hexdigest()!=digest: raise ValueError('Source changed')
    Path('docs/transformer_t4_preparation.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps({k:report[k] for k in ('counts','natural_snapshots','categories','orders')},indent=2))
    print(json.dumps({name:{b:{k:r[k] for k in ('action','max_depth')} for b,r in rows.items()}
                      for name,rows in probes.items()},indent=2))


if __name__=='__main__': main()
