"""Training readiness regression tests; tiny updates are fixtures, not an experiment."""
import json
from copy import deepcopy
from pathlib import Path

import numpy as np
import pytest
import torch

from sts2_env.az import all_runner as runner
from sts2_env.az.config import EpisodeLimits
from sts2_env.az.enemy_lifecycle import EnemyLedger, EnemyLife, ALL_CONTRACT_VERSION
from sts2_env.az.summon import ledger_rows, ledger_from_rows, primary_summary

CONFIG = 'configs/az_all_xs_v1/config.json'
PROTOCOL = 'configs/az_all_xs_v1/protocol.json'


def test_resolved_defaults_and_seed():
    config = runner.load_frozen_config(CONFIG)
    s = runner.effective_settings(config)
    assert (s['iterations'], s['episodes'], s['updates'], s['batch_size'], s['budget']) == (8, 48, 16, 64, 8)
    assert (s['value_weight'], s['max_turns'], s['eval_max_turns'], s['max_decisions']) == (.1, 40, 40, 400)
    a, b = runner.fresh_model(config, 1), runner.fresh_model(config, 2)
    assert any(not torch.equal(x, y) for x, y in zip(a.parameters(), b.parameters()))
    assert runner.effective_settings(config, budget=32)['budget'] == 32
    with pytest.raises(ValueError):
        runner.effective_settings(config, budget=0)


def test_weight_changes_value_gradient():
    from sts2_env.az.network import policy_value_loss
    class Model(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.value = torch.nn.Parameter(torch.tensor([0.2]))
            self.logits = torch.nn.Parameter(torch.tensor([[0.2, 0.3]]))
        def forward(self, batch):
            return self.logits, self.value
    m = Model()
    batch = {'legal_mask': torch.tensor([[True, True]])}
    args = (m, batch, torch.tensor([[1., 0.]]), torch.tensor([1.]))
    loss, metrics = policy_value_loss(*args, value_weight=.1)
    assert loss.item() == pytest.approx(metrics['policy_loss'] + .1 * metrics['value_loss'])
    loss.backward(); small = m.value.grad.clone(); m.zero_grad()
    policy_value_loss(*args, value_weight=1.)[0].backward()
    assert torch.allclose(small * 10, m.value.grad)


def test_spawn_budget_and_native_terminal_removal():
    initial = EnemyLife(0, 'LEADER', True, 100, 100, 50)
    summon = EnemyLife(1, 'SUMMON', True, 80, 80, 80, spawned=True)
    ledger = EnemyLedger((initial, summon), ALL_CONTRACT_VERSION)
    assert ledger.damage_progress == .5
    assert primary_summary(ledger) == (100, 50, 100)
    assert ledger_from_rows(ledger_rows(ledger)) == ledger
    defeated = ledger.update(0, 0, 'defeated')
    assert defeated.terminal_reward('win', 60, 80) > .8
    assert defeated.terminal_reward('time_limit', 60, 80) <= .2
    assert ledger.update(1, 0, 'defeated').damage_progress == .5
    escaped = ledger.update(0, 0, 'removed')
    assert escaped.damage_progress == 0
    assert escaped.terminal_reward('win', 60, 80) > .8
    with pytest.raises(ValueError):
        EnemyLedger((initial, summon)).validate()  # old v5 stays strict


def test_promotion_requires_paired_confidence_and_full_coverage():
    base = [dict(scenario_id=str(i), reward=0.) for i in range(10)]
    good = [dict(scenario_id=str(i), reward=.2) for i in range(10)]
    noisy = [dict(scenario_id=str(i), reward=1. if i < 6 else -1.) for i in range(10)]
    assert runner.promotion(base, good, 10)[0]
    assert not runner.promotion(base, noisy, 10)[0]
    assert not runner.promotion(base, good[:-1], 10)[0]
    assert not runner.promotion(base, base, 10)[0]


def mock_pipeline(monkeypatch):
    calls = {'collect': [], 'values': iter([0., .5, -.5, .7])}
    def collect(model, recipes, **kw):
        calls['collect'].append(kw['iteration'])
        return [dict(episode_id=str(kw['iteration']) * 64, rows=[dict(policy_target={'end': 1.}, forced_action=True)],
                     outcome={'termination_reason': 'win'})]
    def evaluate(model, recipes, **kw):
        value = next(calls['values'])
        rows = [dict(scenario_id=r.scenario_id, encounter_id=r.encounter_id, reward=value,
                     termination_reason='win') for r in recipes]
        return dict(episodes=len(rows), mean_utility=value, win_rate=1., contract_rejections=0), rows
    class Replay:
        size = 1
        def __init__(self, *a, **kw): pass
        def commit(self, episode): pass
    monkeypatch.setattr(runner, 'collect', collect)
    monkeypatch.setattr(runner, 'evaluate_recipes', evaluate)
    monkeypatch.setattr(runner, 'EntityReplayBuffer', Replay)
    def update(model, replay, **kw):
        kw['on_update'](model, dict(history=[{'loss': .2}]))
        return model, [{'loss': .2}]
    monkeypatch.setattr(runner, 'update', update)
    return calls


def test_crash_after_round_commit_recovers_champion_without_report(tmp_path, monkeypatch):
    calls = mock_pipeline(monkeypatch)
    atomic = runner.atomic_json
    crashed = False
    def interrupt(path, value):
        nonlocal crashed
        if Path(path).name == 'report.json' and not crashed:
            crashed = True
            raise RuntimeError('power loss before report')
        atomic(path, value)
    monkeypatch.setattr(runner, 'atomic_json', interrupt)
    kw = dict(iterations=2, episodes=1, updates=1, budget=1, batch_size=2)
    with pytest.raises(RuntimeError, match='power loss'):
        runner.run(CONFIG, PROTOCOL, tmp_path, **kw)
    assert not (tmp_path / 'report.json').exists()
    report = runner.run(CONFIG, PROTOCOL, tmp_path, resume=True, **kw)
    assert calls['collect'] == [0, 1]
    assert [r['promoted'] for r in report['history']] == [True, False]
    assert report['champion_checkpoint'] == 'iteration-000.pt'
    assert report['final_validation']['mean_utility'] == .5
    assert len(json.loads((tmp_path / 'state.json').read_text())['baseline_rows']) == 64
    with pytest.raises(ValueError, match='configuration'):
        runner.run(CONFIG, PROTOCOL, tmp_path, resume=True, **dict(kw, budget=2))
    with pytest.raises(ValueError, match='not empty'):
        runner.run(CONFIG, PROTOCOL, tmp_path, **kw)


def test_update_checkpoint_resumes_exact_optimizer_and_rng(tmp_path):
    config = runner.load_frozen_config(CONFIG)
    model = runner.fresh_model(config, 7)
    episodes = runner.collect(model, runner.training_recipes(0, 1), iteration=0, budget=1,
        error_dir=tmp_path / 'errors', limits=EpisodeLimits(max_turns=1, max_decisions=3), version='fixture', seed=7)
    replay = runner.EntityReplayBuffer(tmp_path / 'replay', capacity=100,
        content_version=config['content'], reward_version=config['reward'])
    replay.commit(episodes[0])
    settings = dict(learning_rate=3e-4, batch_size=2, updates=2, seed=11, value_weight=.1)
    champion_before = {k: v.clone() for k, v in model.state_dict().items()}
    full, full_losses = runner.update(model, replay, **settings)
    assert all(torch.equal(v, champion_before[k]) for k, v in model.state_dict().items())
    assert any(not torch.equal(v, champion_before[k]) for k, v in full.state_dict().items())
    def interrupt(model, state):
        runner.save_transformer_checkpoint(tmp_path / 'update.pt', model, training_state=state)
        raise RuntimeError('update interruption')
    with pytest.raises(RuntimeError):
        runner.update(model, replay, on_update=interrupt, **settings)
    partial, payload = runner.load_transformer_checkpoint(tmp_path / 'update.pt', 'XS', config['content'], config['reward'])
    resumed, losses = runner.update(partial, replay, resume_state=payload['training_state'], **settings)
    assert losses == full_losses
    assert all(torch.equal(x, y) for x, y in zip(full.parameters(), resumed.parameters()))

def test_hex_restores_current_piles_and_preserves_upgrade_keyword(tmp_path):
    from collections import Counter
    from sts2_env.az.adapter import ObservableCombatAdapter
    from sts2_env.az.information import BeliefSampler
    from sts2_env.az.content_expansion import CODEC
    from sts2_env.az.card_memory import inventory
    from sts2_env.core.enums import PowerId
    protocol = json.loads(Path(PROTOCOL).read_text())
    recipe = runner.protocol_recipes(protocol, 'validation')[29]
    env = ObservableCombatAdapter(recipe, reward_version='risk-terminal-v7', error_dir=tmp_path)
    env.step(0)
    assert PowerId.HEX in env.world.player.powers
    particle = BeliefSampler().sample(env.information, np.random.default_rng(42))
    world = particle.world
    power = world.player.powers[PowerId.HEX]
    cards = [c for pile in world.current_player_state.all_piles for c in pile]
    assert set(map(id, power._hexed_cards)) == {id(c) for c in cards if c.affliction == 'hexed'}
    assert power.applier.monster_id == 'SPECTRAL_KNIGHT'
    card = next(c for c in cards if not c.upgraded and c.affliction == 'hexed')
    world.upgrade_card(card)
    assert card.is_ethereal
    CODEC.capture(card)
    world._remove_power(world.player, PowerId.HEX)
    assert all(c.affliction != 'hexed' for c in cards)
    observed = Counter(CODEC.capture(c) for c in cards)
    assert observed == inventory(env.information.known_deck, world.visible_card_events, CODEC)


def test_hex_cleanup_does_not_journal_removed_power(tmp_path):
    from sts2_env.az.adapter import ObservableCombatAdapter
    from sts2_env.core.enums import PowerId
    protocol = json.loads(Path(PROTOCOL).read_text())
    env = ObservableCombatAdapter(runner.protocol_recipes(protocol, 'validation')[29],
                                 reward_version='risk-terminal-v7', error_dir=tmp_path)
    env.step(0)
    world = env.world
    card = next(c for c in world.hand if c.affliction == 'hexed')
    world.hand.remove(card)  # no longer in combat, as after a resolved power
    before = len(world.visible_card_events)
    card.clear_affliction('hexed')
    assert len(world.visible_card_events) == before

def test_extended_birth_slots_remain_targetable_in_world_and_particle(tmp_path):
    from dataclasses import replace
    from sts2_env.az.adapter import ObservableCombatAdapter
    from sts2_env.az.all_content import observe_all
    from sts2_env.az.information import BeliefSampler
    from sts2_env.az.action_candidates import action_candidates
    from sts2_env.az.scenarios import DeckEntry
    from sts2_env.az.actions import ALL_TARGET_BASE, decode_card_action
    from sts2_env.az.content import ALL_CONTENT
    from sts2_env.monsters.act1_weak import create_shrinker_beetle
    from sts2_env.core.rng import Rng
    recipe = replace(runner.training_recipes(0, 1)[0], encounter_id='setup_shrinker_beetle_weak',
        deck=(DeckEntry('STRIKE_IRONCLAD', False, 4), DeckEntry('BASH', False, 4)))
    env = ObservableCombatAdapter(recipe, reward_version='risk-terminal-v7', error_dir=tmp_path)
    for i in range(5):
        enemy, ai = create_shrinker_beetle(Rng(i))
        env.world.add_enemy(enemy, ai)
    env._information = observe_all(env.world, env.information.history, env.limits, 80,
        known_deck=env.information.known_deck, enemy_initial_hp=env.public_initial[1],
        encounter=recipe.encounter_id)
    actions, mapping = action_candidates(env.information)
    chosen = next(a for a in actions if a.target_refs == ('enemy/5',))
    action = mapping[chosen.action_key]
    assert action >= ALL_TARGET_BASE and decode_card_action(action, ALL_CONTENT)[1] == 5
    particle = BeliefSampler().sample(env.information, np.random.default_rng(5))
    old_hp = env.world.enemies[5].current_hp
    particle.step(action)
    env.step(action)
    assert env.world.enemies[5].current_hp < old_hp
    assert particle.info == env.information


def test_native_heal_intent_and_ringing_roundtrip():
    from sts2_env.az.monster_registry import move_from_intents
    from sts2_env.az.content_expansion import CODEC
    assert move_from_intents('DECIMILLIPEDE_SEGMENT', 'DEAD_MOVE', (('HEAL', 0, 1),)) == 'REATTACH_MOVE'
    card = CODEC._make('STRIKE_IRONCLAD')
    card.afflict('ringing')
    face = CODEC.capture(card)
    assert CODEC.capture(CODEC.restore(face)) == face

def test_runner_recovers_mid_update_without_recollecting(tmp_path, monkeypatch):
    def evaluate(model, recipes, **kw):
        value = 0. if 'baseline' in kw['version'] else .2
        rows = [dict(scenario_id=r.scenario_id, encounter_id=r.encounter_id,
                     reward=value, termination_reason='win') for r in recipes]
        return dict(episodes=len(rows), mean_utility=value, win_rate=1., contract_rejections=0), rows
    monkeypatch.setattr(runner, 'evaluate_recipes', evaluate)
    settings = dict(iterations=1, episodes=1, updates=2, budget=1, batch_size=2,
                    max_turns=1, max_decisions=3, seed=19)
    full = runner.run(CONFIG, PROTOCOL, tmp_path / 'full', **settings)
    atomic = runner.atomic_json
    interrupted = False
    def crash(path, value):
        nonlocal interrupted
        atomic(path, value)
        if (Path(path).name == 'state.json' and value.get('pending')
                and value['pending'].get('update_checkpoint') and not interrupted):
            interrupted = True
            raise RuntimeError('crash after durable update')
    monkeypatch.setattr(runner, 'atomic_json', crash)
    with pytest.raises(RuntimeError, match='durable update'):
        runner.run(CONFIG, PROTOCOL, tmp_path / 'resumed', **settings)
    monkeypatch.setattr(runner, 'collect', lambda *a, **k: pytest.fail('cached collection was repeated'))
    restored = runner.run(CONFIG, PROTOCOL, tmp_path / 'resumed', resume=True, **settings)
    assert full['history'][0]['updates'] == restored['history'][0]['updates']
    assert full['history'][0]['episodes'] == restored['history'][0]['episodes']
    config = runner.load_frozen_config(CONFIG)
    a, _ = runner.load_transformer_checkpoint(tmp_path / 'full' / full['champion_checkpoint'],
        'XS', config['content'], config['reward'])
    b, _ = runner.load_transformer_checkpoint(tmp_path / 'resumed' / restored['champion_checkpoint'],
        'XS', config['content'], config['reward'])
    assert all(torch.equal(x, y) for x, y in zip(a.parameters(), b.parameters()))


def test_performed_intent_journal_survives_json_roundtrip(tmp_path):
    from sts2_env.az.adapter import ObservableCombatAdapter
    from sts2_env.az.entity_transition import public_snapshot, public_from_dict
    env = ObservableCombatAdapter(runner.training_recipes(0, 1)[0],
                                  reward_version='risk-terminal-v7', error_dir=tmp_path)
    env.step(0)
    assert any(e[0] == 'enemy_intent_action' for e in env.information.history.public_events)
    assert public_from_dict(json.loads(json.dumps(public_snapshot(env.information)))) == env.information


def test_full_battle_mcts_collection_replay_reload(tmp_path):
    config = runner.load_frozen_config(CONFIG)
    model = runner.fresh_model(config, 0)
    episode = runner.collect(model, runner.training_recipes(0, 1), iteration=0, budget=8,
        error_dir=tmp_path / 'errors', limits=EpisodeLimits(max_turns=40, max_decisions=400),
        version='full-battle-contract-fixture', seed=0)[0]
    assert any(e[0] == 'enemy_intent_action' for e in episode['final_public']['history']['public_events'])
    replay = runner.EntityReplayBuffer(tmp_path / 'replay', content_version=config['content'], reward_version=config['reward'])
    replay.commit(episode)
    loaded = runner.EntityReplayBuffer(tmp_path / 'replay', content_version=config['content'], reward_version=config['reward'])
    assert loaded.size == replay.size == len(episode['rows'])
    assert loaded.read_episode(episode['episode_id']) == json.loads(json.dumps(episode))
