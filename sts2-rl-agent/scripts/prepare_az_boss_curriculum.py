"""Freeze the full-fight Boss curriculum without changing the content schema."""
from pathlib import Path
from dataclasses import asdict
import json
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from sts2_env.az.boss_curriculum import VERSION, configuration, manifest, generate
from sts2_env.az.content import BOSS_CONTENT
from sts2_env.az.coordinator import TrainingConfig
from sts2_env.az.config import atomic_json, content_hash
from sts2_env.az.encoder import schema_for
from sts2_env.az.rewards import V6
from sts2_env.az.scenarios import save_manifest, load_manifest
from sts2_env.az.self_play import file_digest


def prepare():
    root=Path("configs/az_g2_boss_curriculum_v1")
    atomic_json(root/"generator.json",configuration())
    schema=schema_for("observable",V6,BOSS_CONTENT)
    atomic_json(root/"encoder_schema.json",dict(schema=schema,sha256=content_hash(schema)))
    sources=json.loads(Path("output/az_g2_boss_v1_quick/frozen_final_models.json").read_text(encoding="utf-8"))
    for seed in (42,43):
        source=sources[str(seed)]
        assert file_digest(source["final"])==source["final_sha256"]
        config=TrainingConfig(seed=seed,workers=8,iterations=3,episodes_per_iteration=180,updates=16,
                              batch_size=64,simulations=8,eval_simulations=8,content_version=BOSS_CONTENT,
                              reward_version=V6,sampling_version=VERSION,initial_checkpoint=source["final"])
        atomic_json(root/f"seed-{seed}.json",asdict(config))
    atomic_json(root/"weight_sources.json",sources)
    recipes=manifest()
    save_manifest("data/az/g2_boss_curriculum_v1_manifest.json",recipes)
    actual=[r for r in recipes if r.split!="train"]+[generate(s,i,j) for s in (42,43) for i in range(3) for j in range(180)]
    seeds={r.environment_seed for r in actual}
    assert len(seeds)==len(actual)
    checked=[]
    for base in Path("output").glob("az_*"):
        if "curriculum" in base.name:
            continue
        for p in list(base.glob("manifest.json"))+list(base.glob("seed-*/manifests/*.json")):
            old=load_manifest(p)
            assert not seeds.intersection(r.environment_seed for r in old),str(p)
            checked.append(str(p))
    atomic_json(root/"seed_isolation.json",dict(actual_unique=len(seeds),historical_manifests=checked,overlaps=[]))


if __name__=="__main__":
    prepare()
