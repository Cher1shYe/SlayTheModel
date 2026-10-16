"""Terminal reward provenance, tensor conditioning, and policy gradient tests."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
import torch

from spireformer.assemble import (
    WIN_RTG_SCHEME,
    _episode_trajectories,
    _episode_win_returns,
    assemble_raw_dataset,
)
from spireformer.data import TensorShardDataset
from spireformer.losses import SpireFormerLossConfig, compute_spireformer_loss
from spireformer.model import SpireFormer, SpireFormerConfig
from spireformer.raw_features import RawFeatureEncoder, RawFeatureSpec
from spireformer.raw_journal import load_episode
from spireformer.rewards import win_reward, win_returns_to_go
from spireformer.trajectory import collate_trajectories

from test_raw_journal import JournalBuilder


class _FeatureJournalBuilder(JournalBuilder):
    def add(self, kind, payload, **kwargs):
        if kind == "decision":
            payload = {**payload, "observation": {
                "schema_version": 5, "surface": "event", "players": [], "map_points": [],
            }}
        return super().add(kind, payload, **kwargs)


def _journal(
    path: Path, outcome: str = "win", *, cancelled: tuple[int, ...] = (),
    count: int = 5,
) -> Path:
    """Valid hash-chained journal deliberately has no HP observations/deltas."""

    journal = _FeatureJournalBuilder(path)
    journal.add("episode_started", {
        "reward_version": "whole-run-v2",
        "no_sl_expected": True,
        "metadata": {"observed_from_run_start": "True", "information_mode": "no_sl"},
    })
    for index in range(count):
        decision = journal.decision(index)
        attempt = journal.submit(decision)
        status = "cancelled" if index in cancelled else "observed_transition"
        journal.result(decision, attempt, status)
        if status != "cancelled":
            # The raw collector reward closes the action. Its value and its
            # components belong to a different reward definition.
            journal.add("reward", {
                "decision_id": decision["decision_id"],
                "reward_version": "whole-run-v2",
                "components": {"gold_delta": 17},
            }, step=index)
    journal.add("episode_finished", {
        "outcome": outcome,
        "termination_reason": "native_run_history",
        "completeness": "complete",
        "value_target_valid": True,
        "coverage_gap_count": 0,
        "rewind_count": 0,
        "unknown_save_load_count": 0,
        "manual_combat_input_count": 0,
        "unresolved_manual_combat_input_count": 0,
    })
    return journal.save()


def test_reward_distinguishes_ongoing_from_unverified_terminal_results() -> None:
    assert win_reward(None) == 0.0
    assert win_reward("defeat") == 0.0
    assert win_reward("win") == 1.0
    for invalid in ("abandoned", "interrupted", "truncated", "unknown", ""):
        with pytest.raises(ValueError):
            win_reward(invalid)
        with pytest.raises(ValueError):
            win_returns_to_go(invalid, 3)
    with pytest.raises(ValueError):
        win_returns_to_go(None, 3)
    for count in (0, -1, True, 1.5):
        with pytest.raises(ValueError):
            win_returns_to_go("win", count)


@pytest.mark.parametrize("outcome,expected", [("win", 1.0), ("defeat", 0.0)])
def test_returns_are_terminal_only_and_survive_window_cuts(
    tmp_path: Path, outcome: str, expected: float,
) -> None:
    audit = load_episode(_journal(tmp_path / "episode.jsonl", outcome))
    assert audit.value_target_valid
    values, report = _episode_win_returns(audit)
    assert values == {index: expected for index in range(5)}
    assert report["terminal_reward"] == expected
    spec = RawFeatureSpec.fit(step.decision.payload for step in audit.steps)
    trajectories, _ = _episode_trajectories(
        audit, RawFeatureEncoder(spec), 2, WIN_RTG_SCHEME,
    )
    assert [len(part.steps) for part in trajectories] == [2, 2, 1]
    assert [step.return_to_go for part in trajectories for step in part.steps] == [expected] * 5
    assert all(step.value_target is None for part in trajectories for step in part.steps)


@pytest.mark.parametrize("defect", [
    "invalid_audit", "old_reward_version", "missing_terminal",
    "abandoned", "interrupted", "truncated", "unknown", "missing_outcome",
    "non_native_terminal", "midrun", "missing_start_evidence", "invalid_start_evidence",
    "missing_initial_step", "noncontiguous_steps", "unknown_information", "sl",
    "save_load", "coverage_gap", "potion_loss", "illegal_potion_slot",
])
def test_strict_return_gate_rejects_unverified_sources(tmp_path: Path, defect: str) -> None:
    audit = load_episode(_journal(tmp_path / "episode.jsonl"))
    if defect == "invalid_audit":
        audit = replace(audit, value_target_valid=False)
    elif defect == "old_reward_version":
        audit.started.payload["reward_version"] = "whole-run-v1"
    elif defect == "missing_terminal":
        audit = replace(audit, finished=None)
    elif defect in ("abandoned", "interrupted", "truncated", "unknown", "missing_outcome"):
        audit.finished.payload["outcome"] = None if defect == "missing_outcome" else defect
    elif defect == "non_native_terminal":
        audit.finished.payload["termination_reason"] = "process_exit"
    elif defect in ("midrun", "missing_start_evidence", "invalid_start_evidence"):
        audit.started.payload["metadata"]["observed_from_run_start"] = {
            "midrun": False, "missing_start_evidence": None, "invalid_start_evidence": "yes",
        }[defect]
    elif defect == "missing_initial_step":
        audit = replace(audit, steps=audit.steps[1:])
    elif defect == "noncontiguous_steps":
        audit = replace(audit, steps=(audit.steps[0], *audit.steps[2:]))
    elif defect in ("unknown_information", "sl"):
        audit.steps[1].decision.payload["information_regime"] = (
            "unknown" if defect == "unknown_information" else "sl"
        )
    elif defect in ("save_load", "coverage_gap"):
        audit = replace(audit, events=(*audit.events, replace(audit.started, event_type=defect)))
    elif defect == "potion_loss":
        bad_step = replace(audit.steps[1], bc_reasons=("unexplained_outside_potion_decrease",))
        audit = replace(audit, steps=(audit.steps[0], bad_step, *audit.steps[2:]))
    elif defect == "illegal_potion_slot":
        payload = audit.steps[1].decision.payload
        payload["domain"] = "combat"
        payload["observation"] = {"players": [{"player_id": 1, "potions": []}]}
        payload["legal_actions"] = [{"kind": "use_potion", "actor_player_id": 1, "potion_index": 0}]
    with pytest.raises(ValueError):
        _episode_win_returns(audit)


def test_cancelled_final_input_does_not_drop_terminal_return(tmp_path: Path) -> None:
    audit = load_episode(_journal(tmp_path / "episode.jsonl", cancelled=(1, 4)))
    assert audit.value_target_valid
    spec = RawFeatureSpec.fit(step.decision.payload for step in audit.steps)
    trajectories, report = _episode_trajectories(
        audit, RawFeatureEncoder(spec), 64, WIN_RTG_SCHEME,
    )
    assert [[step.timestep for step in part.steps] for part in trajectories] == [[0], [2, 3]]
    assert report["excluded_steps"] == 2
    assert all(step.return_to_go == 1.0 for part in trajectories for step in part.steps)


def test_assembly_versions_reward_and_keeps_future_outcome_out_of_features(tmp_path: Path) -> None:
    victory = _journal(tmp_path / "victory.jsonl", "win")
    defeat = _journal(tmp_path / "defeat.jsonl", "defeat")
    win_id = load_episode(victory).episode_id
    loss_id = load_episode(defeat).episode_id
    result = assemble_raw_dataset(
        [victory, defeat], tmp_path / "dataset",
        train_episodes=[win_id], val_episodes=[loss_id],
        reward_scheme=WIN_RTG_SCHEME, max_window_steps=2,
    )
    assert result.report["reward_version"] == WIN_RTG_SCHEME
    assert result.report["conditioning"] == "realized_whole_run_return_to_go"
    assert result.report["reward_parameters"]["discount"] == 1.0
    datasets = [TensorShardDataset(
        result.output / split, verify_hashes=True, expected_reward_version=WIN_RTG_SCHEME,
    ) for split in ("train", "val")]
    assert all(dataset.manifest.reward_version == WIN_RTG_SCHEME for dataset in datasets)
    win_steps, loss_steps = [
        [step for part in dataset for step in part.steps] for dataset in datasets
    ]
    for winner, loser in zip(win_steps, loss_steps, strict=True):
        assert winner.return_to_go == 1.0
        assert loser.return_to_go == 0.0
        assert torch.equal(winner.entity_features, loser.entity_features)
        assert torch.equal(winner.legal_action_features, loser.legal_action_features)
        assert winner.value_target is loser.value_target is None
    with pytest.raises(ValueError, match="reward_version mismatch"):
        TensorShardDataset(result.output / "train", expected_reward_version="bc-only-v1")


def test_mixed_returns_reach_policy_and_receive_gradients(tmp_path: Path) -> None:
    audits = [load_episode(_journal(tmp_path / f"{outcome}.jsonl", outcome, count=2))
              for outcome in ("win", "defeat")]
    spec = RawFeatureSpec.fit(step.decision.payload for audit in audits for step in audit.steps)
    trajectories = [part for audit in audits for part in _episode_trajectories(
        audit, RawFeatureEncoder(spec), 64, WIN_RTG_SCHEME,
    )[0]]
    batch, targets = collate_trajectories(
        trajectories, entity_feature_dim=spec.entity_feature_dim,
        action_feature_dim=spec.action_feature_dim,
    )
    assert torch.equal(batch.returns_to_go[:, :, 0], torch.tensor([[1., 1.], [0., 0.]]))
    assert not targets.value_target_mask.any()
    torch.manual_seed(7)
    model = SpireFormer(SpireFormerConfig(
        entity_feature_dim=spec.entity_feature_dim,
        action_feature_dim=spec.action_feature_dim,
        model_dim=8, set_num_heads=2, set_num_layers=1, set_num_inducing_points=2,
        temporal_num_heads=2, temporal_num_layers=1, temporal_ff_multiplier=2,
        action_num_heads=2, dropout=0.0, max_timestep=8,
    ))
    output = model(batch)
    assert torch.isfinite(output.policy_logits).all()
    assert not torch.allclose(output.policy_logits[0], output.policy_logits[1])
    loss = compute_spireformer_loss(
        output, batch, targets, SpireFormerLossConfig(value_weight=0.0, entropy_weight=0.0),
    )
    loss.total.backward()
    gradient = model.temporal_core.return_projection.weight.grad
    assert gradient is not None and torch.isfinite(gradient).all()
    assert gradient.abs().sum().item() > 0
