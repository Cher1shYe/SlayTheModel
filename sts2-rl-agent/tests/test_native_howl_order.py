import gzip
import json
from pathlib import Path
from sts2_env.az.native_generic import validate_raw


def load(name):
    with gzip.open(Path(__file__).parent/'fixtures'/name, 'rt', encoding='utf-8') as f:
        return json.load(f)


def test_exhausted_howls_follow_current_pile_order():
    evidence = load('native_howl_pile_order_prefix.json.gz')
    raw = evidence['replay']
    assert raw['recipe']['seed'] == 6000062
    assert len(raw['steps']) == 23
    assert raw['steps'][-1]['action'].startswith('EndTurn:')
    assert all(s['featureParity'] and s['successorParity'] for s in raw['steps'])
    assert raw['continuation'] == evidence['expected_continuation']
    # The two adjacent copies differ in original-deck identity; their order matters.
    discard = raw['continuation'].split(';D=')[1].split(';C=')[0]
    howls = [part for part in discard.split('HOWL_FROM_BEYOND+1/')[1:]]
    assert len(howls) == 2
    assert howls[0].startswith('False:3/False:-1/0/False/False/False/False/')
    assert howls[1].startswith('False:3/False:-1/0/False/False/False/True/')


def test_howl_full_recipe_strict_completion():
    raw = load('native_howl_pile_order_full.json.gz')
    validate_raw(raw, allow_training_cutoff=True)
    assert raw['seed'] == 6000062
    assert raw['complete']
    assert all(s['featureParity'] and s['successorParity'] for s in raw['steps'])
