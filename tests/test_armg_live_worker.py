"""Live ArmG protocol: feature shape, guarded actions and approximate status."""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

import numpy as np
import pytest

ROOT = Path(os.environ.get('ARMG_STS2_ROOT', 'D:/sts2_datacollection/sts2'))
PYD = ROOT / '.scratch/potion-module/sts2_sim.cp312-win_amd64.pyd'
CHECKPOINT = ROOT / 'runs/armg_puct_3000_500_prior005_1024_20261030/latest.pt'
WORKER = Path(__file__).resolve().parents[1] / 'scripts/armg_live_worker.py'


@pytest.fixture(scope='module')
def encoder():
    if not PYD.is_file():
        pytest.skip('matching STS2 simulator not available')
    os.environ['STS2_PRIOR_PYD'] = str(PYD)
    sys.path.insert(0, str(ROOT))
    import deployment.evaluate_battle_root_prior
    from agent import armg
    from agent.common import sim
    spec = importlib.util.spec_from_file_location('armg_live_worker', WORKER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module, module.Encoder(ROOT, sim, armg), sim, armg


def decision(surface='card_reward'):
    actions = [
        {'action_id': 'card', 'kind': 'choose_card', 'target_id': 'CARD.BASH', 'target_upgrade_level': 1},
        {'action_id': 'skip', 'kind': 'skip'},
    ]
    if surface == 'map':
        actions = [{'action_id': 'travel', 'kind': 'travel', 'map_coordinate': {'row': 1, 'column': 3}}]
    return {'build': {'game_version': 'v0.111.0',
             'assembly_sha256': '0861bfa1df347538d932f22d580e75420f08082792eb914e53b4882764acdbe9'},
        'state_fingerprint': 'a' * 64,
        'observation': {'surface': surface, 'total_floor': 2, 'act_index': 0, 'act_floor': 2,
            'current_map_coordinate': {'row': 0, 'column': 3},
            'players': [{'character_id': 'CHARACTER.IRONCLAD', 'current_hp': 70,
                'max_hp': 80, 'gold': 100, 'max_potion_count': 3,
                'deck': [{'deck_index': 0, 'model_id': 'CARD.STRIKE_IRONCLAD', 'upgrade_level': 0}],
                'relics': [{'model_id': 'RELIC.BURNING_BLOOD'}], 'potions': []}],
            'map_points': [
                {'coordinate': {'row': 0, 'column': 3}, 'point_type': 'Ancient', 'visited': True,
                 'children': [{'row': 1, 'column': 3}]},
                {'coordinate': {'row': 1, 'column': 3}, 'point_type': 'Monster', 'visited': False,
                 'children': []},
            ]}, 'legal_actions': actions}


def test_reward_action_features_and_dimensions(encoder):
    _, enc, sim, armg = encoder
    obs, rows = enc.encode(decision())
    assert obs.shape == (armg.ARMG_OBS_DIM,)
    assert rows.shape == (2, armg.ARMG_ACTION_DIM)
    bash = enc.cards['BASH']
    assert rows[0, armg._ACTION_OFF + 1] == 1
    np.testing.assert_array_equal(rows[0, armg._CARD_OFF:armg._CARD_OFF + armg.CARD_FEAT_DIM],
                                  np.asarray(sim.card_features(bash, True, -1), dtype=np.float32))
    assert rows[1, armg._ACTION_OFF + 2] == 1
    assert rows[1, armg._SLOT_OFF] == 1


def test_map_action_records_visible_children(encoder):
    _, enc, _, armg = encoder
    obs, rows = enc.encode(decision('map'))
    assert obs.shape == (armg.ARMG_OBS_DIM,)
    assert rows[0, armg._ACTION_OFF] == 1
    assert rows[0, armg._MAP_OFF + 5] == 1
    assert rows[0, armg._META_OFF + 2] == pytest.approx(3 / 6)
    assert rows[0, armg._META_OFF + 3] == pytest.approx(1 / 16)


def shop_decision():
    d = decision('merchant')
    d['observation']['players'][0]['gold'] = 200
    d['observation']['shop'] = {
        'cards': [{'slot_index': 0, 'model_id': 'CARD.BASH', 'upgrade_level': 0, 'cost': 50, 'sold': False},
                  {'slot_index': 1, 'model_id': 'CARD.ANGER', 'upgrade_level': 0, 'cost': 49, 'sold': True}],
        'relics': [{'slot_index': 0, 'model_id': 'RELIC.ANCHOR', 'cost': 150, 'sold': False}],
        'potions': [{'slot_index': 0, 'model_id': 'POTION.ENERGY_POTION', 'cost': 60, 'sold': False}],
        'removal_cost': 75, 'removal_available': True,
    }
    d['legal_actions'] = [
        {'action_id': 'buy-c', 'kind': 'buy_card', 'target_id': 'CARD.BASH', 'target_shop_index': 0, 'cost': 50},
        {'action_id': 'buy-r', 'kind': 'buy_relic', 'target_id': 'RELIC.ANCHOR', 'target_shop_index': 0, 'cost': 150},
        {'action_id': 'buy-p', 'kind': 'buy_potion', 'target_id': 'POTION.ENERGY_POTION', 'target_shop_index': 0, 'cost': 60},
        {'action_id': 'remove', 'kind': 'open_card_removal', 'target_id': 'CARD.STRIKE_IRONCLAD', 'target_deck_index': 0, 'cost': 75},
        {'action_id': 'leave', 'kind': 'leave_merchant'},
    ]
    return d


def test_shop_features_cover_inventory_and_competing_actions(encoder):
    _, enc, sim, armg = encoder
    obs, rows = enc.encode(shop_decision())
    assert obs.shape == (armg.ARMG_OBS_DIM,)
    assert obs[38 + 4] == 1  # simulator SHOP screen, not map or card reward
    assert rows.shape == (5, armg.ARMG_ACTION_DIM)
    for i, kind in enumerate((7, 8, 9, 10, 11)):
        assert rows[i, armg._ACTION_OFF + kind] == 1
        assert rows[i, armg._SLOT_OFF] == 1
    np.testing.assert_array_equal(rows[0, armg._CARD_OFF:armg._CARD_OFF + armg.CARD_FEAT_DIM],
                                  sim.card_features(enc.cards['BASH'], False, 50))
    assert rows[1, armg._RELIC_OFF + enc.relics['ANCHOR']] == 1
    assert rows[2, armg._POTION_OFF + enc.potions['EnergyPotion']] == 1
    np.testing.assert_array_equal(rows[3, armg._CARD_OFF:armg._CARD_OFF + armg.CARD_FEAT_DIM],
                                  sim.card_features(enc.cards['STRIKE_IRONCLAD'], False, -1))
    assert list(rows[:4, armg._META_OFF + 4]) == pytest.approx([50/300, 150/300, 60/300, 75/300])
    shop_start = -(7 * (enc.card_dim + 2) + 3 * (enc.relic_count + 2) + 3 * (enc.potion_count + 2) + 4)
    np.testing.assert_array_equal(obs[shop_start:shop_start + enc.card_dim],
                                  sim.card_features(enc.cards['BASH'], False, -1))
    assert obs[shop_start + enc.card_dim] == pytest.approx(50/200)
    assert obs[shop_start + 2 * (enc.card_dim + 2) - 1] == 1  # sold second card
    assert obs[-4] == pytest.approx(75/200)
    assert obs[-3] == 0


def test_shop_rejects_stale_and_unaffordable_actions(encoder):
    module, enc, _, _ = encoder
    for mutation in ('sold', 'cost', 'identity', 'removal'):
        d = shop_decision()
        if mutation == 'sold': d['observation']['shop']['cards'][0]['sold'] = True
        elif mutation == 'cost': d['legal_actions'][0]['cost'] = 500
        elif mutation == 'identity': d['legal_actions'][0]['target_id'] = 'CARD.ANGER'
        else: d['legal_actions'][3]['target_deck_index'] = 99
        with pytest.raises(module.Unsupported): enc.encode(d)


def test_shop_sold_slot_without_identity_keeps_remaining_actions(encoder):
    _, enc, _, armg = encoder
    d = shop_decision()
    d['observation']['shop']['cards'][1]['model_id'] = None
    obs, rows = enc.encode(d)
    assert rows.shape[0] == len(d['legal_actions'])
    assert rows[0, armg._ACTION_OFF + 7] == 1
    shop_start = -(7 * (enc.card_dim + 2) + 3 * (enc.relic_count + 2) + 3 * (enc.potion_count + 2) + 4)
    assert obs[shop_start + 2 * (enc.card_dim + 2) - 1] == 1
    if not CHECKPOINT.is_file():
        return
    proc = subprocess.run([sys.executable, str(WORKER), '--checkpoint', str(CHECKPOINT),
        '--sts2-root', str(ROOT), '--simulator', str(PYD)],
        input=json.dumps({'request_id': 'sold', 'decision': d}) + '\n',
        capture_output=True, text=True, timeout=60, check=True)
    result = json.loads(proc.stdout)
    assert result['status'] == 'ok'
    assert 'sold_shop_item_identity' in result['missing_features']


def test_shop_worker_scores_multiple_types(encoder):
    if not CHECKPOINT.is_file():
        pytest.skip('matching checkpoint not available')
    proc = subprocess.run([sys.executable, str(WORKER), '--checkpoint', str(CHECKPOINT),
        '--sts2-root', str(ROOT), '--simulator', str(PYD)],
        input=json.dumps({'request_id': 'shop', 'decision': shop_decision()}) + '\n',
        capture_output=True, text=True, timeout=60, check=True)
    result = json.loads(proc.stdout)
    assert result['status'] == 'ok' and result['approximate'] is True
    assert result['action_id'] in ('buy-c', 'buy-r', 'buy-p', 'remove', 'leave')
    assert len(result['scores']) == 5


def test_verified_live_event_uses_simulator_option_indices(encoder):
    module, enc, sim, armg = encoder
    d = decision('event')
    d['observation']['room_model_id'] = 'EVENT.SUNKEN_STATUE'
    d['legal_actions'] = [
        {'action_id': 'water', 'kind': 'choose_event_option',
         'target_id': 'SUNKEN_STATUE.pages.INITIAL.options.DIVE_INTO_WATER'},
        {'action_id': 'sword', 'kind': 'choose_event_option',
         'target_id': 'SUNKEN_STATUE.pages.INITIAL.options.GRAB_SWORD'},
    ]
    obs, rows = enc.encode(d)
    event_id = next(i for i in range(sim.event_count()) if sim.event_info(i)[0] == 'SUNKEN_STATUE')
    assert obs[14] == pytest.approx((event_id + 1) / 48)
    assert obs[38 + 5] == 1
    assert rows[:, armg._ACTION_OFF + 12].tolist() == [1, 1]
    assert rows[0, armg._SLOT_OFF + 1] == 1 and rows[1, armg._SLOT_OFF] == 1
    assert rows[:, armg._META_OFF].tolist() == pytest.approx([1 / 127, 0])
    d['legal_actions'][0]['target_id'] = 'PROCEED'
    with pytest.raises(module.Unsupported): enc.encode(d)


def test_event_worker_scores_verified_choices(encoder):
    if not CHECKPOINT.is_file():
        pytest.skip('matching checkpoint not available')
    d = decision('event')
    d['observation']['room_model_id'] = 'EVENT.SUNKEN_STATUE'
    d['legal_actions'] = [
        {'action_id': 'sword', 'kind': 'choose_event_option',
         'target_id': 'SUNKEN_STATUE.pages.INITIAL.options.GRAB_SWORD'},
        {'action_id': 'water', 'kind': 'choose_event_option',
         'target_id': 'SUNKEN_STATUE.pages.INITIAL.options.DIVE_INTO_WATER'},
    ]
    proc = subprocess.run([sys.executable, str(WORKER), '--checkpoint', str(CHECKPOINT),
        '--sts2-root', str(ROOT), '--simulator', str(PYD)],
        input=json.dumps({'request_id': 'event', 'decision': d}) + '\n',
        capture_output=True, text=True, timeout=60, check=True)
    result = json.loads(proc.stdout)
    assert result['status'] == 'ok' and result['approximate'] is True
    assert result['action_id'] in ('sword', 'water')
    assert len(result['scores']) == 2


def test_ancient_offers_encode_relics(encoder):
    _, enc, _, armg = encoder
    d = decision('event')
    d['observation']['room_model_id'] = 'EVENT.PAEL'
    d['legal_actions'] = [
        {'action_id': name, 'kind': 'choose_event_option',
         'target_id': 'PAEL.pages.INITIAL.options.' + name}
        for name in ('PAELS_HORN', 'PAELS_CLAW', 'PAELS_BLOOD')]
    _, rows = enc.encode(d)
    for i, name in enumerate(('PAELS_HORN', 'PAELS_CLAW', 'PAELS_BLOOD')):
        assert rows[i, armg._ACTION_OFF + 12] == 1
        assert rows[i, armg._SLOT_OFF + i] == 1
        assert rows[i, armg._RELIC_OFF + enc.relics[name]] == 1


def test_reject_unknown_or_unreliable_actions(encoder):
    module, enc, _, _ = encoder
    d = decision()
    d['legal_actions'][0].pop('target_upgrade_level')
    with pytest.raises(module.Unsupported): enc.encode(d)
    d = decision(); d['legal_actions'][0]['target_id'] = 'CARD.UNKNOWN_NEW_CARD'
    with pytest.raises(module.Unsupported): enc.encode(d)
    d = decision(); d['legal_actions'].append({'action_id': 'x', 'kind': 'choose_event_option'})
    with pytest.raises(module.Unsupported): enc.encode(d)
    d = decision('rest_site')
    with pytest.raises(module.Unsupported): enc.encode(d)
    d = decision(); d['build']['game_version'] = 'future'
    with pytest.raises(module.Unsupported): enc.encode(d)


def test_protocol_process_returns_approximate_and_echoes_identity(encoder):
    if not CHECKPOINT.is_file():
        pytest.skip('matching checkpoint not available')
    d = decision()
    bad = decision(); bad['legal_actions'][0].pop('target_upgrade_level')
    inputs = '\n'.join(json.dumps({'request_id': i, 'decision': x}) for i, x in [(1, d), (2, bad)]) + '\n'
    proc = subprocess.run([sys.executable, str(WORKER), '--checkpoint', str(CHECKPOINT),
        '--sts2-root', str(ROOT), '--simulator', str(PYD)], input=inputs,
        capture_output=True, text=True, timeout=60, check=True)
    rows = [json.loads(line) for line in proc.stdout.splitlines()]
    assert [r['request_id'] for r in rows] == [1, 2]
    assert rows[0]['status'] == 'ok' and rows[0]['approximate'] is True
    assert rows[0]['state_fingerprint'] == 'a' * 64 and rows[0]['action_id'] in ('card', 'skip')
    assert rows[1]['status'] == 'unsupported'


def test_card_reward_without_skip_and_ignored_alternative_use_native_action_indices(encoder):
    module, enc, _, armg = encoder
    d = decision()
    d['legal_actions'] = [
        {'action_id': 'alternative', 'kind': 'choose_reward_alternative'},
        {'action_id': 'first', 'kind': 'choose_card', 'target_id': 'CARD.BASH', 'target_upgrade_level': 1},
        {'action_id': 'second', 'kind': 'choose_card', 'target_id': 'CARD.ANGER', 'target_upgrade_level': 0},
    ]
    _, features = enc.encode(d)
    assert features.shape == (3, armg.ARMG_ACTION_DIM)
    assert not features[0].any()
    assert features[1, armg._SLOT_OFF] == 1
    assert features[2, armg._SLOT_OFF + 1] == 1
    inputs = json.dumps({'request_id': 'mixed', 'decision': d}) + '\n'
    proc = subprocess.run([sys.executable, str(WORKER), '--checkpoint', str(CHECKPOINT),
        '--sts2-root', str(ROOT), '--simulator', str(PYD)], input=inputs,
        capture_output=True, text=True, timeout=60, check=True)
    result = json.loads(proc.stdout)
    assert result['status'] == 'ok' and result['action_id'] in ('first', 'second')
    assert result['scores'][0] == pytest.approx(-1e30)
    assert 'ignored_unscored_action:alternative' in result['missing_features']


def test_single_legal_action_is_returned_without_a_model_choice(encoder):
    d = decision('rest_site')
    d['legal_actions'] = [{'action_id': 'only', 'kind': 'proceed'}]
    inputs = json.dumps({'request_id': 'forced', 'decision': d}) + '\n'
    proc = subprocess.run([sys.executable, str(WORKER), '--checkpoint', str(CHECKPOINT),
        '--sts2-root', str(ROOT), '--simulator', str(PYD)], input=inputs,
        capture_output=True, text=True, timeout=60, check=True)
    result = json.loads(proc.stdout)
    assert result['status'] == 'ok' and result['action_id'] == 'only'
    assert result['approximate'] is False and result['scores'] == [0.0]
    assert result['missing_features'] == ['single_legal_action_no_model']


def test_historical_real_reward_protocol_preserves_candidate_order(encoder):
    _, enc, _, armg = encoder
    sample = None
    root = Path(__file__).resolve().parents[1] / 'artifacts/human-dataset/episodes'
    for path in sorted(root.glob('*.jsonl')):
        with path.open(encoding='utf-8') as stream:
            for line in stream:
                row = json.loads(line)
                payload = row.get('payload') or {}
                if (payload.get('observation') or {}).get('surface') == 'card_reward':
                    sample = payload
                    break
        if sample is not None:
            break
    if sample is None:
        pytest.skip('no historical real reward observation in the workspace')
    # Historical captures did not record offered-card upgrade levels. This is
    # a test assumption only; the live protocol must supply the actual value.
    for action in sample['legal_actions']:
        if action['kind'] == 'choose_card':
            action['target_upgrade_level'] = 0
    observation, features = enc.encode(sample)
    assert observation.shape == (armg.ARMG_OBS_DIM,)
    assert features.shape[0] == len(sample['legal_actions'])
    for index, action in enumerate(sample['legal_actions']):
        if action['kind'] == 'choose_card':
            assert features[index, armg._ACTION_OFF + 1] == 1
