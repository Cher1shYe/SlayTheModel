"""Card registry auditing must catch mismatched identities as well as values."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("audit_cards_registry", ROOT / "sim/tools/audit_cards_registry.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class CardRegistryAuditTests(unittest.TestCase):
    def setUp(self):
        self.oracle = json.loads((ROOT / "sim/native-fixtures/native-round4-step2-card-reward-fixtures/content-metadata.json").read_text())
        self.fresh = json.loads((ROOT / "sim/native-fixtures/native-registry-41cef1ea.json").read_text())

    def test_full_registry_and_generated_table_with_explicit_exceptions(self):
        result = MODULE.audit(ROOT)
        self.assertEqual(result["differences"], [])
        self.assertEqual(result["counts"]["matched_identities"], 595)
        self.assertEqual(result["counts"]["fresh_readable_variants"], 1190)
        self.assertEqual(result["counts"]["fresh_unavailable_variants"], 2)
        self.assertEqual({(row["id"], row["field"]) for row in result["exceptions"]},
                         {("GRAPPLE", "registration"), ("DEPRECATED_CARD", "registration"),
                          ("MAD_SCIENCE", "type"), ("MAD_SCIENCE", "target"),
                          ("STARDUST", "fresh_registry.base.readable"),
                          ("STARDUST", "fresh_registry.upgraded.readable")})
        aliases = {row["simulator_id"]: row["native_id"] for row in result["aliases"]}
        self.assertEqual(aliases["SLOTH_STATUS"], "SLOTH")
        self.assertEqual(aliases["NULL_CARD"], "NULL")

    def test_changed_native_card_cost_is_detected(self):
        changed = deepcopy(self.oracle)
        changed["results"][0]["variants"][0]["cost"] += 1
        result = MODULE.audit(ROOT, changed)
        self.assertIn((changed["results"][0]["id"], "base.cost"),
                      {(row["id"], row["field"]) for row in result["differences"]})

    def test_changed_native_identity_is_not_matched_by_position(self):
        changed = deepcopy(self.oracle)
        old_id = changed["results"][0]["id"]
        changed["results"][0]["id"] = "NOT_AN_ACTUAL_CARD"
        result = MODULE.audit(ROOT, changed)
        missing = {row["id"] for row in result["differences"] if row["field"] == "registration"}
        self.assertEqual(missing, {old_id, "NOT_AN_ACTUAL_CARD"})

    def test_fresh_export_value_drift_is_detected(self):
        changed = deepcopy(self.fresh)
        card = changed["cards"][0]
        card["variants"][0]["cost"] += 1
        result = MODULE.audit(ROOT, changed)
        self.assertIn((card["id"], "fresh_registry.base.cost"),
                      {(row["id"], row["field"]) for row in result["differences"]})

    def test_unexpected_export_error_is_not_a_zero_or_known_exception(self):
        changed = deepcopy(self.fresh)
        card = changed["cards"][0]
        card["variants"][0] = {"error": "NullReferenceException", "message": "unexpected"}
        result = MODULE.audit(ROOT, changed)
        self.assertIn((card["id"], "fresh_registry.base.readable"),
                      {(row["id"], row["field"]) for row in result["differences"]})
        self.assertFalse(any(row["id"] == card["id"] for row in result["exceptions"]))


if __name__ == "__main__":
    unittest.main()
