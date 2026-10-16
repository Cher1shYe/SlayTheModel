"""Diagnostic only: same archived weights, same scenarios, old vs V7 search.

No checkpoint is saved or transferred into a training run. Does not estimate
learning gain; these are first-decision probes on already accessed validation.
"""
import argparse
from collections import Counter
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import torch
from sts2_env.az.model_factory import load_transformer_checkpoint, create_transformer
from sts2_env.az.adapter import ObservableCombatAdapter
from sts2_env.az.rewards import V6,V7
from sts2_env.az.content import BOSS_CONTENT
from sts2_env.az.dynamic_search import plan_dynamic
from sts2_env.az.search_config import DYNAMIC_RISK
from sts2_env.az.scenarios import load_manifest
from sts2_env.az.self_play import file_digest


def compare(root):
    torch.set_num_threads(1)
    root=Path(root)
    recipes=[r for r in load_manifest(root/'manifest.json') if r.split=='validation']
    result={'scope':'diagnostic first decisions only; no training or learning-gain claim','checkpoints':{}}
    for name in ('initial.pt','candidate-0.pt','candidate-1.pt'):
        old,meta=load_transformer_checkpoint(root/'seed-42'/name,'S',BOSS_CONTENT,V6)
        new=create_transformer('S',BOSS_CONTENT,V7)
        new.load_state_dict(old.state_dict()); new.eval()
        rows=[]
        for recipe in recipes:
            actions={}
            for label,model,reward,version in [('old',old,V6,'dynamic-key-puct-v1'),('new',new,V7,DYNAMIC_RISK)]:
                env=ObservableCombatAdapter(recipe,reward_version=reward)
                search=plan_dynamic(env.information,model,model_version=meta['model_version'],budget=4,search_seed=42,search_version=version)
                actions[label]={'action':search.action,'visits':search.root_visits,
                    'target':search.policy_target,'q':{k:e.q for k,e in search.root.edges.items()}}
                if label=='old':
                    actions['q_tie_only']=max(search.root_visits,key=lambda k:(search.root_visits[k],search.root.edges[k].q,search.root_priors[k]))
            rows.append({'scenario':recipe.scenario_id,**actions})
        summary={label:dict(Counter((r[label]['action'] if label!='q_tie_only' else r[label]).split(':')[0] for r in rows))
                 for label in ('old','q_tie_only','new')}
        result['checkpoints'][name]={'sha256':file_digest(root/'seed-42'/name),'summary':summary,'rows':rows}
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('root');p.add_argument('--output',required=True);a=p.parse_args()
    result=compare(a.root)
    Path(a.output).write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps({k:v['summary'] for k,v in result['checkpoints'].items()}))
