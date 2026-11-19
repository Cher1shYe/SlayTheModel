"""Regenerate basic relic/potion metadata from the pinned DLL registry export.

No ID is inserted, removed or reordered. Effects are deliberately not generated.
"""
from pathlib import Path
import argparse
import json
import subprocess
import sys

from audit_relics_registry import RELIC_RARITY, POTION_RARITY, TARGET, USAGE, _pool_short

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--native",type=Path,default=ROOT/"sim/native-fixtures/native-registry-41cef1ea.json")
    parser.add_argument("--apply",action="store_true")
    args=parser.parse_args()
    native=json.loads(args.native.read_text())
    identity=json.loads((ROOT/"sim/PORT_SOURCE.json").read_text())
    if native["gameDllSha256"]!=identity["target_game_dll_sha256"]:
        raise ValueError("Registry is not from the pinned target DLL")
    changes=[]
    for plural,singular in (("relics","Relic"),("potions","Potion")):
        path=ROOT/"sim/content"/(plural+".json")
        rows=json.loads(path.read_text())
        by_name={row["className"].split(".")[-1]:row for row in native[plural]}
        rarity={name:value for value,name in (RELIC_RARITY if singular=="Relic" else POTION_RARITY).items()}
        if singular=="Relic":rarity["None"]=-1
        for row in rows:
            other=by_name[row["name"] if singular=="Relic" else row["id"]]
            updated=dict(row,rarity=rarity[other["rarityName"]])
            if singular=="Relic":
                pools=[_pool_short(pool,singular) for pool in other["poolIds"]]
                if row["pool"] not in pools:
                    if len(pools)!=1:raise ValueError(f"Ambiguous pool for {other['id']}: {pools}")
                    updated["pool"]=pools[0]
            else:
                updated["usage"]={name:value for value,name in USAGE.items()}[other["usageName"]]
                updated["target"]={name:value for value,name in TARGET.items()}[other["targetName"]]
                updated["combatGen"]=other["canBeGeneratedInCombat"]
                if other["className"]=="FoulPotion":updated["targetInCombat"]=2
            for key in updated:
                if updated[key]!=row.get(key):changes.append({"id":other["id"],"field":key,"before":row.get(key),"after":updated[key]})
            row.clear();row.update(updated)
        if args.apply:path.write_text(json.dumps(rows,ensure_ascii=False,indent=1)+"\n")
    if args.apply:
        for tool,source,target in (("gen_relics.py","relics.json","relics_generated.inc"),
            ("gen_relic_raw_rarity.py","relics.json","relic_raw_rarity.h"),
            ("gen_potions.py","potions.json","potions_generated.inc")):
            subprocess.run([sys.executable,str(ROOT/"sim/tools"/tool),"--json",str(ROOT/"sim/content"/source),
                "--out",str(ROOT/"sim/include/sts2"/target)],check=True)
    print(json.dumps(changes,indent=2))


if __name__=="__main__":main()
