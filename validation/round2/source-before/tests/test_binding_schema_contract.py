"""Binding input validation and the current public observation contract."""

import pytest

from agent.common import sim


@pytest.fixture
def contexts():
    strike = next(i for i in range(sim.card_count()) if sim.card_name(i) == "Strike")
    battle = sim.BattleContext()
    battle.init(int(sim.Encounter.SETUP_CEREMONIAL_BEAST_BOSS), 1234,
                [strike] * 10, [False] * 10, 0, 100, 100)
    run = sim.RunContext()
    run.init(1234, 0)
    return battle, run


@pytest.mark.parametrize("field,value", [
    (0, -1), (0, 5), (0, 256),
    (1, -1), (1, 256), (2, -1), (2, 256),
    (3, -1), (3, 65536),
])
@pytest.mark.parametrize("endpoint", ["battle_step", "battle_features", "run_step", "run_features"])
def test_combat_action_components_are_checked_before_narrowing(contexts, field, value, endpoint):
    battle, run = contexts
    action = [int(sim.ActionType.PLAY_CARD), 0, 0, 0]
    action[field] = value
    methods = {
        "battle_step": battle.step,
        "battle_features": battle.action_features,
        "run_step": run.step_combat,
        "run_features": run.combat_action_features,
    }
    before_battle = battle.observation_public()
    before_run = run.snapshot()
    with pytest.raises(ValueError, match=["type", "hand", "target", "uid"][field]):
        methods[endpoint](*action)
    assert battle.observation_public() == before_battle
    assert run.snapshot() == before_run


@pytest.mark.parametrize("action_type", [-1, int(sim.RunActionType.REST_CLONE) + 1, 256])
def test_run_action_type_is_checked_before_narrowing(contexts, action_type):
    _, run = contexts
    before = run.snapshot()
    with pytest.raises(ValueError, match="type"):
        run.step(action_type, 0)
    assert run.snapshot() == before


def test_field_limits_and_public_schema(contexts):
    battle, run = contexts
    assert len(battle.action_features(int(sim.ActionType.END_TURN), 255, 255, 65535)) == 340
    assert int(sim.PUBLIC_OBS_VERSION) == 10
    assert int(sim.ACTION_SCHEMA_VERSION) == 9
    assert int(sim.PUBLIC_OBS_DIM) == len(run.observe_public()) == 37305
    assert int(sim.PUBLIC_COMBAT_OBS_DIM) == len(battle.observation_public()) == 21330
    assert int(sim.CARD_FEAT_DIM) == 250
    assert int(sim.ACTION_FEAT_DIM) == 340


def test_generate_map_takes_raw_rng_seed():
    run = sim.RunContext()
    run.init(123, 0)
    # Numeric APIs now both take the raw native 64-bit seed. Human-readable
    # game seeds use init_seed and are covered by test_native_seed_identity.
    assert sim.generate_map(123, 0)[2] == run.map_nodes()
    text_run = sim.RunContext()
    text_run.init_seed("123", 0)
    assert text_run.seed != run.seed
    assert sim.generate_map(text_run.seed, 0)[2] == text_run.map_nodes()


def test_a10_map_includes_second_boss_coordinates():
    _, length, nodes = sim.generate_map(123, 2, 10)
    bosses = [node for node in nodes if node[1] == 7]
    assert sorted(node[3] for node in bosses) == [length, length + 1]
    assert all(node[2] >= 0 for node in bosses)
