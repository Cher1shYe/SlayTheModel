"""Convert Spire Codex replay journals into a safe reconstructed dataset.

Spire Codex records a detailed event stream, but it is not the native
SlayTheModel collector schema.  In particular, combat ``play`` events do not
carry the complete legal action set at the moment of input.  This module keeps
that distinction explicit:

* recorded outside decisions are paired with their recorded options and can be
  marked BC eligible;
* combat actions receive a public, order-free reconstructed observation, but
  remain BC ineligible until a native replay supplies the legal action set;
* future draw order, RNG state, seed, timestamps, localized text and native
  object IDs never appear in the converted records.

The result is an auditable intermediate format.  It is deliberately not
accepted by the collector tensorizer as if it were a native collector journal.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from copy import deepcopy
from dataclasses import dataclass, field
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import tempfile
from typing import Any, Iterable, Mapping, Sequence


FORMAT_VERSION = "stm-spire-codex-reconstructed-v1"
EXPECTED_REPLAY_VERSION = 7
EXPECTED_RECORDER_VERSION = "v1.2.1"
EXPECTED_BUILD = "v0.111.0"
STANDARD_RUN_STARTING_GOLD = 99
CHARACTERS = frozenset({"IRONCLAD", "SILENT", "DEFECT", "NECROBINDER", "REGENT"})
CORE_MODS = frozenset({"BaseLib", "SpireCodex"})

# These source fields are either private metadata, future information, local
# timing, localized prose, or native instance identities.  Converted records
# are allowlisted, then recursively checked against this set as a final guard.
FORBIDDEN_OUTPUT_KEYS = frozenset(
    {
        "seed",
        "start_time",
        "wall_clock",
        "rng_state",
        "draw_order",
        "order_c",
        "order_deck_c",
        "ms",
        "label",
        "desc",
        "instance_id",
        "combat_card_id",
        "native_id",
    }
)


class ConversionError(ValueError):
    """A source replay violates the converter's trust boundary."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_events(path: Path) -> list[dict[str, Any]]:
    opener = gzip.open if path.suffix == ".gz" else open
    events: list[dict[str, Any]] = []
    with opener(path, "rt", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            try:
                event = json.loads(line)
            except (UnicodeError, json.JSONDecodeError) as exc:
                raise ConversionError(f"{path}:{line_number}: invalid JSON: {exc}") from exc
            if not isinstance(event, dict):
                raise ConversionError(f"{path}:{line_number}: event is not an object")
            events.append(event)
    if not events:
        raise ConversionError(f"{path}: empty replay")
    sequences = [event.get("s") for event in events]
    if not all(type(value) is int for value in sequences):
        raise ConversionError(f"{path}: missing integer source sequence")
    expected = list(range(sequences[0], sequences[0] + len(sequences)))
    if sequences != expected:
        raise ConversionError(f"{path}: non-contiguous source sequence")
    return events


def _card_public(card: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if not card or not isinstance(card.get("model_id"), str):
        return None
    result: dict[str, Any] = {
        "model_id": card["model_id"],
        "upgrade": int(card.get("upgrade", 0)),
    }
    enchantment = card.get("enchantment")
    if isinstance(enchantment, str):
        result["enchantment"] = enchantment
        if type(card.get("enchantment_amount")) is int:
            result["enchantment_amount"] = card["enchantment_amount"]
    afflictions = card.get("afflictions")
    if isinstance(afflictions, dict) and afflictions:
        result["afflictions"] = [
            {"model_id": model_id, "amount": amount}
            for model_id, amount in sorted(afflictions.items())
            if isinstance(model_id, str) and type(amount) is int and amount > 0
        ]
    return result


def _card_sort_key(card: Mapping[str, Any]) -> str:
    return json.dumps(card, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _copy_card_from_source(raw: Mapping[str, Any]) -> dict[str, Any] | None:
    model_id = raw.get("id")
    if not isinstance(model_id, str):
        return None
    card: dict[str, Any] = {"model_id": model_id, "upgrade": int(raw.get("up", 0))}
    if isinstance(raw.get("enchantment"), str):
        card["enchantment"] = raw["enchantment"]
        if type(raw.get("amount")) is int:
            card["enchantment_amount"] = raw["amount"]
    return card


def _public_option(raw: Mapping[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {
        "source_option_index": raw.get("option_index"),
        "kind": raw.get("option_kind"),
        "option_id": raw.get("option_id"),
        "selectable": raw.get("selectable") is True,
    }
    for source, target in (
        ("up", "upgrade"),
        ("selectable_reason", "selectable_reason"),
        ("grants_relic", "grants_relic"),
        ("grants_card", "grants_card"),
    ):
        value = raw.get(source)
        if isinstance(value, (str, int)) and not isinstance(value, bool):
            result[target] = value
    return {key: value for key, value in result.items() if value is not None}


def _public_shop_item(kind: str, raw: Mapping[str, Any]) -> dict[str, Any] | None:
    model_id = raw.get("id")
    slot = raw.get("slot")
    cost = raw.get("cost")
    if not isinstance(model_id, str) or type(slot) is not int or type(cost) is not int:
        return None
    result: dict[str, Any] = {
        "kind": f"buy_{kind}",
        "slot": slot,
        "model_id": model_id,
        "cost": cost,
        "stocked": raw.get("stocked") is True,
    }
    if raw.get("sale") is True:
        result["sale"] = True
    if isinstance(raw.get("pool"), str):
        result["pool"] = raw["pool"]
    return result


def _assert_safe(value: Any, *, path: str = "record") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if key in FORBIDDEN_OUTPUT_KEYS:
                raise ConversionError(f"{path}: forbidden output field {key!r}")
            _assert_safe(child, path=f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _assert_safe(child, path=f"{path}[{index}]")


@dataclass(frozen=True)
class _Segment:
    index: int
    start: int
    stop: int
    capture_status: str
    terminal_reason: str | None
    resumed: bool


def _segments(events: Sequence[Mapping[str, Any]]) -> tuple[list[_Segment], list[int]]:
    starts = [index for index, event in enumerate(events) if event.get("t") == "header"]
    if not starts or starts[0] != 0:
        raise ConversionError("replay does not start with a header")
    segments: list[_Segment] = []
    index_by_event = [-1] * len(events)
    for segment_index, start in enumerate(starts):
        stop = starts[segment_index + 1] if segment_index + 1 < len(starts) else len(events)
        body = events[start:stop]
        endings = [event for event in body if event.get("t") == "end"]
        ending = endings[-1] if endings else {}
        segment = _Segment(
            index=segment_index,
            start=start,
            stop=stop,
            capture_status=str(ending.get("capture_status") or "missing"),
            terminal_reason=ending.get("terminal_reason") if isinstance(ending.get("terminal_reason"), str) else None,
            resumed=any(event.get("t") == "resume" for event in body),
        )
        segments.append(segment)
        for event_index in range(start, stop):
            index_by_event[event_index] = segment_index
    return segments, index_by_event


@dataclass
class _RunState:
    character: str | None = None
    ascension: int | None = None
    act: int | None = None
    floor: int | None = None
    hp: int | None = None
    max_hp: int | None = None
    gold: int | None = None
    deck: dict[int, dict[str, Any]] = field(default_factory=dict)
    relics: dict[str, int | None] = field(default_factory=dict)
    potions: dict[int, str] = field(default_factory=dict)
    map_state: dict[str, Any] | None = None
    room: dict[str, Any] | None = None
    shop: dict[str, Any] | None = None
    combat: dict[str, Any] | None = None
    cards: dict[int, dict[str, Any]] = field(default_factory=dict)
    # The recorder's player ``end_turn`` hook runs immediately after the
    # native hand flush. Preserve the state from immediately before that
    # flush so the action uses the hand the player actually saw.
    before_hand_flush: tuple[dict[str, Any], list[str]] | None = None

    def reset(self, header: Mapping[str, Any]) -> None:
        self.character = header.get("character") if isinstance(header.get("character"), str) else None
        self.ascension = header.get("ascension") if type(header.get("ascension")) is int else None
        self.act = header.get("act") if type(header.get("act")) is int else 1
        self.floor = header.get("floor") if type(header.get("floor")) is int else 0
        self.hp = None
        self.max_hp = header.get("starting_max_hp") if type(header.get("starting_max_hp")) is int else None
        # The curated corpus is restricted to unmodified standard solo runs.
        # v0.111.0 starts those runs at 99 gold.  Reloaded segments receive an
        # exact current value from the following ``resume`` event instead.
        self.gold = STANDARD_RUN_STARTING_GOLD if header.get("reloads") == 0 else None
        self.deck = {}
        self.relics = {
            relic["id"]: relic.get("n") if type(relic.get("n")) is int else None
            for relic in header.get("relics", [])
            if isinstance(relic, dict) and isinstance(relic.get("id"), str)
        }
        self.potions = {
            potion["slot"]: potion["id"]
            for potion in header.get("potions", [])
            if isinstance(potion, dict)
            and type(potion.get("slot")) is int
            and isinstance(potion.get("id"), str)
        }
        self.map_state = None
        self.room = None
        self.shop = None
        self.combat = None
        self.cards = {}
        self.before_hand_flush = None
        starting_deck = header.get("starting_deck")
        if isinstance(starting_deck, list):
            self._set_deck(starting_deck)

    def _set_deck(self, raw_cards: Iterable[Any]) -> None:
        deck: dict[int, dict[str, Any]] = {}
        for raw in raw_cards:
            if not isinstance(raw, dict) or type(raw.get("c")) is not int:
                continue
            card = _copy_card_from_source(raw)
            if card is not None:
                deck[raw["c"]] = card
        self.deck = deck

    def _card(self, event: Mapping[str, Any]) -> dict[str, Any] | None:
        ref = event.get("c")
        if type(ref) is not int:
            return _copy_card_from_source(event)
        if ref not in self.cards:
            deck_ref = event.get("deck_c")
            if type(deck_ref) is int and deck_ref in self.deck:
                self.cards[ref] = deepcopy(self.deck[deck_ref])
            else:
                card = _copy_card_from_source(event)
                if card is not None:
                    self.cards[ref] = card
        card = self.cards.get(ref)
        if card is not None:
            if isinstance(event.get("id"), str):
                card["model_id"] = event["id"]
            if type(event.get("up")) is int:
                card["upgrade"] = event["up"]
        return card

    def _remove_from_piles(self, ref: int) -> None:
        if self.combat is None:
            return
        for refs in self.combat["piles"].values():
            refs.discard(ref)

    def _creature(self, event: Mapping[str, Any], prefix: str) -> dict[str, Any] | None:
        if self.combat is None:
            return None
        cid = event.get(f"{prefix}_cid")
        if type(cid) is int:
            return self.combat["creatures"].get(cid)
        name = event.get(prefix)
        if name == "player":
            return self.combat["player"]
        matches = [
            creature
            for creature in self.combat["creatures"].values()
            if creature.get("model_id") == name and creature.get("alive") is not False
        ]
        return matches[0] if len(matches) == 1 else None

    def _public_cards(self, refs: Iterable[int]) -> list[dict[str, Any]]:
        cards = [_card_public(self.cards.get(ref)) for ref in refs]
        return sorted((card for card in cards if card is not None), key=_card_sort_key)

    def snapshot(self, *, include_map: bool) -> tuple[dict[str, Any], list[str]]:
        issues: list[str] = []
        deck = sorted(
            (card for card in (_card_public(value) for value in self.deck.values()) if card is not None),
            key=_card_sort_key,
        )
        run: dict[str, Any] = {
            "character": self.character,
            "ascension": self.ascension,
            "act": self.act,
            "floor": self.floor,
            "current_hp": self.hp,
            "max_hp": self.max_hp,
            "gold": self.gold,
            "deck": deck,
            "relics": [
                {"model_id": model_id, **({"counter": counter} if counter is not None else {})}
                for model_id, counter in sorted(self.relics.items())
            ],
            "potions": [
                {"slot": slot, "model_id": model_id}
                for slot, model_id in sorted(self.potions.items())
            ],
            "room": deepcopy(self.room),
        }
        if include_map and self.map_state is not None:
            run["map"] = deepcopy(self.map_state)
        if self.character is None:
            issues.append("character_missing")
        if not deck:
            issues.append("deck_missing")
        if self.max_hp is None:
            issues.append("max_hp_missing")
        observation: dict[str, Any] = {"run": run, "combat": None}
        if self.combat is not None:
            player = self.combat["player"]
            enemies = []
            companions = []
            for creature in sorted(self.combat["creatures"].values(), key=lambda item: item["slot"]):
                projected = {
                    "slot": creature["slot"],
                    "model_id": creature.get("model_id"),
                    "current_hp": creature.get("hp"),
                    "max_hp": creature.get("max_hp"),
                    "block": creature.get("block", 0),
                    "alive": creature.get("alive", True),
                    "powers": [
                        {"model_id": model_id, "amount": amount}
                        for model_id, amount in sorted(creature.get("powers", {}).items())
                        if type(amount) is int and amount != 0
                    ],
                }
                if creature.get("side") == "ally":
                    companions.append(projected)
                else:
                    projected["intent"] = deepcopy(creature.get("intent"))
                    enemies.append(projected)
            piles = self.combat["piles"]
            observation["combat"] = {
                "encounter": self.combat.get("encounter"),
                "turn": self.combat.get("turn"),
                "round": self.combat.get("round"),
                "energy": self.combat.get("energy"),
                "stars": self.combat.get("stars"),
                "player": {
                    "current_hp": self.hp,
                    "max_hp": self.max_hp,
                    "block": player.get("block", 0),
                    "powers": [
                        {"model_id": model_id, "amount": amount}
                        for model_id, amount in sorted(player.get("powers", {}).items())
                        if type(amount) is int and amount != 0
                    ],
                },
                "enemies": enemies,
                "companions": companions,
                "piles": {
                    "hand": self._public_cards(piles["hand"]),
                    "draw": self._public_cards(piles["draw"]),
                    "discard": self._public_cards(piles["discard"]),
                    "exhaust": self._public_cards(piles["exhaust"]),
                },
                "orbs": [dict(orb) for orb in self.combat.get("orbs", [])],
            }
            if not self.combat.get("draw_membership_known"):
                issues.append("draw_pile_membership_unknown")
        return observation, issues

    def apply(self, event: Mapping[str, Any]) -> None:
        kind = event.get("t")
        if type(event.get("act")) is int:
            self.act = event["act"]
        if type(event.get("floor")) is int:
            self.floor = event["floor"]

        if kind == "header":
            self.reset(event)
        elif kind == "resume":
            for source, target in (("hp", "hp"), ("gold", "gold")):
                if type(event.get(source)) is int:
                    setattr(self, target, event[source])
            self.relics = {
                relic["id"]: relic.get("n") if type(relic.get("n")) is int else None
                for relic in event.get("relics", [])
                if isinstance(relic, dict) and isinstance(relic.get("id"), str)
            }
            self.potions = {
                potion["slot"]: potion["id"]
                for potion in event.get("potions", [])
                if isinstance(potion, dict)
                and type(potion.get("slot")) is int
                and isinstance(potion.get("id"), str)
            }
        elif kind == "deck":
            self._set_deck(event.get("cards", []))
        elif kind == "map":
            nodes = []
            for node in event.get("nodes", []):
                if not isinstance(node, dict) or not isinstance(node.get("coord"), str):
                    continue
                nodes.append(
                    {
                        "coordinate": node["coord"],
                        "kind": node.get("kind"),
                        "children": sorted(child for child in node.get("children", []) if isinstance(child, str)),
                    }
                )
            self.map_state = {
                "act": event.get("act"),
                "boss": event.get("boss"),
                "nodes": sorted(nodes, key=lambda node: node["coordinate"]),
            }
        elif kind == "room":
            self.room = {
                key: event[key]
                for key in ("kind", "room_type", "point_type", "coord", "id")
                if isinstance(event.get(key), str)
            }
            if event.get("kind") != "merchant" and event.get("room_type") != "shop":
                self.shop = None
        elif kind == "shop":
            items: list[dict[str, Any]] = []
            for collection, item_kind in (("cards", "card"), ("relics", "relic"), ("potions", "potion")):
                for raw in event.get(collection, []):
                    if isinstance(raw, dict) and (item := _public_shop_item(item_kind, raw)) is not None:
                        items.append(item)
            self.shop = {
                "items": items,
                "removal_cost": event.get("removal_cost") if type(event.get("removal_cost")) is int else None,
                "removal_stocked": event.get("removal_stocked") is True,
            }
            if type(event.get("gold")) is int:
                self.gold = event["gold"]
        elif kind == "gold" and type(event.get("gold")) is int:
            self.gold = event["gold"]
        elif kind == "hp":
            if event.get("dst") == "player" and type(event.get("hp")) is int:
                self.hp = event["hp"]
            else:
                creature = self._creature(event, "dst")
                if creature is not None and type(event.get("hp")) is int:
                    creature["hp"] = event["hp"]
        elif kind == "max_hp":
            if event.get("dst") == "player":
                if type(event.get("max_hp")) is int:
                    self.max_hp = event["max_hp"]
                if type(event.get("hp")) is int:
                    self.hp = event["hp"]
            else:
                creature = self._creature(event, "dst")
                if creature is not None:
                    if type(event.get("max_hp")) is int:
                        creature["max_hp"] = event["max_hp"]
                    if type(event.get("hp")) is int:
                        creature["hp"] = event["hp"]
        elif kind == "relic" and isinstance(event.get("id"), str):
            self.relics.setdefault(event["id"], None)
        elif kind == "relic_lost" and isinstance(event.get("id"), str):
            self.relics.pop(event["id"], None)
        elif kind == "relic_counter" and isinstance(event.get("id"), str):
            self.relics[event["id"]] = event.get("n") if type(event.get("n")) is int else None
        elif kind == "potion_got" and isinstance(event.get("id"), str):
            slot = next((index for index in range(max(3, len(self.potions) + 1)) if index not in self.potions), max(self.potions, default=-1) + 1)
            self.potions[slot] = event["id"]
        elif kind in ("potion_used", "potion_dropped") and isinstance(event.get("id"), str):
            slot = next((slot for slot, model_id in sorted(self.potions.items()) if model_id == event["id"]), None)
            if slot is not None:
                self.potions.pop(slot, None)
        elif kind == "acquire" and type(event.get("c")) is int:
            card = _copy_card_from_source(event)
            if card is not None:
                self.deck[event["c"]] = card
        elif kind in ("upgrade", "downgrade"):
            ref = event.get("c")
            if type(ref) is int:
                for collection in (self.deck, self.cards):
                    if ref in collection:
                        collection[ref]["upgrade"] = int(event.get("up", collection[ref].get("upgrade", 0) + (1 if kind == "upgrade" else -1)))
        elif kind == "remove" and type(event.get("c")) is int:
            self.deck.pop(event["c"], None)
        elif kind == "transform":
            if type(event.get("from_c")) is int:
                self.deck.pop(event["from_c"], None)
            if type(event.get("to_c")) is int and isinstance(event.get("to_id"), str):
                self.deck[event["to_c"]] = {"model_id": event["to_id"], "upgrade": 0}
        elif kind == "enchant":
            ref = event.get("c")
            if type(ref) is int:
                for collection in (self.deck, self.cards):
                    if ref in collection and isinstance(event.get("enchantment"), str):
                        collection[ref]["enchantment"] = event["enchantment"]
                        if type(event.get("amount_total")) is int:
                            collection[ref]["enchantment_amount"] = event["amount_total"]
        elif kind in ("afflict", "unafflict"):
            card = self._card(event)
            affliction = event.get("affliction")
            if card is not None and isinstance(affliction, str):
                afflictions = card.setdefault("afflictions", {})
                amount = event.get("amount_total") if kind == "afflict" else 0
                if type(amount) is int and amount > 0:
                    afflictions[affliction] = amount
                else:
                    afflictions.pop(affliction, None)
        elif kind == "remap":
            for row in event.get("cards", []):
                if not isinstance(row, dict) or type(row.get("from")) is not int or type(row.get("to")) is not int:
                    continue
                old, new = row["from"], row["to"]
                if old in self.cards:
                    self.cards[new] = self.cards.pop(old)
                if old in self.deck:
                    self.deck[new] = self.deck.pop(old)
        elif kind == "combat_start":
            creatures: dict[int, dict[str, Any]] = {}
            for raw in event.get("enemies", []):
                if not isinstance(raw, dict) or type(raw.get("cid")) is not int:
                    continue
                creatures[raw["cid"]] = {
                    "slot": raw.get("i") if type(raw.get("i")) is int else len(creatures),
                    "model_id": raw.get("id"),
                    "hp": raw.get("hp"),
                    "max_hp": raw.get("max_hp"),
                    "block": 0,
                    "alive": True,
                    "powers": {},
                    "side": "enemy",
                }
            for raw in event.get("allies", []):
                if not isinstance(raw, dict) or type(raw.get("cid")) is not int:
                    continue
                creatures[raw["cid"]] = {
                    "slot": len(creatures),
                    "model_id": raw.get("id"),
                    "hp": raw.get("hp"),
                    "max_hp": raw.get("max_hp"),
                    "block": 0,
                    "alive": True,
                    "powers": {},
                    "side": "ally",
                }
            self.combat = {
                "encounter": event.get("encounter"),
                "turn": None,
                "round": None,
                "energy": None,
                "stars": None,
                "player": {"block": 0, "powers": {}},
                "creatures": creatures,
                "piles": {name: set() for name in ("hand", "draw", "discard", "exhaust")},
                "draw_membership_known": False,
                "orbs": [],
            }
            self.cards = {}
            self.before_hand_flush = None
        elif kind == "draw_order" and self.combat is not None:
            refs = event.get("order_c")
            deck_refs = event.get("order_deck_c")
            if isinstance(refs, list):
                for index, ref in enumerate(refs):
                    if type(ref) is not int:
                        continue
                    if ref not in self.cards and isinstance(deck_refs, list) and index < len(deck_refs):
                        deck_ref = deck_refs[index]
                        if type(deck_ref) is int and deck_ref in self.deck:
                            self.cards[ref] = deepcopy(self.deck[deck_ref])
                    self.combat["piles"]["draw"].add(ref)
                self.combat["draw_membership_known"] = True
        elif kind == "shuffle" and self.combat is not None:
            refs = event.get("order_c")
            if isinstance(refs, list) and all(type(ref) is int for ref in refs):
                for ref in refs:
                    self._remove_from_piles(ref)
                    self.combat["piles"]["draw"].add(ref)
                self.combat["draw_membership_known"] = True
        elif kind == "draw" and self.combat is not None and type(event.get("c")) is int:
            ref = event["c"]
            self._card(event)
            self._remove_from_piles(ref)
            self.combat["piles"]["hand"].add(ref)
        elif kind in ("discard", "exhaust") and self.combat is not None and type(event.get("c")) is int:
            ref = event["c"]
            self._card(event)
            self._remove_from_piles(ref)
            self.combat["piles"][kind].add(ref)
        elif kind == "flush" and self.combat is not None:
            self.before_hand_flush = self.snapshot(include_map=False)
            for ref in event.get("flushed_c", []):
                if type(ref) is int:
                    self._remove_from_piles(ref)
                    self.combat["piles"]["discard"].add(ref)
            retained = {ref for ref in event.get("retained_c", []) if type(ref) is int}
            if retained:
                self.combat["piles"]["hand"].intersection_update(retained)
        elif kind == "generate":
            self._card(event)
        elif kind == "play" and self.combat is not None:
            ref = event.get("c")
            if type(ref) is int:
                self._card(event)
                self._remove_from_piles(ref)
                pile = event.get("result_pile")
                if pile in self.combat["piles"]:
                    self.combat["piles"][pile].add(ref)
            if type(event.get("cost_paid")) is int and type(self.combat.get("energy")) is int:
                self.combat["energy"] = max(0, self.combat["energy"] - event["cost_paid"])
            if type(event.get("stars_paid")) is int and type(self.combat.get("stars")) is int:
                self.combat["stars"] = max(0, self.combat["stars"] - event["stars_paid"])
        elif kind == "turn" and self.combat is not None:
            if event.get("side") == "player":
                if type(event.get("n")) is int:
                    self.combat["turn"] = event["n"]
                if type(event.get("round")) is int:
                    self.combat["round"] = event["round"]
        elif kind == "end_turn":
            self.before_hand_flush = None
        elif kind == "energy" and self.combat is not None and type(event.get("energy")) is int:
            self.combat["energy"] = event["energy"]
        elif kind == "stars" and self.combat is not None and type(event.get("stars")) is int:
            self.combat["stars"] = event["stars"]
        elif kind == "block" and self.combat is not None:
            creature = self._creature(event, "src")
            if creature is not None and type(event.get("left")) is int:
                creature["block"] = event["left"]
        elif kind == "hit" and self.combat is not None:
            creature = self._creature(event, "dst")
            if creature is not None:
                if type(event.get("dmg")) is int and type(creature.get("hp")) is int:
                    creature["hp"] = max(0, creature["hp"] - event["dmg"])
                if type(event.get("blocked")) is int:
                    creature["block"] = max(0, int(creature.get("block", 0)) - event["blocked"])
                if event.get("killed") is True:
                    creature["alive"] = False
            if event.get("dst") == "player" and type(event.get("dmg")) is int and self.hp is not None:
                self.hp = max(0, self.hp - event["dmg"])
        elif kind == "hp_loss" and self.combat is not None and type(event.get("dmg")) is int and self.hp is not None:
            self.hp = max(0, self.hp - event["dmg"])
        elif kind == "death" and self.combat is not None:
            creature = self._creature(event, "tgt")
            if creature is not None:
                creature["alive"] = False
                creature["hp"] = 0
        elif kind == "spawn" and self.combat is not None and type(event.get("cid")) is int:
            slot_value = event.get("slot")
            slot = max((item["slot"] for item in self.combat["creatures"].values()), default=-1) + 1
            if type(slot_value) is int:
                slot = slot_value
            self.combat["creatures"][event["cid"]] = {
                "slot": slot,
                "model_id": event.get("id"),
                "hp": event.get("hp"),
                "max_hp": event.get("max_hp"),
                "block": 0,
                "alive": True,
                "powers": {},
                "side": event.get("side") if event.get("side") in ("ally", "enemy") else "enemy",
            }
        elif kind == "intent" and self.combat is not None:
            creature = self._creature(event, "src")
            if creature is not None:
                creature["intent"] = {
                    "move_id": event.get("id"),
                    "types": [value for value in event.get("intents", []) if isinstance(value, str)],
                    "damage": event.get("dmg") if type(event.get("dmg")) is int else None,
                    "hits": event.get("hits") if type(event.get("hits")) is int else None,
                }
        elif kind in ("power", "power_lost") and self.combat is not None:
            creature = self._creature(event, "tgt")
            power_id = event.get("id")
            if creature is not None and isinstance(power_id, str):
                amount = event.get("amount")
                if kind == "power_lost" or amount == 0:
                    creature["powers"].pop(power_id, None)
                elif type(amount) is int:
                    creature["powers"][power_id] = amount
        elif kind == "orb_channel" and self.combat is not None and isinstance(event.get("id"), str):
            self.combat["orbs"].append({"model_id": event["id"]})
        elif kind == "orb_evoke" and self.combat is not None and isinstance(event.get("id"), str):
            index = next((i for i, orb in enumerate(self.combat["orbs"]) if orb.get("model_id") == event["id"]), None)
            if index is not None and event.get("kept") is not True:
                self.combat["orbs"].pop(index)
        elif kind == "combat_end":
            self.combat = None
            self.cards = {}
            self.before_hand_flush = None

    def apply_buy(self, event: Mapping[str, Any]) -> None:
        if type(event.get("gold_on_hand")) is int:
            self.gold = event["gold_on_hand"]
        if self.shop is None:
            return
        selected_kind = f"buy_{event.get('kind')}"
        for item in self.shop["items"]:
            if item.get("kind") == selected_kind and item.get("slot") == event.get("slot"):
                item["stocked"] = False
        if event.get("kind") == "removal_service":
            self.shop["removal_stocked"] = False


def _choice_context(event: Mapping[str, Any]) -> dict[str, Any]:
    result = {
        "decision_type": event.get("decision_type"),
        "source": event.get("source"),
    }
    for key in ("event_id", "page_key", "select_kind", "enchantment", "offer_generation"):
        value = event.get(key)
        if isinstance(value, (str, int)) and not isinstance(value, bool):
            result[key] = value
    return result


def _direct_candidates(event: Mapping[str, Any]) -> list[dict[str, Any]]:
    candidates = [_public_option(option) for option in event.get("options", []) if isinstance(option, dict) and option.get("selectable") is True]
    if event.get("decline_available") is True:
        candidates.append({"kind": "decline"})
    if event.get("can_reroll") is True:
        candidates.append({"kind": "reroll"})
    return candidates


def _source_option(candidate: Mapping[str, Any], source_index: int) -> bool:
    return candidate.get("source_option_index") == source_index


def _resolve_decision_action(
    decision: Mapping[str, Any], evidence: Sequence[Mapping[str, Any]]
) -> tuple[dict[str, Any] | None, list[str], dict[str, Any]]:
    decision_id = decision.get("decision_id")
    decision_type = decision.get("decision_type")
    related = [event for event in evidence if event.get("decision_id") == decision_id]
    outcomes = [event for event in related if event.get("t") == "outcome"]
    action: dict[str, Any] | None = None
    audit: dict[str, Any] = {}
    is_set = isinstance(decision_type, str) and decision_type.startswith("deck_select_")

    outcome = outcomes[0] if outcomes else None
    if outcome is not None:
        outcome_name = outcome.get("outcome")
        if outcome_name in ("skip", "decline"):
            action = {"kind": "decline"}
        elif outcome_name == "reroll":
            action = {"kind": "reroll"}
        elif isinstance(outcome.get("selected_option_indices"), list):
            indices = [value for value in outcome["selected_option_indices"] if type(value) is int]
            if is_set:
                action = {"kind": "select_set", "source_option_indices": sorted(set(indices))}
            elif len(indices) == 1:
                action = {"kind": "choose_option", "source_option_index": indices[0]}
            elif not indices and decision.get("decline_available") is True:
                action = {"kind": "decline"}
        elif type(outcome.get("option_index")) is int:
            action = {"kind": "choose_option", "source_option_index": outcome["option_index"]}

    if action is None and isinstance(decision_type, str) and decision_type.startswith("deck_select_"):
        picks = [event for event in related if event.get("t") == "pick"]
        if picks:
            indices = [
                card.get("option_index")
                for card in picks[0].get("cards", [])
                if isinstance(card, dict) and type(card.get("option_index")) is int
            ]
            if len(indices) == picks[0].get("n_picked"):
                action = {"kind": "select_set", "source_option_indices": sorted(set(indices))}

    if action is None and decision_type == "card_reward":
        acquisitions = [event for event in related if event.get("t") == "acquire" and type(event.get("option_index")) is int]
        if acquisitions:
            action = {"kind": "choose_option", "source_option_index": acquisitions[0]["option_index"]}

    if action is None and decision_type == "relic_reward":
        resolves = [event for event in related if event.get("t") == "resolve" and event.get("reward_kind") == "RelicReward"]
        if resolves and isinstance(resolves[0].get("id"), str):
            matches = [
                option.get("option_index")
                for option in decision.get("options", [])
                if isinstance(option, dict) and option.get("option_id") == resolves[0]["id"]
            ]
            if len(matches) == 1:
                action = {"kind": "choose_option", "source_option_index": matches[0]}

    if action is None and decision_type == "rest":
        rests = [event for event in related if event.get("t") == "rest" and type(event.get("option_index")) is int]
        if rests:
            action = {"kind": "choose_option", "source_option_index": rests[0]["option_index"]}

    reasons: list[str] = []
    output: dict[str, Any] = {"choice": _choice_context(decision)}
    if is_set:
        candidates = [_public_option(option) for option in decision.get("options", []) if isinstance(option, dict) and option.get("selectable") is True]
        minimum = decision.get("min_select") if type(decision.get("min_select")) is int else 1
        maximum = decision.get("max_select") if type(decision.get("max_select")) is int else 1
        output["set_candidates"] = candidates
        output["selection_bounds"] = {
            "minimum": minimum,
            "maximum": maximum,
            "can_decline": decision.get("decline_available") is True,
        }
        if action is None:
            reasons.append("recorded_action_missing")
        elif action["kind"] == "decline":
            if decision.get("decline_available") is not True:
                reasons.append("recorded_decline_not_offered")
        elif action["kind"] == "select_set":
            source_indices = action["source_option_indices"]
            offered = {candidate.get("source_option_index") for candidate in candidates}
            if not set(source_indices) <= offered:
                reasons.append("selected_set_not_offered")
            elif not minimum <= len(source_indices) <= maximum:
                reasons.append("selected_set_size_invalid")
            else:
                action["candidate_indices"] = [
                    next(index for index, candidate in enumerate(candidates) if _source_option(candidate, source_index))
                    for source_index in source_indices
                ]
        else:
            reasons.append("recorded_set_action_kind_invalid")
    else:
        candidates = _direct_candidates(decision)
        output["legal_actions"] = candidates
        if action is None:
            reasons.append("recorded_action_missing")
        elif action["kind"] in ("decline", "reroll"):
            matches = [index for index, candidate in enumerate(candidates) if candidate.get("kind") == action["kind"]]
            if len(matches) != 1:
                reasons.append("recorded_special_action_not_offered")
            else:
                action["action_index"] = matches[0]
        elif action["kind"] == "choose_option":
            matches = [
                index
                for index, candidate in enumerate(candidates)
                if _source_option(candidate, action["source_option_index"])
            ]
            if len(matches) != 1:
                reasons.append("recorded_option_not_offered")
            else:
                action["action_index"] = matches[0]
                action["option"] = candidates[matches[0]]
        else:
            reasons.append("recorded_action_kind_invalid")
    audit["evidence_source_sequences"] = [event["s"] for event in related if type(event.get("s")) is int]
    return action, reasons, {**output, **audit}


def _shop_step(
    state: _RunState,
    event: Mapping[str, Any],
    segment: _Segment,
) -> dict[str, Any]:
    observation, state_issues = state.snapshot(include_map=True)
    reasons = list(state_issues)
    legal_actions: list[dict[str, Any]] = []
    if state.shop is None:
        reasons.append("shop_offer_missing")
    else:
        for item in state.shop["items"]:
            if item.get("stocked") is not True:
                continue
            if self_cost := item.get("cost"):
                if state.gold is not None and self_cost > state.gold:
                    continue
            legal_actions.append({key: value for key, value in item.items() if key != "stocked"})
        if state.shop.get("removal_stocked") is True and type(state.shop.get("removal_cost")) is int:
            if state.gold is None or state.shop["removal_cost"] <= state.gold:
                legal_actions.append({"kind": "buy_removal_service", "cost": state.shop["removal_cost"]})
        legal_actions.append({"kind": "leave_shop"})
    kind = f"buy_{event.get('kind')}"
    matches = [
        index
        for index, candidate in enumerate(legal_actions)
        if candidate.get("kind") == kind
        and (event.get("kind") == "removal_service" or candidate.get("slot") == event.get("slot"))
        and (not isinstance(event.get("id"), str) or candidate.get("model_id") == event.get("id"))
    ]
    action: dict[str, Any] | None = None
    if event.get("cost_resource") != "gold":
        reasons.append("non_gold_shop_resource")
    elif len(matches) != 1:
        reasons.append("purchased_item_not_in_shop_offer")
    else:
        action = {"kind": kind, "action_index": matches[0], "option": legal_actions[matches[0]]}
    if segment.capture_status != "complete":
        reasons.append("segment_not_complete")
    if segment.resumed:
        reasons.append("resumed_segment_unverified")
    return {
        "record_type": "step",
        "segment_index": segment.index,
        "source_sequence": event["s"],
        "domain": "outside_combat",
        "observation": observation,
        "legal_actions": legal_actions,
        "legal_actions_complete": state.shop is not None and event.get("cost_resource") == "gold",
        "action": action,
        "bc_eligible": not reasons,
        "bc_exclusion_reasons": sorted(set(reasons)),
        "source_kind": "shop_purchase",
    }


def _combat_step(
    state: _RunState,
    event: Mapping[str, Any],
    segment: _Segment,
) -> dict[str, Any] | None:
    kind = event.get("t")
    if kind == "play" and event.get("auto") is True:
        return None
    if kind == "end_turn" and event.get("side") == "player" and state.before_hand_flush is not None:
        observation, issues = deepcopy(state.before_hand_flush)
    else:
        observation, issues = state.snapshot(include_map=False)
    action: dict[str, Any]
    replay_reasons = list(issues)
    if state.combat is None:
        replay_reasons.append("combat_state_missing")
    if kind == "play":
        card = state._card(event)
        public_card = _card_public(card)
        if public_card is None:
            replay_reasons.append("played_card_unknown")
            public_card = {"model_id": event.get("id"), "upgrade": int(event.get("up", 0))}
        ref = event.get("c")
        hand = state.combat["piles"]["hand"] if state.combat is not None else set()
        if type(ref) is not int or ref not in hand:
            replay_reasons.append("played_card_not_in_reconstructed_hand")
        action = {"kind": "play_card", "card": public_card}
        target = state._creature(event, "target")
        if event.get("target") is not None:
            if target is None:
                replay_reasons.append("target_not_reconstructed")
            else:
                action["target"] = {"slot": target.get("slot"), "model_id": target.get("model_id")}
        for source, target_key in (("cost_paid", "energy_paid"), ("stars_paid", "stars_paid"), ("x_value", "x_value")):
            if type(event.get(source)) is int:
                action[target_key] = event[source]
    elif kind == "potion_start":
        action = {"kind": "use_potion", "model_id": event.get("id")}
        target = state._creature(event, "target")
        if target is not None:
            action["target"] = {"slot": target.get("slot"), "model_id": target.get("model_id")}
    elif kind == "end_turn" and event.get("side") == "player":
        action = {"kind": "end_turn"}
        if state.before_hand_flush is None:
            replay_reasons.append("pre_flush_observation_missing")
    else:
        return None
    if segment.capture_status != "complete":
        replay_reasons.append("segment_not_complete")
    if segment.resumed:
        replay_reasons.append("resumed_segment_unverified")
    return {
        "record_type": "step",
        "segment_index": segment.index,
        "source_sequence": event["s"],
        "domain": "combat",
        "observation": observation,
        "legal_actions": [],
        "legal_actions_complete": False,
        "action": action,
        "bc_eligible": False,
        "bc_exclusion_reasons": ["combat_legal_actions_not_recorded"],
        "native_replay_eligible": not replay_reasons,
        "native_replay_exclusion_reasons": sorted(set(replay_reasons)),
        "reconstructed_observation_valid": kind != "end_turn",
        "source_kind": kind,
    }


def convert_events(
    run_hash: str,
    events: Sequence[dict[str, Any]],
    *,
    source_sha256: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    segments, segment_by_event = _segments(events)
    first_header = events[0]
    if first_header.get("replay_version") != EXPECTED_REPLAY_VERSION:
        raise ConversionError(f"{run_hash}: unexpected replay version")
    if first_header.get("mod_version") != EXPECTED_RECORDER_VERSION:
        raise ConversionError(f"{run_hash}: unexpected recorder version")
    if first_header.get("build_id") != EXPECTED_BUILD:
        raise ConversionError(f"{run_hash}: unexpected game build")
    character = first_header.get("character")
    if character not in CHARACTERS:
        raise ConversionError(f"{run_hash}: unexpected character")
    mods = first_header.get("mods")
    if not isinstance(mods, list) or {mod.get("id") for mod in mods if isinstance(mod, dict)} != CORE_MODS:
        raise ConversionError(f"{run_hash}: unexpected loaded mods")

    state = _RunState()
    steps: list[dict[str, Any]] = []
    decisions: list[tuple[int, dict[str, Any], dict[str, Any], list[str]]] = []
    for event_index, event in enumerate(events):
        segment = segments[segment_by_event[event_index]]
        kind = event.get("t")
        if kind == "decision":
            # The decision event is the authoritative public room position.
            # Some screens (notably Neow) publish their room event after the
            # first decision, so waiting for apply() would leave the captured
            # decision one floor behind.
            if type(event.get("act")) is int:
                state.act = event["act"]
            if type(event.get("floor")) is int:
                state.floor = event["floor"]
            observation, issues = state.snapshot(include_map=True)
            decisions.append((event_index, observation, deepcopy(event), issues))
        elif kind == "buy":
            steps.append(_shop_step(state, event, segment))
        elif kind in ("play", "potion_start") or (kind == "end_turn" and event.get("side") == "player"):
            step = _combat_step(state, event, segment)
            if step is not None:
                steps.append(step)
        state.apply(event)
        if kind == "buy":
            state.apply_buy(event)

    for event_index, observation, decision, state_issues in decisions:
        segment = segments[segment_by_event[event_index]]
        stop = segment.stop
        for later in range(event_index + 1, segment.stop):
            event = events[later]
            if event.get("t") == "decision" and event.get("decision_id") == decision.get("decision_id"):
                stop = later
                break
        action, reasons, choice_payload = _resolve_decision_action(decision, events[event_index + 1 : stop])
        reasons.extend(state_issues)
        if segment.capture_status != "complete":
            reasons.append("segment_not_complete")
        if segment.resumed:
            reasons.append("resumed_segment_unverified")
        step = {
            "record_type": "step",
            "segment_index": segment.index,
            "source_sequence": decision["s"],
            "domain": "outside_combat",
            "observation": observation,
            "action": action,
            "legal_actions_complete": True,
            "bc_eligible": not reasons,
            "bc_exclusion_reasons": sorted(set(reasons)),
            "source_kind": "recorded_decision",
            **choice_payload,
        }
        steps.append(step)

    steps.sort(key=lambda step: (step["source_sequence"], 0 if step["domain"] == "outside_combat" else 1))
    for step_index, step in enumerate(steps):
        step["step_index"] = step_index
        step["episode_id"] = run_hash
        _assert_safe(step)

    endings = [event for event in events if event.get("t") == "end"]
    final_end = endings[-1] if endings else {}
    header_record = {
        "record_type": "episode",
        "format_version": FORMAT_VERSION,
        "episode_id": run_hash,
        "source": {
            "kind": "spire_codex",
            "source_sha256": source_sha256,
            "replay_version": EXPECTED_REPLAY_VERSION,
            "recorder_version": EXPECTED_RECORDER_VERSION,
            "game_build": EXPECTED_BUILD,
        },
        "character": character,
        "ascension": first_header.get("ascension"),
        "segments": [
            {
                "segment_index": segment.index,
                "capture_status": segment.capture_status,
                "terminal_reason": segment.terminal_reason,
                "resumed": segment.resumed,
            }
            for segment in segments
        ],
        "sanitization": {
            "future_draw_order_removed": True,
            "rng_state_removed": True,
            "seed_removed": True,
            "timestamps_removed": True,
            "localized_text_removed": True,
            "native_instance_ids_removed": True,
            "pile_order_removed": True,
        },
    }
    trailer = {
        "record_type": "episode_end",
        "episode_id": run_hash,
        "terminal_reason": final_end.get("terminal_reason"),
        "is_game_over": final_end.get("is_game_over") is True,
        "capture_status": final_end.get("capture_status"),
        "final_hp": final_end.get("hp") if type(final_end.get("hp")) is int else None,
        "final_max_hp": final_end.get("max_hp") if type(final_end.get("max_hp")) is int else None,
    }
    _assert_safe(header_record)
    _assert_safe(trailer)
    records = [header_record, *steps, trailer]
    exclusion_counts = Counter(
        reason for step in steps for reason in step.get("bc_exclusion_reasons", [])
    )
    replay_exclusions = Counter(
        reason for step in steps for reason in step.get("native_replay_exclusion_reasons", [])
    )
    report = {
        "episode_id": run_hash,
        "character": character,
        "segments": len(segments),
        "resumed_segments": sum(segment.resumed for segment in segments),
        "steps": len(steps),
        "outside_steps": sum(step["domain"] == "outside_combat" for step in steps),
        "combat_steps": sum(step["domain"] == "combat" for step in steps),
        "bc_eligible_steps": sum(step["bc_eligible"] for step in steps),
        "native_replay_eligible_combat_steps": sum(
            step["domain"] == "combat" and step.get("native_replay_eligible") is True
            for step in steps
        ),
        "bc_exclusions": dict(sorted(exclusion_counts.items())),
        "native_replay_exclusions": dict(sorted(replay_exclusions.items())),
        "terminal_reason": trailer["terminal_reason"],
        "is_game_over": trailer["is_game_over"],
    }
    return records, report


def _write_gzip_jsonl(path: Path, records: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(descriptor, "wb") as raw:
            with gzip.GzipFile(filename="", mode="wb", fileobj=raw, compresslevel=6, mtime=0) as compressed:
                with io.TextIOWrapper(compressed, encoding="utf-8") as text:
                    for record in records:
                        text.write(json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
                        text.write("\n")
        os.replace(temporary_name, path)
    except BaseException:
        Path(temporary_name).unlink(missing_ok=True)
        raise


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, sort_keys=True, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_name, path)
    except BaseException:
        Path(temporary_name).unlink(missing_ok=True)
        raise


def _write_jsonl(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            for row in rows:
                stream.write(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
                stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_name, path)
    except BaseException:
        Path(temporary_name).unlink(missing_ok=True)
        raise


def convert_archive(archive: Path, output: Path) -> dict[str, Any]:
    """Convert the curated 166-replay archive into a new atomic dataset."""
    archive = archive.resolve()
    output = output.resolve()
    if output.exists():
        raise ConversionError(f"output already exists: {output}")
    manifest_path = archive / "v1.2.1" / "manifest.jsonl"
    if not manifest_path.is_file():
        raise ConversionError(f"curated manifest is missing: {manifest_path}")
    rows = [json.loads(line) for line in manifest_path.open(encoding="utf-8")]
    if len(rows) != 166 or len({row.get("run_hash") for row in rows}) != 166:
        raise ConversionError("curated manifest must contain 166 unique replays")

    temporary = output.with_name(f".{output.name}.{os.getpid()}.tmp")
    if temporary.exists():
        raise ConversionError(f"temporary output already exists: {temporary}")
    temporary.mkdir(parents=True)
    converted_rows: list[dict[str, Any]] = []
    bc_index: list[dict[str, Any]] = []
    native_replay_index: list[dict[str, Any]] = []
    aggregate = Counter()
    bc_exclusions = Counter()
    bc_observation_missing_fields = Counter()
    replay_exclusions = Counter()
    by_character = Counter()
    try:
        for source_row in rows:
            run_hash = source_row.get("run_hash")
            relative = source_row.get("archive_path")
            if not isinstance(run_hash, str) or not isinstance(relative, str):
                raise ConversionError("manifest row lacks run_hash/archive_path")
            source = archive / relative
            if not source.is_file():
                raise ConversionError(f"source replay is missing: {source}")
            source_digest = _sha256(source)
            if source_row.get("sha256") != source_digest:
                raise ConversionError(f"source replay hash mismatch: {run_hash}")
            records, report = convert_events(run_hash, _read_events(source), source_sha256=source_digest)
            character = report["character"]
            relative_output = Path("episodes") / character / f"{run_hash}.jsonl.gz"
            target = temporary / relative_output
            _write_gzip_jsonl(target, records)
            for record in records:
                if record.get("record_type") != "step":
                    continue
                index_row = {
                    "episode_id": run_hash,
                    "character": character,
                    "file": str(relative_output),
                    "step_index": record["step_index"],
                    "segment_index": record["segment_index"],
                    "source_sequence": record["source_sequence"],
                    "domain": record["domain"],
                    "action_kind": record["action"].get("kind") if isinstance(record.get("action"), dict) else None,
                }
                if record.get("bc_eligible") is True:
                    bc_index.append(index_row)
                    run_observation = record.get("observation", {}).get("run", {})
                    for field_name in (
                        "character",
                        "ascension",
                        "act",
                        "floor",
                        "current_hp",
                        "max_hp",
                        "gold",
                        "deck",
                        "relics",
                        "potions",
                    ):
                        if run_observation.get(field_name) is None:
                            bc_observation_missing_fields[field_name] += 1
                if record.get("domain") == "combat" and record.get("native_replay_eligible") is True:
                    native_replay_index.append(index_row)
            output_digest = _sha256(target)
            converted = {
                **report,
                "file": str(relative_output),
                "source_sha256": source_digest,
                "output_sha256": output_digest,
            }
            converted_rows.append(converted)
            by_character[character] += 1
            for key in ("segments", "resumed_segments", "steps", "outside_steps", "combat_steps", "bc_eligible_steps", "native_replay_eligible_combat_steps"):
                aggregate[key] += int(report[key])
            bc_exclusions.update(report["bc_exclusions"])
            replay_exclusions.update(report["native_replay_exclusions"])

        converted_rows.sort(key=lambda row: (row["character"], row["episode_id"]))
        _write_jsonl(temporary / "manifest.jsonl", converted_rows)
        _write_jsonl(temporary / "bc-eligible-index.jsonl", bc_index)
        _write_jsonl(temporary / "native-replay-index.jsonl", native_replay_index)
        for character in sorted(CHARACTERS):
            _write_jsonl(
                temporary / "by-character" / character / "manifest.jsonl",
                (row for row in converted_rows if row["character"] == character),
            )
            _write_jsonl(
                temporary / "by-character" / character / "bc-eligible-index.jsonl",
                (row for row in bc_index if row["character"] == character),
            )
            _write_jsonl(
                temporary / "by-character" / character / "native-replay-index.jsonl",
                (row for row in native_replay_index if row["character"] == character),
            )
        summary = {
            "format_version": FORMAT_VERSION,
            "episodes": len(converted_rows),
            "by_character": dict(sorted(by_character.items())),
            **dict(aggregate),
            "bc_exclusions": dict(sorted(bc_exclusions.items())),
            "bc_observation_missing_fields": dict(sorted(bc_observation_missing_fields.items())),
            "native_replay_exclusions": dict(sorted(replay_exclusions.items())),
            "policy": {
                "outside_decisions_with_complete_recorded_options_may_be_bc_eligible": True,
                "combat_actions_require_native_legal_action_replay_before_bc": True,
                "hidden_future_information_is_removed": True,
                "resumed_recordings_are_split_into_segments": True,
                "resumed_segments_are_excluded_until_continuity_is_verified": True,
                "rtg_and_value_targets_are_not_emitted": True,
            },
        }
        _write_json(temporary / "summary.json", summary)
        os.replace(temporary, output)
        return summary
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
