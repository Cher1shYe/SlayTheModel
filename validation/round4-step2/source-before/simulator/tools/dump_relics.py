"""Dump relic metadata from the reference engine to JSON."""
from __future__ import annotations

import argparse
import json

from sts2_env.relics.base import RelicId
from sts2_env.relics.registry import RELIC_REGISTRY, load_all_relics


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    load_all_relics()
    rows = []
    for rid in RelicId:
        cls = RELIC_REGISTRY.get(rid)
        if cls is None:
            continue
        rows.append({
            "id": rid.name,
            "name": cls.__name__,
            "rarity": cls.rarity.value - 1,
            "pool": cls.pool.name,
            "doc": (cls.__doc__ or "").strip().split("\n")[0],
        })
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(rows, f, indent=1)
    print(f"wrote {len(rows)} relics")


if __name__ == "__main__":
    main()
