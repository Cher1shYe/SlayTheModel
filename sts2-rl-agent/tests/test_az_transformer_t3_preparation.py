"""Preparation contracts only; never run a smoke or training experiment."""
from dataclasses import asdict,replace
import json
import pytest
from scripts.prepare_az_transformer_t3 import prepare,config
from sts2_env.az import transformer_course as course
from sts2_env.az import boss_search_curriculum as previous
from sts2_env.az.config import content_hash
from sts2_env.az.coordinator import Coordinator


def test_preparation_idempotent_immutable_and_no_final_test(tmp_path,monkeypatch):
    original=previous.generate
    def guarded(master,iteration,job,split='train'):
        assert split!='test', 'Preparation must not materialize final test'
        return original(master,iteration,job,split)
    monkeypatch.setattr(previous,'generate',guarded)
    plan=prepare(tmp_path)
    assert plan['status']=='prepared_not_started'
    assert prepare(tmp_path)==plan
    assert not list(tmp_path.rglob('*.pt')) and not list(tmp_path.rglob('state.json'))
    for name,digest in plan['document_hashes'].items():
        assert content_hash(json.loads((tmp_path/name).read_text()))==digest
    p=tmp_path/'formal-seed-42.json'
    p.write_text('{}')
    with pytest.raises(ValueError,match='Frozen preparation changed'): prepare(tmp_path)
    assert p.read_text()=='{}'


def test_all_train_coordinates_disjoint_and_composition_unchanged():
    seen=set()
    old={previous.generate(s,i,j).environment_seed for s in (42,43) for i in range(3) for j in range(180)}
    for smoke in (True,False):
        for seed in ((42,) if smoke else (42,43)):
            for iteration in range(2 if smoke else 3):
                for job in range(180):
                    r=course.generate(seed,iteration,job,smoke=smoke)
                    prior=previous.generate(seed,iteration,job)
                    a,b=asdict(r),asdict(prior)
                    for k in ('scenario_id','environment_seed'): a.pop(k); b.pop(k)
                    assert a==b
                    assert r.environment_seed not in seen|old
                    assert 0<=r.environment_seed<2**31
                    seen.add(r.environment_seed)
        manifest=course.preparation_manifest(smoke)
        assert len(manifest)==436 and all(r.split!='test' for r in manifest)
        for r in manifest:
            if r.split=='validation':
                assert r.environment_seed not in seen|old
                seen.add(r.environment_seed)


@pytest.mark.parametrize('change',[{'model_tier':'XS'},{'iterations':4},{'seed':44},{'initial_checkpoint':'old.pt'}])
def test_incompatible_t3_config_rejected(change):
    with pytest.raises(ValueError): replace(config(),**change)


@pytest.mark.parametrize('smoke',[False,True])
def test_coordinator_generator_dispatch_without_running(smoke):
    # No Coordinator initialization: check recipe dispatch metadata only.
    c=object.__new__(Coordinator)
    c.config=config(smoke=smoke)
    assert c.generator_config()==course.configuration(smoke)
    assert c.config.batch_size%c.config.microbatch_size==0
    assert c.config.search_version=='dynamic-risk-puct-v2'


@pytest.mark.parametrize('args',[ (42,3,0), (43,0,0), (42,0,180)])
def test_smoke_rejects_outside_frozen_coordinates(args):
    with pytest.raises(ValueError): course.generate(*args,smoke=True)
