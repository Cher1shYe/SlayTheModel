"""Replay preserved real-DLL observations through the complete public interface.

This fixture covers Neow, the first combat, and its explicit reward decisions;
it is evidence for these recorded transitions, not full-game rule equivalence.
"""
import hashlib
import json
from pathlib import Path
import sys
import unittest

from parity.compare import compare_decision, initialize_simulator, load_actions, verify_native_identity
from parity.semantic import SimulatorCatalog, native_request_for_candidate


ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "parity/fixtures/native-public-first-combat-rewards-parity0001-a10"


class NativePublicFixtureEvidenceTests(unittest.TestCase):
    def test_original_capture_bytes_match_manifest(self):
        manifest = json.loads((FIXTURES / "manifest.json").read_text())
        self.assertTrue(manifest["sha256"])
        for name, expected in manifest["sha256"].items():
            with self.subTest(file=name):
                self.assertEqual(hashlib.sha256((FIXTURES / name).read_bytes()).hexdigest(), expected)
        # Every replayed frame must be covered by the original-byte manifest.
        captures = sorted(FIXTURES.glob("decision-*-native.json"))
        self.assertTrue(captures)
        for capture in captures:
            self.assertIn(capture.name, manifest["sha256"])
        self.assertIn("actions.json", manifest["sha256"])


class NativePublicFixtureReplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, str(ROOT / "sim/build"))
        try:
            import numpy  # noqa: F401: required by public model encoding
            import sts2_sim
        except ImportError as exc:
            raise unittest.SkipTest(f"built simulator/numpy unavailable for this Python: {exc}")
        cls.sim = sts2_sim

    def test_full_public_inputs_and_actions_match_through_reward_exit(self):
        config = json.loads((FIXTURES / "config.json").read_text())
        target = json.loads((ROOT / "sim/PORT_SOURCE.json").read_text())
        expected_identity = dict(seed="PAR1TY0001", character="IRONCLAD", ascension=10,
                                 gameVersion=target["target_release"], gameCommit=target["target_commit"],
                                 gameDllSha256=target["target_game_dll_sha256"])
        rc, initialization = initialize_simulator(
            self.sim, config["seed"], config["ascension"], "fresh-unlocked-host")
        self.assertEqual(initialization["profile"], "fresh-unlocked-host")
        catalog = SimulatorCatalog.from_repo()
        actions = load_actions(FIXTURES / "actions.json")
        captures = sorted(FIXTURES.glob("decision-*-native.json"))
        self.assertGreater(len(actions), 0)
        self.assertEqual(len(captures), len(actions) + 1)
        self.assertEqual([p.name for p in captures],
                         [f"decision-{i:04d}-native.json" for i in range(len(actions) + 1)])

        for index, capture in enumerate(captures):
            frame = json.loads(capture.read_text())
            verify_native_identity(frame, expected_identity)
            result, simulated, native = compare_decision(
                frame, rc, self.sim, catalog, observation_schema="spire.public/1",
                legacy_capture=True)  # captured before the host exported act encounter history (D)
            self.assertEqual(result["status"], "aligned_model_interface",
                             f"decision {index}: {result}")
            if index == len(actions):
                break
            desired = actions[index]
            matches = [i for i, candidate in enumerate(simulated.actions) if candidate.key == desired]
            self.assertEqual(len(matches), 1, f"decision {index}: action is not uniquely legal: {desired}")
            candidate_index = matches[0]
            request = native_request_for_candidate(simulated, native, candidate_index)
            self.assertEqual(request["revision"], frame["revision"])
            self.assertIn(request["actionId"], {action["id"] for action in frame["actions"]})
            selected = simulated.actions[candidate_index]
            accepted = (rc.step_combat(*selected.handle) if simulated.screen == "combat"
                        else rc.step(*selected.handle))
            self.assertTrue(accepted, f"decision {index}: simulator rejected {desired}")

        self.assertEqual((simulated.screen, native.screen), ("map", "map"))
        self.assertEqual(rc.screen, self.sim.RunScreen.MAP)
        self.assertEqual((rc.hp, rc.max_hp, rc.gold, rc.deck_count), (51, 80, 258, 12))
        self.assertEqual((frame["player"]["hp"], frame["player"]["maxHp"], frame["player"]["gold"]),
                         (51, 80, 258))
        simulator_public = self.sim.public_model_state(rc)
        for public in (simulator_public, frame["publicObservation"]):
            self.assertIn("POTION.ASHWATER", {potion.get("modelId") for potion in public["potions"]})
            deck = [card for card in public["cards"] if card["pile"] == "deck"]
            self.assertEqual(len(deck), 12)
            self.assertEqual(sum(card["modelId"] == "CARD.THUNDERCLAP" for card in deck), 1)


if __name__ == "__main__":
    unittest.main()
