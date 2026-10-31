from concurrent.futures import Future
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
import torch

from deployment import train_armg_a10_ppo as trainer
from agent.armg import ARMG_OBS_DIM, ARMG_ACTION_DIM
from agent.armg_ppo import (ArmGActorCritic, TrajectoryRecorder, gae, prepare,
                            clipped_loss, update)
from agent.common import SCREEN, RACT


class NoPrior:
    def target(self, record): return None


@pytest.mark.parametrize('elo_bonus', [0.0, .3])
@pytest.mark.parametrize('reject,upgrades,removes', [(None, 1, 1), ('upgrade', 0, 0), ('remove', 1, 0)])
def test_action_rewards_only_after_success_and_enter_ppo_returns(monkeypatch, reject, upgrades, removes, elo_bonus):
    base = trainer.base
    class Run:
        screen = SCREEN.REST
        act = 0
        floor = 5
        hp = 10
        won = False
        deck = [(1, False, 123, 1)]
        def step(self, kind, index):
            if kind == int(RACT.REST_UPGRADE):
                if reject == 'upgrade': return False
                self.screen = SCREEN.SHOP
            else:
                assert kind == int(RACT.REMOVE_CARD)
                if reject == 'remove': return False
                self.screen = SCREEN.RUN_OVER
            return True
    rc = Run()
    def candidates(rc):
        kind = RACT.REST_UPGRADE if rc.screen == SCREEN.REST else RACT.REMOVE_CARD
        return np.zeros(ARMG_OBS_DIM, np.float32), [(int(kind), 0)], np.zeros((1, ARMG_ACTION_DIM), np.float32)
    monkeypatch.setattr(base, 'new_run', lambda *args: rc)
    monkeypatch.setattr(base, 'build_candidates', candidates)
    monkeypatch.setattr(base, 'completed_run_status', lambda rc: 'terminated')
    model = ArmGActorCritic()
    ep = base.collect_episode(1, model, track_boss_wins=True, track_elite_wins=True,
                              trajectory=TrajectoryRecorder(model), campfire_upgrade_reward=.05,
                              shop_remove_reward=.02, terminal_deck_elo=lambda deck: dict(deck_elo_bonus=elo_bonus, deck_mean_elo=elo_bonus*5000, deck_elo_missing_cards=0))
    assert ep['campfire_upgrades'] == upgrades and ep['shop_removals'] == removes
    if reject:
        assert ep['status'] == 'error' and not ep['ppo_records']
    else:
        rewards = [r['reward'] for r in ep['ppo_records']]
        assert rewards == pytest.approx([.30, .02 + elo_bonus])
        assert trainer.episode_reward(ep, 'floor20-boss-elite01-actions-elo') == pytest.approx(sum(rewards))
        summary = trainer.reward_summary([ep], 'floor20-boss-elite01-actions')
        assert summary['mean_upgrade_bonus'] == .05 and summary['mean_removal_bonus'] == .02
        assert summary['campfire_upgrades'] == 1 and summary['shop_removals'] == 1


def make_episode(model, seed=1, forced=False):
    rng = np.random.default_rng(seed)
    recorder = TrajectoryRecorder(model)
    for j, n in enumerate([2, 5, 1, 3]):
        obs = rng.normal(0, .1, ARMG_OBS_DIM).astype(np.float32)
        features = rng.normal(0, .1, (n, ARMG_ACTION_DIM)).astype(np.float32)
        recorder.record(obs, features, j % n, forced, .1 * j)
    return {'status': 'terminated', 'ppo_records': recorder.finish(1.7)}


def test_transition_rewards_and_forced_actions():
    model = ArmGActorCritic()
    ep = make_episode(model)
    rows = ep['ppo_records']
    assert [r['reward'] for r in rows] == pytest.approx([.1, .1, .1, 1.4])
    assert sum(r['reward'] for r in rows) == pytest.approx(1.7)
    assert [r['actor_valid'] for r in rows] == [True, True, False, True]
    assert all(not r['actor_valid'] for r in make_episode(model, forced=True)['ppo_records'])
    for r in rows:
        assert np.exp(r['old_logps']).sum() == pytest.approx(1)
        assert r['old_logp'] == r['old_logps'][r['choice']]


def test_gae_terminal_and_episode_boundaries():
    adv, returns = gae([.2, .3, 1], [.1, .4, .8], gamma=1, lam=1)
    assert returns == pytest.approx([1.5, 1.3, 1.0])
    assert adv == pytest.approx([1.4, .9, .2])
    adv0, returns0 = gae([.2, .3, 1], [.1, .4, .8], gamma=1, lam=0)
    assert adv0 == pytest.approx([.5, .7, .2])
    m = ArmGActorCritic()
    a, b = make_episode(m, 1), make_episode(m, 2)
    together = prepare([a, b], lam=1)
    assert [r['target'] for r in together[:4]] == pytest.approx([1.7, 1.6, 1.5, 1.4])
    assert [r['target'] for r in together[4:]] == pytest.approx([1.7, 1.6, 1.5, 1.4])
    with pytest.raises(ValueError, match='complete'):
        prepare([dict(a, status='truncated')])


def test_clip_both_advantage_signs_and_gradients():
    log_ratio = torch.log(torch.tensor([1.5, .5, 1.5, .5])).requires_grad_()
    loss = clipped_loss(log_ratio, torch.tensor([1., 1., -1., -1.]), .2)
    assert loss.detach().numpy() == pytest.approx([-1.2, -.5, 1.5, .8])
    loss.sum().backward()
    assert log_ratio.grad.numpy() == pytest.approx([0, -.5, 1.5, 0])


def test_ppo_updates_actor_critic_and_rejects_stale_rollout():
    torch.set_num_threads(1)
    torch.manual_seed(3)
    model = ArmGActorCritic()
    episodes = [make_episode(model, i) for i in range(3)]
    before = {k: v.clone() for k, v in model.state_dict().items()}
    optimizer = torch.optim.Adam(model.parameters(), lr=1e-3)
    stats = update(model, optimizer, episodes, NoPrior(), 0, minibatch_size=4, epochs=2)
    assert stats['updates'] > 0 and stats['actor_decisions'] == 9
    assert stats['exact_kl'] >= 0 and stats['prior_eligible_decisions'] == 0
    assert any(not torch.equal(before[k], v) for k, v in model.state_dict().items() if k.startswith('actor.'))
    assert any(not torch.equal(before[k], v) for k, v in model.state_dict().items() if k.startswith('critic.'))
    assert all(torch.isfinite(p).all() for p in model.parameters())
    with pytest.raises(RuntimeError, match='stale'):
        update(model, optimizer, episodes, NoPrior(), 0)


def test_forced_only_episode_cannot_update_actor():
    torch.set_num_threads(1)
    model = ArmGActorCritic()
    before = [p.clone() for p in model.actor.parameters()]
    stats = update(model, torch.optim.Adam(model.parameters(), lr=.001),
                   [make_episode(model, forced=True)], NoPrior(), .2, epochs=1)
    assert stats['actor_decisions'] == 0
    assert all(torch.equal(a, b) for a, b in zip(before, model.actor.parameters()))


def test_kl_early_stop_with_large_update():
    torch.set_num_threads(1)
    model = ArmGActorCritic()
    stats = update(model, torch.optim.Adam(model.parameters(), lr=.1),
                   [make_episode(model, i) for i in range(4)], NoPrior(), 0,
                   epochs=4, minibatch_size=4, target_kl=1e-5)
    assert stats['kl_early_stop'] and stats['updates'] < 16


def test_prior_kl_and_padding_are_finite():
    class Prior:
        def target(self, record):
            if len(record[1]) < 2: return None
            return {'eligible': True, 'indices': [0, 1],
                    'target': np.array([.2, .8], dtype=np.float32)}
    torch.set_num_threads(1)
    model = ArmGActorCritic()
    stats = update(model, torch.optim.Adam(model.parameters(), lr=.0003),
                   [make_episode(model)], Prior(), .2, epochs=1, minibatch_size=4)
    assert stats['prior_eligible_decisions'] == 3
    assert stats['prior_kl'] >= 0 and stats['prior_strength'] == .2


@pytest.mark.parametrize('fixed_game_seed', [None, 10600000])
def test_full_trainer_resume_matches_uninterrupted(tmp_path, monkeypatch, fixed_game_seed):
    if not trainer.extension_loader._extension:
        pytest.skip('requires configured isolated simulator for preflight')
    class Pool:
        def __init__(self, *args, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def submit(self, fn, task):
            f = Future()
            try: f.set_result(fn(task))
            except Exception as exc: f.set_exception(exc)
            return f
    def fake_play(task):
        seed, sample, search, version, weights, deterministic, *_ = task
        if fixed_game_seed is not None:
            assert seed == fixed_game_seed
        model = ArmGActorCritic()
        model.load_state_dict(torch.load(weights, weights_only=True))
        ep = make_episode(model, seed)
        # A deliberately synthetic rollout used only to test training/resume.
        ep.update(seed=seed, won=False, floor=10, hp=0, steps=4, records=[],
                  boss_wins=[], elite_wins=[], error=None, cycle_recoveries=0,
                  mcts_searches=0, mcts_simulations=0)
        for key in ('normal_decisions', 'boss_decisions', 'normal_simulations',
                    'boss_simulations', 'elite_decisions', 'elite_simulations'):
            ep[key] = 0
        if deterministic: ep['ppo_records'] = []
        return ep
    monkeypatch.setattr(trainer, 'ProcessPoolExecutor', Pool)
    monkeypatch.setattr(trainer, '_play', fake_play)
    monkeypatch.setattr(trainer, 'FloorCardSkipPrior', lambda _: NoPrior())
    kwargs = dict(data_dir='runs/armg_spire_wr50_prior_20261030/data', games=4,
                  batch_size=2, workers=1, eval_every=4, eval_runs=1,
                  ppo_epochs=2, minibatch_size=4, fixed_game_seed=fixed_game_seed)
    trainer.train(out_dir=tmp_path/'full', **kwargs)
    save = trainer.base._save
    class Interrupted(Exception): pass
    def interrupt(path, model, optimizer, progress, settings):
        save(path, model, optimizer, progress, settings)
        if Path(path).name == 'latest.pt' and progress['games'] == 2:
            raise Interrupted()
    monkeypatch.setattr(trainer.base, '_save', interrupt)
    with pytest.raises(Interrupted):
        trainer.train(out_dir=tmp_path/'resumed', **kwargs)
    monkeypatch.setattr(trainer.base, '_save', save)
    trainer.train(out_dir=tmp_path/'resumed', resume=tmp_path/'resumed'/'latest.pt', **kwargs)
    a = torch.load(tmp_path/'full'/'latest.pt', weights_only=False)
    b = torch.load(tmp_path/'resumed'/'latest.pt', weights_only=False)
    assert a['settings']['algorithm'] == 'ppo'
    assert all(torch.equal(a['state_dict'][k], v) for k, v in b['state_dict'].items())
    assert torch.equal(a['torch_rng_state'], b['torch_rng_state'])
    for key, state in a['optimizer_state_dict']['state'].items():
        for name, value in state.items():
            assert torch.equal(value, b['optimizer_state_dict']['state'][key][name])


def test_deck_elo_duplicate_upgraded_missing_and_empty(monkeypatch):
    from agent.armg_deck_elo import DeckEloReward
    from agent.common import sim
    reward = DeckEloReward.__new__(DeckEloReward)
    reward.excluded_titles = {'curse', 'corruption', 'token', 'event', 'status', 'multiplayer'}
    reward.site = SimpleNamespace(card_row=lambda i: {"elo": 2000.0} if i == 4 else None)
    monkeypatch.setattr(sim, 'card_name', lambda i: {1:'Strike', 2:'Defend', 3:'Bash', 4:'Other', 5:'Unknown',6:'Curse',7:'Corruption',8:'Token',9:'Event',10:'Status',11:'Multiplayer'}[i])
    stats = reward([(1,False), (2,True), (3,True), (4,False), (4,True), (5,False)])
    assert stats['deck_mean_elo'] == pytest.approx((4*1150+2*2000)/6)
    assert stats['deck_elo_missing_cards'] == 1
    assert stats['deck_elo_bonus'] == stats['deck_mean_elo']/5000
    assert reward([])['deck_elo_bonus'] == 0
    excluded = [(i,False) for i in range(6,12)]
    assert reward(excluded)['deck_elo_bonus'] == 0
    mixed = reward([(4,False)] + excluded)
    assert mixed['deck_mean_elo'] == 2000
    assert mixed['deck_elo_counted_cards'] == 1
    assert mixed['deck_elo_excluded_cards'] == 6
    assert mixed['final_deck_size'] == 7


def test_deck_elo_excludes_break_and_grapple():
    from agent.armg_deck_elo import DeckEloReward
    from agent.common import sim, CARD_COUNT
    reward = DeckEloReward('runs/armg_a10_ppo_floor20_elite01_20261031/data_snapshot')
    ids = {sim.card_name(i).lower(): i for i in range(CARD_COUNT)}
    stats = reward([(ids[name], False) for name in ('bash', 'break', 'grapple', 'corruption')])
    assert stats['deck_mean_elo'] == 1150
    assert stats['deck_elo_counted_cards'] == 1
    assert stats['deck_elo_excluded_cards'] == 3
    assert stats['deck_elo_missing_cards'] == 0
