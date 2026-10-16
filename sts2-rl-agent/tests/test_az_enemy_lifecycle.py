import json
from dataclasses import FrozenInstanceError, replace

import pytest

from sts2_env.az.enemy_lifecycle import EnemyLife, EnemyLedger, CONTRACT_VERSION
from sts2_env.az.rewards import validate_reward


def ledger(hp=50, maximum=100):
    return EnemyLedger((EnemyLife(0, "PRIMARY", True, hp, maximum, hp),))


def test_repeat_summon_kill_revive_cannot_farm_reward_or_denominator():
    original = ledger().update(0, 25, "alive")
    branch = original
    for _ in range(20):
        branch = branch.spawn_secondary("ILLUSION", 6)
        slot = len(branch.entries) - 1
        for _ in range(4):
            branch = branch.update(slot, 0, "reviving")
            assert branch.terminal_reward("time_limit", 10, 40) == 0.0
            branch = branch.update(slot, 6, "alive")
        branch = branch.update(slot, 0, "removed")
        assert branch.damage_progress == 0.5
    assert len(original.entries) == 1
    assert [e.slot for e in branch.entries] == list(range(21))
    with pytest.raises(FrozenInstanceError):
        original.entries[0].hp = 0


def test_primary_revival_and_healing_retract_progress():
    damaged = ledger().update(0, 10, "alive")
    assert damaged.damage_progress == 0.8
    dead = damaged.update(0, 0, "reviving")
    assert dead.damage_progress == 0
    for _ in range(10):
        dead = dead.update(0, 25, "alive")
        assert dead.damage_progress == 0.5
        dead = dead.update(0, 0, "reviving")
    assert dead.update(0, 100, "alive").damage_progress == 0
    permanent = dead.update(0, 0, "defeated")
    assert permanent.terminal_reward("win", 20, 40) == pytest.approx(0.9)
    with pytest.raises(ValueError):
        permanent.update(0, 50, "alive")


def test_win_ignores_secondary_hp_but_not_primary_or_explicit_blocker():
    start = ledger().spawn_secondary("EYE", 6)
    with pytest.raises(ValueError):
        start.terminal_reward("win", 20, 40)
    won = start.update(0, 0, "defeated")
    assert won.terminal_reward("win", 40, 40) == 1
    with pytest.raises(ValueError):
        won.terminal_reward("win", 40, 40, blocks_combat_end=True)
    assert won.terminal_reward("time_limit", 40, 40, blocks_combat_end=True) == pytest.approx(.2)
    for reason in (None, "time_limit"):
        with pytest.raises(ValueError):
            won.terminal_reward(reason, 40, 40)


def test_multiple_primary_budget_is_net_sum_and_json_roundtrips():
    start = EnemyLedger((EnemyLife(0, "A", True, 40, 80, 20), EnemyLife(1, "B", True, 60, 60, 30)))
    assert start.damage_progress == .5
    assert EnemyLedger.from_dict(json.loads(json.dumps(start.to_dict()))) == start
    healed = start.update(0, 60, "alive")
    assert healed.damage_progress == pytest.approx(.1)
    assert start.damage_progress == .5


@pytest.mark.parametrize("reason,expected", [(None, 0), ("time_limit", 0), ("death", -.9)])
def test_shared_coefficients_and_zero_process_reward(reason, expected):
    assert ledger().update(0, 25, "alive").terminal_reward(reason, 0 if reason == "death" else 20, 40) == expected


@pytest.mark.parametrize("change", [
    {"slot": True}, {"slot": 2}, {"primary": 1}, {"spawned": 1},
    {"initial_hp": 0}, {"initial_hp": 101}, {"hp": -1}, {"hp": float("nan")},
    {"hp": 0}, {"phase": "reviving"}, {"phase": "other"},
    {"spawned": True}, {"monster_id": ""}, {"max_hp": 0},
])
def test_invalid_or_unsupported_states_rejected(change):
    with pytest.raises(ValueError):
        EnemyLedger((replace(ledger().entries[0], **change),)).validate()


@pytest.mark.parametrize("data", [{}, {"version": CONTRACT_VERSION, "entries": [{}]},
    {"version": "old", "entries": []}, {"version": CONTRACT_VERSION, "entries": [None]}])
def test_corrupt_serialized_records_rejected(data):
    with pytest.raises(ValueError):
        EnemyLedger.from_dict(data)


@pytest.mark.parametrize("hp", [float("nan"), float("inf"), -1, True, "40"])
def test_invalid_player_hp_rejected(hp):
    with pytest.raises(ValueError):
        ledger().terminal_reward("time_limit", hp, 40)


def test_contract_registered_only_with_new_content_schema():
    assert validate_reward(CONTRACT_VERSION) == CONTRACT_VERSION
    from sts2_env.az.encoder import schema_for
    from sts2_env.az.content import MULTI_CONTENT
    with pytest.raises(ValueError):
        schema_for("observable", CONTRACT_VERSION, MULTI_CONTENT)


def test_no_primary_summon_removal_or_slot_reuse():
    with pytest.raises(ValueError):
        ledger().update(0, 0, "removed")
    with pytest.raises(ValueError):
        ledger().update(1, 0, "defeated")
    removed = ledger().spawn_secondary("EYE", 6).update(1, 0, "removed")
    with pytest.raises(ValueError):
        removed.update(1, 6, "alive")
    with pytest.raises(ValueError):
        EnemyLedger((EnemyLife(0, "EYE", False, 6, 6, 6),)).validate()
