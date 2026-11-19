"""Offline regression against preserved real-DLL captures, with fixed provenance."""
import hashlib
import json
from pathlib import Path
import sys
import unittest

from parity.compare import compare_decision, initialize_simulator, verify_native_identity
from parity.semantic import ActionKey, SimulatorCatalog, project_native


ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "parity/fixtures/native-opening-parity0001-a10"


def frame(index):
    return json.loads((FIXTURES / f"decision-{index:04d}-native.json").read_text())


class NativeCaptureEvidenceTests(unittest.TestCase):
    def test_original_capture_bytes_match_provenance_manifest(self):
        manifest = json.loads((FIXTURES / "manifest.json").read_text())
        self.assertTrue(manifest["bytes_preserved"])
        self.assertIn("real native", manifest["source_kind"])
        for name, expected in manifest["sha256"].items():
            with self.subTest(file=name):
                self.assertEqual(hashlib.sha256((FIXTURES / name).read_bytes()).hexdigest(), expected)

    def test_real_identity_matches_pinned_native_target(self):
        target = json.loads((ROOT / "sim/PORT_SOURCE.json").read_text())
        expected = dict(seed="PAR1TY0001", character="IRONCLAD", ascension=10,
                        gameVersion=target["target_release"], gameCommit=target["target_commit"],
                        gameDllSha256=target["target_game_dll_sha256"])
        for i in range(4):
            verify_native_identity(frame(i), expected)

    def test_actual_proceed_is_a_separate_public_decision(self):
        initial, proceeding = project_native(frame(0)), project_native(frame(1))
        self.assertEqual({a.key for a in initial.actions}, {
            ActionKey("neow_relic", ("NEW_LEAF",)), ActionKey("neow_relic", ("GOLDEN_PEARL",)),
            ActionKey("neow_relic", ("SILKEN_TRESS",))})
        self.assertEqual([a.key for a in proceeding.actions], [ActionKey("neow_proceed")])
        self.assertEqual(initial.public_state["gold"], 99)
        self.assertEqual(proceeding.public_state["gold"], 249)
        self.assertEqual(project_native(frame(2)).screen, "map")

    def test_first_combat_evidence_is_native_toadpoles_not_simulated_seapunk(self):
        captured = frame(3)
        self.assertEqual(captured["surfaceModelId"], "ENCOUNTER.TOADPOLES_WEAK")
        enemies = [e for e in captured["entities"] if e["kind"] == "enemy"]
        self.assertEqual([e["modelId"] for e in enemies], ["MONSTER.TOADPOLE"] * 2)
        self.assertEqual(sorted(e["enemyOrderIndex"] for e in enemies), [0, 1])


class NativeOpeningSimulatorRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, str(ROOT / "sim/build"))
        try:
            import sts2_sim
        except ImportError as exc:
            raise unittest.SkipTest(f"simulator unavailable for this Python: {exc}")
        cls.sim = sts2_sim

    def test_neow_reward_proceed_map_and_first_combat_match_real_captures(self):
        rc, _ = initialize_simulator(self.sim, "PARITY0001", 10, "fresh-unlocked-host")
        catalog = SimulatorCatalog.from_repo()
        actions = [ActionKey("neow_relic", ("GOLDEN_PEARL",)), ActionKey("neow_proceed"),
                   ActionKey("move", (0, 1))]
        for i in range(4):
            result, simulated, _ = compare_decision(frame(i), rc, self.sim, catalog)
            with self.subTest(decision=i):
                self.assertEqual(result["status"], "aligned_supported_subset", result)
            if i < len(actions):
                selected = next(a for a in simulated.actions if a.key == actions[i])
                rc.step(*selected.handle)
        self.assertEqual(sorted(m[1] for m in rc.battle.monsters if m[7]), [25, 26])


if __name__ == "__main__":
    unittest.main()
