"""Public binding and snapshot contract for cumulative power self-damage."""
import pytest

from agent.common import sim


def card_id(name):
    return next(i for i in range(sim.card_count()) if sim.card_name(i) == name)


@pytest.mark.parametrize("inferno_first", [False, True])
def test_played_power_counts_and_order_reach_public_binding(inferno_first):
    mantle, inferno = card_id("Crimson Mantle"), card_id("Inferno")
    battle = sim.BattleContext()
    battle.init(int(sim.Encounter.SETUP_CEREMONIAL_BEAST_BOSS), 123,
                [mantle, mantle, inferno], [False, True, True], 0, 80, 80)
    ids = [inferno, mantle, mantle] if inferno_first else [mantle, mantle, inferno]
    for ident in ids:
        index = next(i for i, card in enumerate(battle.hand) if card[0] == ident)
        action = next(a for a in battle.legal_actions()
                      if a[0] == int(sim.ActionType.PLAY_CARD) and a[1] == index)
        assert battle.step(*action)
    assert battle.crimson_mantle_self_damage == 2
    assert battle.inferno_self_damage == 1
    assert battle.inferno_before_crimson_mantle is inferno_first
    assert battle.observation_public()[-3:] == pytest.approx([0.2, 0.1, int(inferno_first)])
    assert len(battle.observation_public()) == int(sim.PUBLIC_COMBAT_OBS_DIM)


def test_previous_snapshot_version_is_rejected():
    run = sim.RunContext()
    run.init(123, 0)
    snapshot = run.snapshot()
    assert snapshot[4:6] == b"\x08\x00"
    stale = snapshot[:4] + b"\x07\x00" + snapshot[6:]
    assert not run.restore(stale)
    assert run.snapshot() == snapshot
