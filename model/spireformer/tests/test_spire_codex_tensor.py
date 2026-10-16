from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import unittest


MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "spireformer"
    / "spire_codex_tensor.py"
)
SPEC = importlib.util.spec_from_file_location("spire_codex_tensor_test_module", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
spire_codex_tensor = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = spire_codex_tensor
SPEC.loader.exec_module(spire_codex_tensor)


def _run() -> dict[str, object]:
    return {
        "act": 1,
        "ascension": 7,
        "character": "IRONCLAD",
        "current_hp": 72,
        "max_hp": 80,
        "gold": 99,
        "floor": 1,
        "deck": [
            {"model_id": "STRIKE_IRONCLAD", "upgrade": 0},
            {"model_id": "DEFEND_IRONCLAD", "upgrade": 1},
        ],
        "relics": [{"model_id": "BURNING_BLOOD"}],
        "potions": [{"slot": 1, "model_id": "FIRE_POTION"}],
        "room": {"coord": "3,0", "kind": "ancient", "room_type": "ancient"},
        "map": {
            "nodes": [
                {"coordinate": "3,0", "kind": "ancient", "children": ["2,1"]},
                {"coordinate": "2,1", "kind": "monster", "children": []},
            ]
        },
    }


def _step() -> dict[str, object]:
    return {
        "record_type": "step",
        "episode_id": "episode-a",
        "segment_index": 0,
        "step_index": 4,
        "source_sequence": 12,
        "domain": "outside_combat",
        "source_kind": "recorded_decision",
        "bc_eligible": True,
        "choice": {"decision_type": "event", "source": "event"},
        "observation": {"run": _run(), "combat": None},
        "legal_actions": [
            {"kind": "event_option", "option_id": "OPTION_A"},
            {"kind": "event_option", "option_id": "OPTION_B"},
        ],
        "action": {"kind": "choose_option", "action_index": 1},
    }


class SpireCodexTensorBridgeTests(unittest.TestCase):
    def test_direct_choice_projects_public_state_and_label(self) -> None:
        decision = spire_codex_tensor.feature_decision(_step())

        self.assertEqual("outside_combat", decision["domain"])
        self.assertEqual("Event", decision["observation"]["surface"])
        self.assertEqual(99, decision["observation"]["players"][0]["gold"])
        self.assertEqual(3, decision["observation"]["players"][0]["max_potion_count"])
        self.assertEqual({"row": 0, "column": 3}, decision["observation"]["current_map_coordinate"])
        self.assertEqual(["choose_event_option", "choose_event_option"], [
            action["kind"] for action in decision["legal_actions"]
        ])
        self.assertEqual(1, decision["selected_action_index"])
        self.assertIsNone(decision["selected_action"])

    def test_set_selection_uses_one_template_and_concrete_selected_cards(self) -> None:
        step = _step()
        step.update(
            {
                "choice": {
                    "decision_type": "deck_select_upgrade",
                    "source": "deck_select",
                    "select_kind": "upgrade",
                },
                "legal_actions": None,
                "set_candidates": [
                    {"option_id": "STRIKE_IRONCLAD", "upgrade": 0},
                    {"option_id": "DEFEND_IRONCLAD", "upgrade": 1},
                ],
                "selection_bounds": {"minimum": 1, "maximum": 1, "can_decline": False},
                "action": {"kind": "select_set", "candidate_indices": [1]},
            }
        )

        decision = spire_codex_tensor.feature_decision(step)
        self.assertEqual(["choose_card_set"], [
            action["kind"] for action in decision["legal_actions"]
        ])
        self.assertEqual(0, decision["selected_action_index"])
        self.assertEqual(
            "DEFEND_IRONCLAD",
            decision["selected_action"]["selected_cards"][0]["model_id"],
        )

    def test_cancelable_set_choice_keeps_template_and_cancel_action(self) -> None:
        step = _step()
        step.update(
            {
                "choice": {
                    "decision_type": "deck_select_remove",
                    "source": "deck_select",
                    "select_kind": "remove",
                },
                "legal_actions": None,
                "set_candidates": [{"option_id": "STRIKE_IRONCLAD", "upgrade": 0}],
                "selection_bounds": {"minimum": 1, "maximum": 1, "can_decline": True},
                "action": {"kind": "decline"},
            }
        )

        decision = spire_codex_tensor.feature_decision(step)
        self.assertEqual(["remove_card_set", "cancel_choice"], [
            action["kind"] for action in decision["legal_actions"]
        ])
        self.assertEqual(1, decision["selected_action_index"])
        self.assertIsNone(decision["selected_action"])

    def test_rejects_ineligible_step(self) -> None:
        step = _step()
        step["bc_eligible"] = False
        with self.assertRaisesRegex(ValueError, "BC-eligible"):
            spire_codex_tensor.feature_decision(step)

    def test_split_is_deterministic_stratified_and_disjoint(self) -> None:
        episodes = tuple(
            spire_codex_tensor.EpisodeFeatures(
                episode_id=f"{character}-{index}",
                character=character,
                source_sha256=str(index) * 64,
                steps=({},),
            )
            for character in ("IRONCLAD", "SILENT")
            for index in range(10)
        )
        first = spire_codex_tensor.split_episodes(episodes)
        second = spire_codex_tensor.split_episodes(tuple(reversed(episodes)))
        self.assertEqual(first, second)
        self.assertEqual({"train", "val", "test"}, set(first))
        self.assertEqual(16, len(first["train"]))
        self.assertEqual(2, len(first["val"]))
        self.assertEqual(2, len(first["test"]))
        ids = [episode.episode_id for split in first.values() for episode in split]
        self.assertEqual(len(ids), len(set(ids)))


if __name__ == "__main__":
    unittest.main()
