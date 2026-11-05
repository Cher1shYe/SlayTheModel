"""Binding-level act routing. Full native parity remains a separate gate."""
import pytest
import sts2_sim as sim


def test_explicit_underdocks_and_snapshot_context():
    progress = sim.NativeProgressContext()
    progress.underdocks_unlocked = True
    progress.apply_discovery_order = True
    progress.seen_encounters = []
    run = sim.RunContext()
    run.init_seed_with_context("native act check", 0, 3, progress)
    assert run.act == 0
    assert run.act_types == [sim.ActType.UNDERDOCKS, sim.ActType.HIVE, sim.ActType.GLORY]
    assert run.map_rooms == 15
    assert run.native_progress.underdocks_unlocked
    restored = sim.RunContext()
    assert restored.restore(run.snapshot())
    assert restored.act_types == run.act_types
    assert restored.native_progress.seen_encounters == []
    assert restored.boss_encounter == run.boss_encounter


def test_fixed_underdocks_requires_unlock_and_seen_ids_are_checked():
    progress = sim.NativeProgressContext()
    run = sim.RunContext()
    with pytest.raises(ValueError, match="unlocked"):
        run.init_with_context(1, 0, 3, progress)
    with pytest.raises(ValueError, match="Invalid seen encounter"):
        progress.seen_encounters = [-1]
    with pytest.raises(ValueError, match="Invalid ascension"):
        run.init_with_context(1, 0, 1, progress)


def test_newly_unlocked_alternate_act_precedes_random_choice():
    progress = sim.NativeProgressContext()
    progress.underdocks_unlocked = True
    progress.underdocks_discovered = False
    run = sim.RunContext()
    for seed in range(8):
        run.init_with_context(seed, 0, -1, progress)
        assert run.act_types[0] == sim.ActType.UNDERDOCKS
