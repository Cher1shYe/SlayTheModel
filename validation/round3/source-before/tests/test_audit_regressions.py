"""Regressions for the 2026-10-28 deep audit (see docs/simulator-deep-audit-2026-10-28.md).

The rule-level checks live in the native ``rules_test`` binary so they can
inspect piles/counters directly; this module runs it and covers the Python-side
schema, labelling and metric contracts.
"""
from __future__ import annotations

import pathlib
import subprocess

import pytest

from agent.common import sim

ROOT = pathlib.Path(__file__).resolve().parents[1]
RULES_TEST = ROOT / "simulator" / ("rules_test.exe" if hasattr(subprocess, "CREATE_NO_WINDOW") else "rules_test")


def battle(cards, upgraded=None, relics=(), potions=()):
    bc = sim.BattleContext()
    up = upgraded or [False] * len(cards)
    bc.init(getattr(sim.Encounter, "SETUP_CEREMONIAL_BEAST_BOSS"), 1234, cards, up,
            0, 500, 500, list(relics), list(potions))
    return bc


def card_id(name: str) -> int:
    for i in range(1, sim.card_count()):
        if sim.card_name(i) == name:
            return i
    raise KeyError(name)


def test_native_rule_regressions():
    """D01-D24 rule pins; the binary exits non-zero on any failure."""
    if not RULES_TEST.exists():
        pytest.fail(f"{RULES_TEST} missing; build the simulator target sts2_rules_test")
    out = subprocess.run([str(RULES_TEST)], capture_output=True, text=True)
    assert out.returncode == 0, out.stdout + out.stderr
    assert "failures=0" in out.stdout


def test_observation_schema_versions_are_bumped():
    """Layout changes must bump versions and expose one exact dimension."""
    assert int(sim.PUBLIC_OBS_VERSION) == 11
    assert int(sim.ACTION_SCHEMA_VERSION) == 10
    assert int(sim.PUBLIC_OBS_DIM) == 46023
    assert int(sim.PUBLIC_COMBAT_OBS_DIM) == 29651
    assert int(sim.CARD_FEAT_DIM) == 250
    assert int(sim.ACTION_FEAT_DIM) == 342


def test_binding_rejects_out_of_range_action_components():
    """pybind must reject integers that would wrap into a different action."""
    from agent.common import SCREEN
    from agent.heuristics import run_policy
    from agent.run_env import RunEnv

    env = RunEnv(3)
    guard = 0
    while env.screen != SCREEN.COMBAT and guard < 400:
        guard += 1
        assert env.step(run_policy(env))
    assert env.screen == SCREEN.COMBAT

    battle = env.battle
    play = next(
        a for a in battle.legal_actions()
        if a[0] == int(sim.ActionType.PLAY_CARD)
    )
    action_type, hand, target, uid = play
    with pytest.raises(ValueError, match="hand"):
        battle.step(action_type, hand + 256, target, uid)
    with pytest.raises(ValueError, match="target"):
        battle.step(action_type, hand, target + 256, uid)
    with pytest.raises(ValueError, match="uid"):
        battle.step(action_type, hand, target, uid + 65536)
    with pytest.raises(ValueError, match="hand"):
        battle.action_features(action_type, hand + 256, target, uid)
    with pytest.raises(ValueError, match="hand"):
        env.rc.step_combat(action_type, hand + 256, target, uid)


def test_status_cards_are_playable_when_data_allows_it():
    """D24: Slimed/Toxic are playable; Wound/Dazed are flagged unplayable."""
    slime = battle([card_id("Slimed")] * 10)
    play_card = int(sim.ActionType.PLAY_CARD)
    assert any(a[0] == play_card for a in slime.legal_actions())

    wound = battle([card_id("Wound")] * 10)
    assert not any(a[0] == play_card for a in wound.legal_actions())


def _base_cost(cid: int) -> int:
    # card_features lays out the CardId one-hot first, then cost / 3.
    return round(sim.card_features(cid, False)[sim.card_count()] * 3)


def test_discovery_free_card_retained_then_restored():
    """D11 end-to-end: Discovery's chosen card costs 0 this turn, survives
    Runic Pyramid retention, and gets its base cost back next turn."""
    discovery = card_id("Discovery")
    bc = battle([discovery] * 10, relics=[int(sim.RelicId.RUNIC_PYRAMID)])
    hand_idx = next(i for i, (cid, _, _, _) in enumerate(bc.hand) if cid == discovery)
    assert bc.step(int(sim.ActionType.PLAY_CARD), hand_idx, 0, 0)
    assert bc.pending_info[2] == 1 and bc.pending_info[3] == 3

    # Pick an offered card whose printed cost is non-zero, so the restore is
    # observable.  Determinism comes from the fixed combat seed.
    chosen = None
    for uid in list(bc.pending_options):
        probe = bc.clone()
        probe.step(int(sim.ActionType.CHOOSE), 0, 0, uid)
        entry = next((h for h in probe.hand if h[1] == uid), None)
        if entry is not None and _base_cost(entry[0]) > 0:
            chosen = entry
            break
    assert chosen is not None
    cid, uid, _, cost_now = chosen
    base = _base_cost(cid)
    assert cost_now == 0 and base > 0

    assert bc.step(int(sim.ActionType.CHOOSE), 0, 0, uid)
    in_hand = [h for h in bc.hand if h[1] == uid]
    assert in_hand and in_hand[0][3] == 0

    assert bc.step(int(sim.ActionType.END_TURN), 0, 0, 0)
    assert bc.turn == 2
    retained = [h for h in bc.hand if h[1] == uid]
    assert retained, "Runic Pyramid must retain the chosen card"
    assert retained[0][3] == base, "temporary cost must be restored next turn"


def test_oracle_strategies_are_never_player_usable():
    """D21: only player-information-compliant strategies may be quoted."""
    from deployment.evaluate import strategy_player_usable

    assert strategy_player_usable("heuristic")
    assert strategy_player_usable("network")
    assert strategy_player_usable("search_resampled")
    assert not strategy_player_usable("search")
    assert not strategy_player_usable("search_value")
    assert not strategy_player_usable("heuristic_oracle")


def test_benchmark_counts_real_terminal_outcomes(monkeypatch):
    """D23: completed_runs counts terminated episodes, not requested runs."""
    import agent.selfplay as selfplay
    from deployment.benchmark_speed import _bench_selfplay

    statuses = iter(["terminated", "truncated", "error", "terminated"])

    def fake_episode(seed, model, simulations, sample=False):
        status = next(statuses)
        return {"records": [], "won": status == "terminated", "floor": 1, "hp": 1,
                "status": status, "steps": 1, "simulations": 0}

    monkeypatch.setattr(selfplay, "play_episode", fake_episode)
    row = _bench_selfplay(1, 4)
    assert row["runs"] == 4
    assert row["completed_runs"] == 2
    assert row["truncated_runs"] == 1
    assert row["error_runs"] == 1
    assert row["win_rate"] == pytest.approx(1.0)
