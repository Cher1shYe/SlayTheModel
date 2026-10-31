"""Verify root PUCT ArmG training semantics without running training."""
import json
from pathlib import Path
import numpy as np
import pytest
import torch

from deployment import train_armg_puct_prior_rl as trainer


def test_reward_win_override_and_other_floors():
    assert trainer.episode_reward({'floor': 48, 'won': False}) == pytest.approx(.96)
    assert trainer.episode_reward({'floor': 48, 'won': True}) == 1
    assert trainer.episode_reward({'floor': 17, 'won': False}) == pytest.approx(.34)


def test_root_puct_budget_prior_and_final_potion(monkeypatch):
    actions = [(0, 0, 0, 0), (1, 0, 0, 0)]
    monkeypatch.setattr(trainer, 'combat_action_arrays', lambda b: (actions, np.zeros((2, 3), np.float32)))
    monkeypatch.setattr(trainer, 'public_combat_observation', lambda b: np.zeros(4, np.float32))
    class Policy(torch.nn.Module):
        def forward(self, obs, feat): return torch.tensor([[0.0, 2.0]])
    class Battle:
        calls=[]
        def legal_actions(self): return actions
        def mcts_priors(self, *args):
            self.calls.append(args)
            return [actions[1], actions[0]], args[0], True
    battle=Battle()
    ctrl=trainer.FloorRootPuctController(Policy(), 4321, start=3000, increment=500, elite_bonus=0, boss_bonus=0)
    for elite,boss,weight in [(False,False,4), (True,False,4), (False,True,0)]:
        budget=ctrl.budget_for_context(8,elite,boss)
        ctrl.potion_weight = weight
        assert ctrl.plan(battle,0,'mcts-oracle',budget,.05,boss) == ([actions[1]],6500)
        args=battle.calls[-1]
        assert args[0] == 6500 and args[1] == actions
        assert args[2][1] == pytest.approx(0.880797, rel=1e-5)
        assert args[3] == 3.0 and args[5:8] == (False,False,.05) and args[8] == weight
    assert ctrl.decisions == 3 and ctrl.simulations == 19500
    assert ctrl.elite_decisions == 1 and ctrl.boss_decisions == 1


def test_single_legal_action_does_not_search(monkeypatch):
    class Battle:
        def legal_actions(self): return [(0,0,0,0)]
        def mcts_priors(self, *args): raise AssertionError('forced action must not search')
    ctrl=trainer.FloorRootPuctController(None,1,start=3000,increment=500,elite_bonus=0,boss_bonus=0)
    budget=ctrl.budget_for_context(1,False,False)
    assert ctrl.plan(Battle(),0,'mcts-oracle',budget,.05,False)==([(0,0,0,0)],0)
    assert ctrl.decisions == 0


def test_real_checkpoint_preflight_stops_before_worker_creation(tmp_path,monkeypatch):
    source=Path('runs/armg_floor2000_elite1000_boss2000_rl_20261030/latest.pt')
    data=Path('runs/armg_spire_wr50_prior_20261030/data')
    combat=Path('runs/combat_dagger_a0_20261029/round5.pt')
    if not source.exists() or not data.exists() or not combat.exists() or not trainer.extension_loader._extension:
        pytest.skip('real assets unavailable')
    previous=torch.load(source,map_location='cpu',weights_only=False)
    old=previous['settings']['simulator_sha256']
    new=trainer._sha(trainer.extension_loader._extension)
    class PreflightComplete(Exception): pass
    def stop(*args, **kwargs): raise PreflightComplete()
    monkeypatch.setattr(trainer,'ProcessPoolExecutor',stop)
    out=tmp_path/'preflight'
    with pytest.raises(PreflightComplete):
        trainer.train(init_checkpoint=source,out_dir=out,data_dir=data,combat_checkpoint=combat,
                      resume_simulator_old_sha256=old,resume_simulator_new_sha256=new)
    settings=json.loads((out/'config.json').read_text(encoding='utf-8'))
    assert settings['combat']=='puct-root-oracle' and settings['combat_prior_depth']==1
    assert settings['combat_budget_start']==3000 and settings['combat_budget_per_floor']==500
    assert settings['combat_budget_elite_bonus']==settings['combat_budget_boss_bonus']==0
    assert settings['prior_weight']==.05 and settings['target_games']==1024 and settings['workers']==8
    assert settings['reward_formula']=='1.0 if won else floor / 50.0'
    assert settings['training_seed_base']==10330000 and settings['final_boss_potion_weight']==0
    assert settings['combat_prior_sha256']==trainer._sha(combat)
