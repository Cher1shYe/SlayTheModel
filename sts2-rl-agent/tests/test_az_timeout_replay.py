from copy import deepcopy
from types import SimpleNamespace
import pytest
from sts2_env.az.config import EpisodeLimits
from sts2_env.az.content import BOSS_CONTENT
from sts2_env.az.rewards import V7
from sts2_env.az.t4_protocol import generate_protocol
from sts2_env.az.self_play import CollectionJob
from sts2_env.az.entity_replay import EntityReplayBuffer
from sts2_env.az.action_candidates import action_candidates
from sts2_env.az import entity_transition


@pytest.mark.parametrize('limits,expected_turn,expected_count',[
    (EpisodeLimits(max_turns=1,max_decisions=400),2,1),
    (EpisodeLimits(max_turns=100,max_decisions=1),2,2),
])
def test_timeout_replay_turn_semantics(monkeypatch,tmp_path,limits,expected_turn,expected_count):
    def end(info,*args,**kwargs):
        keys=action_candidates(info)[1]
        return SimpleNamespace(action='end_turn',policy_target={k:float(k=='end_turn') for k in keys},
            root_visits={k:int(k=='end_turn') for k in keys},simulations=1,
            forced_action=False,elapsed=0.)
    monkeypatch.setattr(entity_transition,'plan_dynamic',end)
    recipe=generate_protocol()['groups']['train'][0]
    job=CollectionJob('timeout',0,41,recipe,'unused','unused','regression',str(tmp_path/'errors'),1,limits,V7,'dynamic-risk-puct-v2')
    record=entity_transition.collect_entity_episode(job,None)
    assert record['outcome']['termination_reason']=='time_limit'
    assert record['final_public']['turn']==expected_turn
    assert record['outcome']['turns']==expected_count
    validator=EntityReplayBuffer(tmp_path/'replay',content_version=BOSS_CONTENT,reward_version=V7)
    validator.validate(record)
    for field,value in [('turns',expected_count+1),('reward',0.123),('final_hp',-1)]:
        bad=deepcopy(record);bad['outcome'][field]=value
        with pytest.raises(ValueError):validator.validate(bad)


def test_migration_preserves_optimizer_tensors_and_rejects_drift():
    import torch
    from scripts.migrate_t4_timeout_smoke import equal
    original={'model':torch.tensor([1.,2.]),'optimizer':{'step':torch.tensor(4.),'moment':torch.tensor([.1])},'budget':[135,45]}
    equal(original,deepcopy(original))
    changed=deepcopy(original);changed['optimizer']['moment'][0]=.2
    with pytest.raises(ValueError,match='Tensor changed'):equal(original,changed)
    changed=deepcopy(original);changed['budget'][0]=136
    with pytest.raises(ValueError,match='Metadata changed'):equal(original,changed)
