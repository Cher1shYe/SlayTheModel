"""Small real-extension contract tests. Never launch the game or a policy worker."""
from pathlib import Path
import importlib.util
import numpy as np
import pytest
from agent import armg
from agent.common import sim

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('native_armg_bridge', ROOT/'scripts/armg_live_worker.py')
worker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(worker)


def decision():
    return {'build': {'game_version':'v0.111.0',
        'assembly_sha256':'9cb4f1ad8c9f284aa8fec3122ffd6d780bbf543d875c817abdd12ff63fbf12b4'},
        'observation': {'surface':'card_reward','total_floor':2,'act_index':0,'act_floor':2,
        'players':[{'character_id':'CHARACTER.IRONCLAD','current_hp':70,'max_hp':80,
        'gold':100,'max_potion_count':3,'potions':[],
        'relics':[{'model_id':'RELIC.BURNING_BLOOD'}],
        'deck':[{'deck_index':0,'model_id':'CARD.STRIKE_IRONCLAD','upgrade_level':0,
        'guilty_combats_seen':0,'current_energy_cost':1,'enchantment_amount':2,
        'enchantment_disabled':False,'enchantment_id':'ENCHANTMENT.SWIFT'}]}],
        'map_points':[], 'arm_g_native_context':{
        'schema_version':1,'act_ids':['ACT.OVERGROWTH','ACT.HIVE','ACT.GLORY'],
        'golden_path_act':-1,'unknown_map_points_visited':3,'number_of_runs':5,
        'apply_discovery_order':True,'neow_unlocked':True,'orobas_unlocked':False,
        'darv_unlocked':False,'underdocks_unlocked':True,'underdocks_discovered':False,
        'aeonglass_seen':False,'seen_encounter_ids':['ENCOUNTER.SLIMES_NORMAL'],
        'boss_encounter_id':'ENCOUNTER.THE_KIN_BOSS','second_boss_encounter_id':None,
        'paels_tooth_stored_count':0}},
        'legal_actions':[{'action_id':'card','kind':'choose_card','target_id':'CARD.BASH','target_upgrade_level':1},
        {'action_id':'skip','kind':'skip'}]}


def test_native_new_fields_encode_at_real_schema_boundaries():
    enc = worker.Encoder(ROOT,sim,armg)
    obs, rows = enc.encode(decision())
    assert obs.shape == (armg.ARMG_OBS_DIM,)
    assert rows.shape == (2,armg.ARMG_ACTION_DIM)
    deck_start = 38+9+sim.CARD_COUNT
    np.testing.assert_allclose(obs[deck_start+2:deck_start+6], [0,3/5,2/10,0])
    assert obs[int(sim.PUB_RUN_BOSS_OFFSET)+enc.encounter_ids['THE_KIN_BOSS']] == 1
    ext = obs[-int(sim.PUB_RUN_EXTENSION):]
    np.testing.assert_array_equal(ext[:16], [1,0,0,0, 0,1,0,0, 0,0,1,0, 1,0,0,0])
    assert ext[16] == pytest.approx(3/30)
    assert ext[18] == pytest.approx(5/100)


@pytest.mark.parametrize('mutation,reason',[
    (lambda d: d['observation'].pop('arm_g_native_context'), 'native ArmG context'),
    (lambda d: d['observation']['arm_g_native_context'].update(paels_tooth_stored_count=1), 'Pael stored'),
    (lambda d: d['observation']['players'][0]['deck'][0].pop('enchantment_amount'), 'exact cost'),
    (lambda d: d['legal_actions'][0].update(is_selection_template=True), 'selection template'),
    (lambda d: d['legal_actions'].append({'action_id':'alternative','kind':'choose_reward_alternative'}), 'alternative'),
    (lambda d: d['legal_actions'][1].update(action_id='card'), 'duplicate'),
    (lambda d: d['observation'].update(surface='card_grid_choice'), 'unsupported surface'),
    (lambda d: d['build'].update(assembly_sha256='0'*64), 'assembly'),
])
def test_unknown_states_and_candidates_reject_instead_of_neutral_features(mutation,reason):
    d=decision(); mutation(d)
    with pytest.raises(worker.Unsupported,match=reason):
        worker.Encoder(ROOT,sim,armg).encode(d)
