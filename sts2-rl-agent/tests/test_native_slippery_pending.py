import gzip
import json
from pathlib import Path
from sts2_env.az.native_generic import validate_raw


def load(name):
    with gzip.open(Path(__file__).parent/'fixtures'/name, 'rt', encoding='utf-8') as f:
        return json.load(f)


def layers(step):
    enemy = next(c for c in step['observation']['observation']['Creatures']
                 if c['MonsterId'] == 'MONSTER.VANTOM')
    return next((p['Amount'] for p in enemy['Powers']
                 if p['ModelId'] == 'POWER.SLIPPERY_POWER'), 0)


def test_slippery_pending_draw_projects_consumed_layer():
    raw = load('native_slippery_pending_prefix.json.gz')
    assert raw['format'] == 'native-diagnostic-replay-v1'
    assert len(raw['steps']) == 9
    step = raw['steps'][8]
    assert step['action'].startswith('choice:PlayCard:FLASH_OF_STEEL:')
    assert step['observation']['choice'] is not None
    assert layers(step) == 6
    assert all(s['featureParity'] and s['successorParity'] for s in raw['steps'])


def test_slippery_original_recipe_completes_through_zero_layers():
    raw = load('native_slippery_pending_full.json.gz')
    validate_raw(raw)
    assert raw['seed'] == 4040737 and raw['complete']
    assert len(raw['steps']) == 49
    assert layers(raw['steps'][0]) == 8
    assert any(layers(s) == 1 for s in raw['steps'])
    assert any(layers(s) == 0 for s in raw['steps'])
    assert all(s['featureParity'] and s['successorParity'] for s in raw['steps'])
