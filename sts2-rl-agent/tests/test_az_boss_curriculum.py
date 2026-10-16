from collections import Counter
from dataclasses import replace
from pathlib import Path
import numpy as np
import pytest
import torch

from sts2_env.az.boss_curriculum import VERSION, generate, manifest, profile, block_rule_action
from sts2_env.az.content import BOSS_CONTENT
from sts2_env.az.coordinator import TrainingConfig, Coordinator
from sts2_env.az.rewards import V6
from sts2_env.az.scenarios import save_manifest, load_manifest


def test_curriculum_mix_coverage_and_seed_isolation():
    held = [r for r in manifest() if r.split != "train"]
    train = [generate(s,i,j) for s in (42,43) for i in range(3) for j in range(180)]
    seeds = {r.environment_seed for r in held+train}
    assert len(seeds) == len(held)+len(train)
    assert Counter(r.split for r in held) == {"validation":256,"test":216}
    assert Counter(profile(r.scenario_id) for r in train) == {"retained":540,"focused":540}
    strata = {(r.family_id,r.encounter_id,r.player_hp) for r in train[:360] if profile(r.scenario_id)=="retained"}
    assert len(strata) == 180
    for path in Path("data/az").glob("*manifest.json"):
        if "curriculum" not in path.name:
            assert not seeds.intersection(r.environment_seed for r in load_manifest(path))
    for row in train+held:
        assert row == generate(int(row.scenario_id.split('-')[-3]), int(row.scenario_id.split('-')[-2]),
                               int(row.scenario_id.split('-')[-1]), row.split)


@pytest.mark.parametrize("kwargs", [dict(sampling_version="unknown"),dict(episodes_per_iteration=90),dict(content_version="g2-summon-v1")])
def test_curriculum_rejects_mismatched_configuration(kwargs):
    config=dict(content_version=BOSS_CONTENT,reward_version=V6,sampling_version=VERSION,episodes_per_iteration=180)
    config.update(kwargs)
    with pytest.raises(ValueError):
        TrainingConfig(**config)


def test_warm_start_preserves_weights_provenance_and_resume(tmp_path):
    from sts2_env.az.network import PolicyValueNetwork, save_checkpoint, load_checkpoint
    from sts2_env.az.self_play import initialize_worker, file_digest
    initialize_worker()
    model=PolicyValueNetwork("observable",V6,BOSS_CONTENT)
    source=tmp_path/"source.pt"
    save_checkpoint(source,model,"old-champion",{}, {})
    manifest_path=tmp_path/"manifest.json"
    save_manifest(manifest_path,manifest())
    config=TrainingConfig(content_version=BOSS_CONTENT,reward_version=V6,sampling_version=VERSION,
                          episodes_per_iteration=180,initial_checkpoint=str(source))
    coordinator=Coordinator(tmp_path/"run",manifest_path,config)
    try:
        new,meta=load_checkpoint(tmp_path/"run/initial.pt","observable",V6,BOSS_CONTENT)
        assert all(torch.equal(value,new.state_dict()[key]) for key,value in model.state_dict().items())
        assert meta["statistics"]["initialization"]["sha256"] == file_digest(source)
        assert "training_state" not in meta
        assert coordinator.state["iteration"] == 0
    finally:
        coordinator.close()
    restored=Coordinator(tmp_path/"run",manifest_path,config)
    restored.close()
    with pytest.raises(ValueError,match="configuration"):
        Coordinator(tmp_path/"run",manifest_path,replace(config,sampling_version="standard"))


def test_focused_rule_cannot_silently_rank_unsupported_decks():
    from sts2_env.az.adapter import ObservableCombatAdapter
    env=ObservableCombatAdapter(generate(42,0,0),reward_version=V6)
    with pytest.raises(ValueError,match="curated"):
        block_rule_action(env.information)


def test_status_tokens_never_make_upgrade_events():
    from sts2_env.az.card_upgrades import upgradable
    assert not any(upgradable(t) for t in ("BURN","WOUND","DAZED"))
