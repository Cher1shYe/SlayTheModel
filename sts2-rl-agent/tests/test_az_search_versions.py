from dataclasses import replace
import numpy as np
import pytest
import torch
from tests.test_az_boss_search_diagnostic import State, Particle
from sts2_env.az.observable_puct import search_belief
from sts2_env.az.search_config import LEGACY, PRIOR, PARENT, COMBINED, VERSIONS
from sts2_env.az.boss_search_curriculum import generate, manifest
from sts2_env.az.content import BOSS_CONTENT
from sts2_env.az.rewards import V6
from sts2_env.az.network import PolicyValueNetwork, save_checkpoint
from sts2_env.az.self_play import CollectionJob, Collector, collect_episode, file_digest, initialize_worker
from sts2_env.az.config import EpisodeLimits
from sts2_env.az.replay_buffer import ReplayBuffer


def toy(version):
    return search_belief(State(),Particle,lambda _: (np.array([.07]*7+[.51]),-.9),
                         model_version="toy",budget=8,search_version=version)


def test_prior_tie_alone_keeps_labels_but_parent_fpu_changes_visits():
    old,prior,parent,combined=map(toy,VERSIONS)
    assert old.action==0 and prior.action==7
    np.testing.assert_array_equal(old.policy_target,prior.policy_target)
    assert parent.root.initial_value==-.9
    assert parent.root_visits[7]>1
    assert not np.array_equal(parent.policy_target,old.policy_target)
    np.testing.assert_array_equal(parent.root_visits,combined.root_visits)
    assert combined.action==7
    assert all(e.q==pytest.approx(-.9) for e in parent.root.edges.values() if e.visits)


def test_unknown_search_version_fails_closed():
    with pytest.raises(ValueError,match="search version"):
        toy("typo")


def test_new_recipe_namespace_disjoint_and_rotates_retained_strata():
    from sts2_env.az.boss_curriculum import manifest as old_manifest, generate as old_generate, profile
    new=[generate(s,i,j) for s in (42,43) for i in range(3) for j in range(180)]
    held=[r for r in manifest() if r.split!="train"]
    assert len({r.environment_seed for r in new+held})==1552
    old=old_manifest()+[old_generate(s,i,j) for s in (42,43) for i in range(3) for j in range(180)]
    assert not {r.environment_seed for r in new+held}&{r.environment_seed for r in old}
    assert len({(r.family_id,r.encounter_id,r.player_hp) for r in new[:360] if profile(r.scenario_id)=="retained"})==180


def test_versioned_collection_replay_and_spawn(tmp_path):
    initialize_worker()
    torch.manual_seed(7)
    model=PolicyValueNetwork("observable",V6,BOSS_CONTENT)
    checkpoint=tmp_path/"model.pt"
    save_checkpoint(checkpoint,model,"versioned",{}, {})
    job=CollectionJob("0",0,42,generate(42,0,90).to_dict(),str(checkpoint),file_digest(checkpoint),
                      "versioned",str(tmp_path/"errors"),8,EpisodeLimits(max_decisions=3),V6,COMBINED)
    serial=collect_episode(job)
    with Collector(1) as pool:
        parallel=pool.collect([job])[0]
    for a,b in zip(serial["rows"],parallel["rows"]):
        assert {k:v for k,v in a.items() if k!="search_seconds"}=={k:v for k,v in b.items() if k!="search_seconds"}
    buffer=ReplayBuffer(tmp_path/"new",reward_version=V6,content_version=BOSS_CONTENT,search_version=COMBINED)
    buffer.commit(serial)
    assert buffer.size==3
    before=buffer.sample(4,np.random.default_rng(77))
    buffer.release_memory()
    assert buffer._episodes is None
    assert buffer.sample(4,np.random.default_rng(77))==before
    assert buffer.size==3
    with pytest.raises(ValueError,match="search version"):
        ReplayBuffer(tmp_path/"legacy",reward_version=V6,content_version=BOSS_CONTENT).commit(serial)
    with pytest.raises(ValueError,match="version/capacity"):
        ReplayBuffer(tmp_path/"new",reward_version=V6,content_version=BOSS_CONTENT,search_version=PRIOR)
    old=collect_episode(replace(job,search_version=LEGACY))
    with pytest.raises(ValueError,match="search version"):
        buffer.commit(old)
    import json
    path=tmp_path/"new/episodes"/(serial["episode_id"]+".json")
    document=json.loads(path.read_text())
    document["rows"][0]["z"]=123
    path.write_text(json.dumps(document))
    buffer.release_memory()
    with pytest.raises(ValueError):
        buffer.sample(1,np.random.default_rng(77))
    assert buffer._episodes is None


def test_config_resume_rejects_search_change(tmp_path):
    from sts2_env.az.coordinator import Coordinator, TrainingConfig
    from sts2_env.az.scenarios import save_manifest
    path=tmp_path/"manifest.json"
    save_manifest(path,manifest())
    config=TrainingConfig(content_version=BOSS_CONTENT,reward_version=V6,search_version=COMBINED,
                          sampling_version="boss-search-course-v1",episodes_per_iteration=180)
    c=Coordinator(tmp_path/"run",path,config)
    c.close()
    with pytest.raises(ValueError,match="configuration"):
        Coordinator(tmp_path/"run",path,replace(config,search_version=PARENT))


@pytest.mark.parametrize("version",(PRIOR,PARENT,COMBINED))
def test_new_search_public_boundary_and_global_isolation(version):
    from sts2_env.az.adapter import ObservableCombatAdapter
    from sts2_env.az.information import observe, BeliefSampler
    from sts2_env.az.observable_puct import plan_observable
    from sts2_env.core.rng import Rng
    from sts2_env.cards import base
    initialize_worker()
    torch.manual_seed(9)
    env=ObservableCombatAdapter(generate(42,0,90),reward_version=V6)
    original=env.information
    allocator=base._next_instance_id
    model=PolicyValueNetwork("observable",V6,BOSS_CONTENT)
    options=dict(model_version="test",budget=8,search_seed=11,training=True,search_version=version)
    first=plan_observable(original,model,**options)
    assert env.information==original and base._next_instance_id==allocator
    env.world.draw_pile.reverse()
    env.world.rng=Rng(9876)
    perturbed=observe(env.world,original.history,original.limits,original.initial_hp,V6,BOSS_CONTENT,original.known_deck,(100,))
    assert perturbed==original
    second=plan_observable(perturbed,model,**options)
    np.testing.assert_array_equal(first.root_visits,second.root_visits)
    assert first.action==second.action
    a=BeliefSampler().sample(original,np.random.default_rng(4))
    b=BeliefSampler().sample(original,np.random.default_rng(4))
    before=b.info
    a.step(first.action)
    assert b.info==before


def test_evaluation_cache_separates_search_versions(tmp_path):
    from sts2_env.az.evaluation import evaluate_parallel
    initialize_worker()
    torch.manual_seed(8)
    checkpoint=tmp_path/"model.pt"
    save_checkpoint(checkpoint,PolicyValueNetwork("observable",V6,BOSS_CONTENT),"eval",{}, {})
    class Inline:
        map=staticmethod(map)
    for version in (PRIOR,COMBINED):
        rows=evaluate_parallel(Inline(),checkpoint,[generate(188,0,180,"validation")],2,123,
            EpisodeLimits(max_decisions=3),tmp_path/"cache",reward_version=V6,search_version=version)
        assert rows[0]["search_version"]==version
    assert len(list((tmp_path/"cache").glob("*.json")))==2
