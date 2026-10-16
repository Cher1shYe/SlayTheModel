"""Frozen 2x2 tie/FPU probe on nine training recipes before G2.3e training."""
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict
import json
import multiprocessing
from pathlib import Path
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import numpy as np
from sts2_env.az.adapter import ObservableCombatAdapter
from sts2_env.az.boss_curriculum import generate
from sts2_env.az.config import atomic_json,derive_seed
from sts2_env.az.content import BOSS_CONTENT
from sts2_env.az.encoder import encode_information
from sts2_env.az.network import load_checkpoint,code_digest
from sts2_env.az.observable_puct import plan_observable
from sts2_env.az.rewards import V6
from sts2_env.az.search_config import VERSIONS,COMBINED
from sts2_env.az.self_play import initialize_worker,file_digest


def probe(job):
    seed,version,j,source=job
    if file_digest(source["final"])!=source["final_sha256"]:
        raise ValueError("Source changed")
    model,meta=load_checkpoint(source["final"],"observable",V6,BOSS_CONTENT)
    recipe=generate(48,0,j)
    env=ObservableCombatAdapter(recipe,reward_version=V6)
    rows=[]
    start=time.perf_counter()
    initial=plan_observable(env.information,model,model_version=meta["model_version"],budget=8,
        search_seed=derive_seed(20261016,seed,recipe.scenario_id,"step-0"),
        search_version=version,training=True,temperature=1)
    target=initial.policy_target[np.asarray(env.information.legal_mask,dtype=bool)]
    label_entropy=float(-sum(p*np.log(p) for p in target if p)/np.log(len(target)))
    while not env.outcome().done:
        info=env.information
        result=plan_observable(info,model,model_version=meta["model_version"],budget=8,
            search_seed=derive_seed(20261016,seed,recipe.scenario_id,f"step-{len(rows)}"),search_version=version)
        rows.append(dict(phase=info.boss.phase.cursor[0]+1,hp=info.player_hp,turn=info.turn,
            action=result.action,choice=bool(info.choice),
            visits={str(a):e.visits for a,e in result.root.edges.items()},
            prior={str(a):e.prior for a,e in result.root.edges.items()},
            root_value=result.root.initial_value,
            tied=bool(sum(result.root_visits==result.root_visits.max())>1) if not result.forced_action else False))
        env.step(result.action)
    return dict(seed=seed,search_version=version,recipe=recipe.to_dict(),rows=rows,
        initial_noisy_visits=initial.root_visits.tolist(),initial_label_entropy=label_entropy,
        outcome=asdict(env.outcome()),seconds=time.perf_counter()-start)


def run():
    root=Path("output/az_search_v1_probe_v4")
    if (root/"plan.json").exists():
        raise ValueError("Fresh probe output required")
    sources=json.loads(Path("output/az_g2_boss_curriculum_v1_quick/frozen_final_models.json").read_text())
    atomic_json(root/"plan.json",dict(versions=VERSIONS,master=48,jobs=list(range(90,99)),
        sources=sources,code_digest=code_digest(),script_digest=file_digest(__file__),
        proposed_training_version=COMBINED,
        decision_rule="Combined is a prespecified mechanism trial, not tuned to maximize this small probe; halt on errors"))
    cases=[]
    with ProcessPoolExecutor(4,mp_context=multiprocessing.get_context("spawn"),initializer=initialize_worker) as pool:
        for c in pool.map(probe,[(s,v,j,sources[str(s)]) for s in (42,43) for v in VERSIONS for j in range(90,99)]):
            cases.append(c)
            atomic_json(root/f"case-{c['seed']}-{c['search_version']}-{c['recipe']['scenario_id']}.json",c)
            atomic_json(root/"progress.json",dict(completed=len(cases),total=72))
    summary={}
    for s in (42,43):
        for v in VERSIONS:
            group=[c for c in cases if c["seed"]==s and c["search_version"]==v]
            summary[f"{s}/{v}"]=dict(episodes=len(group),wins=sum(c["outcome"]["termination_reason"]=="win" for c in group),
                phase2=sum(any(r["phase"]>=2 for r in c["rows"]) for c in group),
                phase3=sum(any(r["phase"]==3 for r in c["rows"]) for c in group),
                mean_reward=float(np.mean([c["outcome"]["reward"] for c in group])),
                noisy_label_entropy=float(np.mean([c["initial_label_entropy"] for c in group])),
                tied=sum(r["tied"] for c in group for r in c["rows"]),
                decisions=sum(len(c["rows"]) for c in group),seconds=sum(c["seconds"] for c in group))
    atomic_json(root/"report.json",summary)
    print(json.dumps(summary,indent=2))


if __name__=="__main__":
    run()
