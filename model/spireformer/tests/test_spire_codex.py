"""Tests for the safe Spire Codex reconstruction boundary."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
import unittest


MODULE_PATH = Path(__file__).resolve().parents[1] / "spireformer" / "spire_codex.py"
SPEC = importlib.util.spec_from_file_location("spire_codex_under_test", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
spire_codex = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = spire_codex
SPEC.loader.exec_module(spire_codex)


def _events() -> list[dict[str, object]]:
    events: list[dict[str, object]] = [
        {
            "t": "header",
            "s": 0,
            "ms": 1,
            "seed": "SECRET",
            "start_time": 123,
            "rng_state": {"shuffle": 9},
            "replay_version": 7,
            "mod_version": "v1.2.1",
            "build_id": "v0.111.0",
            "character": "IRONCLAD",
            "ascension": 3,
            "reloads": 0,
            "starting_max_hp": 80,
            "mods": [
                {"id": "BaseLib", "affects_gameplay": False},
                {"id": "SpireCodex", "affects_gameplay": False},
            ],
            "relics": [{"id": "BURNING_BLOOD"}],
            "potions": [{"slot": 0}],
            "starting_deck": [{"c": 1, "id": "STRIKE_IRONCLAD", "up": 0}],
        },
        {"t": "deck", "s": 1, "cards": [{"c": 1, "id": "STRIKE_IRONCLAD", "up": 0}]},
        {"t": "hp", "s": 2, "dst": "player", "hp": 80},
        {
            "t": "decision",
            "s": 3,
            "decision_id": 1,
            "decision_type": "event",
            "source": "event",
            "event_id": "NEOW",
            "act": 1,
            "floor": 1,
            "options": [
                {
                    "option_index": 0,
                    "option_kind": "event_option",
                    "option_id": "SAFE_OPTION",
                    "presented": True,
                    "selectable": True,
                    "label": "localized",
                    "desc": "localized prose",
                }
            ],
        },
        {
            "t": "outcome",
            "s": 4,
            "decision_id": 1,
            "decision_type": "event",
            "outcome": "chosen",
            "option_index": 0,
        },
        {
            "t": "combat_start",
            "s": 5,
            "encounter": "TEST_ENCOUNTER",
            "rng_state": {"monster_ai": 4},
            "enemies": [{"i": 0, "cid": 99, "id": "TEST_ENEMY", "hp": 20, "max_hp": 20}],
        },
        {"t": "draw_order", "s": 6, "order_c": [10], "order_deck_c": [1]},
        {"t": "energy", "s": 7, "energy": 3},
        {"t": "draw", "s": 8, "c": 10, "deck_c": 1, "id": "STRIKE_IRONCLAD"},
        {"t": "turn", "s": 9, "side": "player", "n": 1, "round": 1},
        {
            "t": "intent",
            "s": 10,
            "src": "TEST_ENEMY",
            "src_cid": 99,
            "id": "ATTACK",
            "intents": ["attack"],
            "dmg": 5,
            "hits": 1,
        },
        {
            "t": "play",
            "s": 11,
            "c": 10,
            "deck_c": 1,
            "id": "STRIKE_IRONCLAD",
            "up": 0,
            "target": "TEST_ENEMY",
            "target_cid": 99,
            "auto": False,
            "cost_paid": 1,
            "stars_paid": 0,
            "result_pile": "discard",
        },
        {"t": "flush", "s": 12, "flushed_c": [], "retained_c": []},
        {"t": "end_turn", "s": 13, "side": "player", "n": 1, "round": 1},
        {"t": "combat_end", "s": 14, "result": "victory"},
        {
            "t": "end",
            "s": 15,
            "terminal_reason": "death",
            "is_game_over": True,
            "capture_status": "complete",
            "hp": 0,
            "max_hp": 80,
        },
    ]
    return events


class SpireCodexConversionTests(unittest.TestCase):
    def test_public_outside_step_and_combat_replay_step(self) -> None:
        records, report = spire_codex.convert_events(
            "0123456789abcdef", _events(), source_sha256="a" * 64
        )
        steps = [record for record in records if record["record_type"] == "step"]
        self.assertEqual(3, len(steps))

        outside = steps[0]
        self.assertTrue(outside["bc_eligible"])
        self.assertTrue(outside["legal_actions_complete"])
        self.assertEqual(99, outside["observation"]["run"]["gold"])
        self.assertEqual(1, outside["observation"]["run"]["floor"])
        self.assertEqual(0, outside["action"]["action_index"])
        self.assertEqual("SAFE_OPTION", outside["legal_actions"][0]["option_id"])

        play = steps[1]
        self.assertFalse(play["bc_eligible"])
        self.assertTrue(play["native_replay_eligible"])
        self.assertEqual("STRIKE_IRONCLAD", play["action"]["card"]["model_id"])
        self.assertEqual("TEST_ENEMY", play["action"]["target"]["model_id"])
        self.assertEqual(
            ["STRIKE_IRONCLAD"],
            [card["model_id"] for card in play["observation"]["combat"]["piles"]["hand"]],
        )

        end_turn = steps[2]
        self.assertTrue(end_turn["native_replay_eligible"])
        self.assertFalse(end_turn["reconstructed_observation_valid"])
        self.assertEqual([], end_turn["native_replay_exclusion_reasons"])
        self.assertEqual(
            [],
            [card["model_id"] for card in end_turn["observation"]["combat"]["piles"]["hand"]],
        )
        self.assertEqual(1, report["bc_eligible_steps"])

    def test_hidden_and_native_source_fields_are_absent(self) -> None:
        records, _ = spire_codex.convert_events(
            "0123456789abcdef", _events(), source_sha256="a" * 64
        )
        encoded = json.dumps(records, ensure_ascii=False, sort_keys=True)
        for forbidden in (
            '"seed"',
            '"rng_state"',
            '"draw_order"',
            '"order_c"',
            '"order_deck_c"',
            '"start_time"',
            '"label"',
            '"desc"',
            '"instance_id"',
            '"cid"',
            '"deck_c"',
        ):
            self.assertNotIn(forbidden, encoded)

    def test_deck_set_selection_uses_candidates_without_instance_ids(self) -> None:
        events = _events()
        events[3] = {
            "t": "decision",
            "s": 3,
            "decision_id": 1,
            "decision_type": "deck_select_upgrade",
            "source": "deck_select",
            "min_select": 1,
            "max_select": 1,
            "decline_available": False,
            "options": [
                {
                    "option_index": 0,
                    "option_kind": "upgrade",
                    "option_id": "STRIKE_IRONCLAD",
                    "instance_id": 1,
                    "up": 0,
                    "presented": True,
                    "selectable": True,
                }
            ],
        }
        events[4] = {
            "t": "outcome",
            "s": 4,
            "decision_id": 1,
            "decision_type": "deck_select_upgrade",
            "outcome": "select",
            "selected_option_indices": [0],
        }
        records, _ = spire_codex.convert_events(
            "0123456789abcdef", events, source_sha256="a" * 64
        )
        step = next(record for record in records if record.get("domain") == "outside_combat")
        self.assertTrue(step["bc_eligible"])
        self.assertEqual([0], step["action"]["candidate_indices"])
        self.assertNotIn("instance_id", step["set_candidates"][0])

    def test_resumed_segment_is_retained_but_not_trainable(self) -> None:
        events = _events()
        events[-1] = {
            "t": "end",
            "s": 14,
            "terminal_reason": "left_run",
            "is_game_over": False,
            "capture_status": "complete",
            "hp": 80,
            "max_hp": 80,
        }
        resumed_header = dict(events[0])
        resumed_header.update({"s": 15, "reloads": 1, "floor": 1})
        events.extend(
            [
                resumed_header,
                {
                    "t": "resume",
                    "s": 16,
                    "act": 1,
                    "floor": 1,
                    "hp": 80,
                    "gold": 99,
                    "relics": [{"id": "BURNING_BLOOD"}],
                    "potions": [],
                },
                {
                    "t": "decision",
                    "s": 17,
                    "decision_id": 2,
                    "decision_type": "event",
                    "source": "event",
                    "event_id": "TEST_EVENT",
                    "options": [
                        {
                            "option_index": 0,
                            "option_kind": "event_option",
                            "option_id": "TEST_OPTION",
                            "presented": True,
                            "selectable": True,
                        }
                    ],
                },
                {
                    "t": "outcome",
                    "s": 18,
                    "decision_id": 2,
                    "decision_type": "event",
                    "outcome": "chosen",
                    "option_index": 0,
                },
                {
                    "t": "end",
                    "s": 19,
                    "terminal_reason": "death",
                    "is_game_over": True,
                    "capture_status": "complete",
                    "hp": 0,
                    "max_hp": 80,
                },
            ]
        )
        records, _ = spire_codex.convert_events(
            "0123456789abcdef", events, source_sha256="a" * 64
        )
        resumed = next(record for record in records if record.get("source_sequence") == 17)
        self.assertFalse(resumed["bc_eligible"])
        self.assertIn("resumed_segment_unverified", resumed["bc_exclusion_reasons"])


if __name__ == "__main__":
    unittest.main()
