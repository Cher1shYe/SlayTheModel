"""Versioned, source-independent public observation and policy encoder.

Both backends first produce PublicState and then call exactly the same ``encode``.
Transport IDs are routing handles, never features or sorting tie breakers. A missing
field or unsupported conversion raises ObservationCoverageError with its full path.
The legacy obs.observe API remains available for old experiments.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
import json
import math
import re
import hashlib

import numpy as np

from .obs import UObs
from . import public_derived as derived
from . import public_tactics as tactics

SCHEMA_ID = "spire.public/1"
# Derived feature layout (public_derived.py); bump on any change. Checkpoints record it.
FEATURE_VERSION = 12  # 12: every numeric input bounded (squash; lengths / their caps; Waterfall Giant HP 999999999 was 5e6), DEVLOG 50; 11: channeled orbs (player row 107..178), A4 counts their turn-end passives; 10: A2 advances the rat summon cooldown, A4 drops enemies killed by Poison first; 9: B player-side resolution + HP lost during the play (col 522)
_CATALOG = json.loads(Path(__file__).with_name("public_catalog.json").read_text())
CATALOG_SHA256 = hashlib.sha256(Path(__file__).with_name("public_catalog.json").read_bytes()).hexdigest()
_MODELS = _CATALOG["models"]
_IDS = {category: {key: i + 1 for i, key in enumerate(keys)} for category, keys in _MODELS.items()}
_VARIABLE_INDEX = {}
for _i, _name in enumerate(_CATALOG["variableNames"]):
    _VARIABLE_INDEX.setdefault(_name, _i)  # same as list.index: first occurrence
MACRO_KINDS, COMBAT_KINDS, KINDS = 13, 13, 26
MACRO_NUM = COMBAT_NUM = NUM = 768
CAND_NUM = 544          # 0..15 scalar args, 15 length, 16..510 descriptor bytes, 512..543 B preview (appended)
DESCRIPTOR_CAP = 495
SQUASH_CAP = 6.0


def _sq(x, scale):
    """Bounded numeric input (FEATURE_VERSION 12): x / scale unchanged inside [-1, 1], log-compressed
    beyond (1 + ln|v|) and capped at SQUASH_CAP. Monotone, so order and equality are kept. Before,
    raw prices (300+), lengths (495) and a 999999999-HP enemy (5e6) entered the network directly."""
    v = float(x) / scale
    a = abs(v)
    return v if a <= 1.0 else math.copysign(min(1.0 + math.log(a), SQUASH_CAP), v)
B_OFFSET = 512
# Stable, semantic actions shared by both transports. New choices append here.
ACTION_KINDS = (
    "neow_relic", "neow_proceed", "move", "play", "end_turn", "use_potion", "discard_potion",
    "take_gold", "take_relic", "take_potion", "open_card_reward", "choose_reward_card", "skip_card_reward",
    "proceed", "event_option", "event_proceed", "rest", "shop_card", "shop_relic", "shop_potion", "shop_remove",
    "grid_card", "grid_confirm", "grid_cancel", "choose_card", "confirm", "cancel", "treasure", "sphere_small", "sphere_big",
    "take_relic_reward", "take_special_card", "open_card_removal_reward", "take_card", "skip_card", "sacrifice_card_reward",
    "reroll_card_reward", "heal_card_reward", "select_card", "deselect_card", "confirm_selection", "cancel_preview", "cancel_selection",
    "skip_selection", "buy_card", "buy_relic", "buy_potion", "open_remove_card", "leave_shop", "rest_proceed", "leave_rewards",
    "open_treasure", "take_treasure_relic", "leave_treasure", "select_relic", "select_bundle", "reveal_cell", "small_divination", "big_divination",
)
CAND_TYPES = len(ACTION_KINDS)
_KIND_CATEGORY = (None, None, "CARD", "RELIC", "POTION", None, "ENCOUNTER", "CARD", "RELIC", "POTION",
                  None, "EVENT", None, None, "ENCOUNTER", "POWER", "CARD", "CARD", "CARD", "CARD", "CARD",
                  "CARD", "MONSTER", "POWER", "POTION", "RELIC")
CARD_TYPES = ("Attack", "Skill", "Power", "Status", "Curse", "Quest")
RARITIES = ("Basic", "Common", "Uncommon", "Rare", "Special", "Ancient", "Event", "Token", "Status", "Curse", "Quest")
TARGETS = ("AnyEnemy", "AllEnemies", "Self", "RandomEnemy", "AnyAlly", "AllAllies", "None")
KEYWORDS = ("Exhaust", "Ethereal", "Innate", "Unplayable", "Retain", "Sly", "Eternal")
TAGS = ("None", "Strike", "Defend", "Minion", "OstyAttack", "Shiv")
INTENTS = ("Attack", "Buff", "Debuff", "DebuffStrong", "Defend", "Escape", "Heal", "Hidden", "Summon", "Sleep", "Stun", "StatusCard", "CardDebuff", "DeathBlow", "Unknown")
MAP_TYPES = ("Unassigned", "Unknown", "Shop", "Treasure", "RestSite", "Monster", "Elite", "Boss", "Ancient")
ENCHANTMENTS = (None, "SOWN", "VIGOROUS", "SWIFT", "GLAM", "CLONE", "SPIRAL", "STEADY", "NIMBLE", "INKY",
                "SLITHER", "PERFECT_FIT", "CORRUPTED", "SOULS_POWER", "SHARP", "IMBUED", "ADROIT", "MOMENTUM", "ROYALLY_APPROVED",
                # v16 (append-only, same order as C++ EnchantmentId).
                "GOOPY", "INSTINCT", "TEZCATARAS_EMBER")
# Card-row one-hot: the original 19 entries (incl. None) use offsets 56..74; later
# entries go to the free block 238.. so existing feature positions never move.
def _enchantment_offset(index):
    return 56 + index if index < 19 else 238 + index - 19
_CARD_SCALARS = ("upgrade", "maxUpgrade", "costX", "cost", "baseCost", "localCost", "starCostX", "starCost",
                 "damage", "block", "replay", "enchantedReplay", "retain", "exhaustOnNextPlay", "progress", "tinkerRider",
                 "position", "knownTopPosition", "selected", "price", "sold", "retainThisTurn", "slyThisTurn", "dampened")
_CARD_SCALE = {"price": 100}    # every other non-bool card scalar: _sq(x, 10)
MAX_ORBS = 10
ORB_KINDS = ("ORB.LIGHTNING_ORB", "ORB.FROST_ORB", "ORB.DARK_ORB", "ORB.PLASMA_ORB", "ORB.GLASS_ORB")
_COMBAT_SCALARS = ("turn", "round", "cardsPlayedTurn", "attacksPlayedTurn", "skillsPlayedTurn", "cardsPlayedCombat",
                   "cardsFinishedCombat", "cardsExhaustedTurn", "unblockedHitsCombat", "hpLostTurn", "manualCardsPlayedTurn")


class ObservationCoverageError(ValueError):
    """A public fact required by the actor has not been established."""


def need(obj, key, path):
    if type(obj) is dict:  # fast path; dict subclasses take the general check below
        try:
            return obj[key]
        except KeyError:
            raise ObservationCoverageError(f"{path}.{key}: missing public field") from None
    if not isinstance(obj, dict) or key not in obj:
        raise ObservationCoverageError(f"{path}.{key}: missing public field")
    return obj[key]


def number(value, path):
    kind = type(value)
    if kind is int or kind is bool:  # fast paths, same results as the general check
        return value
    if kind is float and math.isfinite(value):
        return int(value) if value.is_integer() else value
    if not isinstance(value, (bool, int, float)) or not math.isfinite(value):
        raise ObservationCoverageError(f"{path}: expected finite public number, got {value!r}")
    return int(value) if isinstance(value, float) and value.is_integer() else value


def enum(value, vocabulary, path):
    if isinstance(value, int) and not isinstance(value, bool) and 0 <= value < len(vocabulary):
        return vocabulary[value]
    if value not in vocabulary:
        raise ObservationCoverageError(f"{path}: unsupported public value {value!r}")
    return value


def model(value, category, path):
    if value not in _IDS[category]:
        raise ObservationCoverageError(f"{path}: unknown {category} model {value!r}")
    return value


def _vars(raw, path):
    return {need(item, "name", path): number(need(item, "value", path), path) for item in raw}


def _card(raw, source, path):
    ident = need(raw, "modelId", path)
    if source == "simulator":
        ident = _CATALOG["simCardIds"].get(ident)
    result = {"modelId": model(ident, "CARD", path), "pile": need(raw, "pile", path)}
    for name in ("upgrade", "maxUpgrade", "costX", "cost", "baseCost", "localCost", "starCostX", "starCost", "replay", "retain", "progress", "tinkerRider", "retainThisTurn", "slyThisTurn", "dampened"):
        result[name] = number(need(raw, name, path), path + "." + name)
    if source == "simulator":
        # C++ historically uses -1 for both X and unplayable energy costs.
        # CostsX is immutable public model metadata, not an RNG-derived guess.
        result["costX"] = need(_CATALOG["cardCostsX"], ident, "public catalog")
        if result["costX"]: result["baseCost"], result["localCost"] = 0, 0
    result["position"] = -1 if raw.get("position") is None else number(raw["position"], path + ".position")
    result["knownTopPosition"] = -1
    result["selected"], result["price"], result["sold"] = raw.get("selected", False), raw.get("price", -1), raw.get("sold", False)
    result["type"] = enum(need(raw, "type", path), CARD_TYPES, path + ".type")
    result["rarity"] = enum(need(raw, "rarity", path), RARITIES, path + ".rarity")
    result["target"] = enum(need(raw, "target", path), TARGETS, path + ".target")
    result["keywords"] = tuple(sorted(enum(k, KEYWORDS, path + ".keywords") for k in need(raw, "keywords", path)))
    result["localKeywords"] = tuple(sorted(enum(k, KEYWORDS, path + ".localKeywords") for k in need(raw, "localKeywords", path)))
    result["tags"] = tuple(sorted(enum(k, TAGS, path + ".tags") for k in
        (need(_CATALOG["cardTags"], ident, "public catalog") if source == "simulator" else need(raw, "tags", path))))
    modifiers = []
    for mod in need(raw, "costModifiers", path):
        amount, absolute, expiration, reduce = (number(need(mod, field, path), path + ".costModifiers." + field)
            for field in ("amount", "absolute", "expiration", "reduceOnly"))
        if not absolute and reduce: amount = min(0, amount)
        if not absolute and amount == 0: continue
        if absolute and not reduce and expiration == 0: modifiers.clear()
        if not absolute and modifiers and not modifiers[-1][1] and modifiers[-1][2:] == (expiration, reduce):
            modifiers[-1] = (modifiers[-1][0] + amount, False, expiration, reduce)
        else: modifiers.append((amount, absolute, expiration, reduce))
    result["costModifiers"] = tuple(modifiers)
    if len(result["costModifiers"]) > 32:
        raise ObservationCoverageError(path + ".costModifiers: capacity exceeds 32; extend schema, do not truncate")
    enchantment = raw.get("enchantment")
    if source == "simulator":
        eid = need(enchantment, "id", path + ".enchantment")
        if not 0 <= eid < len(ENCHANTMENTS):
            raise ObservationCoverageError(path + ".enchantment: unknown enum")
        enchantment = None if eid == 0 else dict(enchantment, modelId="ENCHANTMENT." + ENCHANTMENTS[eid])
        variants = _CATALOG["cardVars"].get(ident)
        if variants is None or result["upgrade"] >= len(variants):
            raise ObservationCoverageError(path + ".dynamicVars: native canonical metadata unavailable")
        variables = dict(variants[result["upgrade"]])
        if "Damage" in variables: variables["Damage"] += need(raw, "bonusDamage", path)
        if "Block" in variables: variables["Block"] += need(raw, "bonusBlock", path)
        if ident == "CARD.DOWSING": variables["Rooms"] = 5 - result["progress"]
        if ident == "CARD.GUILTY": variables["Combats"] = 5 - result["progress"]
        result["damage"], result["block"] = variables.get("Damage", 0), variables.get("Block", 0)
        result["exhaustOnNextPlay"] = need(raw, "exhaustOnNextPlay", path)
        result["enchantedReplay"] = need(raw, "enchantedReplay", path)
        afflictions = need(raw, "afflictions", path)
    else:
        variables = _vars(need(raw, "dynamicVars", path), path + ".dynamicVars")
        # Absence means this model has no Damage/Block dynamic variable. It is a
        # documented zero, distinct from a missing dynamicVars collection.
        result["damage"], result["block"] = variables.get("Damage", 0), variables.get("Block", 0)
        result["exhaustOnNextPlay"] = need(raw, "exhaustOnNextPlay", path)
        result["enchantedReplay"] = need(raw, "enchantedReplay", path)
        afflictions = [raw["affliction"]] if raw.get("affliction") is not None else []
    result["dynamicVars"] = tuple(sorted((name, number(value, path + ".dynamicVars." + name)) for name, value in variables.items()))
    result["damage"] = number(result["damage"], path + ".damage")
    result["block"] = number(result["block"], path + ".block")
    result["enchantment"] = None if enchantment is None else (
        model(need(enchantment, "modelId", path), "ENCHANTMENT", path),
        number(need(enchantment, "amount", path), path), bool(need(enchantment, "disabled", path)),
        number(need(enchantment, "extraDamage", path), path))
    result["afflictions"] = tuple(sorted((model(need(a, "modelId", path), "AFFLICTION", path),
        number(need(a, "amount", path), path)) for a in afflictions))
    _display_values(result, raw, source, path)
    return result


# Checklist A1. Native/simulator export the value each Hand/Play card displays
# (CardModel.UpdateDynamicVarPreview, untargeted and per public enemy order). A value
# is kept only when the card has the variable. MISSING_PREVIEW marks a native capture
# that predates the export; _common rejects it unless replaying a legacy capture.
MISSING_PREVIEW = "__preview_missing__"
PREVIEW_UNSUPPORTED = -1000000  # sim/include/sts2/card_preview.h
DISPLAY_KEYS = ("displayDamage", "displayBlock", "displayDamageVs", "previewUnsupported")


def _display_values(result, raw, source, path):
    names = {name for name, _ in result["dynamicVars"]}
    has_damage = bool(names & {"Damage", "CalculatedDamage"})
    has_block = bool(names & {"Block", "CalculatedBlock"})
    result.update(displayDamage=None, displayBlock=None, displayDamageVs=None, previewUnsupported=False)
    if result["pile"] not in ("hand", "play"):
        return
    def value(key, wanted):
        if not wanted:
            return None
        if raw.get(key) is None:
            if source == "native":
                return MISSING_PREVIEW
            raise ObservationCoverageError(f"{path}.{key}: simulator preview missing")
        if key == "previewDamageVs":
            return tuple(None if v is None else number(v, path + "." + key) for v in raw[key])
        return number(raw[key], path + "." + key)
    result["displayDamage"] = value("previewDamage", has_damage)
    result["displayBlock"] = value("previewBlock", has_block)
    result["displayDamageVs"] = value("previewDamageVs", has_damage)
    if PREVIEW_UNSUPPORTED in (result["displayDamage"], result["displayBlock"]) or (
            isinstance(result["displayDamageVs"], tuple) and PREVIEW_UNSUPPORTED in result["displayDamageVs"]):
        # Calculated variable this port does not model: explicit unknown, never a number.
        result.update(displayDamage=None, displayBlock=None, displayDamageVs=None, previewUnsupported=True)


def _raw_key(value):
    """Hashable, type-exact image of a raw transport value (bool/int/float stay distinct)."""
    kind = type(value)
    if kind is dict:
        return (dict,) + tuple((key, _raw_key(item)) for key, item in value.items())
    if kind is list or kind is tuple:
        return (kind,) + tuple(_raw_key(item) for item in value)
    if kind is str or kind is int or kind is bool or kind is float or value is None:
        return (kind, value)
    raise TypeError("uncacheable raw value")


# _card is a pure function of (raw content, source); the transport UID is never read.
# Cached results are only ever handed out as shallow copies (all values are immutable).
_CARD_CACHE: dict = {}
_CARD_CACHE_LIMIT = 8192  # about 5 KB per entry


def _card_text(card):
    return json.dumps({k: v for k, v in card.items() if k not in DISPLAY_KEYS}, sort_keys=True, separators=(",", ":"))


def _card_cached(raw, source, path):
    """(_card(raw, source, path), its sort text) with memoization of repeated cards."""
    try:
        key = (source,) + tuple((name, _raw_key(item)) for name, item in raw.items() if name != "transportId") \
            if type(raw) is dict else None
    except TypeError:
        key = None
    hit = _CARD_CACHE.get(key) if key is not None else None
    if hit is None:
        card = _card(raw, source, path)
        hit = (dict(card), _card_text(card))
        if key is not None:
            if len(_CARD_CACHE) >= _CARD_CACHE_LIMIT:
                _CARD_CACHE.clear()
            _CARD_CACHE[key] = hit
    return dict(hit[0]), hit[1]


def _freeze(value):
    if isinstance(value, dict):
        return tuple((key, _freeze(value[key])) for key in sorted(value))
    if isinstance(value, (tuple, list)):
        return tuple(_freeze(item) for item in value)
    return value


def card_semantic_fingerprint(raw, source):
    """Complete visible card identity for action routing; never contains a UID."""
    card = _card_cached(raw, source, source + ".card")[0]
    for key in ("pile", "position", "knownTopPosition", "selected", "price", "sold") + DISPLAY_KEYS:
        card.pop(key)
    return _freeze(card)


@dataclass
class PublicState:
    facts: dict[str, Any]
    actions: tuple  # BoundAction instances; handles never enter encode
    source: str


def _common(raw, projection, source, legacy_capture=False):
    if need(raw, "version", source) != 1:
        raise ObservationCoverageError(f"{source}: unsupported public export version")
    result = {"screen": projection.screen}
    result["eventPage"]=raw.get("eventPage")
    if projection.screen in ("event","neow") and not isinstance(result["eventPage"],str):
        raise ObservationCoverageError(source+".eventPage: missing visible event description key")
    p = need(raw, "player", source)
    result["player"] = {key: number(need(p, key, source + ".player"), key)
                        for key in ("hp", "maxHp", "block", "gold", "energy", "maxEnergy", "stars", "potionSlots")}
    for key in ("ostyHp", "ostyMaxHp"):  # appended later; pre-export native captures lack them
        if key in p: result["player"][key] = number(p[key], key)
        elif legacy_capture: result["player"][key] = None
        else: raise ObservationCoverageError(f"{source}.player.{key}: missing")
    if "orbs" in p:
        result["player"]["orbCapacity"] = number(need(p, "orbCapacity", source + ".player"), "orbCapacity")
        result["player"]["orbs"] = [{"modelId": need(orb, "modelId", source + ".player.orbs"),
                                     "passive": number(need(orb, "passive", source + ".player.orbs"), "passive"),
                                     "evoke": number(need(orb, "evoke", source + ".player.orbs"), "evoke")}
                                    for orb in p["orbs"]]
    elif legacy_capture:
        result["player"].update(orbCapacity=None, orbs=None)
    else:
        raise ObservationCoverageError(f"{source}.player.orbs: missing")
    run=need(raw,"run",source)
    result["run"] = {key:need(run,key,source+".run") for key in
        ("act","floor","actFloor","ascension","currentAct","boss","combatsFought","elitesFought","bossesFought",
         "cardShopRemovalsUsed","unknownMapPointsVisited")}
    result["run"]["secondBoss"]=run.get("secondBoss") # explicit nullable native JSON field
    for key in ("actNormalEncounters", "actEliteEncounters"):
        if key not in run:
            # Captures recorded before the host exported checklist D are replayable
            # only in explicit legacy mode; live states must carry the history.
            if not legacy_capture:
                raise ObservationCoverageError(f"{source}.run.{key}: missing act encounter history")
            result["run"][key] = None
        else:
            result["run"][key] = tuple(model(e, "ENCOUNTER", f"{source}.run.{key}") for e in run[key])
    combat = raw.get("combat")
    result["combat"] = None if combat is None else {key: number(need(combat, key, source + ".combat"), key) for key in _COMBAT_SCALARS}
    result["cards"] = []
    by_transport = {}
    sort_text = {}  # id(card) -> json text of the card as it was cached (knownTopPosition -1)
    for i, raw_card in enumerate(need(raw, "cards", source)):
        card, text = _card_cached(raw_card, source, f"{source}.cards[{i}]")
        sort_text[id(card)] = text
        result["cards"].append(card)
        # The same deck/combat UID can legitimately occur twice. Pile is part
        # of the routing key; it is never part of hidden order.
        by_transport[(raw_card.get("transportId"), card["pile"])] = card
    for i, known in enumerate(need(raw, "knownTop", source)):
        target = by_transport.get((known.get("transportId"), "draw"))
        if target is None:
            raise ObservationCoverageError(f"{source}.knownTop[{i}]: card is not in the visible draw multiset")
        target["knownTopPosition"] = i
        sort_text.pop(id(target), None)  # changed after caching: recompute its text
    result["cards"].sort(key=lambda c: sort_text.get(id(c)) or _card_text(c))
    for card in result["cards"]:
        if MISSING_PREVIEW in (card["displayDamage"], card["displayBlock"], card["displayDamageVs"]):
            if not legacy_capture:
                raise ObservationCoverageError(f"{source}.cards: hand/play card preview values missing")
            card.update(displayDamage=None, displayBlock=None, displayDamageVs=None)
    result["powers"] = _powers(need(p, "powers", source), source, source + ".player.powers")
    result["enemies"] = []
    for i, enemy in enumerate(need(raw, "enemies", source)):
        path = f"{source}.enemies[{i}]"
        row = {key: need(enemy, key, path) for key in ("modelId", "order", "hp", "maxHp", "block", "intentsVisible", "alive", "hittable", "reviving")}
        model(row["modelId"], "MONSTER", path)
        row["slotName"] = enemy.get("slotName")
        # A2 move prediction (appended export): steps of (move, local, p, type, damage, hits).
        if "moves" in enemy:
            row["moves"] = tuple(tuple(sorted((need(m, "move", path), number(need(m, "local", path), path),
                round(float(need(m, "p", path)), 9), need(m, "type", path), number(need(m, "damage", path), path),
                number(need(m, "hits", path), path)) for m in step)) for step in enemy["moves"])
            row["stunned"] = bool(need(enemy, "stunned", path))
        elif legacy_capture:
            row["moves"], row["stunned"] = None, None
        else:
            raise ObservationCoverageError(path + ".moves: missing move prediction")
        row["powers"] = _powers(need(enemy, "powers", path), source, path + ".powers")
        row["intents"] = tuple(sorted((enum(need(intent, "type", path), INTENTS, path),
            number(need(intent, "damage", path), path),
            max(1, number(need(intent, "hits", path), path)) if need(intent, "type", path) in (0, 13, "Attack", "DeathBlow") else 0)
            for intent in need(enemy, "intents", path)))
        result["enemies"].append(row)
    result["enemies"].sort(key=lambda e: e["order"])
    result["relics"] = []
    for i, relic in enumerate(need(raw, "relics", source)):
        path = f"{source}.relics[{i}]"
        row = {key: need(relic, key, path) for key in ("modelId", "position", "wax", "melted", "counterVisible", "counter", "status")}
        model(row["modelId"], "RELIC", path)
        result["relics"].append(row)
    # Native transport omits nullable properties (WhenWritingNull); an empty
    # physical potion slot therefore has no modelId, but retains its slot/state.
    result["potions"] = [dict({key:need(p,key,source+".potions") for key in
        ("slot", "queued", "disabledUntilRemoved")}, modelId=p.get("modelId"))
        for p in need(raw, "potions", source)]
    result["offers"]=[]
    for offer in need(raw,"offers",source):
        row={key:need(offer,key,source+".offers") for key in ("kind","modelId","amount","recovered","price","available")}
        if row["modelId"] is not None:
            if source=="simulator" and row["modelId"].startswith("CARD."):row["modelId"]=_CATALOG["simCardIds"].get(row["modelId"])
            model(row["modelId"],row["modelId"].split(".")[0],source+".offers")
        result["offers"].append(row)
    result["offers"].sort(key=lambda x:json.dumps(x,sort_keys=True))
    result["board"] = raw.get("board")
    if result["board"] is not None:
        board=result["board"]
        result["board"]={key:need(board,key,source+".board") for key in ("width","height","remaining","finished")}
        result["board"]["cells"]=sorted(({key:need(cell,key,source+".board.cells") for key in
            ("x","y","hidden","fragment","revealedItem","revealedReward")} for cell in need(board,"cells",source)),key=lambda c:(c["y"],c["x"]))
    result["map"] = []
    for point in need(raw, "map", source):
        point = dict(point)
        point["type"] = enum(point["type"], MAP_TYPES, source + ".map.type")
        point["children"] = sorted(point["children"], key=lambda c: (c["row"], c["col"]))
        point["quests"] = sorted(point["quests"])
        result["map"].append(point)
    result["map"].sort(key=lambda point: (point["row"], point["col"]))
    result["choices"] = [_card(card, source, source + ".choices") for card in need(raw, "choices", source)]
    for card in result["choices"]:
        card["pile"] = "offer"
        card["position"] = -1
    result["choices"].sort(key=lambda c: json.dumps(c, sort_keys=True, separators=(",", ":")))
    for index, card in enumerate(result["choices"]): card["position"] = index
    decision = raw.get("decision")
    result["decision"] = None if decision is None else {key: number(need(decision, key, source + ".decision"), key)
        for key in ("minSelect", "maxSelect", "requireManualConfirmation", "preview", "cancelable", "selectedCount")}
    if decision is not None:  # A6 (appended export)
        if "purpose" in decision:
            result["decision"]["purpose"] = enum(decision["purpose"], PURPOSES, source + ".decision.purpose")
            result["decision"]["service"] = number(need(decision, "service", source + ".decision"), "service")
        elif legacy_capture:
            result["decision"]["purpose"] = result["decision"]["service"] = None
        else:
            raise ObservationCoverageError(source + ".decision.purpose: missing selection purpose")
    # Semantic action ordering is public and reproducible; transport ordering
    # and native GUIDs are deliberately irrelevant.
    actions = tuple(sorted(projection.actions, key=lambda action: repr(action.key)))
    return PublicState(result, actions, source)


def _powers(rows, source, path):
    result = []
    for row in rows:
        ident = row.get("modelId")
        if source == "simulator":
            ident = _CATALOG["simPowerIds"][need(row, "id", path)]
        model(ident, "POWER", path)
        variables = _vars(need(row, "dynamicVars", path), path)
        required_variables = {"POWER.THE_BOMB_POWER": ("Damage",), "POWER.TORIC_TOUGHNESS_POWER": ("Block",),
            "POWER.CRIMSON_MANTLE_POWER": ("SelfDamage",), "POWER.INFERNO_POWER": ("SelfDamage",),
            "POWER.SLOW_POWER": ("SlowAmount",),
            "POWER.WITHERING_PRESENCE_POWER": ("CardsLeft",)}.get(ident, ())
        values = tuple((name, number(need(variables, name, path), path)) for name in required_variables)
        result.append((ident, number(need(row, "amount", path), path),
            number(need(row, "displayAmount", path), path), values))
    return tuple(sorted(result))


def from_native(frame, projection=None, legacy_capture=False):
    if projection is None:
        from parity.semantic import project_native
        projection = project_native(frame)
    raw = dict(need(frame, "publicObservation", "native"))
    choices = []
    offers=[]
    decision = frame.get("decision") or {}
    for choice in decision.get("choices", ()):
        card = choice.get("publicCard")
        if card is not None:
            choices.append(dict(card, selected=choice.get("selected", False), price=choice.get("cost", -1), sold=choice.get("sold", False)))
        for card in choice.get("publicCards", ()):
            choices.append(dict(card))
        if choice.get("kind","").startswith("Merchant") and card is None:
            offers.append(dict(kind=choice["kind"],modelId=None if choice["modelId"]=="CARD_REMOVAL" else choice["modelId"],
                amount=None,recovered=False,price=choice["cost"],available=choice["purchasable"]))
    for reward in decision.get("rewards",()):
        offers.append(dict(kind=reward["rewardType"],modelId=reward.get("modelId"),amount=reward.get("amount"),
            recovered=reward["recovered"],price=-1,available=reward["claimable"]))
        if reward.get("publicCard") is not None:choices.append(dict(reward["publicCard"]))
    if not choices:
        # Older host metadata is sufficient at interactive states; previews
        # require Decision.publicCard because actions can be temporarily absent.
        seen = set()
        for action in frame.get("actions", ()):
            metadata = action.get("metadata") or {}
            card = metadata.get("card")
            if card is not None and card.get("transportId") not in seen:
                seen.add(card.get("transportId"))
                choices.append(dict(card, price=metadata.get("cost", -1)))
    raw["choices"] = choices
    raw["offers"] = offers
    raw["board"] = decision.get("board")
    raw["eventPage"] = decision.get("pageKey") if projection.screen in ("event","neow") else None
    raw["decision"] = None
    if "minSelect" in decision or "maxSelect" in decision:
        raw["decision"] = {key: need(decision, key, "native.decision") for key in
                           ("minSelect", "maxSelect", "requireManualConfirmation", "cancelable")}
        raw["decision"]["preview"] = decision.get("preview", False) # hand picker has no preview surface
        for key in ("purpose", "service"):  # A6, once the host maps its selection screens
            if key in decision: raw["decision"][key] = decision[key]
        raw["decision"]["selectedCount"] = sum(bool(choice.get("selected")) for choice in decision.get("choices", ()))
        if decision.get("kind") == "hand_selection":
            raw["decision"]["maxSelect"] = min(raw["decision"]["maxSelect"], len(choices))
    return _common(raw, projection, "native", legacy_capture)


def from_simulator(rc, projection=None):
    from .sim import sim
    if projection is None:
        from parity.semantic import project_simulator
        projection = project_simulator(rc, sim)
    if not hasattr(sim, "public_model_state"):
        raise ObservationCoverageError("simulator: rebuild extension with public_model_state binding")
    raw=sim.public_model_state(rc)
    raw["eventPage"]=sim.event_page_key(rc) if projection.screen in ("event","neow") else None
    return _common(raw, projection, "simulator")


def vocab_sizes():
    return [(len(_MODELS[c]) + 1) if c else 64 for c in _KIND_CATEGORY]


# The encoded row of a card is a pure function of its fact dict. Keys keep scalar types
# exact (a bool and an int encode differently); nested values were already normalized by
# number(), so equal nested tuples encode to identical bytes.
_ROW_CACHE: dict = {}
_ROW_CACHE_LIMIT = 8192  # about 5 KB per entry


def _card_row(card, row):
    try:
        key = tuple([(name, type(value), value) for name, value in card.items()])
        cached = _ROW_CACHE.get(key)
    except TypeError:  # unhashable value: encode without caching
        key = cached = None
    if cached is not None:
        row[:] = cached
        return
    _fill_card_row(card, row)
    if key is not None:
        if len(_ROW_CACHE) >= _ROW_CACHE_LIMIT:
            _ROW_CACHE.clear()
        _ROW_CACHE[key] = row.copy()


def _fill_card_row(card, row):
    row[:len(_CARD_SCALARS)] = [number(need(card, key, "card"), key) if isinstance(card[key], bool)
                                else _sq(number(need(card, key, "card"), key), _CARD_SCALE.get(key, 10))
                                for key in _CARD_SCALARS]
    row[24 + CARD_TYPES.index(card["type"])] = 1
    row[30 + RARITIES.index(card["rarity"])] = 1
    row[41 + TARGETS.index(card["target"])] = 1
    for keyword in card["keywords"]: row[48 + KEYWORDS.index(keyword)] = 1
    for keyword in card["localKeywords"]: row[224 + KEYWORDS.index(keyword)] = 1
    for tag in card["tags"]: row[232 + TAGS.index(tag)] = 1
    for name, value in card["dynamicVars"]:
        if name not in _VARIABLE_INDEX:
            raise ObservationCoverageError("card.dynamicVars: unknown variable " + name)
        offset = 256 + 2 * _VARIABLE_INDEX[name]
        if offset + 1 >= NUM:
            raise ObservationCoverageError("card.dynamicVars: feature capacity exceeded")
        row[offset:offset+2] = [1, _sq(value, 30)]
    if card["enchantment"]:
        eid, amount, disabled, extra_damage = card["enchantment"]
        row[_enchantment_offset(ENCHANTMENTS.index(eid.split(".", 1)[1]))] = 1
        row[76:79] = [_sq(amount, 10), disabled, _sq(extra_damage, 30)]
    for affliction, amount in card["afflictions"]:
        row[80 + _IDS["AFFLICTION"][affliction]] = _sq(amount, 10)
    for j, (amount, absolute, expiration, reduce) in enumerate(card["costModifiers"]):
        row[96 + 4*j:100 + 4*j] = [_sq(amount, 5), absolute, expiration / 16, reduce]   # expiration: bits 2, 4, 8
    # A1 (appended block 544..): displayed damage/block and damage vs each enemy (public order).
    damage, block, vs = card["displayDamage"], card["displayBlock"], card["displayDamageVs"]
    row[544:549] = [damage is not None, _sq(damage or 0, 30), block is not None, _sq(block or 0, 30), card["previewUnsupported"]]
    if vs is not None:
        if len(vs) > 6:
            raise ObservationCoverageError("card.displayDamageVs: more than 6 enemies")
        for k, v in enumerate(vs):
            if v is not None: row[552 + 2*k:554 + 2*k] = [1, _sq(v, 30)]


# A6: public selection purposes (append-only; context row one-hot 360..). The native host
# must map its selection screens to the same names.
PURPOSES = ("none", "combat.upgrade", "combat.exhaust", "combat.return_discard_top", "combat.put_hand_top",
    "combat.draw_to_hand", "combat.discard_to_hand", "combat.offer_to_hand", "combat.give_replay", "combat.transform",
    "combat.make_free", "combat.duplicate", "combat.discard", "combat.silent_discard", "combat.sculpt_ethereal",
    "combat.regent_transform", "combat.knowledge_curse", "combat.gambling_chip",
    "deck.brain_leech", "deck.cheese", "deck.claws", "deck.paels_growth", "deck.scroll_boxes", "deck.remove",
    "deck.transform", "deck.transform_upgrade", "deck.upgrade", "deck.paels_tooth", "deck.enchant_spiral",
    "deck.enchant_steady", "deck.sea_glass", "deck.dusty_tome", "deck.enchant_imbued", "deck.hefty_tablet",
    "deck.duplicate", "deck.enchant_sharp", "deck.enchant_adroit", "deck.enchant_momentum",
    "deck.enchant_royally_approved", "deck.event", "deck.enchant_instinct",
    # v9: ChoiceOps the old positional table mislabelled (other characters' selections).
    "combat.silent_sly", "combat.silent_nightmare", "combat.snap_retain", "combat.seance", "combat.transfigure",
    "combat.regent_clone", "combat.regent_auto_skill")
# Card-grid service: 0 none, 1 rest-site Smith, 2 merchant removal, 3 removal reward, 4 Cook, 5 Lord's Parasol.
SERVICES = 6

_ROW_BLOCK = 64


def encode(state: PublicState) -> UObs:
    """Encode simulator/native PublicState with one numeric layout and action mask."""
    f = state.facts
    kinds, ids, rows, edges = [], [], [], []
    # Rows are views into zeroed blocks (one allocation per 64 entities instead of one
    # per entity); earlier views stay valid because filled blocks are never reallocated.
    blocks = []
    def add(kind, ident=None, values=()):
        index = len(rows)
        if index % _ROW_BLOCK == 0:
            blocks.append(np.zeros((_ROW_BLOCK, NUM), np.float32))
        row = blocks[-1][index % _ROW_BLOCK]
        if len(values) > NUM:
            raise ObservationCoverageError("entity feature capacity exceeded")
        row[:len(values)] = values
        kinds.append(kind); ids.append(_IDS[_KIND_CATEGORY[kind]][ident] if ident else 0); rows.append(row)
        return index, row
    p, r = f["player"], f["run"]
    g = np.zeros(NUM, np.float32)
    g[:5] = [p["hp"] / p["maxHp"], _sq(p["hp"], 100), _sq(p["maxHp"], 100), _sq(p["gold"], 300), r["floor"] / 49]
    g[5 + r["act"]] = 1
    g[8:12] = [r["actFloor"] / 16, r["ascension"] / 10, p["potionSlots"] / 5, _sq(len(f["cards"]), 100)]
    g[12:17] = [_sq(need(r, key, "run"), 20) for key in ("combatsFought", "elitesFought", "bossesFought", "cardShopRemovalsUsed", "unknownMapPointsVisited")]
    g[17 + ("ACT.OVERGROWTH", "ACT.HIVE", "ACT.GLORY", "ACT.UNDERDOCKS").index(r["currentAct"])] = 1
    g[derived.DECK_OFFSET:derived.DECK_OFFSET + derived.DECK_WIDTH] = derived.deck_summary(f["cards"])  # E
    act_summary, act_rows = derived.act_encounters(r, _CATALOG["acts"], _CATALOG["encounterTags"])  # D
    g[derived.ACT_OFFSET:derived.ACT_OFFSET + derived.ACT_WIDTH] = act_summary
    add(0, values=g)
    context = add(1)[1]
    screens = ("neow", "event", "map", "combat", "rewards", "card_reward", "shop", "rest", "treasure", "card_grid", "terminal", "combat_selection", "card_selection", "crystal_sphere", "relic_selection", "card_bundle", "shop_entry")
    if f["screen"] not in screens:
        raise ObservationCoverageError("screen: unsupported semantic screen " + f["screen"])
    context[screens.index(f["screen"])] = 1
    if f["eventPage"] is not None:
        page=f["eventPage"].encode("utf-8")
        if len(page)>256:raise ObservationCoverageError("eventPage: exceeds public encoding capacity")
        context[96]=len(page)/256;context[97:97+len(page)]=np.frombuffer(page,dtype=np.uint8)/255
    if f["decision"] is not None:
        d = f["decision"]
        context[32:39] = [1, _sq(d["minSelect"], 10), _sq(d["maxSelect"], 10), d["requireManualConfirmation"],
                          d["preview"], d["cancelable"], _sq(d["selectedCount"], 10)]
        purpose = f["decision"].get("purpose")
        if purpose is None:
            context[359] = 1  # purpose not exported (legacy capture)
        else:
            context[360 + PURPOSES.index(purpose)] = 1
            context[424 + int(f["decision"]["service"])] = 1
    card_refs, enemy_refs, potion_refs = {}, {}, {}
    def add_card(card):
        pile = card["pile"]
        kind = {"deck": 2, "offer": 7, "choice": 20, "hand": 16, "draw": 17, "discard": 18, "exhaust": 19, "play": 21}.get(pile)
        if kind is None:
            raise ObservationCoverageError("card.pile: " + pile)
        i, row = add(kind, card["modelId"])
        _card_row(card, row)
        if pile == "hand": card_refs[card["position"]] = i
        return i
    for card in f["cards"]:
        if card["pile"] == "deck": add_card(card)
    choice_refs = [add_card(card) for card in f["choices"]]
    for relic in f["relics"]:
        add(3, relic["modelId"], [relic["position"] / 64, relic["wax"], relic["melted"], relic["counterVisible"],
            _sq(relic["counter"], 10), ("Normal", "Active", "Disabled").index(relic["status"])])
    map_refs = {}
    routes = derived.route_summary(f["map"])  # A5
    for point in f["map"]:
        index, row = add(5, values=[point["row"] / 18, point["col"] / 7, point["visited"], point["current"]])
        map_refs[(point["row"], point["col"])] = index
        row[4 + MAP_TYPES.index(enum(point["type"], MAP_TYPES, "map.type"))] = 1
        row[15] = len(point["quests"])
        for quest in point["quests"]:
            # Map-point quest markers: Spoils Map (16); Fur Coat's 1-HP combat marks (17, appended).
            if quest == "CARD.SPOILS_MAP": row[16]=1
            elif quest == "RELIC.FUR_COAT": row[17]=1
            else: raise ObservationCoverageError("map.quests: unknown visible quest "+quest)
        row[derived.ROUTE_OFFSET:derived.ROUTE_OFFSET + derived.ROUTE_WIDTH] = routes[(point["row"], point["col"])]
    for point in f["map"]:
        for child in point["children"]:
            edges.append((map_refs[(point["row"], point["col"])], map_refs[(child["row"], child["col"])]))
    for second, boss in enumerate((r["boss"], r["secondBoss"])):
        if boss: add(6, model(boss, "ENCOUNTER", "run.boss"), [1, 0, 0, 0, 0, 0, 0, 0, 0, second])
    for name in sorted(act_rows):
        add(6, model(name, "ENCOUNTER", "run.actEncounters"), [0] + act_rows[name])
    offer_types=("GoldReward","PotionReward","RelicReward","CardReward","CardRemovalReward","SpecialCardReward",
        "MerchantRelicEntry","MerchantPotionEntry","MerchantCardRemovalEntry")
    for offer in f["offers"]:
        ident=offer["modelId"];category=ident.split(".")[0] if ident else None
        _,row=add({"RELIC":8,"POTION":9,"CARD":7,None:10}[category],ident,
            [offer["amount"] is not None,_sq(offer["amount"] or 0,100),offer["recovered"],_sq(offer["price"],100),offer["available"]])
        if offer["kind"] not in offer_types:raise ObservationCoverageError("offer.kind: unknown "+offer["kind"])
        row[8+offer_types.index(offer["kind"])]=1
    sphere_refs={}
    if f["board"] is not None:
        board=f["board"];context[48:53]=[1,_sq(board["width"],10),_sq(board["height"],10),_sq(board["remaining"],10),board["finished"]]
        item_types=(None,"CrystalSphereRelic","CrystalSpherePotion","CrystalSphereCardReward","CrystalSphereCurse","CrystalSphereGold")
        for cell in board["cells"]:
            i,row=add(12,values=[cell["x"]/10,cell["y"]/10,cell["hidden"],cell["fragment"]])
            row[4+item_types.index(cell["revealedItem"])]=1;sphere_refs[(cell["x"],cell["y"])]=i
            if cell["revealedReward"] is not None:
                reward=cell["revealedReward"];row[12:14]=[reward["amount"] is not None,_sq(reward["amount"] or 0,30)]
                row[14+(None,"Common","Uncommon","Rare").index(reward["rarity"])]=1
    # Visible non-card offers have their own model embeddings, including Neow
    # options. Their identity must not disappear into an anonymous action mask.
    offer_refs = {}
    offer_categories = {"neow_relic":"RELIC", "take_relic_reward":"RELIC", "take_treasure_relic":"RELIC",
        "select_relic":"RELIC", "buy_relic":"RELIC", "take_potion":"POTION", "buy_potion":"POTION",
        "take_special_card":"CARD", "buy_card":"CARD"}
    for action in state.actions:
        category = offer_categories.get(action.key.kind)
        if category:
            ident = category + "." + action.key.args[0]
            if category == "CARD": ident = _CATALOG["simCardIds"].get(ident, ident)
            model(ident, category, "action.offer")
            if ident not in offer_refs:
                offer_refs[ident] = add({"CARD":7,"RELIC":8,"POTION":9}[category], ident)[0]
        elif action.key.kind in ("event_option", "event_proceed"):
            ident = "EVENT." + action.key.args[0]
            model(ident, "EVENT", "action.event")
            if ident not in offer_refs: offer_refs[ident] = add(11, ident)[0]
    n_ctx = len(rows)
    player_row = np.zeros(NUM, np.float32)
    in_combat = f["combat"] is not None
    if in_combat:
        player_row[:7] = [p["hp"] / p["maxHp"], _sq(p["hp"], 100), _sq(p["maxHp"], 100), _sq(p["block"], 50),
                           _sq(p["energy"], 3), _sq(p["maxEnergy"], 3), _sq(p["stars"], 10)]
        player_row[8:8+len(_COMBAT_SCALARS)] = [_sq(f["combat"][key], 10) for key in _COMBAT_SCALARS]
        player_row[derived.DRAW_OFFSET:derived.DRAW_OFFSET + derived.DRAW_WIDTH] = derived.draw_odds(f)  # C
        loss, unknown, self_damage, incoming = tactics.end_turn(f)  # A4 (appended 96..)
        player_row[96:102] = [1, _sq(loss, 50), loss >= p["hp"], unknown, _sq(self_damage, 20), _sq(incoming, 50)]
        player_row[104:107] = [p["ostyHp"] is not None, _sq(p["ostyHp"] or 0, 50), _sq(p["ostyMaxHp"] or 0, 50)]
        player_row[107:109] = [p["orbs"] is not None, _sq(p["orbCapacity"] or 0, 10)]
        for slot, orb in enumerate(p["orbs"] or ()):         # queue order, 7 columns per slot
            if slot >= MAX_ORBS or orb["modelId"] not in ORB_KINDS:
                raise ObservationCoverageError("player.orbs: unexpected orb " + str(orb["modelId"]))
            base = 109 + 7 * slot
            player_row[base + ORB_KINDS.index(orb["modelId"])] = 1
            player_row[base + 5:base + 7] = [_sq(orb["passive"], 20), _sq(orb["evoke"], 20)]
        reach = tactics.max_damage(state)  # A3
        previews = tactics.action_preview(state)  # B
        add(13, values=player_row)
        for ident, amount, display, variables in f["powers"]:
            add(15, ident, [_sq(amount, 10), _sq(display, 10)] + [_sq(value, 10) for name, value in variables])
        for card in f["cards"]:
            if card["pile"] != "deck": add_card(card)
        for enemy in f["enemies"]:
            i, row = add(22, enemy["modelId"], [enemy["order"] / 5, _sq(enemy["hp"], 200), _sq(enemy["maxHp"], 200),
                _sq(enemy["block"], 50), enemy["intentsVisible"], enemy["alive"], enemy["hittable"], enemy["reviving"]])
            enemy_refs[enemy["order"]] = i
            if enemy["moves"] is None:   # A2 (appended 610..)
                row[665] = 1
            else:
                for k, step in enumerate(enemy["moves"][:3]):
                    for move, local, prob, kind, damage, hits in step:
                        if not 0 <= local < 16:
                            raise ObservationCoverageError("enemy.moves: more than 16 monster states")
                        row[610 + 16 * k + local] += prob
                        if k and kind == 0:
                            row[658 + 2 * (k - 1)] += prob
                            row[659 + 2 * (k - 1)] += prob * damage * max(1, hits) / 50
                row[659] = _sq(row[659], 1); row[661] = _sq(row[661], 1)   # expected damage (already / 50)
                row[664] = bool(enemy["stunned"])
            if enemy["order"] in reach:  # A3 (appended 600..)
                total, kills, unknown = reach[enemy["order"]]
                row[600:604] = [1, _sq(total, 50), kills, unknown]
            slot=(enemy["slotName"] or "").encode("utf-8")
            if len(slot)>128:raise ObservationCoverageError("enemy.slotName: exceeds public encoding capacity")
            row[64]=len(slot)/128;row[65:65+len(slot)]=np.frombuffer(slot,dtype=np.uint8)/255
            for intent, damage, hits in enemy["intents"]:
                pos = 8 + INTENTS.index(intent) * 3
                row[pos:pos+3] = [1, _sq(damage, 50), _sq(hits, 5)]
            for ident, amount, display, variables in enemy["powers"]:
                add(23, ident, [_sq(amount, 10), enemy["order"] / 5, _sq(display, 10)] + [_sq(value, 10) for name, value in variables])
    for potion in f["potions"]:
        index, _ = add(24 if in_combat else 4, potion["modelId"], [potion["slot"] / 5, potion["modelId"] is None,
            potion["queued"],potion["disabledUntilRemoved"]])
        potion_refs[potion["slot"]] = index
    if not in_combat: n_ctx = len(rows)
    if not in_combat: previews = {}
    types, c1, c2, nums = [], [], [], []
    def fingerprint(card):
        return _freeze({k:v for k,v in card.items() if k not in ("pile","position","knownTopPosition","selected","price","sold")+DISPLAY_KEYS})
    card_fp_refs = {}
    for card, ref in zip(f["choices"], choice_refs): card_fp_refs.setdefault(fingerprint(card), []).append(ref)
    def descriptor(value):
        if isinstance(value, tuple):
            if value in card_fp_refs:
                return {"cardEntity": card_fp_refs[value][0]}
            return [descriptor(x) for x in value]
        if isinstance(value, (bool, int, float, str)) or value is None: return value
        raise ObservationCoverageError("action: unsupported semantic argument type")
    for index, action in enumerate(state.actions):
        key = action.key
        if key.kind not in ACTION_KINDS:
            raise ObservationCoverageError(f"action[{index}].kind: unmapped {key.kind!r}")
        t1, t2, values = -1, -1, np.zeros(CAND_NUM, np.float32)
        args = key.args
        if key.kind == "play":
            t1 = card_refs[args[0][0]]
            if len(args) > 1 and args[1] is not None: t2 = enemy_refs[args[1][0]]
        elif key.kind == "move":
            t1 = map_refs[(args[1], args[0])]
        elif key.kind == "reveal_cell":
            t1 = sphere_refs[(args[-2],args[-1])]
        elif key.kind in ("use_potion", "discard_potion"):
            t1 = potion_refs[args[0]]
            if key.kind == "use_potion" and len(args)>2 and args[2] is not None: t2 = enemy_refs[args[2][0]]
        elif key.kind in ("select_card", "deselect_card", "take_card"):
            if len(args) < 4 or args[2] not in card_fp_refs:
                raise ObservationCoverageError(f"action[{index}]: full visible card fingerprint has no candidate entity")
            matches = [ref for ref in card_fp_refs[args[2]] if key.kind == "take_card" or
                       bool(f["choices"][choice_refs.index(ref)]["selected"]) == (key.kind == "deselect_card")]
            ordinal = args[-1]
            if not 0 <= ordinal < len(matches):
                raise ObservationCoverageError(f"action[{index}]: duplicate candidate ordinal is out of range")
            t1 = matches[ordinal]
        elif key.kind in offer_categories:
            category = offer_categories[key.kind]
            ident = category + "." + args[0]
            if category == "CARD": ident = _CATALOG["simCardIds"].get(ident, ident)
            t1 = offer_refs[ident]
        elif key.kind in ("event_option", "event_proceed"):
            t1 = offer_refs["EVENT." + args[0]]
        # Explicit numeric arguments are useful for prices, option/candidate
        # display positions and confirmations. No transport IDs enter this row.
        scalar_args = [x for x in args if isinstance(x, (int, float, bool))]
        if len(scalar_args) > 15:
            raise ObservationCoverageError(f"action[{index}]: numeric descriptor capacity")
        values[:len(scalar_args)] = [_sq(x, 10) for x in scalar_args]
        # Preserve the complete semantic descriptor (public model/TextKeys,
        # bundle membership, duplicate ordinal and constraints). UTF-8 bytes are
        # an injective fixed input, unlike Python hash() or truncated model IDs.
        # Rich card tuples are represented by their already encoded entity.
        encoded = json.dumps(descriptor(args), ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        if len(encoded) > DESCRIPTOR_CAP:
            raise ObservationCoverageError(f"action[{index}]: semantic descriptor exceeds {DESCRIPTOR_CAP} bytes")
        values[15] = len(encoded) / DESCRIPTOR_CAP
        values[16:16+len(encoded)] = np.frombuffer(encoded, dtype=np.uint8) / 255
        preview = previews.get(index)  # B (appended block)
        if preview is not None:
            values[B_OFFSET:B_OFFSET + 11] = [1, preview["known"], _sq(preview["hp_damage"], 50), preview["kills"],
                _sq(preview["total_damage"], 50), _sq(preview["block"], 30), _sq(preview["energy_after"], 5),
                _sq(preview["end_turn_loss"], 50), preview["lethal_after"], preview["unknown"],
                _sq(preview["self_hp_loss"], 50)]
        types.append(ACTION_KINDS.index(key.kind)); c1.append(t1); c2.append(t2); nums.append(values)
    out = UObs(np.asarray(kinds, np.int64), np.asarray(ids, np.int64), np.concatenate(blocks)[:len(rows)].copy(),
        np.asarray(edges, np.int64).reshape(-1, 2), g, player_row, np.asarray(types, np.int64),
        np.arange(len(types), dtype=np.int64), np.asarray(c1, np.int64), np.asarray(c2, np.int64),
        np.asarray(nums, np.float32).reshape(-1, CAND_NUM), in_combat, n_ctx)
    out.schema_id = SCHEMA_ID
    return out


def observe_simulator(rc):
    return encode(from_simulator(rc))


def observe_native(frame):
    return encode(from_native(frame))


def differences(left: PublicState, right: PublicState):
    """All differing public paths; never treat absent/missing as numeric zero."""
    found = []
    def visit(a, b, path):
        if isinstance(a, dict) and isinstance(b, dict):
            for key in sorted(set(a) | set(b)):
                if key not in a or key not in b: found.append((path + "." + key, a.get(key, "<missing>"), b.get(key, "<missing>")))
                else: visit(a[key], b[key], path + "." + key)
        elif isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
            if len(a) != len(b): found.append((path + ".length", len(a), len(b)))
            for i, (aa, bb) in enumerate(zip(a, b)): visit(aa, bb, f"{path}[{i}]")
        elif a != b: found.append((path, a, b))
    visit(left.facts, right.facts, "public")
    visit(tuple({"kind":a.key.kind,"args":a.key.args} for a in left.actions),
          tuple({"kind":a.key.kind,"args":a.key.args} for a in right.actions), "actions")
    return found


def candidate_handle(state: PublicState, index: int):
    """Route a sampled semantic candidate back to its backend without UID features."""
    if not isinstance(index, (int, np.integer)) or not 0 <= index < len(state.actions):
        raise IndexError("public policy candidate index is out of range")
    return state.actions[int(index)].handle


def step_simulator(rc, state: PublicState, index: int):
    """Apply the exact candidate shown to the shared network at this decision."""
    if state.source != "simulator":
        raise ValueError("simulator step requires a simulator PublicState")
    from parity.semantic import project_simulator
    from .sim import sim
    current = from_simulator(rc, project_simulator(rc, sim))
    if differences(state, current):
        raise ValueError("stale public policy decision; observe the current state again")
    handle = candidate_handle(state, index)
    return rc.step_combat(*handle) if state.facts["combat"] is not None else rc.step(*handle)
