"""Frozen-network paired solvability witness; no optimization or final-test access."""
import hashlib
import json
from pathlib import Path
import torch
from audit_az_transformer_g23f import (read, trajectory, CombatScenario, action_candidates,
                                     encode_entities, phase, BOSS_CONTENT, V7)
from sts2_env.az.model_factory import load_transformer_checkpoint


def run():
    torch.set_num_threads(1)
    root=Path('output/az_transformer_t3_v7_formal_20261016')
    output=Path('docs/g23f_audit')
    report=read(output/'audit.json')
    witness=read(next(output.glob('rule-win-*.json')))
    recipe=CombatScenario.from_dict(witness['recipe'])
    results={}
    for seed,index in ((42,1),(43,2)):
        path=root/f'seed-{seed}/evaluation-{index}.json'
        reference={r['scenario_id']:r for r in read(path)['modes']['network']['candidate']}
        # Full outcome equality against original validation, excluding timings.
        for row in report['groups'][f'{seed}/validation_network']:
            old=reference[row['scenario_id']]
            assert all(old[k]==v for k,v in row['outcome'].items())
        model,_=load_transformer_checkpoint(root/f'seed-{seed}/candidate-{index}.pt','S',BOSS_CONTENT,V7)
        actions=[]
        def policy(info):
            probs,value=model.predict(encode_entities(info))
            key=max(sorted(probs),key=probs.get)
            candidate=next(a for a in action_candidates(info)[0] if a.action_key==key)
            card=info.hand[int(candidate.source_ref.split('/')[1])] if candidate.source_ref and candidate.source_ref.startswith('hand/') else None
            actions.append(dict(step=len(actions),phase=phase(info),hp=info.player_hp,
                                block=info.player_block,energy=info.energy,card=card,key=key,
                                value=value,enemy_strength=info.enemy_strength))
            return key
        row,actual=trajectory(recipe,policy)
        name=f'network-{seed}-solvable-witness.json'
        (output/name).write_text(json.dumps(actual,indent=2),encoding='utf-8')
        report['witness_sha256'][name]=hashlib.sha256((output/name).read_bytes()).hexdigest()
        report['source_sha256'][str(path.relative_to(root))]=hashlib.sha256(path.read_bytes()).hexdigest()
        results[str(seed)]=dict(summary=row,actions=actions,
            first_action_difference=next((i for i,(a,b) in enumerate(zip(actual['actions'],witness['actions'])) if a!=b),None),
            zero_block_body_slam=sum(a['card']=='BODY_SLAM+' and a['block']==0 for a in actions))
    report['paired_solvable_recipe_diagnostic']=results
    report['validation_outcomes_match_original']=True
    (output/'audit.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps({s:{k:v for k,v in r.items() if k!='actions'} for s,r in results.items()},indent=2))


if __name__=='__main__': run()
