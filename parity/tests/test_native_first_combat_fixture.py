"""Replay 24 exact actions against immutable real native first-combat captures."""
import hashlib
import json
from pathlib import Path
import sys
import unittest

from parity.compare import compare_decision, initialize_simulator, load_actions, verify_native_identity
from parity.semantic import SimulatorCatalog, native_request_for_candidate


ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "parity/fixtures/native-first-combat-parity0001-a10"


def capture(index):
    return json.loads((FIXTURES / f"decision-{index:04d}-native.json").read_text())


class NativeFirstCombatEvidenceTests(unittest.TestCase):
    def test_source_bytes_and_unsupported_reward_boundary_are_preserved(self):
        manifest = json.loads((FIXTURES / "manifest.json").read_text())
        for name, expected in manifest["sha256"].items():
            with self.subTest(file=name):
                self.assertEqual(hashlib.sha256((FIXTURES / name).read_bytes()).hexdigest(), expected)
        summary = json.loads((FIXTURES / "summary.json").read_text())
        self.assertEqual(summary["aligned_decisions"], 24)
        self.assertEqual(summary["actions_submitted"], 24)
        self.assertEqual(summary["status"], "unsupported")
        self.assertEqual(summary["stopped_at"], 24)
        self.assertFalse(manifest["terminal_boundary"]["rewards_claimed"])
        self.assertEqual(capture(24)["screen"], "NRewardsScreen")


class NativeFirstCombatReplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, str(ROOT / "sim/build"))
        try:
            import numpy  # noqa: F401: required by pybind observation export
            import sts2_sim
        except ImportError as exc:
            raise unittest.SkipTest(f"built simulator/numpy unavailable for this Python: {exc}")
        cls.sim = sts2_sim

    def test_all_24_decisions_match_then_stop_before_claiming_rewards(self):
        config = json.loads((FIXTURES / "config.json").read_text())
        target = json.loads((ROOT / "sim/PORT_SOURCE.json").read_text())
        expected_identity = dict(seed="PAR1TY0001", character="IRONCLAD", ascension=10,
                                 gameVersion=target["target_release"], gameCommit=target["target_commit"],
                                 gameDllSha256=target["target_game_dll_sha256"])
        initialization = config["simulator_initialization"]
        context = dict(initialization["effective_progress"], first_act=initialization["first_act"])
        rc, _ = initialize_simulator(self.sim, config["seed"], config["ascension"], context=context)
        catalog = SimulatorCatalog.from_repo()
        actions = load_actions(FIXTURES / "actions.json")
        self.assertEqual(len(actions), 24)
        saw_compressed_target = False
        for index, desired in enumerate(actions):
            native_frame = capture(index)
            verify_native_identity(native_frame, expected_identity)
            result, simulated, native = compare_decision(native_frame, rc, self.sim, catalog)
            with self.subTest(decision=index):
                self.assertEqual(result["status"], "aligned_supported_subset", result)
                matches = [i for i, a in enumerate(simulated.actions) if a.key == desired]
                self.assertEqual(len(matches), 1)
                candidate_index = matches[0]
                selected = simulated.actions[candidate_index]
                request = native_request_for_candidate(simulated, native, candidate_index)
                self.assertEqual(request["revision"], native_frame["revision"])
                native_action = next(a for a in native_frame["actions"] if a["id"] == request["actionId"])
                if desired.kind == "play" and desired.args[1] is not None:
                    enemy_order = desired.args[1][0]
                    target = next(e for e in native_frame["entities"] if e["id"] == native_action["targetId"])
                    self.assertEqual(target["enemyOrderIndex"], enemy_order)
                    living = [i for i, m in enumerate(rc.battle.monsters) if m[7]]
                    if len(living) == 1 and living[0] == 1:
                        # Native's remaining enemy has order 0, while the C++
                        # legal target still names storage slot 1. Do not align
                        # those two integers by coincidence or list position.
                        self.assertEqual(enemy_order, 0)
                        self.assertEqual(selected.handle[2], 1)
                        saw_compressed_target = True
                accepted = (rc.step_combat(*selected.handle) if simulated.screen == "combat"
                            else rc.step(*selected.handle))
                self.assertTrue(accepted)
        self.assertTrue(saw_compressed_target)
        final = capture(24)
        verify_native_identity(final, expected_identity)
        self.assertEqual(final["screen"], "NRewardsScreen")
        self.assertEqual(rc.screen, self.sim.RunScreen.REWARDS)
        self.assertEqual((rc.hp, rc.max_hp, rc.gold), (51, 80, 249))
        self.assertEqual((final["player"]["hp"], final["player"]["maxHp"], final["player"]["gold"]),
                         (51, 80, 249))
        result, _, _ = compare_decision(final, rc, self.sim, catalog)
        self.assertEqual(result["status"], "unsupported")
        # The expanded adapter understands simulator rewards, but this historical
        # capture predates stable reward metadata. Never infer its reward kind
        # from a localized label or retroactively edit the native recording.
        self.assertEqual(set(result["unsupported"]), {"native"})
        self.assertIn("reward", result["unsupported"]["native"])


if __name__ == "__main__":
    unittest.main()
