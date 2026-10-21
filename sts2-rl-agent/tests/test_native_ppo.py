import copy
import math
import gzip
import json
from pathlib import Path
import torch
import pytest
from sts2_env.az import ppo
from sts2_env.az.model_factory import create_transformer, save_transformer_checkpoint, load_transformer_checkpoint
from sts2_env.az.native_generic import CONTENT, SCHEMA_HASH
from sts2_env.az.rewards import V7


def test_gae_terminal_and_cutoff_payoff_not_double_counted():
    rows = [dict(old_value=.2), dict(old_value=.4)]
    ppo.advantages(rows, -1., gamma=1., gae_lambda=1.)
    assert [r['return'] for r in rows] == pytest.approx([-1., -1.])
    rows = [dict(old_value=.2), dict(old_value=.4)]
    ppo.advantages(rows, .3, gamma=1., gae_lambda=.95)
    assert rows[-1]['return'] == pytest.approx(.3)
    assert rows[0]['advantage'] == pytest.approx(.2 + .95*(-.1))


@pytest.mark.parametrize('terminal_reward', [-1., .95, .3])
def test_potential_telescopes_including_cutoff_and_no_cycle_profit(terminal_reward):
    phi = [-.2, .4, -.2, .6]
    rows = [dict(old_value=.1, shaping_reward=.1*((phi[i+1] if i+1<len(phi) else 0)-p))
            for i, p in enumerate(phi)]
    assert sum(r['shaping_reward'] for r in rows) == pytest.approx(-.1*phi[0])
    ppo.advantages(rows, terminal_reward, gae_lambda=1.)
    assert [r['return'] for r in rows] == pytest.approx([terminal_reward-.1*p for p in phi])


def test_potential_evidence_and_defense_credit():
    facts = dict(version='v7-potential-v1', hp=40, maxHp=80, initialHp=40,
                 damage=0., risk=.5, pendingChoice=False, terminal=False, value=-.1625)
    before = ppo.potential(facts, 40, False, 40)
    defended = dict(facts, risk=.25, value=-.115625)
    assert .1*(ppo.potential(defended, 40, False, 40)-before) == pytest.approx(.0046875)
    for key, value in [('value', float('nan')), ('damage', 2), ('initialHp', 41),
                       ('terminal', True), ('pendingChoice', True)]:
        with pytest.raises(ValueError):
            ppo.potential(dict(facts, **{key:value}), 40, False, 40)


def test_native_shaping_trajectories_and_strict_evidence():
    with gzip.open(Path(__file__).parent/'fixtures/native_ppo_shaping_v1.json.gz', 'rt', encoding='utf8') as f:
        raws = json.load(f)
    assert {r['outcome']['won'] for r in raws} == {True, False}
    for raw in raws:
        rows = ppo.trajectory_rows(raw, raw['modelSha256'], .1)
        assert sum(r['shaping_reward'] for r in rows) == pytest.approx(-.1*rows[0]['potential'])
        ppo.advantages(rows, raw['outcome']['reward'], gae_lambda=1.)
        assert rows[0]['return'] == pytest.approx(raw['outcome']['reward']-.1*rows[0]['potential'])
        broken = copy.deepcopy(raw)
        del broken['steps'][0]['potentialBefore']
        with pytest.raises(KeyError):
            ppo.trajectory_rows(broken, raw['modelSha256'], .1)
        broken = copy.deepcopy(raw)
        broken['steps'][0]['potentialAfter']['value'] += .1
        with pytest.raises(ValueError):
            ppo.trajectory_rows(broken, raw['modelSha256'], .1)


def test_pending_stratagem_uses_endpoint_maxhp_after_scrolls():
    with gzip.open(Path(__file__).parent/'fixtures/native_ppo_pending_maxhp_v1.json.gz', 'rt', encoding='utf8') as f:
        raw = json.load(f)
    assert raw['seed'] == 8001450
    assert raw['steps'][24]['potentialAfter']['maxHp'] == 64
    assert raw['steps'][25]['potentialBefore']['pendingChoice'] is True
    assert raw['steps'][25]['potentialBefore']['maxHp'] == 64
    ppo.trajectory_rows(raw, raw['modelSha256'], .1)
    broken = copy.deepcopy(raw)
    broken['steps'][24]['potentialAfter']['maxHp'] = 74
    broken['steps'][25]['potentialBefore']['maxHp'] = 74
    with pytest.raises(ValueError, match='max HP differs'):
        ppo.trajectory_rows(broken, raw['modelSha256'], .1)


def test_ppo_clipping_positive_and_negative_advantages():
    terms = ppo.loss_terms(torch.log(torch.tensor([1.5, .5, .5, 1.5])), torch.zeros(4),
                          torch.zeros(4), torch.zeros(4), torch.zeros(4), torch.tensor([1., -1., 1., -1.]))
    assert terms[0].tolist() == pytest.approx([-1.2, .8, -.5, 1.5])


def make_rows(tier='XS'):
    observations = [dict(schema=SCHEMA_HASH, entities=[{'hp':40+i}],
                         actions=[dict(key=str(j), features={'card':str(j)}) for j in range(n)])
                    for i, n in enumerate([2, 3, 1, 2])]
    model = create_transformer(tier, CONTENT, V7).eval()
    rows = []
    for i, obs in enumerate(observations):
        p, v = model.predict(obs)
        rows.append(dict(observation=obs, action='0', old_logp=math.log(p['0']), old_value=v,
                         old_probabilities=list(p.values()), forced=len(p)==1,
                         scenario_id='test', step=i, advantage=[1.,-1.,0.,.3][i], return_=.1))
        rows[-1]['return'] = .1
    ppo.normalize_advantages(rows)
    return model, rows


CONFIG = dict(seed=42, epochs=3, batch_size=3, microbatch=2, clip=.2,
              value_weight=.5, entropy_weight=.01, target_kl=.03, max_grad_norm=.5)


@pytest.mark.parametrize('tier', ['XS', 'S'])
@pytest.mark.parametrize('kl_scope', ['minibatch', 'rollout'])
def test_resume_matches_uninterrupted_and_updates_weights(tmp_path, tier, kl_scope):
    config = dict(CONFIG, kl_scope=kl_scope)
    torch.set_num_threads(1)
    torch.manual_seed(42)
    model, rows = make_rows(tier)
    assert ppo.verify_behavior(model, rows) < 2e-5
    optimizer = torch.optim.AdamW(model.parameters(), lr=3e-4, weight_decay=0.)
    before = {k:v.clone() for k,v in model.state_dict().items()}
    first = ppo.update(model, optimizer, rows, config, kl_rows=rows)
    assert first['applied']
    assert any(not torch.equal(v, before[k]) for k,v in model.state_dict().items())
    file = tmp_path/'restore.pt'
    save_transformer_checkpoint(file, model, training_state=dict(optimizer=optimizer.state_dict(), rng=torch.get_rng_state()))
    metrics = ppo.update(model, optimizer, rows, config, kl_rows=rows)
    resumed, payload = load_transformer_checkpoint(file, tier, CONTENT, V7)
    restored = torch.optim.AdamW(resumed.parameters(), lr=3e-4, weight_decay=0.)
    restored.load_state_dict(payload['training_state']['optimizer'])
    torch.set_rng_state(payload['training_state']['rng'])
    assert ppo.update(resumed, restored, rows, config, kl_rows=rows) == metrics
    assert all(torch.equal(v, resumed.state_dict()[k]) for k,v in model.state_dict().items())


def test_s_native_inference_service(tmp_path):
    import subprocess
    import sys
    root = Path(__file__).resolve().parents[1]
    with gzip.open(root/'tests/fixtures/native_ppo_sampled_v1.json.gz', 'rt', encoding='utf8') as f:
        raw = json.load(f)
    observation = raw['steps'][0]['observation']
    model = create_transformer('S', CONTENT, V7).eval()
    assert sum(p.numel() for p in model.parameters()) == 9460738
    checkpoint = tmp_path/'s.pt'
    save_transformer_checkpoint(checkpoint, model)
    result = subprocess.run([sys.executable, str(root/'scripts/native_pilot_service.py'),
                             '--source', str(root), '--checkpoint', str(checkpoint)],
                            input=json.dumps(dict(operation='policy_value', observation=observation,
                                                  expected=observation))+'\n',
                            text=True, capture_output=True, timeout=60, check=True)
    messages = [json.loads(line) for line in result.stdout.splitlines()]
    assert messages[0]['ready'] is True
    assert 'error' not in messages[1]
    assert len(messages[1]['priors']) == len(observation['actions'])
    assert sum(messages[1]['priors']) == pytest.approx(1., abs=1e-6)
    assert -1 <= messages[1]['value'] <= 1


def test_bad_behavior_fails_and_high_kl_does_not_update():
    torch.set_num_threads(1)
    model, rows = make_rows()
    corrupted = copy.deepcopy(rows)
    corrupted[0]['old_logp'] += .1
    with pytest.raises(ValueError, match='Frozen PPO'):
        ppo.verify_behavior(model, corrupted)
    for r in corrupted:
        r['old_logp'] -= 3.
    before = {k:v.clone() for k,v in model.state_dict().items()}
    optimizer = torch.optim.AdamW(model.parameters(), lr=3e-4)
    assert not ppo.update(model, optimizer, corrupted, CONFIG)['applied']
    assert all(torch.equal(v, before[k]) for k,v in model.state_dict().items())


def test_every_epoch_covers_every_row():
    plan = list(ppo.batch_plan(11, CONFIG, 2))
    for epoch in range(1, 4):
        assert sorted(i for e, indices in plan if e==epoch for i in indices) == list(range(11))


def test_native_sampled_fixture_and_corruption_rejection():
    with gzip.open(Path(__file__).parent/'fixtures/native_ppo_sampled_v1.json.gz', 'rt', encoding='utf8') as f:
        raw = json.load(f)
    rows = ppo.trajectory_rows(raw, raw['modelSha256'])
    assert len(rows) == len(raw['steps'])
    assert all(s['simulations'] == 0 for s in raw['steps'])
    with pytest.raises(ValueError, match='current-policy'):
        ppo.trajectory_rows(raw, '0'*64)
    for field, value in [('behaviorLogProbability', 10.), ('policyUniform', 1.),
                         ('behaviorValue', float('nan')), ('successorParity', False)]:
        broken = copy.deepcopy(raw)
        broken['steps'][0][field] = value
        with pytest.raises(ValueError):
            ppo.trajectory_rows(broken, raw['modelSha256'])
    broken = copy.deepcopy(raw)
    broken['policySample'] = False
    with pytest.raises(ValueError):
        ppo.trajectory_rows(broken, raw['modelSha256'])


def test_rollout_kl_weights_rows_excludes_forced_and_restores_mode(monkeypatch):
    model = torch.nn.Linear(1, 1).train()
    def fake_distribution(model, rows):
        return torch.tensor([r['new_logp'] for r in rows], dtype=torch.float64), None, None, None, None
    monkeypatch.setattr(ppo, 'distribution', fake_distribution)
    rows = [dict(old_logp=0., new_logp=d, forced=False) for d in (.1, -.2, .8)]
    rows.insert(1, dict(old_logp=0., new_logp=1000., forced=True))
    expected = sum(math.expm1(d)-d for d in (.1, -.2, .8))/3
    for microbatch in (1, 2, 4):
        result = ppo.rollout_kl(model, rows, microbatch)
        assert result['rollout_kl'] == pytest.approx(expected)
        assert result['kl_policy_rows'] == 3 and result['kl_total_rows'] == 4
        assert model.training


def test_full_rollout_rejects_safe_minibatch_when_rest_has_high_kl():
    torch.set_num_threads(1)
    model, rows = make_rows()
    full = copy.deepcopy(rows)
    full[1]['old_logp'] -= 3.
    optimizer = torch.optim.AdamW(model.parameters(), lr=1e-4)
    before = copy.deepcopy(model.state_dict())
    config = dict(CONFIG, kl_scope='rollout')
    result = ppo.update(model, optimizer, rows[:1], config, kl_rows=full)
    assert not result['applied'] and result['rollout_kl'] > .03
    assert not optimizer.state
    assert all(torch.equal(v, before[k]) for k, v in model.state_dict().items())
    with pytest.raises(ValueError, match='Full rollout'):
        ppo.update(model, optimizer, rows, config)


def test_full_rollout_does_not_stop_on_one_outlier_minibatch():
    torch.set_num_threads(1)
    model, rows = make_rows()
    outlier = copy.deepcopy(rows[0])
    outlier['old_logp'] -= .4
    full = [outlier] + [copy.deepcopy(rows[1]) for _ in range(99)]
    optimizer = torch.optim.AdamW(model.parameters(), lr=1e-4)
    result = ppo.update(model, optimizer, [outlier], dict(CONFIG, kl_scope='rollout'), kl_rows=full)
    assert result['approx_kl'] > .03 and result['rollout_kl'] < .03
    assert result['applied']


def test_scheduled_kl_interval_epoch_end_and_applied_stop(monkeypatch):
    checks = []
    monkeypatch.setattr(ppo, 'update', lambda *args, **kwargs: dict(applied=True))
    monkeypatch.setattr(ppo, 'rollout_kl', lambda *args: checks.append(1) or dict(rollout_kl=.04))
    seen = []
    for count in range(1, 33):
        metrics = ppo.scheduled_update(None, None, [], dict(CONFIG, kl_scope='rollout', kl_check_interval=16),
            kl_rows=[], rollout_updates=count-1, epoch_end=count in (10, 20, 32))
        if 'rollout_kl' in metrics:
            seen.append(count)
            assert metrics['applied'] and metrics['stop_rollout']
    assert seen == [10, 16, 20, 32] and len(checks) == 4


def test_resume_before_scheduled_kl_boundary(tmp_path):
    torch.set_num_threads(1)
    torch.manual_seed(42)
    model, rows = make_rows()
    config = dict(CONFIG, kl_scope='rollout', kl_check_interval=16)
    opt = torch.optim.AdamW(model.parameters(), lr=1e-5, weight_decay=0.)
    for count in range(15):
        result = ppo.scheduled_update(model, opt, rows, config, kl_rows=rows, rollout_updates=count, epoch_end=False)
        assert 'rollout_kl' not in result
    path = tmp_path/'boundary.pt'
    save_transformer_checkpoint(path, model, training_state=dict(optimizer=opt.state_dict(), rng=torch.get_rng_state(), rollout_updates=15))
    expected = ppo.scheduled_update(model, opt, rows, config, kl_rows=rows, rollout_updates=15, epoch_end=True)
    resumed, payload = load_transformer_checkpoint(path, 'XS', CONTENT, V7)
    restored = torch.optim.AdamW(resumed.parameters(), lr=1e-5, weight_decay=0.)
    restored.load_state_dict(payload['training_state']['optimizer'])
    torch.set_rng_state(payload['training_state']['rng'])
    actual = ppo.scheduled_update(resumed, restored, rows, config, kl_rows=rows,
        rollout_updates=payload['training_state']['rollout_updates'], epoch_end=True)
    assert actual == expected and 'rollout_kl' in actual
    assert all(torch.equal(v, resumed.state_dict()[k]) for k, v in model.state_dict().items())
