"""Prepare immutable T3 configurations. Never construct a model or start a run."""
import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

from sts2_env.az.config import atomic_json, content_hash
from sts2_env.az.content import BOSS_CONTENT
from sts2_env.az.coordinator import TrainingConfig
from sts2_env.az.entity_encoder import SCHEMA_HASH
from sts2_env.az.network import code_digest
from sts2_env.az.rewards import V6
from sts2_env.az.search_config import DYNAMIC
from sts2_env.az.transformer_course import VERSION,SMOKE_VERSION,configuration,generate,preparation_manifest


def config(seed=42,smoke=False):
    return TrainingConfig(promotion_policy='network-utility-v1',model_tier='S',microbatch_size=8,seed=seed,workers=2,
        episodes_per_iteration=180,simulations=4 if smoke else 8,eval_simulations=4 if smoke else 8,
        validation_count=256,capacity=200_000,batch_size=32 if smoke else 64,
        updates=4 if smoke else 16,iterations=2 if smoke else 3,
        content_version=BOSS_CONTENT,reward_version=V6,
        sampling_version=SMOKE_VERSION if smoke else VERSION,search_version=DYNAMIC)


def documents():
    result={}
    for smoke in (True,False):
        name='smoke' if smoke else 'formal'
        seeds=(42,) if smoke else (42,43)
        rounds=2 if smoke else 3
        manifest=[r.to_dict() for r in preparation_manifest(smoke)]
        result[f'{name}-manifest.json']=manifest
        for seed in seeds: result[f'{name}-seed-{seed}.json']=asdict(config(seed,smoke))
        result[f'{name}-generator.json']=configuration(smoke)
        result[f'{name}-train-hashes.json']={f'{s}/{i}':content_hash([
            generate(s,i,j,smoke=smoke).to_dict() for j in range(180)]) for s in seeds for i in range(rounds)}
    result['plan.json']={
        'version':'transformer-t3-preparation-v2','status':'prepared_not_started','code_digest':code_digest(),
        'schema_hash':SCHEMA_HASH,'spec':'spec_1.md sections 9.2 and 11',
        'initialization':'independent random S per seed; no MLP/champion transfer',
        'optimizer':{'name':'AdamW','learning_rate':.0003,'weight_decay':.0001,'betas':[.9,.999],
                     'eps':1e-8,'scheduler':None,'gradient_clip_norm':1.0,'precision':'FP32'},
        'loss':'state-averaged policy CE + value MSE',
        'resources':{'device':'CPU','workers':2,'threads_per_worker':1,'microbatch':8,
            'oom_policy':'stop; revise microbatch explicitly while preserving effective batch; no automatic hardware change',
            'full_run_peak_memory_and_duration':'unmeasured; smoke evidence required'},
        'promotion':{'policy':'network-utility-v1','criterion':'utility-only-v1','paired_validation_count':256,
            'primary_metric':'mean network terminal V6 utility; not predicted value-head output',
            'threshold':'paired utility difference bootstrap 95% lower bound > 0',
            'bootstrap_samples':10000,'statistics_seed':1729,
            'win_rate_role':'diagnostic only; no veto or tie-break', 'search_role':'observation only',
            'integrity':'all paired scenarios, valid rewards, no exceptions or illegal actions required'},
        'budget':{'smoke':{'seeds':[42],'rounds':2,'episodes_per_round':180,'updates':4,'batch':32,'simulations':4},
                  'formal':{'seeds':[42,43],'rounds':3,'episodes_per_round':180,'updates':16,'batch':64,'simulations':8}},
        'gates':['User explicitly requests experiments; previous no-training instruction remains active.',
                 'Dedicated Transformer smoke/formal orchestration and artifact verification must be completed before launch.',
                 'S two-round smoke must pass with same code/schema/config before either formal seed starts.',
                 'Freeze both final champion hashes before materializing final test recipes.'],
        'final_test':{'count':216,'master':287,'generated':False,'read':False,'claim':'new environment seeds; existing composition distribution, not unseen combinations'},
        'stopping_rule':'2 smoke rounds; exactly 3 formal rounds per seed; errors halt, no extra rounds',
        'required_reports':['per-seed/round promotion','network and search separately','timeout cases',
            'Boss phase coverage','state/action lengths','throughput and process-tree peak memory',
            'Replay/checkpoint/reward recomputation','engineering versus learning gain'],
        'document_hashes':{name:content_hash(doc) for name,doc in result.items()}}
    return json.loads(json.dumps(result))


def prepare(output):
    root=Path(output)
    docs=documents()
    # Check all collisions before writing anything. Frozen plans never overwrite.
    for name,doc in docs.items():
        path=root/name
        if path.exists() and json.loads(path.read_text(encoding='utf-8'))!=doc:
            raise ValueError(f'Frozen preparation changed: {path}')
    for name,doc in docs.items():
        if not (root/name).exists(): atomic_json(root/name,doc)
    return docs['plan.json']


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',default='configs/az_transformer_t3_v1')
    args=parser.parse_args()
    plan=prepare(args.output)
    print(json.dumps({'status':plan['status'],'output':args.output,'final_test_generated':False}))
