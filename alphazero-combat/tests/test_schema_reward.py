from __future__ import annotations

import unittest

from azcombat.reward import Outcome, TerminalResult, score_result
from azcombat.schema import ActionNode, ObservationError, validate_observation


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


if __name__ == "__main__":
    unittest.main()
