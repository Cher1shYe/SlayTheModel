import gzip
import json
from pathlib import Path
from sts2_env.az.native_generic import validate_raw


def load(name):
    with gzip.open(Path(__file__).parent/'fixtures'/name, 'rt', encoding='utf-8') as f:
        return json.load(f)


def test_repeated_thinking_ahead_keeps_all_fourth_selector_options():
    raw = load('native_thinking_replay_prefix.json.gz')
    assert len(raw['steps']) == 17
    step = raw['steps'][16]
    assert step['action'].startswith('choice:PlayCard:THINKING_AHEAD:')
    assert '|replay=3|' in step['action']
    assert {c['model'] for c in step['observation']['choice']['options']} == {
        'COLOSSUS', 'HIDDEN_GEM', 'CRUELTY', 'FIGHT_ME', 'FLASH_OF_STEEL', 'TEAR_ASUNDER'}
    assert all(s['featureParity'] and s['successorParity'] for s in raw['steps'])


def test_repeated_selector_original_recipe_finishes_strictly():
    raw = load('native_thinking_replay_full.json.gz')
    validate_raw(raw, allow_training_cutoff=True)
    assert raw['seed'] == 6000145 and raw['complete']
    assert len(raw['steps']) == 33
    assert raw['outcome']['won'] and raw['outcome']['finalHp'] == 7
    assert all(s['featureParity'] and s['successorParity'] for s in raw['steps'])
