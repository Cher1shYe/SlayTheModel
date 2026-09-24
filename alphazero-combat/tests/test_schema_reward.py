from __future__ import annotations
from pathlib import Path
from tempfile import TemporaryDirectory

import unittest

from azcombat.reward import Outcome, TerminalResult, score_result
from azcombat.schema import ActionNode, ObservationError, validate_observation
from azcombat.samples import TrainingSample, read_jsonl, write_jsonl


def observation():
    return {
        "schemaVersion": 1,
        "roundNumber": 2,
        "currentSide": "Player",
        "players": [{
            "playerId": 1, "characterId": "IRONCLAD", "energy": 2, "stars": 0,
            "turnNumber": 2, "phase": "PlayerTurn",
            "piles": [{"pileType": "Hand", "cards": [{
                "combatCardIndex": 3, "modelId": "STRIKE_IRONCLAD", "energyCost": 1,
                "afflictionId": None, "afflictionCount": 0, "keywords": [],
            }]}],
            "relics": [], "potions": [], "orbs": [],
        }],
        "creatures": [{
            "combatId": 1, "playerId": 1, "monsterId": None,
            "currentHp": 70, "maxHp": 80, "block": 0, "powers": [],
        }],
    }


class SchemaTests(unittest.TestCase):
    def test_accepts_combat_projection(self):
        self.assertEqual(validate_observation(observation()).round_number, 2)

    def test_rejects_rng_and_future_intent(self):
        for forbidden in ("runRng", "playerRng", "monsterIntent", "futureDraws", "nativeCardJson", "stateFingerprint"):
            with self.subTest(forbidden=forbidden):
                data = observation()
                data[forbidden] = {}
                with self.assertRaises(ObservationError):
                    validate_observation(data)

    def test_rejects_nested_unknown_fields(self):
        data = observation()
        data["creatures"][0]["nextIntent"] = "ATTACK"
        with self.assertRaises(ObservationError):
            validate_observation(data)

    def test_nested_action_tree_and_end_turn(self):
        ActionNode("PlayCard", "play:3", children=(
            ActionNode("Target", "target:9", children=(
                ActionNode("CardSubset", "cards:1,2", terminal=True),
            )),
        )).validate()
        ActionNode("EndTurn", "end", terminal=True).validate()
        with self.assertRaises(ValueError):
            ActionNode("EndTurn", "end").validate()


class RewardTests(unittest.TestCase):
    def test_every_win_beats_unresolved_and_loss(self):
        win = score_result(TerminalResult(Outcome.WIN, 80, 1, 30, 30))
        unresolved = score_result(TerminalResult(Outcome.UNRESOLVED, 80, 0, 29, 30))
        loss = score_result(TerminalResult(Outcome.LOSS, 80, 0, 30, 30))
        self.assertGreater(win, unresolved)
        self.assertGreaterEqual(unresolved, loss)

    def test_less_player_damage_improves_win_value(self):
        light = score_result(TerminalResult(Outcome.WIN, 80, 70, 30, 30))
        heavy = score_result(TerminalResult(Outcome.WIN, 80, 10, 30, 30))
        self.assertGreater(light, heavy)

    def test_enemy_damage_is_progress_for_nonwins(self):
        loss_progress = score_result(TerminalResult(Outcome.LOSS, 80, 0, 80, 100))
        loss_no_progress = score_result(TerminalResult(Outcome.LOSS, 80, 0, 0, 100))
        unresolved_progress = score_result(TerminalResult(Outcome.UNRESOLVED, 80, 20, 60, 100))
        self.assertGreater(loss_progress, loss_no_progress)
        self.assertAlmostEqual(unresolved_progress, -0.35)

    def test_unresolved_reward_uses_quarter_progress_scale(self):
        no_progress = score_result(TerminalResult(Outcome.UNRESOLVED, 80, 20, 0, 100))
        full_progress = score_result(TerminalResult(Outcome.UNRESOLVED, 80, 20, 100, 100))
        self.assertAlmostEqual(no_progress, -0.5)
        self.assertAlmostEqual(full_progress, -0.25)
    def test_invalid_result_is_not_labeled(self):
        with self.assertRaises(ValueError):
            score_result(TerminalResult(Outcome.INVALID, 80, 0, 0, 30))


class SampleTests(unittest.TestCase):
    def test_round_trip_requires_every_hierarchical_policy_id(self):
        actions = (
            ActionNode("PlayCard", "play:3", children=(
                ActionNode("Target", "target:9", children=(
                    ActionNode("CardSubset", "cards:1,2", terminal=True),
                )),
            )),
            ActionNode("EndTurn", "end", terminal=True),
        )
        sample = TrainingSample(
            "seed-a", "full_combat", observation(), actions,
            {"play:3": 2, "target:9": 1, "cards:1,2": 1, "end": 1},
            -0.25, "unresolved",
        )
        with TemporaryDirectory() as directory:
            path = Path(directory) / "samples.jsonl"
            self.assertEqual(write_jsonl([sample], path), 1)
            loaded = read_jsonl(path)
        self.assertEqual(loaded[0].to_dict(), sample.to_dict())

    def test_rejects_policy_action_not_in_tree(self):
        action = ActionNode("EndTurn", "end", terminal=True)
        sample = TrainingSample("seed-a", "mid_combat_verified", observation(), (action,), {"other": 1}, 0, "loss")
        with self.assertRaises(ValueError):
            sample.validate()

    def test_rejects_nonfinite_visits_and_duplicate_nested_ids(self):
        leaf = ActionNode("Option", "duplicate", terminal=True)
        roots = (ActionNode("PlayCard", "duplicate", children=(leaf,)),)
        base = TrainingSample("seed-a", "full_combat", observation(), roots,
                              {"duplicate": 1}, 0.5, "win")
        with self.assertRaisesRegex(ValueError, "duplicate actionId"):
            base.validate()
        root = (ActionNode("EndTurn", "end", terminal=True),)
        for bad in (float("nan"), float("inf"), 0, -1, True):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    TrainingSample("seed-a", "full_combat", observation(), root,
                                   {"end": bad}, 0.5, "win").validate()
        with self.assertRaises(ValueError):
            TrainingSample("seed-a", "full_combat", observation(), root,
                           {"end": 1}, float("nan"), "win").validate()

if __name__ == "__main__":
    unittest.main()
