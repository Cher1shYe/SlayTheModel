"""Append missing v0.111.0 Neow relic IDs and regenerate their tables.

Existing IDs remain in their original order. The target game's relic classes
are the source for the added content; effects are implemented in C++.
"""
from pathlib import Path
import argparse
import json
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
MISSING_CLASSES = (
    "DowsingRod", "HeftyTablet", "NeowsBones", "NeowsSacrifice", "FishingRod",
    "Kaleidoscope", "PhialHolster", "WingedBoots", "NeowsTalisman",
)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=ROOT.parent / "artifacts/native-source/v0.111.0/MegaCrit/sts2/Core")
    args = parser.parse_args()
    path = ROOT / "content/relics.json"
    rows = json.loads(path.read_text())
    existing = {row["id"] for row in rows}
    for name in MISSING_CLASSES:
        source = (args.source / "Models/Relics" / (name + ".cs")).read_text()
        if "RelicRarity.Ancient" not in source:
            raise ValueError(f"{name}: expected native Ancient rarity")
        key = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", name).upper()
        if key not in existing:
            rows.append({"id": key, "name": name, "rarity": 7, "pool": "EVENT",
                         "doc": "Native v0.111.0 Neow option; appended without renumbering existing relics."})
            existing.add(key)
    path.write_text(json.dumps(rows, indent=1, ensure_ascii=False) + "\n")
    for tool, output in (("gen_relics.py", "relics_generated.inc"),
                         ("gen_relic_raw_rarity.py", "relic_raw_rarity.h")):
        subprocess.run([sys.executable, str(ROOT / "tools" / tool), "--json", str(path),
                        "--out", str(ROOT / "include/sts2" / output)], check=True)

    # Neow's Sacrifice obtains this event potion. Keep old potion IDs stable.
    potion_source = (args.source / "Models/Potions/Ambergris.cs").read_text()
    for contract in ("PotionRarity.Event", "PotionUsage.AnyTime", "TargetType.AnyPlayer"):
        if contract not in potion_source:
            raise ValueError(f"Ambergris native contract changed: {contract}")
    potion_path = ROOT / "content/potions.json"
    potions = json.loads(potion_path.read_text())
    if not any(row["id"] == "Ambergris" for row in potions):
        potions.append({"id": "Ambergris", "rarity": 3, "usage": 1, "target": 3,
                        "char": None, "combatGen": True, "ironclad": True})
    potion_path.write_text(json.dumps(potions, indent=1, ensure_ascii=False) + "\n")
    subprocess.run([sys.executable, str(ROOT / "tools/gen_potions.py"),
                    "--json", str(potion_path), "--out",
                    str(ROOT / "include/sts2/potions_generated.inc")], check=True)


if __name__ == "__main__":
    main()
