from __future__ import annotations

import pytest
import torch

from agent.armg import ARMG_ACTION_DIM, ARMG_FEATURE_VERSION, ARMG_OBS_DIM, ArmGScorer
from agent.nets import checkpoint_config
from deployment.evaluate_armg import evaluate_pairs, load_armg_checkpoint


def test_paired_evaluation_excludes_abnormal_and_keeps_episode_results():
    policy = object()
    calls = []

    def play(seed, model, **options):
        calls.append((seed, model, options))
        status = "error" if seed == 22 and model is policy else "terminated"
        return {"seed": seed, "status": status, "won": seed == 21 and model is policy,
                "floor": 10 + seed + (2 if model is policy else 0), "hp": 5,
                "records": [object()], "error": "blocked" if status == "error" else None,
                "cycle_recoveries": 3 if seed == 21 and model is policy else 0}

    from agent.run_reward import DeckElo
    deck_elo = DeckElo()
    report = evaluate_pairs(policy, [21, 22, 23], combat="search", simulations=32,
                            epsilon=0.05, max_steps=100, ascension=0, deck_elo=deck_elo,
                            play=play)
    assert len(calls) == 6
    # Both arms must run the same content profile and search budget so the
    # paired comparison measures the policy, not a different environment.
    from agent import content_profile
    from agent.armg_train import FloorBudget
    expected = {"deterministic": True, "combat": "search", "simulations": 32,
                "epsilon": 0.05, "max_steps": 100, "ascension": 0,
                "content_profile": content_profile.PROFILE, "deck_elo": deck_elo,
                "combat_budget_by_context": FloorBudget(32, 0, 0, 0)}
    assert all(c[2].keys() == expected.keys() for c in calls)
    assert all(c[2]["deck_elo"] is deck_elo for c in calls)
    for seed, _model, options in calls:
        assert options["deterministic"] is True
        assert options["content_profile"] == expected["content_profile"]
        assert options["combat_budget_by_context"].as_dict() ==             expected["combat_budget_by_context"].as_dict()
        for key in ("combat", "simulations", "epsilon", "max_steps", "ascension"):
            assert options[key] == expected[key]
    assert report["armg"]["errors"] == 1
    assert report["armg"]["completed"] == 2
    assert report["armg"]["win_rate_completed"] == 0.5
    assert report["armg"]["cycle_recoveries"] == 3
    assert report["armg"]["runs_with_recovery"] == 1
    assert report["heuristic"]["cycle_recoveries"] == 0
    assert report["heuristic"]["completed"] == 3
    assert report["paired"]["complete_pairs"] == 2
    assert report["paired"]["mean_floor_difference"] == 2
    assert report["paired"]["floor_difference_se"] == 0
    assert report["paired"]["armg_only_wins"] == 1
    assert report["episodes"]["armg"][1]["error"] == "blocked"
    assert all("records" not in r for r in report["episodes"]["armg"])


def test_paired_evaluation_no_completed_pairs_and_duplicate_seed():
    def play(seed, model, **kwargs):
        return {"seed": seed, "status": "truncated", "won": False,
                "floor": 9, "hp": 1}

    kwargs = dict(combat="greedy", simulations=1, epsilon=0, max_steps=3, play=play)
    report = evaluate_pairs(object(), [1], **kwargs)
    assert report["paired"]["complete_pairs"] == 0
    assert report["paired"]["mean_floor_difference"] is None
    assert report["armg"]["win_rate_completed"] is None
    assert report["heuristic"]["truncated"] == 1
    with pytest.raises(ValueError, match="unique"):
        evaluate_pairs(object(), [1, 1], **kwargs)


def test_armg_checkpoint_rejects_semantically_wrong_features(tmp_path):
    model = ArmGScorer()
    config = checkpoint_config(model) | {"armg_feature_version": ARMG_FEATURE_VERSION,
                                         "armg_obs_dim": ARMG_OBS_DIM,
                                         "armg_action_dim": ARMG_ACTION_DIM}
    path = tmp_path / "model.pt"
    torch.save({"state_dict": model.state_dict(), "config": config}, path)
    load_armg_checkpoint(path, model)
    config["armg_feature_version"] += 1
    torch.save({"state_dict": model.state_dict(), "config": config}, path)
    with pytest.raises(ValueError, match="armg_feature_version"):
        load_armg_checkpoint(path, model)


def test_ppo_actor_checkpoint_loads_for_evaluation(tmp_path):
    """agent.armg_train writes an actor-critic; evaluation needs the actor only."""
    import torch
    from agent.armg_ppo import ArmGActorCritic
    from agent.armg_train import _save

    model = ArmGActorCritic()
    optimizer = torch.optim.Adam(model.parameters(), lr=1e-3)
    _save(tmp_path / "latest.pt", model, optimizer, {"games": 0}, {"algorithm": "ppo"})
    scorer = ArmGScorer()
    payload = load_armg_checkpoint(tmp_path / "latest.pt", scorer)
    assert payload["settings"]["algorithm"] == "ppo"
    for actor_weight, scorer_weight in zip(model.actor.state_dict().values(),
                                           scorer.state_dict().values()):
        assert torch.equal(actor_weight, scorer_weight)
