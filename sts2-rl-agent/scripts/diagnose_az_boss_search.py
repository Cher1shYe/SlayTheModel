"""G2.3d fixed training-only probes. Never updates weights or production search."""
import argparse
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict
import json
import multiprocessing
from pathlib import Path
import sys
import time
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np

from sts2_env.az.adapter import ObservableCombatAdapter
from sts2_env.az.boss_curriculum import generate, block_rule_action
from sts2_env.az.config import atomic_json, derive_seed
from sts2_env.az.content import BOSS_CONTENT
from sts2_env.az.encoder import encode_information
from sts2_env.az.information import BeliefSampler
from sts2_env.az.network import load_checkpoint, code_digest
from sts2_env.az.observable_puct import search_belief
from sts2_env.az.rewards import V6
from sts2_env.az.scenarios import CombatScenario
from sts2_env.az.self_play import file_digest, initialize_worker

MODES = ("network", "search8", "search32", "tie8", "zero8", "rule")


def prior_tie_action(result):
    """Diagnostic only: keep visits, change just deterministic tie resolution."""
    if result.forced_action:
        return result.action
    candidates = np.flatnonzero(result.root_visits == result.root_visits.max())
    return int(max(candidates, key=lambda a: (result.root_priors[a], -int(a))))


def run_case(job):
    seed, mode, recipe_data, checkpoint, expected_hash, error_dir = job
    if file_digest(checkpoint) != expected_hash:
        raise ValueError("Source model changed")
    model, metadata = load_checkpoint(checkpoint, "observable", V6, BOSS_CONTENT)
    model.requires_grad_(False).eval()
    recipe = CombatScenario.from_dict(recipe_data)
    if recipe.split != "train":
        raise ValueError("Diagnostic admits training recipes only")
    env = ObservableCombatAdapter(recipe, error_dir=error_dir, reward_version=V6)
    rows = []
    started = time.perf_counter()
    while not env.outcome().done:
        info = env.information
        priors, value = model.predict(encode_information(info))
        network_action = int(np.argmax(priors))
        row = dict(step=len(rows), phase=info.boss.phase.cursor[0]+1, turn=info.turn,
                   hp=info.player_hp, block=info.player_block, hand=list(info.hand),
                   choice=info.choice.mechanism if info.choice else None,
                   legal_count=sum(info.legal_mask), value=value, network_action=network_action)
        if mode == "rule":
            action = block_rule_action(info)
        elif mode == "network":
            action = network_action
        else:
            evaluations = []
            def predict(public):
                p, v = model.predict(encode_information(public))
                evaluations.append(v)
                return p, 0.0 if mode == "zero8" else v
            result = search_belief(info, BeliefSampler().sample, predict,
                model_version=metadata["model_version"], budget=32 if mode == "search32" else 8,
                search_seed=derive_seed(20261016, seed, recipe.scenario_id, f"step-{len(rows)}"))
            action = prior_tie_action(result) if mode == "tie8" else result.action
            edges = [dict(action=a, prior=e.prior, visits=e.visits, q=e.q)
                     for a,e in result.root.edges.items()]
            maxima = [e["action"] for e in edges if e["visits"] == int(result.root_visits.max())]
            row.update(edges=edges, tied_max=len(maxima)>1,
                       prior_tie_action=prior_tie_action(result),
                       legacy_action=result.action, evaluations=evaluations,
                       one_visit_edges=sum(e["visits"]==1 for e in edges))
        row["action"] = int(action)
        env.step(action)
        rows.append(row)
    outcome = asdict(env.outcome())
    return dict(seed=seed, mode=mode, recipe=recipe_data, outcome=outcome, rows=rows,
                seconds=time.perf_counter()-started)


def summarize(cases):
    result = {}
    for seed in sorted({c["seed"] for c in cases}):
        for mode in sorted({c["mode"] for c in cases}):
            group = [c for c in cases if c["seed"]==seed and c["mode"]==mode]
            rows = [r for c in group for r in c["rows"]]
            if not group:
                continue
            result[f"{seed}/{mode}"] = dict(episodes=len(group), decisions=len(rows),
                wins=sum(c["outcome"]["termination_reason"]=="win" for c in group),
                timeouts=sum(c["outcome"]["termination_reason"]=="time_limit" for c in group),
                phase2=sum(any(r["phase"]>=2 for r in c["rows"]) for c in group),
                phase3=sum(any(r["phase"]==3 for r in c["rows"]) for c in group),
                mean_reward=float(np.mean([c["outcome"]["reward"] for c in group])),
                mean_value=float(np.mean([r["value"] for r in rows])),
                rollout_value_mae=float(np.mean([abs(r["value"]-c["outcome"]["reward"])
                                                for c in group for r in c["rows"]])),
                search_network_disagreements=sum(r["action"]!=r["network_action"] for r in rows),
                tied_max=sum(r.get("tied_max",False) for r in rows),
                prior_tie_changes=sum(r.get("prior_tie_action")!=r.get("legacy_action") for r in rows),
                tied_end_turn=sum(r.get("tied_max",False) and r.get("legacy_action")==0 and not r["choice"] for r in rows),
                seconds=sum(c["seconds"] for c in group))
    return result


def run(output, cases=9, seeds=(42,43), modes=MODES, workers=4):
    root = Path(output)
    root.mkdir(parents=True, exist_ok=True)
    if (root/"plan.json").exists():
        raise ValueError("Use a fresh diagnostic output; existing evidence is immutable")
    if not 1 <= cases <= 9 or not set(seeds)<= {42,43} or not set(modes)<=set(MODES):
        raise ValueError("Unsupported diagnostic coordinates")
    sources = json.loads(Path("output/az_g2_boss_curriculum_v1_quick/frozen_final_models.json").read_text())
    recipes = [generate(48,0,j) for j in range(90,90+cases)]
    jobs = [(s,m,r.to_dict(),sources[str(s)]["final"],sources[str(s)]["final_sha256"],str(root/"errors"))
            for s in seeds for m in modes for r in recipes]
    atomic_json(root/"plan.json", dict(date="2026-10-16",split="train",master=48,
        recipes=[r.to_dict() for r in recipes],sources=sources,modes=list(modes),seeds=list(seeds),
        code_digest=code_digest(),script_digest=file_digest(__file__),
        stopping_rule="fixed paired diagnostic only; no training, no final test, no automatic tuning",
        caveats=["Nine curated recipes are not a population quality benchmark",
                 "Rollout value error depends on continuation policy; not an oracle value error",
                 "zero8 removes neural leaf values only; terminal utility is unchanged",
                 "tie8 alters chosen action only; visit targets remain unchanged"]))
    completed = []
    with ProcessPoolExecutor(workers, mp_context=multiprocessing.get_context("spawn"),
                             initializer=initialize_worker) as pool:
        for case in pool.map(run_case,jobs):
            atomic_json(root/f"case-{case['seed']}-{case['mode']}-{case['recipe']['scenario_id']}.json",case)
            completed.append(case)
            atomic_json(root/"progress.json",dict(completed=len(completed),total=len(jobs)))
    if code_digest() != json.loads((root/"plan.json").read_text())["code_digest"]:
        raise ValueError("Engine changed during diagnostic")
    report = summarize(completed)
    atomic_json(root/"report.json",report)
    print(json.dumps(report,indent=2))


if __name__ == "__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output",required=True)
    parser.add_argument("--cases",type=int,default=9)
    parser.add_argument("--seeds",type=int,nargs="+",default=[42,43])
    parser.add_argument("--modes",nargs="+",choices=MODES,default=MODES)
    parser.add_argument("--workers",type=int,default=4)
    run(**vars(parser.parse_args()))
