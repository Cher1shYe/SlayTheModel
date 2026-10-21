"""Regression for the stratified validation Soul Fysh terminal power trace."""
import json
from pathlib import Path

from sts2_env.az.adapter import ObservableCombatAdapter
from sts2_env.az.config import EpisodeLimits
from sts2_env.az.scenarios import CombatScenario


def test_completed_power_lethal_after_hook_has_one_inventory_location(tmp_path):
    trace = json.loads((Path(__file__).parent / 'fixtures/az_power_terminal_trace.json').read_text())
    env = ObservableCombatAdapter(CombatScenario.from_dict(trace['scenario']),
        limits=EpisodeLimits(**trace['limits']), reward_version=trace['reward_version'], error_dir=tmp_path)
    for action in trace['actions']:
        env.step(action)
    assert env.outcome().termination_reason == 'win'
    assert env.outcome().final_hp == 24
    assert env.outcome().reward == .93
    assert 'NOSTALGIA_CARD' in env.information.history.removed_powers
    assert not env.world.play_pile
    from sts2_env.az.card_memory import validate
    from sts2_env.az.content_expansion import CODEC
    validate(env.information, CODEC)
    from sts2_env.az.entity_transition import public_snapshot, public_from_dict
    assert public_from_dict(json.loads(json.dumps(public_snapshot(env.information)))) == env.information
