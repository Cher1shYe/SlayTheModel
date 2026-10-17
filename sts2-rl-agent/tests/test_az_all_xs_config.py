"""Frozen P3 all-content XS config/protocol integrity (no training)."""
import hashlib
import json
from pathlib import Path

from sts2_env.az import all_decks
from sts2_env.az.config import RULES_VERSION
from sts2_env.az.rewards import V7

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / 'configs' / 'az_all_xs_v1' / 'config.json'
PROTOCOL = ROOT / 'configs' / 'az_all_xs_v1' / 'protocol.json'


def load(path):
    return json.loads(path.read_text(encoding='utf-8'))


def test_config_is_frozen_before_training():
    config = load(CONFIG)
    assert config['version'] == 'az-all-xs-v1'
    assert config['status'] == 'frozen-before-training'
    assert config['content'] == 'ironclad-colorless-all-v6'
    assert config['reward'] == V7
    assert config['rules_version'] == RULES_VERSION
    assert config['model'] == {'tier': 'XS', 'initialization': 'fresh',
                               'reuse_previous_weights': False}
    assert config['generator'] == all_decks.frozen_manifest()
    assert config['search']['budget'] == 8
    assert config['training']['self_play'].startswith('native monsters')


def test_protocol_recipes_regenerate_from_frozen_coordinates():
    protocol = load(PROTOCOL)
    manifest = all_decks.frozen_manifest()
    assert protocol['generator_manifest_sha'] == hashlib.sha256(
        json.dumps(manifest, sort_keys=True).encode()).hexdigest()
    for split, key in (('validation', 'validation'), ('test', 'test')):
        stored = protocol[key]
        assert len(stored) == 64
        for index, document in enumerate(stored):
            master = all_decks.HELDOUT_MASTER_SEEDS[split]
            recipe = all_decks.generate_recipe(master, 0, index, split)
            assert document['scenario_id'] == recipe.scenario_id
            assert document['encounter'] == recipe.encounter_id
            assert document['seed'] == recipe.environment_seed
            assert document['deck'] == [[entry.card_id, entry.upgraded, entry.count]
                                        for entry in recipe.deck]


def test_protocol_splits_are_disjoint_and_never_training_seeds():
    protocol = load(PROTOCOL)
    validation = {tuple(map(tuple, doc['deck'])) + (doc['seed'],) for doc in protocol['validation']}
    test = {tuple(map(tuple, doc['deck'])) + (doc['seed'],) for doc in protocol['test']}
    assert not validation & test
    for document in protocol['validation'] + protocol['test']:
        assert document['seed'] >= all_decks.VALIDATION_SEED_OFFSET
        assert document['seed'] < 2**31
        assert document['encounter'] in all_decks.admitted_encounters()


def test_training_plan_is_inside_the_frozen_budget():
    protocol = load(PROTOCOL)
    config = load(CONFIG)
    plan = protocol['train_plan']
    assert plan['iterations'] == config['training']['iterations']
    assert plan['episodes_per_iteration'] == config['training']['episodes_per_iteration']
    assert config['evaluation']['test_recipes'] == len(protocol['test'])
    assert config['gate']['requires'].startswith('validation utility gain')
