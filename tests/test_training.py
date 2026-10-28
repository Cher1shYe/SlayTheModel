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
