"""Native reward evidence, decision-time returns, and tensor publication."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
from typing import Callable
from uuid import uuid4

import pytest
import torch

from spireformer.act_reward_journal import act_episode_returns
from spireformer.assemble import ACT_RTG_SCHEME, _episode_trajectories, assemble_raw_dataset
from spireformer.data import TensorShardDataset
from spireformer.raw_features import RawFeatureEncoder, RawFeatureSpec
from spireformer.raw_journal import EpisodeAudit, load_episode

from test_raw_journal import JournalBuilder


class _ActJournal(JournalBuilder):
    """Small complete journals with real combat/map observation structures."""

    def __init__(self, path: Path) -> None:
        super().__init__(path)
        self.next_step = 0
        self.domain = "outside_combat"
        self.surface = "map"
        self.act = 1
        self.add("episode_started", {
            "reward_version": "whole-run-v2", "no_sl_expected": True,
            "metadata": {"observed_from_run_start": "True", "information_mode": "no_sl"},
        })

    def add(self, kind, payload, **kwargs):
        if kind == "decision":
            # These are input-time public states, deliberately different from
            # the explicit reward boundaries. A start effect or final action
            # can change HP between these two native observation points.
            player = {
                "player_id": 1, "character_id": "CHARACTER.IRONCLAD",
                "current_hp": 19, "max_hp": 80, "gold": 99,
                "deck": [{"model_id": "CARD.DEFEND_IRONCLAD", "upgrade_level": 0}],
                "relics": [{"model_id": "RELIC.BURNING_BLOOD"}], "potions": [],
            }
            context = {
                "schema_version": 3, "act_index": self.act - 1,
                "total_floor": self.act * 10, "room_type": "Monster",
                "players": [player], "map": [],
            }
            if self.domain == "combat":
                observation = {
                    "schema_version": 5, "round_number": 1, "current_side": "Player",
                    "players": [{**player, "energy": 3, "stars": 0, "piles": [{
                        "pile_type": "Hand", "cards": [{
                            "combat_card_index": 7, "model_id": "CARD.DEFEND_IRONCLAD",
                            "upgrade_level": 0, "display": {"energy_cost": 1},
                        }],
                    }]}],
                    "creatures": [{"player_id": 1, "current_hp": 19, "max_hp": 80}],
                    "pending_manual_actions": [], "active_choice": None,
                }
                legal = [
                    {"kind": "end_turn", "actor_player_id": 1},
                    {"kind": "play_card", "actor_player_id": 1, "combat_card_index": 7},
                ]
            else:
                observation = {
                    "schema_version": 5, "surface": self.surface,
                    "act_index": self.act - 1, "players": [player], "map_points": [],
                }
                legal = payload["legal_actions"]
            self.action_keys = (
                ["combat:" + hashlib.sha256(json.dumps(
                    action, separators=(",", ":"), ensure_ascii=True,
                ).encode()).hexdigest() for action in legal]
                if self.domain == "combat" else payload["action_keys"]
            )
            payload = {**payload, "domain": self.domain, "observation": observation,
                       "context": {"run_context": context}, "legal_actions": legal,
                       "action_keys": self.action_keys}
        elif kind in ("action_submitted", "execution_result"):
            payload = {**payload, "selected_action_key": self.action_keys[payload["selected_action_index"]]}
        return super().add(kind, payload, **kwargs)

    def step(
        self, domain: str = "outside_combat", *, surface: str = "map",
        transition: Callable[[], None] | None = None,
    ) -> None:
        self.domain, self.surface = domain, surface
        decision = self.decision(self.next_step)
        self.next_step += 1
        attempt = self.submit(decision)
        if transition is not None:
            transition()
        self.result(decision, attempt, "observed_transition")
        # Raw action components may be flushed after the native boundary;
        # neither their timing nor their arbitrary values define this scheme.
        self.add("reward", {
            "decision_id": decision["decision_id"], "reward_version": "whole-run-v2",
            "components": {"hp_delta": 777, "gold_delta": 555},
        }, step=int(decision["step"]))

    def boundary(
        self, phase: str, combat_id: str, *, hp: int, max_hp: int,
        boss: bool = False, upgrades: int = 0, relics: int = 1,
        won: bool | None = None, act_completed: bool = False,
    ) -> None:
        self.add("diagnostic", {"code": "act_reward_boundary", "data": {
            "schema_version": 1, "phase": phase, "combat_id": combat_id,
            "act": self.act, "is_boss": boss, "hp": hp, "max_hp": max_hp,
            "upgraded_cards": upgrades, "relics": relics,
            "won": won, "act_completed": act_completed,
        }})
        if phase == "combat_start":
            self.add("diagnostic", {"code": "combat_started", "data": {
                "combat_id": combat_id, "encounter_id": "ENCOUNTER.TEST", "round": 1,
            }})

    def finish_run(self, outcome: str) -> Path:
        self.add("episode_finished", {
            "outcome": outcome, "termination_reason": "native_run_history",
            "completeness": "complete", "value_target_valid": True,
            "coverage_gap_count": 0, "rewind_count": 0, "unknown_save_load_count": 0,
            "manual_combat_input_count": 0, "unresolved_manual_combat_input_count": 0,
        })
        return self.save()


def _ordinary_run(path: Path, *, fatal: bool = False, boss: bool = False) -> _ActJournal:
    journal = _ActJournal(path)
    journal.step(transition=lambda: journal.boundary(
        "combat_start", "fight-1", hp=40 if fatal else 60, max_hp=80,
        boss=boss, upgrades=2, relics=3,
    ))
    journal.step("combat", transition=lambda: journal.boundary(
        "combat_end", "fight-1", hp=0 if fatal else 72, max_hp=100 if fatal else 90,
        boss=boss, won=not fatal,
    ))
    if not fatal:
        journal.step(surface="event")
    journal.finish_run("defeat")
    return journal


def _boss_run(
    path: Path, outcome: str = "win", *, acts: int = 3, trailing: bool = False,
) -> _ActJournal:
    journal = _ActJournal(path)
    for act in range(1, acts + 1):
        journal.act = act
        combat_id = f"boss-{act}"
        journal.step(transition=lambda: journal.boundary(
            "combat_start", combat_id, hp=30 if act == 3 else 60,
            max_hp=60 if act == 3 else 80, boss=True,
            upgrades=act * 2, relics=act * 2 + 1,
        ))
        won = outcome == "win" or act != acts
        journal.step("combat", transition=lambda: journal.boundary(
            "combat_end", combat_id, hp=1 if won else 0, max_hp=100,
            boss=True, upgrades=act * 2, relics=act * 2 + 1,
            won=won, act_completed=won,
        ))
    if trailing:
        journal.step(surface="rewards")
    journal.finish_run(outcome)
    return journal


def _audit(journal: _ActJournal) -> EpisodeAudit:
    audit = load_episode(journal.path)
    assert audit.value_target_valid
    assert all(step.bc_eligible for step in audit.steps)
    return audit


def _encode(audit: EpisodeAudit, window: int = 2):
    spec = RawFeatureSpec.fit(step.decision.payload for step in audit.steps)
    return _episode_trajectories(audit, RawFeatureEncoder(spec), window, ACT_RTG_SCHEME)


def _rewrite(
    journal: _ActJournal, mutate: Callable[[list[dict]], None], *, require_eligible: bool = True,
) -> EpisodeAudit:
    """Keep even intentionally bad reward evidence inside a valid hash chain."""
    records = deepcopy(journal.records)
    mutate(records)
    rewritten = JournalBuilder(journal.path)
    rewritten.episode_id = journal.episode_id
    for record in records:
        rewritten.add(record["event_type"], record["payload"],
                      step=record["global_step"], event_id=record["event_id"])
    rewritten.save()
    return _audit(journal) if require_eligible else load_episode(journal.path)


def _boundaries(records: list[dict]) -> list[dict]:
    return [record for record in records if record["event_type"] == "diagnostic"
            and record["payload"].get("code") == "act_reward_boundary"]


def test_settled_nonboss_hp_uses_post_max_and_outside_death_is_additive(tmp_path: Path) -> None:
    audit = _audit(_ordinary_run(tmp_path / "ordinary.jsonl"))
    returns, report = act_episode_returns(audit)
    # Net healing 72 - 60 is normalized by POST max 90, not initial max 80,
    # and not by the last input's intentionally different observed HP 19.
    expected = 12 / 90 - 10
    assert returns == pytest.approx({0: expected, 1: expected, 2: -10})
    assert report["total_reward"] == pytest.approx(expected)
    assert report["reward_component_totals"] == pytest.approx({
        "combat_hp": 12 / 90, "defeat": -10,
    })
    assert report["combat_boundaries"] == {"starts": 1, "ends": 1}


def test_preboss_counts_repeat_in_full_and_entry_reward_precedes_first_input(tmp_path: Path) -> None:
    audit = _audit(_boss_run(tmp_path / "win.jsonl", trailing=True))
    returns, report = act_episode_returns(audit)
    # Each map action receives its forthcoming entry bonus, while the first
    # boss input sees only rewards that remain after that bonus was received.
    assert returns == pytest.approx({0: 8.6, 1: 8.2, 2: 7.2, 3: 6.5, 4: 4.5, 5: 3, 6: 0})
    events = report["reward_events"]
    preparations = [event["components"] for event in events if event["kind"] == "combat_start"]
    assert [part["upgraded_cards"] for part in preparations] == pytest.approx([0.1, 0.2, 0.3])
    assert [part["relics"] for part in preparations] == pytest.approx([0.3, 0.5, 0.7])
    assert "act3_entry_hp" not in preparations[0]
    assert "act3_entry_hp" not in preparations[1]
    assert preparations[2]["act3_entry_hp"] == 0.5
    completions = [event["components"] for event in events if event["kind"] == "combat_end"]
    assert completions == [{"act_completion": 1}, {"act_completion": 2}, {"act_completion": 3}]
    assert report["reward_component_totals"] == pytest.approx({
        "upgraded_cards": 0.6, "relics": 1.5, "act3_entry_hp": 0.5, "act_completion": 6,
    })
    assert report["total_reward"] == pytest.approx(8.6)
    assert events[-1]["kind"] == "terminal" and events[-1]["reward"] == 0


@pytest.mark.parametrize("boss,expected", [(False, {0: -10.4, 1: -10.4}),
                                           (True, {0: -9.6, 1: -10.0})])
def test_combat_death_adds_penalty_without_boss_hp_reward(
    tmp_path: Path, boss: bool, expected: dict[int, float],
) -> None:
    audit = _audit(_ordinary_run(tmp_path / "death.jsonl", fatal=True, boss=boss))
    returns, report = act_episode_returns(audit)
    assert returns == pytest.approx(expected)
    assert report["reward_component_totals"]["defeat"] == -10
    assert sum(event["kind"] == "terminal" for event in report["reward_events"]) == 1
    assert ("combat_hp" in report["reward_component_totals"]) is not boss
    assert report["reward_component_totals"].get("act_completion", 0) == 0


def test_outside_death_before_any_fight_is_a_verified_negative_return(tmp_path: Path) -> None:
    journal = _ActJournal(tmp_path / "event-death.jsonl")
    journal.step(surface="event")
    journal.finish_run("defeat")
    returns, report = act_episode_returns(_audit(journal))
    assert returns == {0: -10}
    assert report["combat_boundaries"] == {"starts": 0, "ends": 0}
    assert report["total_reward"] == -10


def test_future_rewards_survive_two_step_window_cuts(tmp_path: Path) -> None:
    audit = _audit(_boss_run(tmp_path / "win.jsonl", trailing=True))
    trajectories, report = _encode(audit)
    assert [len(part.steps) for part in trajectories] == [2, 2, 2, 1]
    assert [step.return_to_go for part in trajectories for step in part.steps] == pytest.approx(
        [8.6, 8.2, 7.2, 6.5, 4.5, 3, 0],
    )
    assert all(step.value_target is None for part in trajectories for step in part.steps)
    assert report["total_reward"] == pytest.approx(8.6)


def test_shard_publication_keeps_reward_version_dimensions_and_no_future_features(tmp_path: Path) -> None:
    victory = _boss_run(tmp_path / "win.jsonl")
    defeat = _boss_run(tmp_path / "loss.jsonl", "defeat")
    result = assemble_raw_dataset(
        [victory.path, defeat.path], tmp_path / "dataset",
        train_episodes=[victory.episode_id], val_episodes=[defeat.episode_id],
        reward_scheme=ACT_RTG_SCHEME, max_window_steps=2, trajectories_per_shard=1,
    )
    assert result.report["reward_version"] == ACT_RTG_SCHEME
    assert result.report["conditioning"] == "realized_whole_run_return_to_go"
    assert result.report["reward_parameters"]["discount"] == 1
    assert result.report["reward_parameters"]["nonboss_combat_hp"] == "(post_hp - pre_hp) / post_max_hp"
    datasets = [TensorShardDataset(
        result.output / split, verify_hashes=True, expected_reward_version=ACT_RTG_SCHEME,
    ) for split in ("train", "val")]
    by_split = [[step for part in dataset for step in part.steps] for dataset in datasets]
    assert [step.return_to_go for step in by_split[0]] == pytest.approx([8.6, 8.2, 7.2, 6.5, 4.5, 3])
    assert [step.return_to_go for step in by_split[1]] == pytest.approx([-4.4, -4.8, -5.8, -6.5, -8.5, -10])
    for dataset, steps in zip(datasets, by_split, strict=True):
        assert dataset.manifest.reward_version == ACT_RTG_SCHEME
        assert dataset.manifest.step_count == 6
        assert len(dataset.manifest.shards) == 3
        assert all(step.entity_features.shape[-1] == result.report["entity_feature_dim"] for step in steps)
        assert all(step.legal_action_features.shape[-1] == result.report["action_feature_dim"] for step in steps)
        assert all(step.value_target is None for step in steps)
    for winner, loser in zip(*by_split, strict=True):
        assert torch.equal(winner.entity_features, loser.entity_features)
        assert torch.equal(winner.legal_action_features, loser.legal_action_features)
    with pytest.raises(ValueError, match="reward_version mismatch"):
        TensorShardDataset(result.output / "train", expected_reward_version="whole-run-win-v1")


def test_legacy_journal_with_inconsistent_generic_transitions_is_rejected(tmp_path: Path) -> None:
    journal = _ordinary_run(tmp_path / "legacy.jsonl")

    def remove_boundary_evidence(records: list[dict]) -> None:
        records[:] = [record for record in records
                      if record["payload"].get("code") != "act_reward_boundary"]

    audit = _rewrite(journal, remove_boundary_evidence)
    assert audit.value_target_valid
    with pytest.raises(ValueError, match="HP"):
        _encode(audit)
    output = tmp_path / "rejected-dataset"
    with pytest.raises(ValueError, match="HP"):
        assemble_raw_dataset([journal.path], output, train_episodes=[journal.episode_id],
                             reward_scheme=ACT_RTG_SCHEME)
    assert not output.exists()


def test_legacy_generic_states_and_transitions_derive_rewards_offline(tmp_path: Path) -> None:
    journal = _ordinary_run(tmp_path / "legacy-derived.jsonl")

    def make_generic(records: list[dict]) -> None:
        boundaries = _boundaries(records)
        start = next(item for item in boundaries if item["payload"]["data"]["phase"] == "combat_start")
        end = next(item for item in boundaries if item["payload"]["data"]["phase"] == "combat_end")
        end_index = records.index(end)
        records.insert(end_index, {
            **deepcopy(end),
            "event_id": str(uuid4()),
            "payload": {"code": "combat_ended", "data": {
                "combat_id": end["payload"]["data"]["combat_id"],
                "round": 1, "player_alive": True,
            }},
        })
        records[:] = [item for item in records if item not in boundaries]
        for item in records:
            step = item["global_step"]
            if item["event_type"] == "decision":
                player = item["payload"]["context"]["run_context"]["players"][0]
                hp, maximum = ((60, 80) if step in (0, 1) else (72, 90))
                player["current_hp"], player["max_hp"] = hp, maximum
                observed = item["payload"]["observation"]
                observed_player = (observed["creatures"][0]
                                   if item["payload"]["domain"] == "combat"
                                   else observed["players"][0])
                observed_player["current_hp"], observed_player["max_hp"] = hp, maximum
            elif item["event_type"] == "reward":
                item["payload"]["components"]["hp_delta"] = 12 if step == 1 else 0

    audit = _rewrite(journal, make_generic)
    returns, report = act_episode_returns(audit)
    assert returns == pytest.approx({0: 12 / 90 - 10, 1: 12 / 90 - 10, 2: -10})
    assert report["evidence_mode"] == "derived_from_public_journal_v1"
    assert report["postcombat_public_state_cross_checks"] == 1
    assert report["reward_component_totals"] == pytest.approx({
        "combat_hp": 12 / 90, "defeat": -10,
    })


@pytest.mark.parametrize("defect", [
    "missing_start", "missing_end", "missing_lifecycle", "duplicate_lifecycle",
    "wrong_lifecycle_id", "missing_lifecycle_id", "duplicate_start", "duplicate_end",
    "unavailable_capture", "combat_outside_active_boundary",
])
def test_lifecycle_coverage_rejects_incomplete_or_misattributed_rewards(tmp_path: Path, defect: str) -> None:
    journal = _ordinary_run(tmp_path / "bad-lifecycle.jsonl")

    def mutate(records: list[dict]) -> None:
        start, end = _boundaries(records)
        lifecycle = next(record for record in records if record["payload"].get("code") == "combat_started")
        if defect == "missing_start":
            records.remove(start)
        elif defect == "missing_end":
            records.remove(end)
        elif defect == "missing_lifecycle":
            records.remove(lifecycle)
        elif defect == "duplicate_lifecycle":
            duplicate = deepcopy(lifecycle)
            duplicate["event_id"] = str(uuid4())
            records.insert(records.index(lifecycle) + 1, duplicate)
        elif defect in ("wrong_lifecycle_id", "missing_lifecycle_id"):
            lifecycle["payload"]["data"]["combat_id"] = "other-fight" if defect == "wrong_lifecycle_id" else None
        elif defect in ("duplicate_start", "duplicate_end"):
            original = start if defect == "duplicate_start" else end
            duplicate = deepcopy(original)
            duplicate["event_id"] = str(uuid4())
            records.insert(records.index(original) + 1, duplicate)
        elif defect == "unavailable_capture":
            unavailable = deepcopy(end)
            unavailable["event_id"] = str(uuid4())
            unavailable["payload"] = {"code": "act_reward_boundary_unavailable", "data": {"reason": "missing run"}}
            records.insert(-1, unavailable)
        elif defect == "combat_outside_active_boundary":
            # Leave one matched start/end pair and lifecycle in the journal,
            # but close it before the first combat decision actually appears.
            records.remove(end)
            records.insert(records.index(lifecycle) + 1, end)

    audit = _rewrite(journal, mutate)
    with pytest.raises(ValueError):
        _encode(audit)


@pytest.mark.parametrize("phase,field,value", [
    ("combat_start", "schema_version", None),
    ("combat_start", "schema_version", True),
    ("combat_start", "schema_version", 2),
    ("combat_start", "phase", "combat_tick"),
    ("combat_start", "combat_id", ""),
    ("combat_start", "act", 0),
    ("combat_start", "act", True),
    ("combat_start", "is_boss", "true"),
    ("combat_start", "hp", -1),
    ("combat_start", "max_hp", 0),
    ("combat_start", "upgraded_cards", -1),
    ("combat_start", "relics", True),
    ("combat_start", "won", True),
    ("combat_start", "act_completed", True),
    ("combat_end", "combat_id", "other-fight"),
    ("combat_end", "act", 2),
    ("combat_end", "is_boss", False),
    ("combat_end", "won", "true"),
    ("combat_end", "act_completed", "true"),
])
def test_bad_boundary_fields_are_rejected(
    tmp_path: Path, phase: str, field: str, value: object,
) -> None:
    journal = _ordinary_run(tmp_path / "bad-field.jsonl", fatal=True, boss=True)

    def mutate(records: list[dict]) -> None:
        boundary = next(record for record in _boundaries(records)
                        if record["payload"]["data"]["phase"] == phase)
        boundary["payload"]["data"][field] = value

    audit = _rewrite(journal, mutate)
    with pytest.raises(ValueError, match="boundary"):
        _encode(audit)


@pytest.mark.parametrize("data", [None, [], "missing"])
def test_malformed_boundary_payload_is_rejected(tmp_path: Path, data: object) -> None:
    journal = _ordinary_run(tmp_path / "malformed.jsonl")
    audit = _rewrite(journal, lambda records: _boundaries(records)[0]["payload"].__setitem__("data", data))
    with pytest.raises(ValueError, match="boundary"):
        _encode(audit)


def test_missing_required_boundary_field_is_rejected(tmp_path: Path) -> None:
    journal = _ordinary_run(tmp_path / "missing-field.jsonl")
    audit = _rewrite(journal, lambda records: _boundaries(records)[0]["payload"]["data"].pop("hp"))
    with pytest.raises(ValueError, match="boundary"):
        _encode(audit)


def test_native_win_without_all_three_act_milestones_is_rejected(tmp_path: Path) -> None:
    audit = _audit(_boss_run(tmp_path / "incomplete-win.jsonl", acts=2))
    with pytest.raises(ValueError, match="three act milestones"):
        _encode(audit)


@pytest.mark.parametrize("defect", ["non_native_terminal", "missing_start_evidence", "unknown_information"])
def test_act_scheme_still_requires_the_whole_run_provenance_gate(tmp_path: Path, defect: str) -> None:
    journal = _boss_run(tmp_path / "unverified.jsonl")

    def mutate(records: list[dict]) -> None:
        if defect == "non_native_terminal":
            records[-1]["payload"]["termination_reason"] = "process_exit"
        elif defect == "missing_start_evidence":
            records[0]["payload"]["metadata"].pop("observed_from_run_start")
        else:
            next(record for record in records if record["event_type"] == "decision")["payload"]["information_regime"] = "unknown"

    # An unknown information regime already makes its raw decision ineligible.
    audit = _rewrite(journal, mutate, require_eligible=defect != "unknown_information")
    with pytest.raises(ValueError):
        _encode(audit)
