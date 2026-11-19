"""Generate the shared public model vocabulary from the pinned public content.

No runtime model IDs, seeds or save files are part of this vocabulary. Unknown
content fails closed instead of hashing distinct models into one embedding.
"""
from pathlib import Path
import hashlib
import json
import re

ROOT = Path(__file__).resolve().parents[2]
NATIVE = ROOT / "artifacts/native-source/v0.111.0/MegaCrit/sts2/Core/Models"
REGISTRY = ROOT / "sim/native-fixtures/native-registry-41cef1ea.json"
REGISTRY_SHA256 = "2fff4579c9fcb9c8eba920a6316ca711267529e041a858d49c9100773caa2969"


def slug(name):
    return re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", name)).upper()


def build_catalog(*, include_relic_traits=True):
    raw = REGISTRY.read_bytes()
    if hashlib.sha256(raw).hexdigest() != REGISTRY_SHA256:
        raise RuntimeError("pinned native registry bytes changed")
    registry = json.loads(raw)
    content = {}
    for category, folder in (("CARD", "Cards"), ("POWER", "Powers"), ("RELIC", "Relics"),
                             ("POTION", "Potions"), ("MONSTER", "Monsters"), ("ENCOUNTER", "Encounters"),
                             ("EVENT", "Events"), ("ENCHANTMENT", "Enchantments"), ("AFFLICTION", "Afflictions")):
        # Source folders include abstract classes and non-model helper classes.
        # ModelDb registration is authoritative; test mocks are not game content.
        content[category] = sorted(row["id"] for row in registry["registered"]
                                   if row["id"].startswith(category + ".")
                                   and ".Mocks" not in row["namespaceName"]
                                   and not row["className"].startswith("Mock"))
        if not content[category]:
            raise RuntimeError(f"missing pinned native {folder} source")
    source = (ROOT / "sim/include/sts2/common.h").read_text()
    body = re.search(r"enum class PowerId[^\{]*\{(.*?)\n\};", source, re.S)[1]
    body = re.sub(r"//[^\n]*", "", body)
    powers = [word.strip() for word in body.split(",") if word.strip() and word.strip() != "COUNT"]
    aliases = {"REGEN": "REGEN", "MANGLE_POW": "MANGLE", "THE_BOMB_DAMAGE": "THE_BOMB",
               "TEMPORARY_STRENGTH": "TEMPORARY_STRENGTH", "TEMPORARY_DEXTERITY": "TEMPORARY_DEXTERITY"}
    power_map = []
    for name in powers:
        ident = "POWER." + aliases.get(name, name) + "_POWER"
        power_map.append(ident if ident in content["POWER"] else None)
    card_map = {}
    for card in json.loads((ROOT / "sim/content/cards.json").read_text()):
        key = card["id"]
        model = "CARD." + card.get("native_id", key)
        if key == "SLOTH_STATUS":
            model = "CARD.SLOTH"
        if model not in content["CARD"] and key.endswith("_CARD"):
            model = "CARD." + key[:-5]
        card_map["CARD." + key] = model if model in content["CARD"] else None
    relic_traits = {}
    if include_relic_traits:
        for row in registry["relics"]:
            path = NATIVE / "Relics" / (row["className"] + ".cs")
            if not path.is_file():
                raise RuntimeError(f"missing native relic source: {path}; refusing to write incomplete UI traits")
            source = path.read_text()
            # Non-overridden counter is false by RelicModel's public UI contract.
            special = bool(re.search(r"override\s+(?:bool ShowCounter|int DisplayAmount)", source))
            relic_traits["RELIC." + row["id"]] = {"customCounter": special}
    result = {"version": 1, "registrySha256": REGISTRY_SHA256,
              "models": content, "simPowerIds": power_map,
              "simCardIds": card_map, "relicTraits": relic_traits}
    oracle = json.loads((ROOT / "sim/native-fixtures/native-round4-step2-card-reward-fixtures/content-metadata.json").read_text())
    if oracle["gameAssemblySha256"] != "9cb4f1ad8c9f284aa8fec3122ffd6d780bbf543d875c817abdd12ff63fbf12b4":
        raise RuntimeError("public card metadata is not from the pinned native DLL")
    result["cardVars"] = {"CARD." + card["id"]: [variant["vars"] for variant in card["variants"]]
                          for card in oracle["results"] if "CARD." + card["id"] in content["CARD"]}
    result["cardCostsX"] = {"CARD." + card["id"]: bool(card["variants"][0]["xCost"])
                            for card in oracle["results"] if "CARD." + card["id"] in content["CARD"]}
    result["cardTags"] = {"CARD." + card["id"]: sorted(card["tags"]) for card in oracle["results"]
                          if "CARD." + card["id"] in content["CARD"]}
    result["variableNames"] = sorted({name for variants in result["cardVars"].values() for variant in variants for name in variant})
    return result


def main():
    result = build_catalog()
    output = ROOT / "train/spire_rl/public_catalog.json"
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(f"wrote {output}")


if __name__ == "__main__":
    main()
