from pathlib import Path
import unittest

from azcombat.r4_promotion import assess_r4


ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / "artifacts" / "alphazero" / "r4-smoke-weighted-mix-20260926-001"
INDEX = ROOT / "artifacts" / "alphazero" / "r4-training-admission-20260926-001" / "index.json"


@unittest.skipUnless(INDEX.exists() and BASE.exists(),
                     "R4 promotion artifacts were intentionally removed during artifact cleanup; regenerate them before replaying this integration test")
class R4PromotionTests(unittest.TestCase):
    def test_engineering_candidate_is_denied_without_evaluation_wave(self):
        result = assess_r4(INDEX, BASE / "report.json", BASE / "candidate.manifest.json")
        self.assertFalse(result["approved"])
        self.assertEqual(result["decision"], "DENY")
        self.assertTrue(any("Native evaluation" in reason for reason in result["reasons"]))
        self.assertEqual(result["parameterCount"], 1970)


if __name__ == "__main__":
    unittest.main()
