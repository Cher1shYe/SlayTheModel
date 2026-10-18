"""Sampling-only tests; no training or held-out outcomes are evaluated."""
from collections import Counter
import json
from pathlib import Path

import pytest

from sts2_env.az import all_decks as decks, all_runner as runner


def test_full_plan_balanced_unique_and_independent():
    encounters = set(decks.admitted_encounters())
    assert len(encounters) == 76
    training = []
    for iteration in range(8):
        recipes = runner.training_recipes(iteration, 304)
        assert Counter(r.encounter_id for r in recipes) == dict.fromkeys(encounters, 4)
        assert len({r.deck for r in recipes}) == 304
        training.extend(recipes)
    assert len({r.scenario_id for r in training}) == 2432
    assert len({r.environment_seed for r in training}) == 2432
    assert len({r.deck for r in training}) == 2432
    protocol = json.loads(Path('configs/az_all_xs_v1/protocol.json').read_text())
    validation = runner.protocol_recipes(protocol, 'validation')
    assert Counter(r.encounter_id for r in validation) == dict.fromkeys(encounters, 4)
    assert len({r.environment_seed for r in validation}) == 304
    assert len({r.deck for r in validation}) == 304
    assert not {r.environment_seed for r in training} & {r.environment_seed for r in validation}
    assert not {r.deck for r in training} & {r.deck for r in validation}
    assert all(r.environment_seed < decks.VALIDATION_SEED_OFFSET for r in training)
    assert all(decks.VALIDATION_SEED_OFFSET <= r.environment_seed < decks.TEST_SEED_OFFSET for r in validation)
    assert validation == tuple(decks.stratified_recipe(0, i, 'validation') for i in range(304))


def test_capacity_no_wrap_and_repeatability():
    recipes = runner.training_recipes(1023, 1024)
    assert len({r.scenario_id for r in recipes}) == 1024
    assert len({r.environment_seed for r in recipes}) == 1024
    assert recipes[:65] == runner.training_recipes(1023, 65)
    assert recipes[0] != recipes[64]
    config = runner.load_frozen_config('configs/az_all_xs_v1/config.json')
    assert runner.effective_settings(config)['episodes'] == 304
    assert runner.effective_settings(config, episodes=1024)['episodes'] == 1024
    with pytest.raises(ValueError):
        runner.effective_settings(config, episodes=1025)
    for iteration, count in [(1024, 1), (-1, 1), (0, 1025), (0, 0)]:
        with pytest.raises(ValueError):
            runner.training_recipes(iteration, count)
    with pytest.raises(ValueError):
        decks.stratified_recipe(1, 0, 'validation')


def test_legacy_final_test_recipes_unchanged():
    protocol = json.loads(Path('configs/az_all_xs_v1/protocol.json').read_text())
    assert runner.protocol_recipes(protocol, 'test') == tuple(
        decks.generate_recipe(287, 0, i, 'test') for i in range(64))


def test_preparation_is_deterministic_and_keeps_runtime_settings(tmp_path, monkeypatch):
    import importlib.util
    spec = importlib.util.spec_from_file_location('prepare_protocol', 'scripts/prepare_all_xs_protocol.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, 'OUT', tmp_path)
    module.main()
    for name in ('config.json', 'protocol.json'):
        assert json.loads((tmp_path / name).read_text()) == json.loads(
            (Path('configs/az_all_xs_v1') / name).read_text())
    config = runner.load_frozen_config(tmp_path / 'config.json')
    assert runner.effective_settings(config)['max_decisions'] == 400
    assert runner.effective_settings(config)['updates'] == 16


def test_duplicate_validation_is_rejected(tmp_path):
    protocol = json.loads(Path('configs/az_all_xs_v1/protocol.json').read_text())
    protocol['validation'][1] = protocol['validation'][0]
    path = tmp_path / 'protocol.json'
    path.write_text(json.dumps(protocol))
    with pytest.raises(ValueError, match='uniqueness'):
        runner.preflight('configs/az_all_xs_v1/config.json', path, iterations=1, episodes=1)
