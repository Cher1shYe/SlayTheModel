"""Fixed first-state probes for actual noisy training visit targets; no updates."""
import json
from pathlib import Path
import numpy as np
from diagnose_az_boss_search import (ObservableCombatAdapter, CombatScenario, V6,
    BOSS_CONTENT, load_checkpoint, initialize_worker, encode_information, BeliefSampler,
    search_belief, derive_seed, atomic_json, code_digest, file_digest)


def run():
    root=Path("output/az_boss_search_diagnostic_v1")
    output=Path("output/az_boss_label_diagnostic_v1.json")
    if output.exists():
        raise ValueError("Preserve existing label probe")
    plan=json.loads((root/"plan.json").read_text())
    if code_digest()!=plan["code_digest"]:
        raise ValueError("Source changed")
    initialize_worker()
    rows=[]
    for seed in plan["seeds"]:
        source=plan["sources"][str(seed)]
        if file_digest(source["final"])!=source["final_sha256"]:
            raise ValueError("Model changed")
        model,meta=load_checkpoint(source["final"],"observable",V6,BOSS_CONTENT)
        for data in plan["recipes"]:
            recipe=CombatScenario.from_dict(data)
            if recipe.split!="train":
                raise ValueError("Training-only diagnostic")
            info=ObservableCombatAdapter(recipe,reward_version=V6).information
            prior,value=model.predict(encode_information(info))
            for noisy in (False,True):
                result=search_belief(info,BeliefSampler().sample,
                    lambda public:model.predict(encode_information(public)),
                    model_version=meta["model_version"],budget=8,training=noisy,
                    temperature=1 if noisy else 0,
                    search_seed=derive_seed(20261016,seed,recipe.scenario_id,"step-0"))
                legal=np.flatnonzero(info.legal_mask)
                target=result.policy_target[legal]
                entropy=float(-sum(p*np.log(p) for p in target if p>0))
                rows.append(dict(seed=seed,scenario_id=recipe.scenario_id,training=noisy,
                    value=value,legal=legal.tolist(),network_prior=prior[legal].tolist(),
                    root_prior=result.root_priors[legal].tolist(),visits=result.root_visits[legal].tolist(),
                    target=target.tolist(),target_normalized_entropy=entropy/np.log(len(legal)),
                    chosen_action=result.action,network_action=int(np.argmax(prior)),
                    tied_max=int(sum(target==target.max()))>1))
    summary={str(seed):{str(noisy):dict(count=len(group),
        mean_normalized_entropy=float(np.mean([r["target_normalized_entropy"] for r in group])),
        tied_max=sum(r["tied_max"] for r in group))
        for noisy in (False,True) for group in [[r for r in rows if r["seed"]==seed and r["training"]==noisy]]}
        for seed in plan["seeds"]}
    atomic_json(output,dict(source_plan_sha256=file_digest(root/"plan.json"),
        script_sha256=file_digest(__file__),code_digest=code_digest(),rows=rows,summary=summary,
        limitation="First states only, 9 unique training recipes; entropy is not an outcome quality metric"))
    print(json.dumps(summary,indent=2))


if __name__=="__main__":
    run()
