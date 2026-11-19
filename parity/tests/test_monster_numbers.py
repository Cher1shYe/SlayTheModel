"""Real DLL numeric samples are immutable, and numerical drift must be detected."""
import importlib.util
import json
from pathlib import Path
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]
SPEC=importlib.util.spec_from_file_location("audit_monster_numbers",ROOT/"sim/tools/audit_monster_numbers.py")
AUDIT=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(AUDIT)


class MonsterNumberAuditTests(unittest.TestCase):
    def test_all_active_monsters_and_boundary_ascensions(self):
        result=AUDIT.audit(ROOT)
        self.assertEqual(result["differences"],[])
        self.assertEqual(result["counts"]["model_contexts"],535)
        self.assertEqual(result["counts"]["numeric_comparisons"],3215)
        self.assertEqual(result["counts"]["attack_contexts"],1075)
        self.assertEqual({(x["id"],x["move"]) for x in result["exceptions"]},
                         {("THE_FORGOTTEN","DREAD"),("WATERFALL_GIANT","PRESSURE_GUN_MOVE")})

    def test_changed_raw_hp_fails_hash_and_numeric_checks(self):
        path=ROOT/AUDIT.FIXTURE/"monster-numbers-a10.json"
        changed=json.loads(path.read_bytes())
        row=changed["run"]["monsters"][0]
        field=next(key for key in row["members"] if key.endswith(".MinInitialHp"))
        row["members"][field]+=1
        original=Path.read_bytes
        with patch.object(Path,"read_bytes",lambda candidate:json.dumps(changed).encode() if candidate==path else original(candidate)):
            result=AUDIT.audit(ROOT)
        fields={row["field"] for row in result["differences"]}
        self.assertIn("fixture.sha256",fields)
        self.assertIn("hp.MinInitialHp",fields)

    def test_manifest_cannot_redefine_the_pinned_hashes(self):
        path=ROOT/AUDIT.FIXTURE/"manifest.json"
        changed=json.loads(path.read_text());changed["files"]["monster-numbers-a10.json"]="altered"
        original=Path.read_text
        with patch.object(Path,"read_text",lambda candidate,*a,**kw:json.dumps(changed) if candidate==path else original(candidate,*a,**kw)):
            result=AUDIT.audit(ROOT)
        self.assertIn("manifest.file_hashes",{row["field"] for row in result["differences"]})

    def test_wrong_deadly_damage_override_fails(self):
        path=ROOT/"sim/content/monsters_a9_damage.json"
        changed=json.loads(path.read_text());changed["BYRDONIS"]["PECK_MOVE"]=123
        original=Path.read_text
        with patch.object(Path,"read_text",lambda candidate,*a,**kw:json.dumps(changed) if candidate==path else original(candidate,*a,**kw)):
            result=AUDIT.audit(ROOT)
        rows=[row for row in result["differences"] if row.get("id")=="BYRDONIS" and row.get("move")=="PECK_MOVE"]
        self.assertEqual({row["ascension"] for row in rows},{9,10})


if __name__=="__main__":unittest.main()
