"""Dump Ironclad + colorless card metadata from the reference Python engine.

Run with the reference repo's interpreter:
    .venv-az/Scripts/python.exe simulator/tools/dump_cards.py \
        --ref D:/project/sts2_compactformer/sts2-rl-agent \
        --out simulator/content/cards.json
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ref", required=True, help="sts2-rl-agent checkout")
    ap.add_argument("--out", default="simulator/content/cards.json")
    ap.add_argument("--loc", default="output/portable_clean_checkout_20261020/sts2-cli/localization_eng/cards.json")
    args = ap.parse_args()

    ref = pathlib.Path(args.ref).resolve()
    sys.path.insert(0, str(ref))
    from sts2_env.cards.factory import (  # noqa: PLC0415
        CHARACTER_CARD_POOLS_BY_ID, COLORLESS_CARD_POOL, CURSE_CARD_POOL,
        EVENT_CARD_POOL, STATUS_CARD_POOL, TOKEN_CARD_POOL, create_card)
    from sts2_env.core.card_pools import CardPoolId  # noqa: PLC0415
    from sts2_env.cards.factory import is_multiplayer_only_card  # noqa: PLC0415

    loc_path = ref / args.loc
    loc = json.loads(loc_path.read_text(encoding="utf-8")) if loc_path.exists() else {}

    def text(card_id, field):
        name = card_id.name
        for key in (name, name.removesuffix("_CARD")):
            value = loc.get(f"{key}.{field}")
            if value:
                return value
        return ""

    out = []
    pools = [("ironclad", c) for c in CHARACTER_CARD_POOLS_BY_ID[CardPoolId.IRONCLAD]]
    pools += [("colorless", c) for c in COLORLESS_CARD_POOL]
    pools += [("status", c) for c in STATUS_CARD_POOL]
    pools += [("curse", c) for c in CURSE_CARD_POOL]
    pools += [("event", c) for c in EVENT_CARD_POOL]
    pools += [("token", c) for c in TOKEN_CARD_POOL]
    for pool, cid in pools:
        variants = {}
        for upgraded in (False, True):
            c = create_card(cid, upgraded=upgraded)
            variants["upgraded" if upgraded else "base"] = {
                "cost": c.cost,
                "x_cost": bool(c.has_energy_cost_x),
                "base_damage": c.base_damage,
                "base_block": c.base_block,
                "effect_vars": {k: (v.name if hasattr(v, "name") else v)
                                for k, v in c.effect_vars.items()},
                "keywords": sorted(str(k) for k in c.keywords),
                "exhausts": bool(c.exhausts),
                "ethereal": bool(c.is_ethereal),
                "innate": bool(c.is_innate),
                "retain": bool(c.is_retain),
                "unplayable": bool(c.is_unplayable),
            }
        c = create_card(cid, upgraded=False)
        out.append({
            "id": cid.name,
            "pool": pool,
            "multiplayer_only": bool(is_multiplayer_only_card(cid)),
            "title": text(cid, "title"),
            "description": text(cid, "description"),
            "cost": c.cost,
            "x_cost": bool(c.has_energy_cost_x),
            "type": c.card_type.name,
            "target": c.target_type.name,
            "rarity": c.rarity.name,
            "keywords": sorted(str(k) for k in c.keywords),
            "tags": sorted(t.name for t in c.tags),
            "flags": {
                "exhausts": bool(c.exhausts),
                "ethereal": bool(c.is_ethereal),
                "innate": bool(c.is_innate),
                "retain": bool(c.is_retain),
                "unplayable": bool(c.is_unplayable),
            },
            "base_damage": c.base_damage,
            "base_block": c.base_block,
            "effect_vars": {k: (v.name if hasattr(v, "name") else v)
                            for k, v in c.effect_vars.items()},
            "variants": variants,
        })

    path = pathlib.Path(args.out)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(f"wrote {len(out)} cards to {path}")
    print("missing text:", sum(1 for e in out if not e["description"]))


if __name__ == "__main__":
    main()
