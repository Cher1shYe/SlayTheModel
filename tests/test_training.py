"""Training-loop integrity: legal actions, episode status and checkpoint schema."""
from __future__ import annotations

import numpy as np
import pytest
import torch

from agent.card_train import collect_episode
from agent.common import SCREEN, new_run, screen_action, sim
from agent.nets import CardScorer, load_checkpoint, save_checkpoint


def test_screen_action_is_always_legal():
    """Events used to hard-code option 0 (illegal for Stone of All Time with no
    potions). Every screen action must be present in legal_actions()."""
    for seed in range(1, 41):
        rc = new_run(seed)
        guard = 0
        while rc.screen != SCREEN.RUN_OVER and guard < 400:
            guard += 1
            if rc.screen == SCREEN.COMBAT:
                assert rc.step_combat(*rc.battle.greedy_action(0.0, seed))
                continue
            action = screen_action(rc)
            legal = [(int(t), int(i)) for t, i in rc.legal_actions()]
            assert action in legal, (seed, rc.screen.name, action, legal)
            assert rc.step(*action)


def test_collect_episode_reports_status_and_filters_samples():
    torch.set_num_threads(1)
    model = CardScorer()
    seen = set()
    for seed in range(1, 13):
        ep = collect_episode(seed, model)
        seen.add(ep["status"])
        assert ep["status"] in ("terminated", "truncated", "error")
        if ep["status"] != "terminated":
            assert ep["records"] == []
            assert not ep["won"]
    assert "terminated" in seen


def test_checkpoint_schema_validation(tmp_path):
    torch.set_num_threads(1)
    model = CardScorer()
    path = tmp_path / "card.pt"
    save_checkpoint(path, model, {"iteration": 1})
    payload = load_checkpoint(path, CardScorer())
    assert payload["config"]["obs_version"] == int(sim.PUBLIC_OBS_VERSION)

    legacy = tmp_path / "legacy.pt"
    torch.save({"state_dict": model.state_dict()}, legacy)
    with pytest.raises(ValueError, match="legacy checkpoint"):
        load_checkpoint(legacy, CardScorer())

    # An older public-observation layout must be rejected, never silently
    # misaligned (the network input grew in v5).
    stale = tmp_path / "stale.pt"
    save_checkpoint(stale, CardScorer())
    payload = torch.load(stale, map_location="cpu", weights_only=False)
    payload["config"]["obs_version"] = int(sim.PUBLIC_OBS_VERSION) - 1
    torch.save(payload, stale)
    with pytest.raises(ValueError, match="observation version"):
        load_checkpoint(stale, CardScorer())


def test_selfplay_episode_records_match_public_schema():
    from agent.selfplay import play_episode
    from agent.nets import CombatNet

    torch.set_num_threads(1)
    model = CombatNet()
    ep = play_episode(5, model, simulations=2, sample=False)
    assert ep["status"] in ("terminated", "truncated", "error")
    for rec in ep["records"][:5]:
        assert rec.state.shape == (sim.PUBLIC_COMBAT_OBS_DIM,)
        assert rec.acts.shape[1] == sim.ACTION_FEAT_DIM
        assert abs(float(np.sum(rec.target)) - 1.0) < 1e-4


def test_hidden_zone_resampling_preserves_composition():
    from agent.common import sim as s

    bc = s.BattleContext()
    cards = [73, 74, 75, 76, 77, 78, 79, 80, 81, 82]
    bc.init(s.Encounter.SETUP_LAGAVULIN_MATRIARCH_BOSS, 5, cards,
            [False] * len(cards), 0, 200, 200, [], [])
    before = list(bc.draw)
    assert before
    bc.resample_hidden(12345)
    assert sorted(bc.draw) == sorted(before)
    assert bc.draw != before  # deterministic seed must actually permute


def test_search_reports_completed_simulations_and_resamples():
    from agent.run_env import RunEnv
    from agent.heuristics import run_policy

    env = RunEnv(3)
    guard = 0
    while env.screen != SCREEN.COMBAT and guard < 400:
        guard += 1
        assert env.step(run_policy(env))
    assert env.screen == SCREEN.COMBAT
    actions, visits, values, done = env.battle.search(8, 1.5, 0.05, 7, True)
    assert len(actions) == len(visits) == len(values)
    assert 0 < done <= 8
    assert sum(visits) == done


def test_prior_search_visits_every_action_once():
    from agent.run_env import RunEnv
    from agent.heuristics import run_policy

    env = RunEnv(3)
    guard = 0
    while env.screen != SCREEN.COMBAT and guard < 400:
        guard += 1
        assert env.step(run_policy(env))
    bc = env.battle
    n = len(bc.legal_actions())
    # Peaked priors: without the initialising pass every simulation would land
    # on the argmax action and the root search would just echo the network.
    priors = [1e-6] * n
    priors[0] = 1.0
    actions, visits, _values, done = bc.search_priors(n, priors, 1.5, 0.05, 7, True)
    assert done == n
    assert all(v == 1 for v in visits), visits
    assert len(set(actions)) == n


def test_policy_entry_points_are_legal_and_status_is_classified():
    from agent.policy import Strategy, play_run_strategy, summarize

    from agent.nets import CombatNet

    torch.set_num_threads(1)
    card_model, combat_model = CardScorer(), CombatNet()
    for strategy, model in (
            (Strategy(combat="heuristic", cards="heuristic"), card_model),
            (Strategy(combat="network", cards="network"), combat_model),
            (Strategy(combat="search", cards="network", simulations=2,
                      resample=True), combat_model),
            (Strategy(combat="search", cards="network", simulations=2,
                      resample=True, search_select="value"), combat_model)):
        result = play_run_strategy(2, model, strategy, card_model=card_model)
        assert result["status"] in ("terminated", "truncated", "error")
        assert 1 <= result["act"] <= 3
    summary = summarize([result])
    assert summary["runs"] == 1
    if result["status"] == "terminated":
        assert 0.0 <= summary["win_rate"] <= 1.0
        assert summary["win_ci95"][0] <= summary["win_rate"] <= summary["win_ci95"][1]
    else:
        assert summary["win_rate"] is None and summary["win_ci95"] is None
