"""Integrity and training-mask tests for the raw collector journal reader.

The reader itself has no PyTorch dependency, so these tests load that single
module directly.  They can run with standard-library unittest before a model
environment has been installed.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from uuid import uuid4


MODULE_PATH = Path(__file__).resolve().parents[1] / "spireformer" / "raw_journal.py"
SPEC = importlib.util.spec_from_file_location("raw_journal_under_test", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
raw_journal = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = raw_journal
SPEC.loader.exec_module(raw_journal)


def _id() -> str:
    return str(uuid4())


class JournalBuilder:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.episode_id = _id()
        self.previous = "0" * 64
        self.generation = 0
        self.records: list[dict[str, object]] = []

    def add(
        self,
        kind: str,
        payload: dict[str, object],
        *,
        step: int | None = None,
        event_id: str | None = None,
    ) -> dict[str, object]:
        if kind == "save_load":
            self.generation += 1
        record: dict[str, object] = {
            "schema_version": 1,
            "event_type": kind,
            "event_id": event_id or _id(),
            "episode_id": self.episode_id,
            "event_sequence": len(self.records),
            "global_step": step,
            "timeline_generation": self.generation,
            "recorded_at_utc": "2026-09-30T00:00:00+00:00",
            "source": "live",
            "previous_event_sha256": self.previous,
            "payload": payload,
        }
        unsigned = json.dumps(record, separators=(",", ":"), ensure_ascii=False)
        digest = hashlib.sha256(unsigned.encode()).hexdigest()
        record["event_sha256"] = digest
        self.previous = digest
        self.records.append(record)
        return record

    def save(self) -> Path:
        with self.path.open("wb") as stream:
            for record in self.records:
                stream.write(
                    json.dumps(record, separators=(",", ":"), ensure_ascii=False).encode()
                    + b"\n"
                )
        return self.path

    def start(self) -> None:
        self.add("episode_started", {"reward_version": "whole-run-v2"})

    def decision(
        self, step: int, regime: str = "no_sl", *, action_kind: str = "stay"
    ) -> dict[str, object]:
        decision_id = _id()
        self.add(
            "decision",
            {
                "decision_id": decision_id,
                "domain": "outside_combat",
                "information_regime": regime,
                "state_fingerprint": "1" * 64,
                "observation": {},
                "legal_actions": [
                    {"action_id": "a", "kind": "leave", "ordinal": 0},
                    {"action_id": "b", "kind": action_kind, "ordinal": 1},
                ],
                "action_keys": ["a", "b"],
            },
            step=step,
            event_id=decision_id,
        )
        return {"decision_id": decision_id, "step": step}

    def submit(self, decision: dict[str, object], *, index: int = 1) -> str:
        attempt_id = _id()
        self.add(
            "action_submitted",
            {
                "decision_id": decision["decision_id"],
                "attempt_id": attempt_id,
                "selected_action_index": index,
                "selected_action_key": ("a", "b")[index],
                "policy": {"actor": "human", "mcts_visit_counts": None},
            },
            step=int(decision["step"]),
        )
        return attempt_id

    def result(
        self,
        decision: dict[str, object],
        attempt_id: str,
        status: str,
        *,
        detail: str | None = None,
    ) -> None:
        self.add(
            "execution_result",
            {
                "decision_id": decision["decision_id"],
                "attempt_id": attempt_id,
                "selected_action_index": 1,
                "selected_action_key": "b",
                "expected_state_fingerprint": "1" * 64,
                "status": status,
                "next_state_fingerprint": "2" * 64 if status == "observed_transition" else None,
                "detail": detail,
            },
            step=int(decision["step"]),
        )

    def reward(
        self, decision: dict[str, object], *, potion_count_delta: int | None = None
    ) -> None:
        components = {"hp_delta": 1.0}
        if potion_count_delta is not None:
            components["potion_count_delta"] = potion_count_delta
        self.add(
            "reward",
            {
                "decision_id": decision["decision_id"],
                "reward_version": "whole-run-v2",
                "components": components,
            },
            step=int(decision["step"]),
        )

    def finish(self, *, value: bool, gaps: int = 0, completeness: str = "complete") -> None:
        self.add(
            "episode_finished",
            {
                "completeness": completeness,
                "value_target_valid": value,
                "coverage_gap_count": gaps,
                "rewind_count": 0,
                "unknown_save_load_count": 0,
                "manual_combat_input_count": 0,
                "unresolved_manual_combat_input_count": 0,
            },
        )


class RawJournalTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / "legacy-uuid.jsonl"

    def test_complete_episode_keeps_cancelled_step_but_masks_it(self) -> None:
        journal = JournalBuilder(self.path)
        journal.start()
        first = journal.decision(0)
        attempt = journal.submit(first)
        journal.result(first, attempt, "observed_transition")
        journal.reward(first)
        second = journal.decision(1)
        cancelled = journal.submit(second)
        journal.result(second, cancelled, "cancelled")
        journal.finish(value=True)

        audit = raw_journal.load_episode(journal.save())
        self.assertEqual(audit.episode_id, journal.episode_id)
        self.assertTrue(audit.value_target_valid)
        self.assertEqual(len(audit.steps), 2)
        self.assertTrue(audit.steps[0].bc_eligible)
        self.assertTrue(audit.steps[0].value_eligible)
        self.assertTrue(audit.steps[0].transition_eligible)
        self.assertFalse(audit.steps[1].bc_eligible)
        self.assertFalse(audit.steps[1].value_eligible)
        self.assertIn("no_successful_execution", audit.steps[1].reasons)

    def test_unexplained_outside_potion_loss_masks_action_and_whole_run(self) -> None:
        journal = JournalBuilder(self.path)
        journal.start()
        before = journal.decision(0)
        attempt = journal.submit(before)
        journal.result(before, attempt, "observed_transition")
        journal.reward(before, potion_count_delta=0)
        affected = journal.decision(1, action_kind="choose_card")
        attempt = journal.submit(affected)
        journal.result(affected, attempt, "observed_transition")
        journal.reward(affected, potion_count_delta=-1)
        after = journal.decision(2)
        attempt = journal.submit(after)
        journal.result(after, attempt, "observed_transition")
        journal.reward(after, potion_count_delta=0)
        journal.finish(value=True)

        audit = raw_journal.load_episode(journal.save())
        self.assertFalse(audit.value_target_valid)
        self.assertTrue(audit.steps[0].bc_eligible)
        self.assertFalse(audit.steps[1].bc_eligible)
        self.assertEqual(
            audit.steps[1].bc_reasons,
            ("unexplained_outside_potion_decrease",),
        )
        self.assertTrue(audit.steps[2].bc_eligible)
        self.assertTrue(all(not step.value_eligible for step in audit.steps))

    def test_explicit_outside_potion_action_can_account_for_loss(self) -> None:
        journal = JournalBuilder(self.path)
        journal.start()
        decision = journal.decision(0, action_kind="use_potion")
        attempt = journal.submit(decision)
        journal.result(decision, attempt, "observed_transition")
        journal.reward(decision, potion_count_delta=-1)
        journal.finish(value=True)

        audit = raw_journal.load_episode(journal.save())
        self.assertTrue(audit.value_target_valid)
        self.assertTrue(audit.steps[0].bc_eligible)

    def test_late_related_gap_masks_only_target_and_episode_value(self) -> None:
        journal = JournalBuilder(self.path)
        journal.start()
        first = journal.decision(0)
        attempt = journal.submit(first)
        journal.result(first, attempt, "observed_transition")
        journal.reward(first)
        second = journal.decision(1)
        second_attempt = journal.submit(second)
        journal.result(second, second_attempt, "observed_transition")
        journal.reward(second)
        journal.add(
            "coverage_gap",
            {
                "related_decision_id": first["decision_id"],
                "related_attempt_id": attempt,
                "invalidates_pending_decision": False,
            },
        )
        journal.finish(value=False, gaps=1, completeness="incomplete")

        audit = raw_journal.load_episode(journal.save())
        self.assertFalse(audit.steps[0].bc_eligible)
        self.assertIn("coverage_gap", audit.steps[0].bc_reasons)
        self.assertTrue(audit.steps[1].bc_eligible)
        self.assertFalse(audit.steps[1].value_eligible)

    def test_rejected_retry_uses_only_successful_attempt(self) -> None:
        journal = JournalBuilder(self.path)
        journal.start()
        decision = journal.decision(0)
        rejected = journal.submit(decision)
        journal.result(decision, rejected, "rejected")
        successful = journal.submit(decision)
        journal.result(decision, successful, "applied")
        journal.reward(decision)
        journal.finish(value=True)

        audit = raw_journal.load_episode(journal.save())
        self.assertEqual(len(audit.steps[0].submissions), 2)
        self.assertEqual(audit.steps[0].submission.payload["attempt_id"], successful)
        self.assertTrue(audit.steps[0].bc_eligible)

    def test_hash_and_torn_line_are_rejected(self) -> None:
        journal = JournalBuilder(self.path)
        journal.start()
        journal.save()
        raw = self.path.read_bytes()
        self.path.write_bytes(raw.replace(b"whole-run-v2", b"whole-run-v1"))
        with self.assertRaisesRegex(raw_journal.JournalValidationError, "SHA-256"):
            raw_journal.load_episode(self.path)
        self.path.write_bytes(raw[:-1])
        with self.assertRaisesRegex(raw_journal.JournalValidationError, "newline"):
            raw_journal.load_episode(self.path)

    def test_sequence_or_generation_discontinuity_is_rejected(self) -> None:
        journal = JournalBuilder(self.path)
        journal.start()
        journal.decision(0)
        journal.records[1]["event_sequence"] = 3
        # A rehashed event must still fail the structural sequence check.
        unsigned = {k: v for k, v in journal.records[1].items() if k != "event_sha256"}
        journal.records[1]["event_sha256"] = hashlib.sha256(
            json.dumps(unsigned, separators=(",", ":")).encode()
        ).hexdigest()
        with self.assertRaisesRegex(raw_journal.JournalValidationError, "event_sequence"):
            raw_journal.load_episode(journal.save())

    def test_partial_episode_allows_bc_but_not_value(self) -> None:
        journal = JournalBuilder(self.path)
        journal.start()
        decision = journal.decision(0)
        attempt = journal.submit(decision)
        journal.result(decision, attempt, "observed_transition")
        journal.reward(decision)
        audit = raw_journal.load_episode(journal.save())
        self.assertTrue(audit.steps[0].bc_eligible)
        self.assertFalse(audit.steps[0].value_eligible)
        self.assertIsNone(audit.finished)

    def test_unknown_information_mode_masks_policy(self) -> None:
        journal = JournalBuilder(self.path)
        journal.start()
        decision = journal.decision(0, regime="unknown")
        attempt = journal.submit(decision)
        journal.result(decision, attempt, "observed_transition")
        journal.reward(decision)
        journal.finish(value=True)
        audit = raw_journal.load_episode(journal.save())
        self.assertFalse(audit.steps[0].bc_eligible)
        self.assertFalse(audit.value_target_valid)
        self.assertIn("information_regime_not_no_sl", audit.steps[0].bc_reasons)

    def test_set_template_checks_selected_cards_against_frozen_candidates(self) -> None:
        journal = JournalBuilder(self.path)
        journal.start()
        decision_id = _id()
        candidates = [
            {"option_index": 0, "model_id": "CARD.A"},
            {"option_index": 1, "model_id": "CARD.B"},
        ]
        journal.add(
            "decision",
            {
                "decision_id": decision_id,
                "domain": "outside_combat",
                "information_regime": "no_sl",
                "state_fingerprint": "1" * 64,
                "observation": {
                    "card_selection_options": candidates,
                    "choice_context": {"min_selections": 1, "max_selections": 2},
                },
                "legal_actions": [
                    {
                        "action_id": "card-set",
                        "kind": "choose_card_set",
                        "ordinal": 0,
                        "is_selection_template": True,
                    }
                ],
                "action_keys": ["card-set"],
            },
            step=0,
            event_id=decision_id,
        )
        submitted = journal.add(
            "action_submitted",
            {
                "decision_id": decision_id,
                "attempt_id": _id(),
                "selected_action_index": 0,
                "selected_action_key": "card-set",
                "policy": {"actor": "human"},
                "selected_action": {
                    "action_id": "card-set",
                    "kind": "choose_card_set",
                    "ordinal": 0,
                    "selected_cards": [candidates[1]],
                },
            },
            step=0,
        )
        self.assertEqual(len(raw_journal.load_episode(journal.save()).steps), 1)

        submitted["payload"]["selected_action"]["selected_cards"] = [
            {"option_index": 1, "model_id": "CARD.C"}
        ]
        unsigned = {k: v for k, v in submitted.items() if k != "event_sha256"}
        submitted["event_sha256"] = hashlib.sha256(
            json.dumps(unsigned, separators=(",", ":")).encode()
        ).hexdigest()
        with self.assertRaisesRegex(raw_journal.JournalValidationError, "frozen candidate"):
            raw_journal.load_episode(journal.save())


if __name__ == "__main__":
    unittest.main()
