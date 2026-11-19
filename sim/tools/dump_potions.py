"""Dump potion metadata from the reference engine to JSON."""
from __future__ import annotations

import argparse
import json

from sts2_env.potions.base import all_potion_models


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    rows = []
    for m in all_potion_models():
        rows.append({
            "id": m.potion_id,
            "rarity": m.rarity.value - 1,
            "usage": m.usage_type.value - 1,
            "target": m.target_type.value - 1,
            "char": m.character_pool,
            "combatGen": m.can_be_generated_in_combat,
            "ironclad": (not m.is_character_specific) or m.character_pool == "Ironclad",
        })
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(rows, f, indent=1)
    print(f"wrote {len(rows)} potions")


if __name__ == "__main__":
    main()
