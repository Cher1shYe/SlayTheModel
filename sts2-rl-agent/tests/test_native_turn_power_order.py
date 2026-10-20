"""Captured strict native/simulation replays; see power-order-fix diagnostics."""
import gzip
import json
from pathlib import Path
import pytest


@pytest.mark.parametrize('name,count,first,second', [
    ('after', 15, 'VIGOR_POWER=4', 'STRENGTH_POWER=3'),
    ('prep_first', 5, 'VIGOR_POWER=8', 'STRENGTH_POWER=6'),
    ('demon_first', 5, 'STRENGTH_POWER=6', 'VIGOR_POWER=8'),
])
def test_turn_start_preserves_power_listener_order(name, count, first, second):
    path = Path(__file__).parent/'fixtures'/f'native_turn_power_order_{name}.json.gz'
    with gzip.open(path, 'rt', encoding='utf-8') as stream:
        raw = json.load(stream)
    assert raw['format'] == 'native-diagnostic-replay-v1'
    assert len(raw['steps']) == count
    assert all(s['featureParity'] and s['successorParity'] for s in raw['steps'])
    assert raw['steps'][-1]['action'].startswith('EndTurn:')
    powers = raw['continuation'].split(';P=')[1].split(';')[0]
    assert powers.index(first) < powers.index(second)
