"""Protect saved numeric identities and the real native model vocabulary."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("audit_native_registry", ROOT / "sim/tools/audit_native_registry.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class RegistryIdentityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.native = json.loads((ROOT / MODULE.REGISTRY_PATH).read_text())
        cls.locked = json.loads((ROOT / MODULE.LOCK_PATH).read_text())["categories"]
        cls.current = MODULE.current_identities(ROOT, cls.native)

    def test_current_numeric_identities_match_frozen_lock(self):
        self.assertEqual(MODULE.compare_lock(self.current, self.locked), [])

    def test_swapped_slots_fail_even_with_unchanged_model_set(self):
        changed = deepcopy(self.current)
        changed["CARD"][1], changed["CARD"][2] = changed["CARD"][2], changed["CARD"][1]
        self.assertTrue(MODULE.compare_lock(changed, self.locked))

    def test_deleted_slot_fails(self):
        changed = deepcopy(self.current)
        del changed["CARD"][1]
        self.assertTrue(MODULE.compare_lock(changed, self.locked))

    def test_content_native_alias_change_reaches_numeric_lock(self):
        path = ROOT / "sim/content/cards.json"
        cards = json.loads(path.read_text())
        row = next(row for row in cards if row["id"] == "NULL_CARD")
        row["native_id"] = "AGGRESSION"
        original_read = Path.read_text

        def read_text(candidate, *args, **kwargs):
            return json.dumps(cards) if candidate == path else original_read(candidate, *args, **kwargs)

        with patch.object(Path, "read_text", read_text):
            changed = MODULE.current_identities(ROOT, self.native)
        changed_row = next(row for row in changed["CARD"] if row["key"] == "NULL_CARD")
        self.assertEqual(changed_row["native_ids"], ["CARD.AGGRESSION"])
        self.assertTrue(MODULE.compare_lock(changed, self.locked))

    def test_new_slots_may_append_without_renumbering_existing_slots(self):
        changed = deepcopy(self.current)
        changed["CARD"].append({"id": changed["CARD"][-1]["id"] + 1,
                                "key": "FUTURE_NATIVE_CARD", "native_ids": ["CARD.FUTURE_NATIVE_CARD"]})
        self.assertEqual(MODULE.compare_lock(changed, self.locked), [])

    def test_appended_slots_cannot_reverse_numeric_order(self):
        changed = deepcopy(self.current)
        last = changed["CARD"][-1]["id"]
        changed["CARD"].extend([
            {"id": last + 2, "key": "FUTURE_A", "native_ids": []},
            {"id": last + 1, "key": "FUTURE_B", "native_ids": []},
        ])
        self.assertTrue(MODULE.compare_lock(changed, self.locked))

    def test_appended_slot_cannot_reuse_an_existing_key(self):
        changed = deepcopy(self.current)
        changed["CARD"].append({"id": changed["CARD"][-1]["id"] + 1,
                                "key": changed["CARD"][1]["key"], "native_ids": []})
        self.assertTrue(MODULE.compare_lock(changed, self.locked))

    def test_enum_parser_rejects_duplicate_values(self):
        with self.assertRaises(ValueError):
            MODULE.enum_rows("enum class Example { FIRST=0, SECOND=0, COUNT };", "Example")

    def test_catalog_contains_real_production_models_only(self):
        catalog = json.loads((ROOT / "train/spire_rl/public_catalog.json").read_text())["models"]
        self.assertEqual(set(catalog), {"CARD", "POWER", "RELIC", "POTION", "MONSTER",
                                        "ENCOUNTER", "EVENT", "ENCHANTMENT", "AFFLICTION"})
        all_models = {identity for values in catalog.values() for identity in values}
        phantom_models = {"RELIC.VAKUU_CARD_SELECTOR", "POWER.TEMPORARY_DEXTERITY_POWER",
                          "POWER.TEMPORARY_FOCUS_POWER", "POWER.TEMPORARY_STRENGTH_POWER",
                          "MONSTER.DECIMILLIPEDE_SEGMENT", "ENCOUNTER.BATTLEWORN_DUMMY_EVENT_ENCOUNTER"}
        self.assertTrue(all_models.isdisjoint(phantom_models))
        mocks = {row["id"] for row in self.native["registered"]
                 if ".Mocks" in row["namespaceName"] or row["className"].startswith("Mock")}
        self.assertTrue(mocks)
        self.assertTrue(all_models.isdisjoint(mocks))
        for category, identities in catalog.items():
            expected = sorted(row["id"] for row in self.native["registered"]
                              if row["id"].startswith(category + ".") and row["id"] not in mocks)
            self.assertEqual(identities, expected)

    def test_real_full_audit_has_no_unexplained_differences(self):
        report = MODULE.audit(ROOT)
        self.assertEqual(report["errors"], [])
        self.assertEqual(report["status"], "pass_with_documented_exceptions")
        self.assertTrue(report["runtime"]["available"])

    def audit_with_changed_json(self, relative_path, changed):
        """Inject altered evidence in memory; production files stay untouched."""
        path = ROOT / relative_path
        original_read = Path.read_text

        def read_text(candidate, *args, **kwargs):
            return json.dumps(changed) if candidate == path else original_read(candidate, *args, **kwargs)

        with patch.object(Path, "read_text", read_text):
            return MODULE.audit(ROOT)

    def test_missing_catalog_category_fails(self):
        path = "train/spire_rl/public_catalog.json"
        changed = json.loads((ROOT / path).read_text())
        del changed["models"]["CARD"]
        report = self.audit_with_changed_json(path, changed)
        self.assertEqual(report["status"], "fail")
        self.assertIn("missing or extra public model categories",
                      {row.get("reason") for row in report["public_catalog"]["differences"]})

    def test_stale_catalog_alias_and_power_mapping_fail(self):
        path = "train/spire_rl/public_catalog.json"
        for field in ("simCardIds", "simPowerIds"):
            with self.subTest(field=field):
                changed = json.loads((ROOT / path).read_text())
                if field == "simCardIds":
                    changed[field]["CARD.NULL_CARD"] = "CARD.AGGRESSION"
                else:
                    changed[field][0] = "POWER.INTENTIONALLY_STALE_MAPPING"
                report = self.audit_with_changed_json(path, changed)
                self.assertEqual(report["status"], "fail")
                self.assertIn(field, {row.get("field") for row in report["public_catalog"]["differences"]})

    def test_wrong_lock_version_or_provenance_fails(self):
        for field, replacement in (("version", 999), ("native_registry_sha256", "wrong")):
            with self.subTest(field=field):
                changed = json.loads((ROOT / MODULE.LOCK_PATH).read_text())
                changed[field] = replacement
                report = self.audit_with_changed_json(MODULE.LOCK_PATH, changed)
                self.assertIn("numeric identity lock mismatch", report["errors"])

    def test_stale_runtime_ruleset_fails(self):
        path = "sim/PORT_SOURCE.json"
        changed = json.loads((ROOT / path).read_text())
        changed["engine_ruleset"] = "intentionally-incompatible-test-ruleset"
        report = self.audit_with_changed_json(path, changed)
        self.assertIn("compiled extension ruleset differs from PORT_SOURCE", report["errors"])

    def test_missing_optional_ui_source_is_reported_without_disabling_registry_checks(self):
        generator = MODULE.module(ROOT, "gen_public_catalog")
        missing = generator.NATIVE / "Relics/Akabeko.cs"
        original = Path.is_file
        with patch.object(Path, "is_file", lambda path: False if path == missing else original(path)):
            report = MODULE.audit(ROOT)
        self.assertEqual(report["errors"], [])
        traits = report["public_catalog"]["relic_ui_traits"]
        self.assertFalse(traits["checked"])
        self.assertEqual(traits["missing_source_count"], 1)
        self.assertIn("relic UI traits source regeneration", report["unverified"])

    def test_generator_refuses_incomplete_ui_sources(self):
        generator = MODULE.module(ROOT, "gen_public_catalog")
        missing = generator.NATIVE / "Relics/Akabeko.cs"
        original = Path.is_file
        with patch.object(Path, "is_file", lambda path: False if path == missing else original(path)):
            with self.assertRaisesRegex(RuntimeError, "refusing to write incomplete"):
                generator.build_catalog()


if __name__ == "__main__":
    unittest.main()
