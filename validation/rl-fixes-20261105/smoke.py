from pathlib import Path
import json, sys
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
import torch
from agent.armg_train import collect_episode,summarize,train
from agent.content_profile import PROFILE
from agent.run_reward import DeckElo
torch.set_num_threads(1)
if __name__=='__main__':
    elo=DeckElo()
    reports=[]
    for ascension in (0,10):
        episodes=[collect_episode(seed,None,combat='greedy',ascension=ascension,
                    content_profile=PROFILE,deck_elo=elo) for seed in list(range(1,201))+[367,466]]
        report={'ascension':ascension,**summarize(episodes),
                'failures':[ep for ep in episodes if ep['status']!='terminated']}
        reports.append(report)
        print(json.dumps(report),flush=True)
    Path(__file__).with_name('smoke.json').write_text(json.dumps(reports,indent=2))
    assert all(r['errors']==r['truncated']==0 for r in reports)
    train(games=8,batch_size=4,eval_every=8,eval_runs=2,combat='greedy',need_rules=True,
          ppo_epochs=1,workers=2,out_dir=str(Path(__file__).with_name('ppo-smoke')))
