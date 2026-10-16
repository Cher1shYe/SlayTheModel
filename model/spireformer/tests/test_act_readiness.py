"""Training readiness must not substitute provenance or boundary evidence."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
from uuid import uuid4

import pytest

from spireformer.act_readiness import audit_act_reward_data, format_readiness_summary
from test_act_reward_journal import _ordinary_run, _rewrite


def _cli():
    path = Path(__file__).resolve().parents[3] / "scripts/audit-act-reward-data.py"
    spec = importlib.util.spec_from_file_location("act_readiness_cli_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _policy(records: list[dict], policy_id: str, teacher: str | None) -> None:
    for record in records:
        if record["event_type"] == "action_submitted":
            record["payload"]["policy"].update({
                "actor": "policy", "policy_id": policy_id, "teacher_information": teacher,
            })


def test_complete_human_audit_binds_source_without_writing(tmp_path: Path) -> None:
    journal = _ordinary_run(tmp_path / "human.jsonl")
    before = journal.path.read_bytes()
    report = audit_act_reward_data([tmp_path])
    episode = report["episodes"][0]
    assert report["training_ready_episode_count"] == 1
    assert report["training_ready_step_count"] == 3
    assert episode["source_sha256"] == hashlib.sha256(before).hexdigest()
    assert episode["decisions_by_domain"] == {"combat": 1, "outside_combat": 2}
    assert episode["human_bc_steps"] == 3
    assert episode["act_reward_boundaries"] == {"starts": 1, "ends": 1, "other": 0}
    assert episode["submission_actors"] == {"human": 3}
    assert "READY" in format_readiness_summary(report)
    assert list(tmp_path.iterdir()) == [journal.path]
    assert journal.path.read_bytes() == before


@pytest.mark.parametrize("policy_id,teacher,allowed,ready,candidates", [
    ("native-mcts", "native_checkpoint_privileged", (), False, 3),
    ("native-mcts", "native_checkpoint_privileged", ("native-mcts",), True, 3),
    ("native-mcts", None, ("native-mcts",), False, 0),
    ("native-mcts", "public_observation", ("native-mcts",), False, 0),
    ("observed-automation", "native_checkpoint_privileged", ("native-mcts",), False, 0),
    ("first-legal", "public_observation", ("first-legal",), True, 0),
])
def test_policy_sources_require_explicit_opt_in_and_evidence(
    tmp_path: Path, policy_id: str, teacher: str | None, allowed: tuple[str, ...],
    ready: bool, candidates: int,
) -> None:
    journal = _ordinary_run(tmp_path / "policy.jsonl")
    _rewrite(journal, lambda records: _policy(records, policy_id, teacher))
    report = audit_act_reward_data([journal.path], allowed_policy_ids=allowed)
    episode = report["episodes"][0]
    assert episode["training_ready"] is ready
    assert episode["human_bc_steps"] == 0
    assert episode["native_mcts_candidate_steps"] == candidates
    assert episode["submission_policy_ids"] == {policy_id: 3}
    assert report["training_ready_step_count"] == (3 if ready else 0)


def test_unknown_mode_and_missing_boundaries_remain_independent_blockers(tmp_path: Path) -> None:
    journal = _ordinary_run(tmp_path / "legacy.jsonl")

    def mutate(records: list[dict]) -> None:
        _policy(records, "native-mcts", "native_checkpoint_privileged")
        for record in records:
            if record["event_type"] == "decision":
                record["payload"]["information_regime"] = "unknown"
            if record["event_type"] == "diagnostic" and record["payload"].get("code") == "act_reward_boundary":
                record["payload"]["code"] = "legacy_boundary"

    _rewrite(journal, mutate, require_eligible=False)
    report = audit_act_reward_data([journal.path], allowed_policy_ids=("native-mcts",))
    episode = report["episodes"][0]
    assert episode["journal_valid"]
    assert episode["information_regimes"] == {"unknown": 3}
    assert episode["native_mcts_candidate_steps"] == 0
    assert episode["training_eligible_steps"] == 0
    assert not episode["act_source_gate"]["passed"]
    assert not episode["complete_run_gate"]["passed"]
    assert not episode["act_reward_evidence_gate"]["passed"]
    assert episode["act_reward_boundaries"]["starts"] == 0


def test_corrupt_source_does_not_hide_remaining_episodes_or_recurse_compact(tmp_path: Path) -> None:
    _ordinary_run(tmp_path / "human.jsonl")
    corrupt = tmp_path / "corrupt.jsonl"
    corrupt.write_text('{"bad":"hash"}\n', encoding="utf-8")
    compact = tmp_path / "_compact"
    compact.mkdir()
    (compact / "derived.compact.jsonl").write_text("not a source\n", encoding="utf-8")
    report = audit_act_reward_data([tmp_path, corrupt])
    assert report["source_count"] == 2
    assert report["valid_journal_count"] == 1
    assert report["training_ready_episode_count"] == 1
    broken = next(item for item in report["episodes"] if not item["journal_valid"])
    assert broken["source_sha256"] == hashlib.sha256(corrupt.read_bytes()).hexdigest()
    assert "event hash" in broken["error"]


def test_linked_and_detached_gaps_cut_history_but_keep_safe_reward_labels(tmp_path: Path) -> None:
    journal = _ordinary_run(tmp_path / "gaps.jsonl")

    def mutate(records: list[dict]) -> None:
        decision = next(record for record in records if record["event_type"] == "decision")
        for related in (decision["event_id"], None):
            records.insert(-1, {
                "event_id": str(uuid4()), "event_type": "coverage_gap", "global_step": None,
                "payload": {"reason": "fixture_missing_choice", "related_decision_id": related},
            })
        records[-1]["payload"].update({"coverage_gap_count": 2, "value_target_valid": False})

    _rewrite(journal, mutate, require_eligible=False)
    episode = audit_act_reward_data([journal.path])["episodes"][0]
    assert episode["coverage_gap_count"] == 2
    assert [gap["related_global_step"] for gap in episode["coverage_gaps"]] == [0, None]
    assert episode["act_reward_evidence_gate"]["passed"]
    assert not episode["complete_run_gate"]["passed"]
    assert episode["act_source_gate"]["passed"]
    assert episode["training_eligible_steps"] == 2
    assert episode["training_ready"]


def test_cli_explicit_json_output_and_exit_status(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    module = _cli()
    journal = _ordinary_run(tmp_path / "human.jsonl")
    report_path = tmp_path / "reports/audit.json"
    assert module.main([str(journal.path), "--output", str(report_path)]) == 0
    report = json.loads(report_path.read_text())
    assert report["read_only"] and not report["tensor_output_created"]
    assert report["training_ready_episode_count"] == 1
    assert "1/1 episodes ready" in capsys.readouterr().out
    journal.path.write_text("broken source\n", encoding="utf-8")
    assert module.main([str(journal.path)]) == 1
    assert "INVALID" in capsys.readouterr().out


def test_cli_cannot_overwrite_a_source_even_through_json_symlink(tmp_path: Path) -> None:
    module = _cli()
    journal = _ordinary_run(tmp_path / "human.jsonl")
    before = journal.path.read_bytes()
    alias = tmp_path / "source-alias.json"
    alias.symlink_to(journal.path)
    with pytest.raises(SystemExit) as error:
        module.main([str(journal.path), "--output", str(alias)])
    assert error.value.code == 2
    assert journal.path.read_bytes() == before


def test_no_inputs_and_unsupported_policy_are_actionable_errors(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="no published JSONL"):
        audit_act_reward_data([tmp_path])
    with pytest.raises(ValueError, match="only native-mcts and first-legal"):
        audit_act_reward_data([tmp_path], allowed_policy_ids=("observed-automation",))
