"""Assembler boundaries that a structurally valid raw journal cannot prove."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
import torch

from spireformer.assemble import (
    HP_SAFE_RTG_SCHEME,
    _episode_returns,
    _episode_trajectories,
    _select_splits,
    _semantic_reasons,
)
from spireformer.cli import build_parser
from spireformer.raw_features import RawFeatureEncoder, RawFeatureSpec
from spireformer.raw_journal import EpisodeAudit, JournalEvent, StepAudit
from spireformer.trajectory import collate_trajectories


def _event(kind: str, sequence: int, step: int | None, payload: dict) -> JournalEvent:
    return JournalEvent(
        event_type=kind,
        event_id=f"event-{sequence}",
        episode_id="a" * 32,
        event_sequence=sequence,
        global_step=step,
        timeline_generation=0,
        payload=payload,
        event_sha256="0" * 64,
        record={},
    )


def _outside_step(sequence: int, global_step: int, *, eligible: bool = True) -> StepAudit:
    observation = {
        "schema_version": 4,
        "surface": "event",
        "players": [],
        "map_points": [],
    }
    legal = [
        {"action_id": "a", "kind": "leave", "ordinal": 0},
        {"action_id": "b", "kind": "choose_event_option", "ordinal": 1, "target_id": "EVENT.OPTION"},
    ]
    decision = _event(
        "decision", sequence, global_step,
        {
            "domain": "outside_combat",
            "information_regime": "no_sl",
            "observation": observation,
            "legal_actions": legal,
            "context": {},
        },
    )
    submission = _event(
        "action_submitted", sequence + 1, global_step,
        {"selected_action_index": 1, "selected_action": None,
         "policy": {"actor": "human"}},
    )
    return StepAudit(
        decision=decision,
        submission=submission if eligible else None,
        result=_event("execution_result", sequence + 2, global_step, {}) if eligible else None,
        reward=None,
        submissions=(submission,),
        results=(),
        bc_eligible=eligible,
        value_eligible=False,
        transition_eligible=False,
        bc_reasons=() if eligible else ("execution_status_cancelled",),
        value_reasons=("episode_value_target_invalid",),
        transition_reasons=(),
    )


def _combat_step(legal: list[dict], *, pending: list[dict] | None = None) -> StepAudit:
    player = {
        "player_id": 1,
        "piles": [{"pile_type": "Hand", "cards": [
            {"combat_card_index": 7, "model_id": "CARD.TEST"}
        ]}],
        "potions": [{"slot_index": 2, "model_id": "POTION.TEST"}],
    }
    decision = _event("decision", 1, 0, {
        "domain": "combat",
        "information_regime": "no_sl",
        "observation": {"players": [player], "pending_manual_actions": pending or []},
        "legal_actions": legal,
        "context": {"run_context": {"players": [{
            "player_id": 1,
            "potions": [{"slot_index": 2, "model_id": "POTION.TEST"}],
        }]}},
    })
    return StepAudit(
        decision=decision, submission=None, result=None, reward=None,
        submissions=(), results=(), bc_eligible=False, value_eligible=False,
        transition_eligible=False, bc_reasons=(), value_reasons=(),
        transition_reasons=(),
    )


def test_legacy_potion_and_queued_card_mismatches_are_excluded() -> None:
    step = _combat_step([
        {"kind": "use_potion", "actor_player_id": 1, "potion_index": 1},
        {"kind": "play_card", "actor_player_id": 1, "combat_card_index": 7},
        {"kind": "play_card", "actor_player_id": 1, "combat_card_index": 8},
    ], pending=[{"kind": "play_card", "actor_player_id": 1, "combat_card_index": 7}])
    assert set(_semantic_reasons(step)) == {
        "potion_slot_not_in_observation",
        "play_card_not_in_hand",
        "queued_card_offered_again",
    }


def test_potion_index_that_exists_but_refers_to_wrong_model_is_excluded() -> None:
    step = _combat_step([
        {"kind": "use_potion", "actor_player_id": 1, "potion_index": 2},
    ])
    # The legal action's slot is present, but the independent run context
    # identifies a different potion there.  This was the old sparse-slot bug.
    step.decision.payload["context"]["run_context"]["players"][0]["potions"][0]["model_id"] = "POTION.OTHER"
    assert _semantic_reasons(step) == ("potion_slots_disagree_with_run_context",)


def test_cancel_and_detached_gap_cut_previous_action_history(tmp_path: Path) -> None:
    source = tmp_path / "episode.jsonl"
    source.write_text("fixture\n", encoding="utf-8")
    first = _outside_step(1, 0)
    cancelled = _outside_step(5, 1, eligible=False)
    third = _outside_step(9, 2)
    fourth = _outside_step(15, 3)
    gap = _event("coverage_gap", 13, None, {})
    started = _event("episode_started", 0, None, {})
    audit = EpisodeAudit(
        path=source,
        episode_id="a" * 32,
        events=(started, first.decision, cancelled.decision, third.decision, gap, fourth.decision),
        steps=(first, cancelled, third, fourth),
        started=started,
        finished=None,
        value_target_valid=False,
    )
    spec = RawFeatureSpec.fit(
        (step.decision.payload for step in (first, third, fourth)),
        max_vocabulary_size=32,
    )
    trajectories, report = _episode_trajectories(audit, RawFeatureEncoder(spec), 64)
    assert [len(item.steps) for item in trajectories] == [1, 1, 1]
    assert report["bc_steps"] == 3
    assert report["excluded_steps"] == 1
    assert report["exclusion_reasons"] == {"execution_status_cancelled": 1}
    batch, targets = collate_trajectories(
        trajectories,
        entity_feature_dim=spec.entity_feature_dim,
        action_feature_dim=spec.action_feature_dim,
    )
    assert torch.count_nonzero(batch.previous_action_features).item() == 0
    assert targets.value_target_mask is not None
    assert not targets.value_target_mask.any()
    assert torch.count_nonzero(batch.returns_to_go).item() == 0


def test_episode_cannot_be_in_two_splits(tmp_path: Path) -> None:
    started = _event("episode_started", 0, None, {})
    audit = EpisodeAudit(tmp_path / "x.jsonl", "a" * 32, (started,), (), started, None, False)
    try:
        _select_splits((audit,), ("aaaaaaaa",), ("aaaaaaaa",), ())
    except ValueError as exc:
        assert "more than one split" in str(exc)
    else:
        raise AssertionError("episode overlap must be rejected")
    assert list(_select_splits((audit,), (), (), (), ("aaaaaaaa",))) == ["holdout"]
    second = EpisodeAudit(tmp_path / "y.jsonl", "b" * 32, (started,), (), started, None, False)
    try:
        _select_splits((audit, second), (), (), ())
    except ValueError as exc:
        assert "explicit" in str(exc)
    else:
        raise AssertionError("a directory of historical episodes needs an allowlist")


def _hp_step(sequence: int, global_step: int, hp: int, max_hp: int = 80) -> StepAudit:
    step = _outside_step(sequence, global_step)
    player = {"player_id": 1, "current_hp": hp, "max_hp": max_hp}
    step.decision.payload["observation"]["players"] = [dict(player)]
    step.decision.payload["context"] = {"run_context": {"players": [dict(player)]}}
    return step


def _complete_hp_audit(tmp_path: Path) -> EpisodeAudit:
    source = tmp_path / "episode.jsonl"
    source.write_text("fixture\n", encoding="utf-8")
    first = _hp_step(1, 0, 80)
    second = _hp_step(5, 1, 20)
    # Healing is already visible in the third decision, although its reward
    # event is published later by the collector.
    third = _hp_step(8, 2, 40)
    started = _event("episode_started", 0, None, {"reward_version": "whole-run-v2"})
    loss = _event("reward", 4, 0, {"components": {"hp_delta": -60}})
    healing = _event("reward", 10, 1, {"components": {"hp_delta": 20}})
    finished = _event("episode_finished", 11, None, {"outcome": "win"})
    return EpisodeAudit(
        path=source,
        episode_id="a" * 32,
        events=(started, first.decision, loss, second.decision,
                third.decision, healing, finished),
        steps=(first, second, third),
        started=started,
        finished=finished,
        value_target_valid=True,
    )


def test_hp_rtg_uses_decision_hp_when_reward_is_written_late(tmp_path: Path) -> None:
    audit = _complete_hp_audit(tmp_path)
    # Published pre-anchor journals already use a string provenance flag.
    audit.started.payload["metadata"] = {"observed_from_run_start": "True"}
    returns, report = _episode_returns(audit)
    assert returns == pytest.approx({0: 1.0, 1: 1.1, 2: 1.0})
    assert report["initial_max_hp"] == 80
    assert report["final_hp"] == 40
    assert report["initial_hp_source"] == "inferred_first_decision"
    spec = RawFeatureSpec.fit(
        (step.decision.payload for step in audit.steps), max_vocabulary_size=32
    )
    trajectories, _ = _episode_trajectories(
        audit, RawFeatureEncoder(spec), 64, HP_SAFE_RTG_SCHEME
    )
    assert [step.return_to_go for step in trajectories[0].steps] == pytest.approx(
        [1.0, 1.1, 1.0]
    )
    assert all(step.value_target is None for step in trajectories[0].steps)


def test_hp_rtg_rejects_incomplete_or_unverified_hp(tmp_path: Path) -> None:
    audit = _complete_hp_audit(tmp_path)
    incomplete = EpisodeAudit(
        audit.path, audit.episode_id, audit.events, audit.steps,
        audit.started, audit.finished, False,
    )
    with pytest.raises(ValueError, match="complete no-SL"):
        _episode_returns(incomplete)
    audit.steps[1].decision.payload["observation"]["players"][0]["current_hp"] = 19
    with pytest.raises(ValueError, match="HP disagree"):
        _episode_returns(audit)


def test_hp_rtg_reports_unexplained_outside_potion_step(tmp_path: Path) -> None:
    audit = _complete_hp_audit(tmp_path)
    affected = replace(
        audit.steps[1],
        bc_eligible=False,
        bc_reasons=("unexplained_outside_potion_decrease",),
    )
    audit = replace(
        audit,
        steps=(audit.steps[0], affected, audit.steps[2]),
        value_target_valid=False,
    )
    with pytest.raises(
        ValueError, match=r"unexplained_outside_potion_decrease at steps \[1\]"
    ):
        _episode_returns(audit)


def test_hp_rtg_cross_checks_new_boundary_metadata(tmp_path: Path) -> None:
    audit = _complete_hp_audit(tmp_path)
    audit.started.payload["metadata"] = {
        "observed_from_run_start": "True",
        "episode_start_current_hp": "80",
        "episode_start_max_hp": "80",
        "run_start_current_hp": "80",
        "run_start_max_hp": "80",
    }
    audit.finished.payload["summary"] = {
        "terminal_hp_status": "available",
        "terminal_current_hp": 40,
        "terminal_max_hp": 90,
    }
    _, report = _episode_returns(audit)
    assert report["initial_hp_source"] == "run_start_metadata"
    assert report["terminal_hp_cross_checked"] is True
    audit.finished.payload["summary"]["terminal_current_hp"] = 39
    with pytest.raises(ValueError, match="reward/terminal HP disagree"):
        _episode_returns(audit)


def test_hp_rtg_rejects_midrun_start_even_if_complete(tmp_path: Path) -> None:
    audit = _complete_hp_audit(tmp_path)
    audit.started.payload["metadata"] = {
        "observed_from_run_start": "False",
        "episode_start_current_hp": "80",
        "episode_start_max_hp": "80",
    }
    with pytest.raises(ValueError, match="after the run start"):
        _episode_returns(audit)


def test_cli_reward_scheme_is_explicit_and_defaults_to_bc_only() -> None:
    parser = build_parser()
    base = ["assemble", "--input", "a.jsonl", "--output", "out"]
    assert parser.parse_args(base).reward_scheme == "bc-only"
    assert parser.parse_args(base + ["--reward-scheme", HP_SAFE_RTG_SCHEME]).reward_scheme == HP_SAFE_RTG_SCHEME
