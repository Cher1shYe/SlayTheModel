"""V7 formula, public risk, dynamic search backup and real training plumbing."""
from dataclasses import replace
from copy import deepcopy
import numpy as np
import pytest
import torch

from sts2_env.az.risk_reward import utility, incoming_risk, public_risk, world_risk, search_utility
from sts2_env.az.rewards import V6, V7
from sts2_env.az.content import BOSS_CONTENT
from sts2_env.az.adapter import ObservableCombatAdapter
from sts2_env.az.transformer_course import generate
from sts2_env.az.model_factory import create_transformer, save_transformer_checkpoint
from sts2_env.az.entity_encoder import encode_entities
from sts2_env.az.entity_replay import EntityReplayBuffer, pack_observation
from sts2_env.az.entity_transition import public_snapshot
from sts2_env.az.dynamic_search import plan_dynamic, search_dynamic
from sts2_env.az.search_config import DYNAMIC_RISK
from sts2_env.az.self_play import initialize_worker, CollectionJob, collect_episode, file_digest
from sts2_env.az.config import EpisodeLimits
from sts2_env.az.information import BeliefSampler
from sts2_env.az.action_candidates import action_candidates
from sts2_env.az.learner import Learner


@pytest.fixture(autouse=True)
def setup():
    initialize_worker(); torch.manual_seed(42)


@pytest.mark.parametrize('hp,start,maximum,d,q,expected', [
    (40,80,80,.5,.2, -.1+.45-.275-.0625-.01),
    (60,40,80,.0,0., -.1+.275),  # net healing, no square penalty
    (80,1,80,1.,0., .8),
    (1,80,80,0.,1., -.8),
    (40,40,80,0.,0., -.1),
])
def test_cutoff_formula(hp,start,maximum,d,q,expected):
    assert utility('time_limit',hp,start,maximum,d,q)==pytest.approx(expected)


def test_true_terminals_and_max_hp_normalization():
    assert utility('win',40,40,80,1.,0.)==pytest.approx(.95)
    assert utility('win',80,40,80,1.,0.)==1.
    for d in (0.,.5,1.): assert utility('death',0,40,80,d,1.)==-1.
    with pytest.raises(ValueError): utility('time_limit',0,40,80,1.,0.)
    with pytest.raises(ValueError): utility('win',40,40,None,1.,0.)
    with pytest.raises(ValueError): utility('time_limit',40,40,80,.5,float('nan'))


def test_risk_strength_multihit_vulnerable_and_shared_block():
    # floor((5+2)*1.5) = 10 per hit, 3 hits, 12 shared block, 20 HP.
    assert incoming_risk(20,12,1,[(5,2,2),(5,1,2)])==pytest.approx(.9)
    assert incoming_risk(20,40,1,[(5,3,2)])==0.
    assert incoming_risk(2,0,0,[(5,3,2)])==1.


@pytest.mark.parametrize('slot',[0,18,36,54,72,90,108,126,144,162,179])
def test_v7_world_public_particle_and_outcome_parity(slot):
    env=ObservableCombatAdapter(generate(42,0,slot,smoke=True),reward_version=V7,limits=EpisodeLimits(12,100))
    rng=np.random.default_rng(slot)
    while not env.outcome().done:
        info=env.information
        assert public_risk(info)==world_risk(env.world)
        particle=BeliefSampler().sample(info,rng)
        assert particle.info==info
        assert encode_entities(info).reward_version==V7
        action=int(rng.choice(np.flatnonzero(info.legal_mask)))
        env.step(action)
    final=env.information
    assert final.terminal_value()==env.outcome().reward
    assert env.outcome().player_max_hp==80
    assert final.player_hp==env.outcome().final_hp


def test_search_cutoff_uses_root_hp_not_battle_initial_hp():
    env=ObservableCombatAdapter(generate(42,0,0,smoke=True),reward_version=V7)
    root=env.information
    root=replace(root,player_hp=30)
    leaf=replace(root,player_hp=20)
    a=search_utility(root,leaf)
    b=search_utility(replace(root,player_hp=60),leaf)
    assert a>b  # same leaf, different simulation loss baseline


def test_search_ties_choose_measured_q_and_do_not_backup_network_value():
    class Info:
        def __init__(self,name='root'): self.name=name
        def terminal_value(self): return None
        def key(self): return self.name
    class Particle:
        info=Info()
        def step(self,key): self.info=Info(key); return self.info
    out=search_dynamic(Info(),lambda *a:Particle(),lambda _:({'end_turn':.51,'play':.49},.99),
        lambda _:('end_turn','play'),model_version='test',budget=2,search_version=DYNAMIC_RISK,
        cutoff_reward=lambda root,leaf:-.5 if leaf.name=='end_turn' else -.1)
    assert out.root_visits=={'end_turn':1,'play':1}
    assert out.action=='play'
    assert out.root.edges['play'].q==-.1
    assert out.root.edges['end_turn'].q==-.5


def test_real_collection_replay_training_and_version_rejection(tmp_path):
    model=create_transformer('XS',BOSS_CONTENT,V7)
    path=tmp_path/'initial.pt'; save_transformer_checkpoint(path,model,'v7-test')
    job=CollectionJob('0',0,42,generate(42,0,0,smoke=True).to_dict(),str(path),file_digest(path),
                      'v7-test',str(tmp_path/'errors'),4,EpisodeLimits(8,100),V7,DYNAMIC_RISK)
    episode=collect_episode(job)
    replay=EntityReplayBuffer(tmp_path/'replay',content_version=BOSS_CONTENT,reward_version=V7,search_version=DYNAMIC_RISK)
    assert replay.commit(episode)
    assert episode['compatibility']['search_version']==DYNAMIC_RISK
    assert all(row['z']==episode['outcome']['reward'] for row in episode['rows'])
    samples,_=replay.sample(4,np.random.default_rng(8))
    learner=Learner(model)
    before=deepcopy(learner.model.state_dict())
    metrics=learner.update(samples,2)
    assert np.isfinite(metrics['loss'])
    assert any(not torch.equal(v,learner.model.state_dict()[k]) for k,v in before.items())
    with pytest.raises(ValueError): EntityReplayBuffer(tmp_path/'replay',content_version=BOSS_CONTENT,reward_version=V6)
    bad=deepcopy(episode); bad['outcome']['incoming_risk']=.123
    with pytest.raises(ValueError): replay.validate(bad)
    bad=deepcopy(episode); bad['outcome']['player_max_hp']=100
    with pytest.raises(ValueError): replay.validate(bad)


def test_action_mapping_attack_and_policy_gradient_direction():
    env=ObservableCombatAdapter(generate(42,0,0,smoke=True),reward_version=V7)
    info=env.information
    model=create_transformer('XS',BOSS_CONTENT,V7)
    obs=encode_entities(info); actions,mapping=action_candidates(info)
    key=next(a.action_key for a in actions if a.action_type=='play' and a.target_refs==('enemy/0',))
    before=env.world.enemies[0].current_hp
    env.step(mapping[key])
    assert env.world.enemies[0].current_hp < before or env.world.enemies[0].block < info.enemy_block
    target={a.action_key:float(a.action_key==key) for a in actions}
    row={'observation':pack_observation(obs),'policy_target':target,'z':-.5}
    learner=Learner(model)
    p0=learner.model.predict(obs)[0][key]
    for _ in range(6): learner.update([row],1)
    assert learner.model.predict(obs)[0][key]>p0


def test_evaluation_recomputes_v7_from_final_public_state(tmp_path):
    from sts2_env.az.evaluation import evaluate, promotion_gate
    from sts2_env.az.transformer_course import preparation_manifest
    recipe=next(r for r in preparation_manifest(True) if r.split=='validation')
    model=create_transformer('XS',BOSS_CONTENT,V7)
    rows=evaluate(model,"v7-test",[recipe],simulations=0,limits=EpisodeLimits(2,100),
                  error_dir=tmp_path, reward_version=V7,search_version=DYNAMIC_RISK)
    assert 'final_public' in rows[0]
    gate=promotion_gate(rows,rows,required_count=1,bootstrap_samples=20,reward_version=V7,criterion='utility-only-v1')
    assert gate['clean'] and gate['mean_utility_difference']==0
    bad=deepcopy(rows);bad[0]['incoming_risk']=.731
    with pytest.raises(ValueError,match='V7 evaluation facts'):
        promotion_gate(rows,bad,required_count=1,reward_version=V7)


@pytest.mark.parametrize('slot',range(180))
def test_visible_risk_matches_native_next_wave_on_course_openings(slot):
    env=ObservableCombatAdapter(generate(42,0,slot,smoke=True),reward_version=V7)
    for _ in range(3):
        if env.outcome().done: break
        hp=env.world.player.current_hp; q=world_risk(env.world)
        env.step(0)
        assert q==pytest.approx((hp-env.world.player.current_hp)/hp)
