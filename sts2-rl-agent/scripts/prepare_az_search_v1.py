"""Freeze G2.3e configurations and audit actual environment seed separation."""
from dataclasses import asdict
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from sts2_env.az.boss_search_curriculum import VERSION,configuration,generate,manifest
from sts2_env.az.boss_curriculum import generate as old_generate
from sts2_env.az.coordinator import TrainingConfig
from sts2_env.az.config import atomic_json
from sts2_env.az.content import BOSS_CONTENT
from sts2_env.az.rewards import V6
from sts2_env.az.search_config import COMBINED
from sts2_env.az.scenarios import load_manifest,save_manifest
from sts2_env.az.self_play import file_digest


def prepare():
    root=Path("configs/az_g2_search_v1")
    sources=json.loads(Path("output/az_g2_boss_curriculum_v1_quick/frozen_final_models.json").read_text())
    for seed in (42,43):
        source=sources[str(seed)]
        if file_digest(source["final"])!=source["final_sha256"]:
            raise ValueError("Source model changed")
        config=TrainingConfig(seed=seed,workers=4,iterations=3,episodes_per_iteration=180,
            updates=16,batch_size=64,simulations=8,eval_simulations=8,content_version=BOSS_CONTENT,
            reward_version=V6,sampling_version=VERSION,search_version=COMBINED,initial_checkpoint=source["final"])
        atomic_json(root/f"seed-{seed}.json",asdict(config))
    atomic_json(root/"generator.json",configuration())
    atomic_json(root/"weight_sources.json",sources)
    recipes=manifest()
    actual=[r for r in recipes if r.split!="train"]+[generate(s,i,j) for s in (42,43) for i in range(3) for j in range(180)]
    seeds={r.environment_seed for r in actual}
    if len(seeds)!=len(actual):
        raise ValueError("New seeds overlap")
    checked=[]
    for base in Path("output").glob("az_*"):
        if base.name.startswith("az_g2_search_v1"):
            continue
        for path in list(base.glob("manifest.json"))+list(base.glob("seed-*/manifests/*.json")):
            if seeds & {r.environment_seed for r in load_manifest(path)}:
                raise ValueError(f"Historical seed overlap: {path}")
            checked.append(str(path))
    if seeds & {old_generate(48,0,j).environment_seed for j in range(90,99)}:
        raise ValueError("Diagnostic seed overlap")
    save_manifest("data/az/g2_search_v1_manifest.json",recipes)
    atomic_json(root/"seed_isolation.json",dict(actual_unique=len(seeds),historical_manifests=checked,overlaps=[]))
    print(dict(unique=len(seeds),historical_manifests=len(checked)))


if __name__=="__main__":
    prepare()
