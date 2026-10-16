"""Engineering fixtures only: training recipes and labelled synthetic states."""
from copy import deepcopy
from dataclasses import replace
import json
import numpy as np
import pytest
import torch

from sts2_env.az.adapter import ObservableCombatAdapter
from sts2_env.az.boss_search_curriculum import generate
from sts2_env.az.boss_cards import CODEC
from sts2_env.az.content import BOSS_CONTENT
from sts2_env.az.rewards import V6
from sts2_env.az.entity_encoder import encode_entities, NUMERIC_FIELDS
from sts2_env.az.entity_transition import public_snapshot, public_from_dict
from sts2_env.az.entity_replay import EntityReplayBuffer, pack_observation, unpack_observation
from sts2_env.az.action_candidates import action_candidates
from sts2_env.az.information import BeliefSampler
from sts2_env.az.model_factory import create_transformer, save_transformer_checkpoint
from sts2_env.az.dynamic_search import plan_dynamic, VERSION
from sts2_env.az.self_play import initialize_worker, CollectionJob, collect_episode, Collector, file_digest
from sts2_env.az.config import EpisodeLimits
from sts2_env.search.clone import clone_state


@pytest.fixture(autouse=True)
def setup():
    initialize_worker()
    torch.manual_seed(17)


def check(info):
    public = public_from_dict(json.loads(json.dumps(public_snapshot(info))))
    assert public == info
    obs = encode_entities(info)
    assert unpack_observation(pack_observation(obs)) == obs
    assert encode_entities(public) == obs
    actions, mapping = action_candidates(info)
    assert set(mapping.values()) == set(np.flatnonzero(info.legal_mask))
    assert len(actions) == len(mapping)
    return obs


@pytest.mark.parametrize('slot', range(180))
def test_training_recipe_complete_trajectory(slot):
    env = ObservableCombatAdapter(generate(42, 0, slot), reward_version=V6)
    rng = np.random.default_rng(slot + 800)
    while not env.outcome().done:
        info = env.information
        check(info)
        particle = BeliefSampler().sample(info, rng)
        assert check(particle.info) == encode_entities(info)
        # Align hidden draws only in the parity oracle, never in model input.
        for attr in ('draw_pile', 'discard_pile'):
            pool = list(getattr(particle.world, attr))
            ordered = []
            for card in getattr(env.world, attr):
                twin = next(c for c in pool if (c.card_id,c.upgraded)==(card.card_id,card.upgraded))
                pool.remove(twin)
                ordered.append(twin)
            setattr(particle.world, attr, ordered)
        particle.world.rng = clone_state(env.world.rng)
        action = int(rng.choice(np.flatnonzero(info.legal_mask)))
        predicted = particle.step(action)
        env.step(action)
        assert predicted == env.information
    assert public_from_dict(json.loads(json.dumps(public_snapshot(env.information)))) == env.information


@pytest.mark.parametrize('token', tuple(CODEC.factories))
def test_every_card_description(token):
    from sts2_env.az.expanded_mechanics import describe_card
    from sts2_env.cards import base
    saved = base._next_instance_id
    d = describe_card(token)
    native = CODEC._reference(token)
    assert (d.cost,d.card_type) == (native.cost,native.card_type.value)
    for op in d.effects: op.validate()
    assert base._next_instance_id == saved
    for keyword in native.keywords: assert keyword in [o.kind for o in d.effects]


def arranged(monkeypatch, **kwargs):
    # Explicitly artificial card placement, never a curriculum quality sample.
    import tests.test_az_selection as old
    monkeypatch.setattr(old, 'SEL_CONTENT', BOSS_CONTENT)
    monkeypatch.setattr(old, 'V3', V6)
    from sts2_env.az import decks
    monkeypatch.setattr(decks, 'SEL_FAMILIES', decks.MORPH_FAMILIES)
    return old.arranged(**kwargs)


@pytest.mark.parametrize('token', ['TRUE_GRIT+', 'BURNING_PACT', 'ARMAMENTS', 'HEADBUTT', 'PURITY', 'PURITY+'])
def test_choice_candidates_execute_once(monkeypatch, token):
    import tests.test_az_selection as old
    env = arranged(monkeypatch, hand=[token]+['STRIKE_IRONCLAD']*5+['DEFEND_IRONCLAD']*4,
                   discard=['BASH','ANGER'],draw=[])
    old.play(env, token)
    info = env.information
    obs = check(info)
    assert info.choice is not None
    actions,mapping = action_candidates(info)
    for a in actions:
        p = BeliefSampler().sample(info,np.random.default_rng(10))
        successor = p.step(mapping[a.action_key])
        assert successor.choice is None
        assert successor.energy == info.energy
        assert successor.history.payments == info.history.payments
        assert successor.history.decisions == info.history.decisions+1
        if successor.terminal_value() is None: check(successor)
    model = create_transformer(content_version=BOSS_CONTENT)
    first = model.predict(obs)
    reordered = replace(obs,entities=tuple(reversed(obs.entities)),actions=tuple(
        replace(a,choice_refs=tuple(reversed(a.choice_refs))) for a in reversed(obs.actions)))
    second = model.predict(reordered,action_chunk_size=7)
    assert first[0].keys() == second[0].keys()
    np.testing.assert_allclose(list(first[0].values()),[second[0][k] for k in first[0]],atol=2e-6)
    assert abs(first[1]-second[1]) < 2e-6


@pytest.mark.parametrize('phase',[1,2])
def test_synthetic_later_boss_phase_reconstruction(phase):
    from tests.test_az_boss_integration import recipe,advance_form
    env = ObservableCombatAdapter(recipe(),reward_version=V6)
    for _ in range(phase): advance_form(env)
    for _ in range(3):
        if env.outcome().done: break
        obs = check(env.information)
        enemy = next(e for e in obs.entities if e.kind=='enemy')
        assert enemy.numbers[NUMERIC_FIELDS.index('phase')]*100 == phase
        particle = BeliefSampler().sample(env.information,np.random.default_rng(3))
        assert check(particle.info) == obs
        result = plan_dynamic(env.information,create_transformer(content_version=BOSS_CONTENT),
                              model_version='contract',budget=2,search_seed=3)
        assert result.action in action_candidates(env.information)[1]
        env.step(0)


def test_boss_replay_spawn_update_exact_restore(tmp_path):
    from sts2_env.az.coordinator import Learner,save_training,restore_training
    model = create_transformer(content_version=BOSS_CONTENT)
    path = tmp_path/'initial.pt'
    save_transformer_checkpoint(path,model,'contract')
    jobs = [CollectionJob(str(i),0,42,generate(42,0,i).to_dict(),str(path),file_digest(path),
        'contract',str(tmp_path/'errors'),2,EpisodeLimits(4,100),V6,search_version=VERSION) for i in (24,87,177)]
    serial = [collect_episode(j) for j in jobs]
    with Collector(2) as pool: parallel = pool.collect(jobs)
    replay = EntityReplayBuffer(tmp_path/'replay',content_version=BOSS_CONTENT,reward_version=V6)
    for a,b in zip(serial,parallel):
        assert [{k:v for k,v in r.items() if k!='search_seconds'} for r in a['rows']] == [
            {k:v for k,v in r.items() if k!='search_seconds'} for r in b['rows']]
        replay.commit(a)
    learner,rng = Learner(model),np.random.default_rng(8)
    rows,_ = replay.sample(4,rng)
    history = [learner.update(rows,microbatch_size=2)]  # Tiny optimizer contract, not an experiment.
    checkpoint = tmp_path/'resume.pt'
    save_training(checkpoint,learner,rng,replay,'contract',{},history,0)
    rows,counts = replay.sample(4,rng)
    expected = learner.update(rows,microbatch_size=2)
    weights = deepcopy(learner.model.state_dict())
    replay.release_memory()
    restored,rng2,_ = restore_training(checkpoint,replay)
    assert replay.sample(4,rng2) == (rows,counts)
    assert restored.update(rows,microbatch_size=2) == expected
    assert all(torch.equal(v,restored.model.state_dict()[k]) for k,v in weights.items())


@pytest.mark.parametrize('tier',['XS','S'])
def test_real_mixed_batch_and_hidden_invariance(tier):
    model = create_transformer(tier,content_version=BOSS_CONTENT)
    infos = [ObservableCombatAdapter(generate(42,0,i),reward_version=V6).information for i in range(0,180,9)]
    observations = [check(i) for i in infos]
    from sts2_env.az.transformer_network import batch_entities
    from sts2_env.az.network import masked_log_probs
    data = batch_entities(observations)
    with torch.no_grad():
        logits,values = model(data,action_chunk_size=3)
        policies = masked_log_probs(logits,data['legal_mask']).exp()
    for i,obs in enumerate(observations):
        p,v = model.predict(obs)
        np.testing.assert_allclose(policies[i,:len(p)].numpy(),list(p.values()),atol=2e-6)
        assert abs(float(values[i])-v)<2e-6
    info = infos[-1]
    before = info.key()
    a = plan_dynamic(info,model,model_version='contract',budget=3,search_seed=11)
    particle = BeliefSampler().sample(info,np.random.default_rng(9876))
    b = plan_dynamic(particle.info,model,model_version='contract',budget=3,search_seed=11)
    assert a.root_visits == b.root_visits and info.key() == before


def test_long_choice_schema_reject_and_content_isolation(tmp_path):
    from sts2_env.az.entity_encoder import SCHEMA,Entity,EntityObservation,ActionCandidate,numeric
    from sts2_env.az.expanded_mechanics import describe_card
    from sts2_env.az.model_factory import load_transformer_checkpoint
    # Synthetic length contract: distinct discard choices, not a legal trajectory.
    entities = (Entity('state','state','none',None,numeric()),
                Entity('pending','card','pending',None,numeric(),describe_card('HEADBUTT').effects))
    cards = tuple(Entity(f'discard/{i}','card','discard',None,numeric(),describe_card('WOUND').effects) for i in range(512))
    actions = tuple(ActionCandidate(f'choose:{e.ref}','choose','pending',choice_refs=(e.ref,)) for e in cards)
    obs = EntityObservation(entities+cards,actions,content_version=BOSS_CONTENT,reward_version=V6).validate()
    model = create_transformer(content_version=BOSS_CONTENT)
    p,v = model.predict(obs,action_chunk_size=32)
    assert len(p)==512 and np.isfinite(v) and abs(sum(p.values())-1)<1e-5
    maximum = replace(obs,entities=entities+tuple(replace(cards[0],ref=f'discard/{i}') for i in range(SCHEMA['max_entities']-2)))
    maximum.validate()
    assert unpack_observation(pack_observation(maximum)) == maximum
    with pytest.raises(ValueError,match='overflow'):
        replace(maximum,entities=maximum.entities+(replace(cards[0],ref='overflow'),)).validate()
    with pytest.raises(ValueError): describe_card('UNKNOWN_CARD')
    with pytest.raises(ValueError): create_transformer().predict(obs)
    path = tmp_path/'boss.pt'
    save_transformer_checkpoint(path,model)
    with pytest.raises(ValueError): load_transformer_checkpoint(path)
    restored,_ = load_transformer_checkpoint(path,expected_content=BOSS_CONTENT,expected_reward=V6)
    assert restored.predict(obs,action_chunk_size=32)==(p,v)


def test_descriptor_order_and_public_mechanic_features(monkeypatch):
    from sts2_env.az.expanded_mechanics import describe_card,monster_program
    import tests.test_az_selection as old
    assert [o.kind for o in describe_card('IRON_WAVE').effects][:2]==['block','damage']
    assert [o.kind for o in describe_card('OFFERING').effects][:3]==['hp_loss','energy','draw']
    assert [o.kind for o in describe_card('BURNING_PACT').effects][:2]==['choose_exhaust','draw']
    assert any(o.kind=='stage' and o.amount==7 for o in monster_program('TEST_SUBJECT'))
    env = arranged(monkeypatch,hand=['HEADBUTT','STOMP','REAVE','PRIMAL_FORCE','STRIKE_IRONCLAD'],discard=['BASH'],draw=[])
    old.play(env,'HEADBUTT')
    if env.information.choice: old.matched_step(env,1,True)
    obs=check(env.information)
    assert any(e.zone=='draw_top' and e.numbers[NUMERIC_FIELDS.index('known_position')]==.01 for e in obs.entities)
    stomp_ref=f'hand/{env.information.hand.index("STOMP")}'
    assert next(e for e in obs.entities if e.ref==stomp_ref).numbers[NUMERIC_FIELDS.index('current_cost')]==.02
    old.play(env,'REAVE')
    obs=check(env.information)
    assert any(e.zone=='draw_bottom' for e in obs.entities)
    old.play(env,'PRIMAL_FORCE')
    check(env.information)
    assert 'GIANT_ROCK' in env.information.hand
