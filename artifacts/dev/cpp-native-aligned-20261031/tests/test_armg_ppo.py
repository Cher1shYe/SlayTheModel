"""PPO objective, masking, GAE and trajectory accounting for agent/armg_ppo.py."""
from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest
import torch

from agent.armg import ARMG_ACTION_DIM, ARMG_OBS_DIM
from agent.armg_ppo import (
    ArmGActorCritic, TrajectoryRecorder, batch_tensors, clipped_loss, diagnostics,
    gae, prepare, update,
)


# Cumulative reward read *before* each action. The increment between two reads
# is what the earlier action earned, so it must land on the earlier row.
CUMS = (0.0, 0.2, 0.2, 0.5)
TOTAL = 1.0
EXPECTED_ROWS = (0.2, 0.0, 0.3, 0.5)
EXPECTED_RETURNS = (1.0, 0.8, 0.8, 0.5)


def make_episode(model, seed=1, forced=False, counts=(2, 5, 1, 3), total=TOTAL):
    rng = np.random.default_rng(seed)
    recorder = TrajectoryRecorder(model)
    for j, n in enumerate(counts):
        obs = rng.normal(0, 0.1, ARMG_OBS_DIM).astype(np.float32)
        features = rng.normal(0, 0.1, (n, ARMG_ACTION_DIM)).astype(np.float32)
        recorder.record(obs, features, j % n, forced, CUMS[j])
    return {"status": "terminated", "ppo_records": recorder.finish(total)}


# ------------------------------------------------------------ trajectory
def test_transition_rewards_sum_to_the_terminal_reward():
    model = ArmGActorCritic()
    rows = make_episode(model)["ppo_records"]
    assert [r["reward"] for r in rows] == pytest.approx(list(EXPECTED_ROWS))
    assert sum(r["reward"] for r in rows) == pytest.approx(TOTAL)


def test_finish_rejects_a_mismatched_terminal_total():
    model = ArmGActorCritic()
    recorder = TrajectoryRecorder(model)
    rng = np.random.default_rng(0)
    recorder.record(rng.normal(size=ARMG_OBS_DIM).astype(np.float32),
                    rng.normal(size=(3, ARMG_ACTION_DIM)).astype(np.float32), 0, False, 0.0)
    recorder.rows[-1]["reward"] = 0.5           # simulate a lost increment
    with pytest.raises(RuntimeError, match="transition rewards"):
        recorder.finish(1.0)


def test_forced_rows_stay_in_the_trajectory_but_not_the_actor():
    model = ArmGActorCritic()
    rows = make_episode(model)["ppo_records"]
    assert [r["actor_valid"] for r in rows] == [True, True, False, True]
    assert all(not r["actor_valid"] for r in make_episode(model, forced=True)["ppo_records"])
    for row in rows:
        probs = np.exp(row["old_logps"])
        assert probs.sum() == pytest.approx(1.0, abs=1e-5)
        assert row["old_logp"] == pytest.approx(row["old_logps"][row["choice"]])
        assert np.isfinite(row["old_value"])


def test_nonfinite_rollout_is_refused():
    model = ArmGActorCritic()
    recorder = TrajectoryRecorder(model)
    with pytest.raises(RuntimeError, match="nonfinite"):
        recorder.record(np.full(ARMG_OBS_DIM, np.nan, dtype=np.float32),
                        np.zeros((2, ARMG_ACTION_DIM), dtype=np.float32), 0, False, 0.0)


# -------------------------------------------------------------------- GAE
def test_gae_matches_the_closed_form_and_never_bootstraps():
    advantages, returns = gae([0.2, 0.3, 1.0], [0.1, 0.4, 0.8], gamma=1.0, lam=1.0)
    assert returns == pytest.approx([1.5, 1.3, 1.0])
    assert advantages == pytest.approx([1.4, 0.9, 0.2])
    assert gae([0.2, 0.3, 1.0], [0.1, 0.4, 0.8], gamma=1.0, lam=0.0)[0] == pytest.approx([0.5, 0.7, 0.2])


def test_gae_validates_inputs():
    with pytest.raises(ValueError):
        gae([0.1], [0.1, 0.2])
    with pytest.raises(ValueError):
        gae([0.1], [0.1], gamma=1.5)
    with pytest.raises(ValueError):
        gae([float("inf")], [0.1])


def test_prepare_rejects_truncation_and_keeps_episodes_separate():
    model = ArmGActorCritic()
    a, b = make_episode(model, 1), make_episode(model, 2)
    rows = prepare([a, b], lam=1.0)
    assert [r["target"] for r in rows[:4]] == pytest.approx(list(EXPECTED_RETURNS))
    assert [r["target"] for r in rows[4:]] == pytest.approx(list(EXPECTED_RETURNS))
    # Advantages are normalised over actor-valid rows only.
    valid = [r["advantage"] for r in rows if r["actor_valid"]]
    assert np.mean(valid) == pytest.approx(0.0, abs=1e-5)
    assert all(r["advantage"] == 0.0 for r in rows if not r["actor_valid"])
    with pytest.raises(ValueError, match="complete"):
        prepare([dict(a, status="truncated")])


# -------------------------------------------------------------- objective
def test_clipped_loss_clips_both_signs_and_gets_zero_gradient_outside():
    log_ratio = torch.log(torch.tensor([1.5, 0.5, 1.5, 0.5])).requires_grad_()
    loss = clipped_loss(log_ratio, torch.tensor([1.0, 1.0, -1.0, -1.0]), 0.2)
    assert loss.detach().numpy() == pytest.approx([-1.2, -0.5, 1.5, 0.8])
    loss.sum().backward()
    assert log_ratio.grad.numpy() == pytest.approx([0.0, -0.5, 1.5, 0.0])


def test_batch_tensors_masks_ragged_action_counts():
    model = ArmGActorCritic()
    rows = prepare([make_episode(model)])
    obs, candidates, mask, old_logps = batch_tensors(rows)
    assert obs.shape == (4, ARMG_OBS_DIM)
    assert candidates.shape == (4, 5, ARMG_ACTION_DIM)
    assert mask.sum(1).tolist() == [2, 5, 1, 3]
    assert (old_logps[~mask] == 0).all()


# ----------------------------------------------------------------- update
def test_update_moves_actor_and_critic_and_reports_finite_metrics():
    torch.set_num_threads(1)
    torch.manual_seed(3)
    model = ArmGActorCritic()
    episodes = [make_episode(model, i) for i in range(3)]
    before = {k: v.clone() for k, v in model.state_dict().items()}
    optimizer = torch.optim.Adam(model.parameters(), lr=1e-3)
    stats = update(model, optimizer, episodes, minibatch_size=4, epochs=2)
    assert stats["updates"] > 0
    assert stats["actor_decisions"] == 9
    assert stats["decisions"] == 12
    assert stats["exact_kl"] >= 0
    assert stats["entropy"] > 0
    assert any(not torch.equal(before[k], v) for k, v in model.state_dict().items()
               if k.startswith("actor."))
    assert any(not torch.equal(before[k], v) for k, v in model.state_dict().items()
               if k.startswith("critic."))
    assert all(torch.isfinite(p).all() for p in model.parameters())
    for key in ("policy_loss", "value_loss", "grad_norm", "clip_fraction"):
        assert np.isfinite(stats[key])


def test_stale_rollout_is_refused_instead_of_silently_reused():
    torch.set_num_threads(1)
    model = ArmGActorCritic()
    episodes = [make_episode(model)]
    optimizer = torch.optim.Adam(model.parameters(), lr=1e-3)
    update(model, optimizer, episodes, epochs=1, minibatch_size=4)
    with pytest.raises(RuntimeError, match="stale"):
        update(model, optimizer, episodes, epochs=1, minibatch_size=4)


def test_forced_only_episode_cannot_move_the_actor():
    torch.set_num_threads(1)
    model = ArmGActorCritic()
    before = [p.clone() for p in model.actor.parameters()]
    stats = update(model, torch.optim.Adam(model.parameters(), lr=1e-3),
                   [make_episode(model, forced=True)], epochs=1)
    assert stats["actor_decisions"] == 0
    assert all(torch.equal(a, b) for a, b in zip(before, model.actor.parameters()))


def test_kl_early_stop_triggers_on_a_large_update():
    torch.set_num_threads(1)
    model = ArmGActorCritic()
    stats = update(model, torch.optim.Adam(model.parameters(), lr=0.1),
                   [make_episode(model, i) for i in range(4)],
                   epochs=4, minibatch_size=4, target_kl=1e-5)
    assert stats["kl_early_stop"] and stats["updates"] < 16


@pytest.mark.parametrize("kwargs", [
    {"epochs": 0}, {"minibatch_size": 0}, {"clip_ratio": 0.0}, {"clip_ratio": 1.0},
    {"target_kl": 0.0}, {"max_grad_norm": 0.0}, {"value_coef": -1.0},
])
def test_invalid_hyperparameters_are_rejected(kwargs):
    model = ArmGActorCritic()
    with pytest.raises(ValueError):
        update(model, torch.optim.Adam(model.parameters()), [make_episode(model)], **kwargs)


def test_diagnostics_explained_variance_is_none_without_variance():
    model = ArmGActorCritic()
    rows = prepare([make_episode(model)])
    for row in rows:
        row["target"] = 1.0
    assert diagnostics(model, rows, 4)["explained_variance"] is None


# ------------------------------------------------------- information note
def test_module_documents_the_information_boundary():
    import agent.armg_ppo as ppo
    doc = ppo.__doc__ or ""
    assert "public_observation" in doc
    assert "external" in doc and "not" in doc

def test_need_overlay_probability_and_ragged_update():
    from agent.armg_need import apply_need_to_logits
    torch.set_num_threads(1)
    torch.manual_seed(19)
    model = ArmGActorCritic()
    recorder = TrajectoryRecorder(model)
    rng = np.random.default_rng(19)
    for n in (3, 5):
        obs = rng.normal(size=ARMG_OBS_DIM).astype(np.float32)
        features = rng.normal(size=(n, ARMG_ACTION_DIM)).astype(np.float32)
        bonus = np.arange(n, dtype=np.float32) / 2
        allowed = np.ones(n, dtype=bool)
        allowed[1] = False
        with torch.no_grad():
            logits = model(torch.from_numpy(obs)[None], torch.from_numpy(features)[None])[0]
            expected = apply_need_to_logits(logits, bonus, allowed, True).softmax(0)
        recorder.record(obs, features, 0, False, 0.0, bonus=bonus, allowed=allowed)
        row = recorder.rows[-1]
        assert np.exp(row['old_logps']) == pytest.approx(expected.numpy(), abs=1e-7)
        assert row['old_logp'] == pytest.approx(float(expected[0].log()), abs=1e-6)
    ep = {'status': 'terminated', 'ppo_records': recorder.finish(1.0)}
    assert diagnostics(model, prepare([ep]), 2)['exact_kl'] < 1e-6
    stats = update(model, torch.optim.Adam(model.parameters(), lr=1e-4), [ep], epochs=1)
    assert stats['updates'] > 0
    assert np.isfinite(stats['entropy']) and np.isfinite(stats['grad_norm'])
