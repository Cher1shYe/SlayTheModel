"""Verify event option mapping and feature blocks against the native simulator."""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import sys

import numpy as np
import pytest


ROOT = Path(os.environ.get('ARMG_STS2_ROOT', 'D:/sts2_datacollection/sts2'))
PYD = ROOT / '.scratch/potion-module/sts2_sim.cp312-win_amd64.pyd'
SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
sys.path.insert(0, str(SCRIPTS))
from armg_live_events import ANCIENT_POOLS, INITIAL_OPTIONS, UnsupportedEvent, encode_live_event


@pytest.fixture(scope='module')
def simulator():
    if not PYD.is_file():
        pytest.skip('matching STS2 simulator not available')
    os.environ['STS2_PRIOR_PYD'] = str(PYD)
    sys.path.insert(0, str(ROOT))
    import deployment.evaluate_battle_root_prior  # loads configured simulator
    from agent.common import new_run, sim
    return new_run, sim


def actions(name, options):
    return [{'kind': 'choose_event_option',
             'target_id': f'{name}.pages.INITIAL.options.{option}'} for option in options]


@pytest.mark.parametrize('name,options', INITIAL_OPTIONS.items())
def test_verified_mapping_matches_live_simulator(simulator, name, options):
    new_run, sim = simulator
    event = encode_live_event({'surface': 'event', 'room_model_id': 'EVENT.' + name},
                              actions(name, options[::-1]), sim)
    assert event.option_indices == tuple(reversed(range(len(options))))
    assert sim.event_info(event.event_id)[0] == name
    run = new_run(123)
    assert run.begin_event(event.event_id)
    obs = np.asarray(run.observe_public(), dtype=np.float32)
    relic_count = max(int(x) for x in sim.RelicId.__members__.values()) + 1
    block = np.asarray(event.observation_block(relic_count), dtype=np.float32)
    # Locate the exact event block in the full public observation.  This checks
    # simulator defaults, event id, choice count, and page, not just shape.
    assert any(np.array_equal(obs[i:i + len(block)], block)
               for i in np.flatnonzero(obs[event.event_id:len(obs) - len(block) + event.event_id + 1] == 1))


def test_unknown_page_or_duplicate_options_rejected(simulator):
    _, sim = simulator
    obs = {'surface': 'event', 'room_model_id': 'EVENT.WELLSPRING'}
    with pytest.raises(UnsupportedEvent):
        encode_live_event(obs, [{'kind': 'choose_event_option', 'target_id': 'PROCEED'}], sim)
    with pytest.raises(UnsupportedEvent):
        encode_live_event(obs, actions('WELLSPRING', ('BOTTLE', 'BOTTLE')), sim)
    with pytest.raises(UnsupportedEvent):
        encode_live_event({'surface': 'event', 'room_model_id': 'EVENT.BYRDONIS_NEST'},
                          actions('BYRDONIS_NEST', ('EAT',)), sim)


@pytest.mark.parametrize('name', ANCIENT_POOLS)
def test_ancient_relic_choices_match_simulator(simulator, name):
    new_run, sim = simulator
    relic_names = {int(value): key for key, value in sim.RelicId.__members__.items()}
    event_id = next(i for i in range(sim.event_count()) if sim.event_info(i)[0] == name)
    for seed in (11, 123, 9881):
        run = new_run(seed)
        assert run.begin_event(event_id)
        relics = tuple(int(r) for r in run.event_relics[:3])
        offered = actions(name, [relic_names[r] for r in relics])
        event = encode_live_event({'surface': 'event', 'room_model_id': 'EVENT.' + name}, offered, sim)
        assert event.option_indices == (0, 1, 2)
        assert event.relic_indices == relics
        obs = np.asarray(run.observe_public(), dtype=np.float32)
        block = np.asarray(event.observation_block(max(relic_names) + 1), dtype=np.float32)
        assert any(np.array_equal(obs[i:i + len(block)], block)
                   for i in np.flatnonzero(obs[event.event_id:len(obs) - len(block) + event.event_id + 1] == 1))


def test_ancient_unknown_or_incomplete_relics_rejected(simulator):
    _, sim = simulator
    obs = {'surface': 'event', 'room_model_id': 'EVENT.PAEL'}
    with pytest.raises(UnsupportedEvent):
        encode_live_event(obs, actions('PAEL', ('PAELS_HORN', 'PAELS_CLAW')), sim)
    with pytest.raises(UnsupportedEvent):
        encode_live_event(obs, actions('PAEL', ('PAELS_HORN', 'PAELS_CLAW', 'NONEXISTENT')), sim)


@pytest.mark.parametrize('name,relics', [
    ('NEOW', ('SMALL_CAPSULE', 'BOOMING_CONCH', 'PRECARIOUS_SHEARS')),
    ('PAEL', ('PAELS_HORN', 'PAELS_CLAW', 'PAELS_BLOOD')),
])
def test_ancient_options_from_actual_live_capture(simulator, name, relics):
    _, sim = simulator
    result = encode_live_event({'surface': 'event', 'room_model_id': f'EVENT.{name}'},
                               actions(name, relics), sim)
    assert result.option_indices == (0, 1, 2)
    assert result.relic_indices == tuple(int(sim.RelicId.__members__[r]) for r in relics)
