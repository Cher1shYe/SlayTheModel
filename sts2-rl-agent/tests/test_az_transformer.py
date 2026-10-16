from dataclasses import replace
import copy
import math
import pytest
import torch

from sts2_env.az.adapter import ObservableCombatAdapter
from sts2_env.az.scenarios import starter_scenario
from sts2_env.az.information import observe
from sts2_env.search.clone import clone_state
from sts2_env.az.entity_encoder import encode_entities, EntityObservation
from sts2_env.az.action_candidates import starter_candidates, execute_candidate
from sts2_env.az.transformer_network import batch_entities, keyed_targets, transformer_loss, TIERS
from sts2_env.az.network import masked_log_probs, PolicyValueNetwork, save_checkpoint, load_checkpoint
from sts2_env.az.model_factory import create_transformer, save_transformer_checkpoint, load_transformer_checkpoint
from sts2_env.az.mechanic_registry import card_descriptor


@pytest.fixture(autouse=True)
def deterministic():
    torch.set_num_threads(1)
    torch.manual_seed(19)


def fixture():
    return ObservableCombatAdapter(starter_scenario(8))


def mixed():
    env = fixture()
    first = encode_entities(env.information)
    action = next(a for a in first.actions if a.action_type == 'play')
    execute_candidate(env, action.action_key)
    return [first, encode_entities(env.information)]


@pytest.mark.parametrize('tier', ['XS', 'S'])
def test_real_mixed_batch_update_and_serial_equivalence(tier):
    obs = mixed()
    model = create_transformer(tier)
    batch = batch_entities(obs)
    logits, values = model(batch)
    probs = masked_log_probs(logits, batch['legal_mask']).exp()
    assert (probs[~batch['legal_mask']] == 0).all()
    for i, item in enumerate(obs):
        p, v = model.predict(item)
        torch.testing.assert_close(probs[i, :len(p)], torch.tensor(list(p.values())), atol=2e-6, rtol=2e-5)
        assert abs(v - float(values[i].detach())) < 2e-6
    targets = keyed_targets(batch, [{a.action_key: 1 / len(o.actions) for a in o.actions} for o in obs])
    before = model.score[-1].weight.detach().clone()
    loss, _ = transformer_loss(model, batch, targets, torch.tensor([1., -1.]))
    optimizer = torch.optim.Adam(model.parameters(), lr=1e-3)
    loss.backward()
    assert all(torch.isfinite(p.grad).all() for p in model.parameters() if p.grad is not None)
    optimizer.step()
    assert not torch.equal(before, model.score[-1].weight)


def test_permutation_chunking_and_gradient_equivalence():
    obs = mixed()[0]
    shuffled = replace(obs, entities=tuple(reversed(obs.entities)), actions=tuple(reversed(obs.actions)))
    model = create_transformer()
    p, v = model.predict(obs)
    q, w = model.predict(shuffled, action_chunk_size=2)
    assert abs(v - w) < 2e-6
    assert all(abs(p[k] - q[k]) < 2e-6 for k in p)
    batch = batch_entities([obs])
    logits, val = model(batch)
    (logits.sum() + val.sum()).backward()
    gradients = {k: t.grad.clone() for k, t in model.named_parameters() if t.grad is not None}
    model.zero_grad()
    logits2, val2 = model(batch, action_chunk_size=1)
    (logits2.sum() + val2.sum()).backward()
    for k, t in model.named_parameters():
        if k in gradients:
            torch.testing.assert_close(t.grad, gradients[k], atol=2e-5, rtol=2e-4)


def test_hidden_rng_and_card_identity_are_absent():
    env = fixture()
    twin = clone_state(env.world)
    twin.draw_pile.reverse()
    for _ in range(20):
        twin.rng.next_int(0, 99999)
    for c in twin.hand + twin.draw_pile:
        c.instance_id += 10000
    other = observe(twin, env.information.history)
    assert encode_entities(other) == encode_entities(env.information)
    model = create_transformer()
    assert model.predict(encode_entities(other)) == model.predict(encode_entities(env.information))


def test_candidate_execution_and_mechanic_parity():
    # Check each legal candidate against native execution at multiple turns.
    env = fixture()
    seen = set()
    for _ in range(3):
        actions, mapping = starter_candidates(env.information)
        for action in actions:
            left, right = copy.deepcopy(env), copy.deepcopy(env)
            execute_candidate(left, action.action_key)
            right.step(mapping[action.action_key])
            assert left.information == right.information
            if action.action_type == 'play':
                slot = int(action.source_ref.split('/')[1])
                name = env.information.hand[slot]
                seen.add(name)
                descriptor = card_descriptor(name)
                assert env.world.hand[slot].cost == descriptor.cost
                assert left.information.energy == env.information.energy - descriptor.cost
                if name == 'DEFEND_IRONCLAD':
                    assert left.information.player_block - env.information.player_block == descriptor.effects[0].amount
                else:
                    damage = math.floor(descriptor.effects[0].amount * (.7 if env.information.shrink else 1))
                    assert env.information.enemy_hp - left.information.enemy_hp == damage
                    if name == 'BASH':
                        assert left.information.vulnerable == 2
        env.step(0)
    assert seen == {'STRIKE_IRONCLAD', 'DEFEND_IRONCLAD', 'BASH'}


def test_rejections_and_ordered_effects():
    obs = mixed()[0]
    with pytest.raises(TypeError):
        encode_entities(fixture().world)
    with pytest.raises(ValueError, match='Unsupported'):
        encode_entities(replace(fixture().information, content_version='unknown'))
    for bad in [replace(obs, actions=()), replace(obs, actions=obs.actions * 2),
                replace(obs, entities=obs.entities * 2),
                replace(obs, actions=(replace(obs.actions[0], source_ref='dangling'),)),
                replace(obs, actions=tuple(replace(a, legal=False) for a in obs.actions))]:
        with pytest.raises(ValueError):
            batch_entities([bad])
    with pytest.raises(ValueError, match='Unsupported mechanic path'):
        card_descriptor('NEW_UNAUDITED_CARD')
    model = create_transformer()
    # Synthetic local change: same effects in opposite order must not alias.
    entities = list(obs.entities)
    idx = next(i for i, e in enumerate(entities) if len(e.effects) >= 2)
    entities[idx] = replace(entities[idx], effects=tuple(reversed(entities[idx].effects)))
    a, _ = model(batch_entities([obs]))
    b, _ = model(batch_entities([replace(obs, entities=tuple(entities))]))
    assert not torch.allclose(a, b, atol=1e-7, rtol=1e-7)


def test_unknown_operation_illegal_probability_and_keyed_labels():
    obs = mixed()[0]
    enemy = obs.entities[2]
    bad = replace(enemy, effects=(replace(enemy.effects[0], kind='unknown'),))
    with pytest.raises(ValueError, match='Unsupported mechanic path'):
        batch_entities([replace(obs, entities=obs.entities[:2] + (bad,) + obs.entities[3:])])
    masked = replace(obs, actions=(obs.actions[0], replace(obs.actions[1], legal=False)))
    p, _ = create_transformer().predict(masked)
    assert p[masked.actions[0].action_key] == 1
    assert p[masked.actions[1].action_key] == 0
    batch = batch_entities([masked])
    targets = keyed_targets(batch, [dict(reversed(list(p.items())))])
    assert targets.tolist() == [[1., 0.]]
    with pytest.raises(ValueError, match='keys'):
        keyed_targets(batch, [{'wrong_key': 1.}])


def test_vulnerable_damage_order_and_public_diagnostic(tmp_path):
    for seed in range(30):
        env = ObservableCombatAdapter(starter_scenario(seed))
        if 'BASH' in env.information.hand and 'STRIKE_IRONCLAD' in env.information.hand:
            break
    else:
        pytest.fail('Fixture must contain Bash and Strike')
    bash_slot = env.information.hand.index('BASH')
    execute_candidate(env, f'play:hand/{bash_slot}:enemy')
    assert env.information.vulnerable == 2
    old_hp = env.information.enemy_hp
    strike_slot = env.information.hand.index('STRIKE_IRONCLAD')
    execute_candidate(env, f'play:hand/{strike_slot}:enemy')
    assert old_hp - env.information.enemy_hp == 9
    env.step(0)
    assert env.information.vulnerable == 1
    assert env.information.shrink == -1
    with pytest.raises(ValueError):
        encode_entities(replace(env.information, reward_version='unknown'), diagnostic_dir=tmp_path)
    assert len(list(tmp_path.glob('*.json'))) == 1


def test_checkpoint_and_legacy_isolation(tmp_path):
    model = create_transformer()
    obs = mixed()[0]
    path = tmp_path / 'transformer.pt'
    save_transformer_checkpoint(path, model)
    restored, _ = load_transformer_checkpoint(path)
    assert restored.predict(obs) == model.predict(obs)
    with pytest.raises(ValueError):
        load_transformer_checkpoint(path, 'S')
    with pytest.raises(ValueError):
        load_checkpoint(path, 'observable')
    legacy = tmp_path / 'mlp.pt'
    save_checkpoint(legacy, PolicyValueNetwork('observable'), 'test', {}, {})
    load_checkpoint(legacy, 'observable')
    with pytest.raises(ValueError):
        load_transformer_checkpoint(legacy)
    payload = torch.load(path, weights_only=True)
    payload['schema']['search'] = 'silently-enabled'
    torch.save(payload, path)
    with pytest.raises(ValueError):
        load_transformer_checkpoint(path)


def test_five_tiers_shapes_and_parameter_counts():
    batch = batch_entities(mixed())
    meta = {k: v.to('meta') if isinstance(v, torch.Tensor) else v for k, v in batch.items()}
    for tier in TIERS:
        with torch.device('meta'):
            model = create_transformer(tier)
        logits, value = model(meta)
        assert logits.shape == batch['legal_mask'].shape
        assert value.shape == (2,)
        assert sum(p.numel() for p in model.parameters()) > 12 * model.config.layers * model.config.d_model**2
