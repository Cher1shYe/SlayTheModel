from pathlib import Path
import pytest
from deployment import evaluate_armg_floor_root_puct as e


def test_root_puct_uses_floor_budget_elite_and_returns_only_one_action(monkeypatch):
    class Battle:
        def legal_actions(self): return [(1, 2, 3), (4, 5, 6)]
    calls=[]
    def fake(battle, seed, combat, simulations, epsilon, is_boss):
        calls.append((seed, combat, simulations, is_boss))
        return [(4,5,6)], simulations
    monkeypatch.setattr(e.root, '_fixed_plan', fake)
    ctrl=e.FloorRootPuctController(100)
    budget=ctrl.budget_for_context(8,True,False)
    assert budget==4400
    assert ctrl.plan(Battle(),10,'mcts-oracle',budget,.05,False)==([(4,5,6)],4400)
    assert calls==[(100,'mcts-oracle',4400,False)]
    assert ctrl.elite_decisions==1 and ctrl.simulations==4400
    ctrl.budget_for_context(8,False,True)
    with pytest.raises(ValueError): ctrl.plan(Battle(),10,'mcts-oracle',4400,.05,True)
    assert ctrl.plan(Battle(),10,'mcts-oracle',5400,.05,True)[1]==5400
    assert calls[-1][0]==8019


def test_forced_action_has_no_search(monkeypatch):
    class Battle:
        def legal_actions(self): return [(1,2,3)]
    ctrl=e.FloorRootPuctController(123)
    budget=ctrl.budget_for_context(1,False,False)
    assert ctrl.plan(Battle(),5,'mcts-oracle',budget,.05,False)==([(1,2,3)],0)
    assert ctrl.decisions==ctrl.simulations==0


def test_progress_and_paired_summary():
    rows=[{'seed':1,'arm':'start','status':'terminated','floor':10,'won':False,'hp':0},
          {'seed':1,'arm':'r640','status':'terminated','floor':15,'won':True,'hp':5},
          {'seed':1,'arm':'r960','status':'terminated','floor':9,'won':False,'hp':0}]
    arms,pairs=e.summaries(rows,bootstrap=True)
    assert pairs['r640_vs_start']['mean_floor_difference']==5
    assert pairs['r960_vs_start']['mean_floor_difference']==-1
    text=e.markdown('running',arms,pairs,60,300,[],8)
    assert '3 / 300' in text and '15.00' in text and '+5.00' in text


def test_real_configuration_preflight_without_pool(tmp_path,monkeypatch):
    class Halt(Exception): pass
    def no_pool(*args,**kwargs): raise Halt()
    monkeypatch.setattr(e,'ProcessPoolExecutor',no_pool)
    out=tmp_path/'run'
    with pytest.raises(Halt):
        e.run('runs/armg_ironclad_skip_site_rl_20261030/train/latest.pt',
              'runs/armg_floor2000_elite1000_boss2000_rl_20261030/best.pt',
              'runs/armg_floor2000_elite1000_boss2000_rl_20261030/latest.pt',
              'runs/combat_dagger_a0_20261029/round5.pt',out,count=1,workers=1)
    import json
    config=json.loads((out/'config.json').read_text(encoding='utf-8'))
    assert config['puct_depth']==1 and config['seed_start']==41020000
    assert len(config['checkpoints'])==3 and config['combat_sha256']
    assert (out/'progress.md').exists()
