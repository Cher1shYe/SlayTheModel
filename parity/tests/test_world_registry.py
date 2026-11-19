"""Full static registry checks against the saved real DLL enumeration."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("world_registry", ROOT / "sim/tools/audit_world_registry.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def native():
    return json.loads((ROOT / "sim/native-fixtures/native-registry-41cef1ea.json").read_text())


def test_world_registration_and_basic_attributes_match_real_dll_registry():
    report = MODULE.audit(ROOT, native())
    assert {key: value["differences"] for key, value in report.items()} == {
        "events": [], "ancients": [], "monsters": [], "encounters": []}
    assert report["events"]["counts"]["native_active"] == 57
    assert report["ancients"]["counts"]["native_active"] == 8
    assert report["monsters"]["counts"]["mapped_active_native_ids"] == 107
    assert report["encounters"]["counts"]["mapped_active_native_ids"] == 85


def test_audit_detects_hp_candidate_membership_and_order_drift():
    changed = deepcopy(native())
    next(row for row in changed["monsters"] if row["id"] == "MYSTERIOUS_KNIGHT")["hpA10"] = [101, 101]
    next(row for row in changed["ancients"] if row["id"] == "NEOW")["possibleRelics"].append("UNKNOWN_RELIC")
    next(row for row in changed["acts"] if row["id"] == "HIVE")["normal"].reverse()
    report = MODULE.audit(ROOT, changed)
    assert [d["field"] for d in report["monsters"]["differences"]] == ["MYSTERIOUS_KNIGHT.hpA10"]
    assert [d["field"] for d in report["ancients"]["differences"]] == ["NEOW.possible_relics"]
    assert [d["field"] for d in report["encounters"]["differences"]] == ["HIVE.normal_order"]
