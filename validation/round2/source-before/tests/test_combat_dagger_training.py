from pathlib import Path
import json

import numpy as np
import pytest
import torch

from agent.combat_dagger import (
    ACTION_FEAT_DIM, PUBLIC_COMBAT_OBS_DIM, CombatPolicy, CombatValue,
    add_replay, load_combat_checkpoint, replay_batches, restore_checkpoint,
    save_checkpoint, train_batch,
)


def _shard(path: Path, n=3):
    states = np.zeros((n, PUBLIC_COMBAT_OBS_DIM), dtype=np.float32)
    actions = np.zeros((2 * n, ACTION_FEAT_DIM), dtype=np.float32)
    for j in range(n):
        states[j, 0] = j / 10
        actions[2 * j, 0] = 1.0
        actions[2 * j + 1, 1] = 1.0
    np.savez_compressed(path, states=states, actions=actions,
                        offsets=np.arange(0, 2 * n + 1, 2, dtype=np.int64),
                        labels=np.array([0, 1, -1][:n], dtype=np.int64),
                        wins=np.ones(n, dtype=np.float32), hp=np.full(n, 0.5, dtype=np.float32))


def test_fifo_replay_and_bounded_shard_loading(tmp_path):
    a, b = tmp_path / "a.npz", tmp_path / "b.npz"
    _shard(a)
    _shard(b)
    entries = [{"path": str(a), "count": 3}, {"path": str(b), "count": 3}]
    manifest = add_replay([], entries, 4)
    assert manifest[0]["start"] == 2
    batches = list(replay_batches(manifest, 3, np.random.default_rng(7)))
    assert [len(batch) for batch in batches] == [3, 1]
    assert all(len(a[1]) == 2 for batch in batches for a in batch)
    assert a.exists() and b.exists()


def test_masked_microbatch_optimizer_matches_one_batch(tmp_path):
    torch.set_num_threads(1)
    torch.manual_seed(42)
    a, b = CombatPolicy(), CombatValue()
    a2, b2 = CombatPolicy(), CombatValue()
    a2.load_state_dict(a.state_dict())
    b2.load_state_dict(b.state_dict())
    opt_a, opt_b = torch.optim.Adam(a.parameters()), torch.optim.Adam(b.parameters())
    opt_a2, opt_b2 = torch.optim.Adam(a2.parameters()), torch.optim.Adam(b2.parameters())
    p = tmp_path / "batch.npz"
    _shard(p)
    batch = next(replay_batches([{"path": str(p), "start": 0, "count": 3}], 3,
                                np.random.default_rng(0)))
    result = train_batch(a, b, opt_a, opt_b, batch, microbatch=1)
    direct = train_batch(a2, b2, opt_a2, opt_b2, batch, microbatch=3)
    assert result["policy_examples"] == 2
    assert result["policy_loss"] == pytest.approx(direct["policy_loss"], rel=1e-5)
    assert result["value_loss"] == pytest.approx(direct["value_loss"], rel=1e-5)
    # Adam magnifies tiny cancellation differences at mathematically zero
    # gradients. Compare the accumulated gradients themselves.
    for left, right in zip(a.parameters(), a2.parameters()):
        assert torch.allclose(left.grad, right.grad, atol=1e-6, rtol=1e-5)
    for left, right in zip(b.parameters(), b2.parameters()):
        assert torch.allclose(left.grad, right.grad, atol=1e-6, rtol=1e-5)


def test_checkpoint_restores_optimizer_progress_and_rejects_schema_mismatch(tmp_path):
    policy, value = CombatPolicy(), CombatValue()
    po, vo = torch.optim.Adam(policy.parameters()), torch.optim.Adam(value.parameters())
    path = tmp_path / "checkpoint.pt"
    settings, progress = {"teacher_sims": 512}, {"stage": "dagger", "total_games": 10}
    save_checkpoint(path, policy, value, po, vo, progress, settings, [])
    p2, v2 = CombatPolicy(), CombatValue()
    p2o, v2o = torch.optim.Adam(p2.parameters()), torch.optim.Adam(v2.parameters())
    restored, manifest = restore_checkpoint(path, p2, v2, p2o, v2o, settings)
    assert restored == progress and manifest == []
    assert all(torch.equal(x, y) for x, y in zip(policy.parameters(), p2.parameters()))
    # Checkpoints from before the train-threads option represent one thread.
    restored, _ = restore_checkpoint(path, p2, v2, p2o, v2o,
                                     {"teacher_sims": 512, "train_threads": 1})
    assert restored == progress
    with pytest.raises(ValueError, match="settings"):
        restore_checkpoint(path, p2, v2, p2o, v2o,
                           {"teacher_sims": 512, "train_threads": 4})
    with pytest.raises(ValueError, match="settings"):
        restore_checkpoint(path, p2, v2, p2o, v2o, {"teacher_sims": 64})
    bad = torch.load(path, weights_only=False)
    bad["config"]["obs_version"] = -1
    torch.save(bad, tmp_path / "bad.pt")
    with pytest.raises(ValueError, match="schema"):
        load_combat_checkpoint(tmp_path / "bad.pt", CombatPolicy())


def test_resume_teacher_budget_change_is_explicit_and_preserves_replay(tmp_path):
    policy, value = CombatPolicy(), CombatValue()
    policy_opt = torch.optim.Adam(policy.parameters())
    value_opt = torch.optim.Adam(value.parameters())
    path = tmp_path / "best.pt"
    old = {"teacher_sims": 512, "teacher_mode": "oracle", "train_threads": 1}
    progress = {"stage": "done", "round": 6, "total_games": 2900}
    manifest = [{"path": "old.npz", "count": 1, "start": 0, "teacher_sims": 512}]
    save_checkpoint(path, policy, value, policy_opt, value_opt, progress, old, manifest)
    restored_policy, restored_value = CombatPolicy(), CombatValue()
    restored_po = torch.optim.Adam(restored_policy.parameters())
    restored_vo = torch.optim.Adam(restored_value.parameters())
    new = {**old, "teacher_sims": 1024}
    with pytest.raises(ValueError, match="settings"):
        restore_checkpoint(path, restored_policy, restored_value, restored_po, restored_vo, new)
    with pytest.raises(ValueError, match="beyond teacher_sims"):
        restore_checkpoint(path, restored_policy, restored_value, restored_po, restored_vo,
                           {**new, "teacher_mode": "resampled"}, allow_teacher_sims_change=True)
    restored, replay = restore_checkpoint(path, restored_policy, restored_value,
                                          restored_po, restored_vo, new,
                                          allow_teacher_sims_change=True)
    assert replay == manifest and replay[0]["teacher_sims"] == 512
    assert restored["round"] == 6 and restored["total_games"] == 2900
    change = restored["teacher_sims_changes"][0]
    assert (change["from"], change["to"], change["at_round"]) == (512, 1024, 6)
    assert change["source_checkpoint"] == str(path.resolve())
    assert len(change["source_sha256"]) == 64
    assert all(torch.equal(x, y) for x, y in zip(policy.parameters(), restored_policy.parameters()))


def test_replay_rejects_shards_from_another_run(tmp_path):
    path = tmp_path / "data.npz"
    _shard(path)
    with np.load(path) as old:
        fields = {key: old[key] for key in old.files}
    meta = {"run_id": "other", "seed": 11, "policy_sha256": "policy",
            "armg_sha256": "armg", "teacher_sims": 512, "resample_hidden": False,
            "battle_mode": "student", "obs_version": 10, "action_schema_version": 9,
            "episode_status": "terminated"}
    fields["metadata_json"] = np.asarray(json.dumps(meta))
    np.savez_compressed(path, **fields)
    entry = {**meta, "run_id": "this-run", "path": str(path), "count": 3, "start": 0}
    with pytest.raises(ValueError, match="run_id"):
        list(replay_batches([entry], 3, np.random.default_rng(0)))


def test_replay_accepts_a_mixture_of_recorded_teacher_budgets(tmp_path):
    entries = []
    for budget in (512, 1024):
        path = tmp_path / f"{budget}.npz"
        _shard(path)
        with np.load(path) as old:
            fields = {key: old[key] for key in old.files}
        meta = {"run_id": "same", "seed": budget, "policy_sha256": "policy",
                "armg_sha256": "armg", "teacher_sims": budget, "resample_hidden": False,
                "battle_mode": "student", "obs_version": 10, "action_schema_version": 9,
                "episode_status": "terminated"}
        fields["metadata_json"] = np.asarray(json.dumps(meta))
        np.savez_compressed(path, **fields)
        entries.append({**meta, "path": str(path), "count": 3, "start": 0})
    samples = list(replay_batches(entries, 6, np.random.default_rng(0)))
    assert len(samples) == 1 and len(samples[0]) == 6
