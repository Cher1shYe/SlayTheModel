import gzip
import json
from pathlib import Path

from sts2_env.az.ppo import trajectory_rows


def test_replayed_rampage_does_not_face_removed_back_attack_power():
    with gzip.open(Path(__file__).parent / 'fixtures/native_surrounded_dead_replay_v1.json.gz',
                   'rt', encoding='utf8') as stream:
        raw = json.load(stream)
    trajectory_rows(raw, raw['modelSha256'], reward_mode='cost')
    assert raw['seed'] == 8000176 and raw['initialHp'] == 9999
    assert len(raw['steps']) == 26 and raw['outcome']['won']
    assert raw['outcome']['finalHp'] == 9882
    killing = raw['steps'][20]
    assert killing['action'].startswith('PlayCard:RAMPAGE:')
    assert 'replay=3' in killing['action']
    assert killing['successorParityScope'] == 'complete_continuation'
    assert all(s['successorParity'] and s['featureParity'] for s in raw['steps'])
