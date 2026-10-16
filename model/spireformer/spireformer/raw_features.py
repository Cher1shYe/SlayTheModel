"""Deterministic, policy-only features for collector decision payloads.

This module deliberately uses an allowlist.  Journal metadata, native object
identifiers, action keys, fingerprints, hidden state and localized descriptions
never become model inputs.  Native IDs are used only to join an action to an
entity already present in the same observation.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from hashlib import sha256
from math import asinh, isfinite
import json
import re
from typing import Iterable, Mapping, Sequence

import torch
from torch import Tensor


FEATURE_VERSION = "sts2-raw-features-v2"
UNKNOWN = "__UNK__"
ENTITY_KINDS = (
    "global", "player", "creature", "companion", "power", "card",
    "relic", "potion", "orb", "intent", "map_point", "map_edge",
    "crystal_cell", "choice", "pending_action",
)

# Each numeric field occupies (asinh(value / scale), present) in the vector.
# A present zero is therefore different from an absent value.
ENTITY_NUMBERS: tuple[tuple[str, float], ...] = (
    ("current_hp", 100), ("max_hp", 100), ("block", 50),
    ("energy", 10), ("stars", 10), ("gold", 500),
    ("turn", 20), ("orb_capacity", 10), ("round", 20),
    ("act", 5), ("act_floor", 20), ("floor", 60),
    ("ascension", 20), ("upgrade", 5), ("affliction_count", 10),
    ("energy_cost", 10), ("star_cost", 10), ("costs_x", 1),
    ("visible_counter", 20), ("power_amount", 20),
    ("orb_passive", 20), ("orb_evoke", 20), ("potion_slot", 10),
    ("row", 20), ("column", 10), ("child_row", 20),
    ("child_column", 10), ("visited", 1),
    ("intent_damage", 50), ("intent_hits", 10),
    ("choice_min", 20), ("choice_max", 20),
    ("choice_selected", 20), ("can_cancel", 1),
    ("requires_confirmation", 1), ("divinations", 20),
    ("board_width", 20), ("board_height", 20),
    ("is_finished", 1), ("hidden", 1), ("highlighted", 1),
)
ACTION_NUMBERS: tuple[tuple[str, float], ...] = (
    ("cost", 500), ("row", 20), ("column", 10),
    ("source_upgrade", 5), ("source_energy_cost", 10),
    ("source_star_cost", 10), ("source_costs_x", 1),
    ("source_potion_slot", 10), ("target_hp", 100),
    ("target_max_hp", 100), ("target_block", 50),
    ("selected_count", 20), ("choice_min", 20),
    ("choice_max", 20), ("is_template", 1),
)
_ENTITY_INDEX = {name: index for index, (name, _) in enumerate(ENTITY_NUMBERS)}
_ACTION_INDEX = {name: index for index, (name, _) in enumerate(ACTION_NUMBERS)}
_SAFE_ID = re.compile(r"^[A-Za-z][A-Za-z0-9_.:/-]{0,119}$")
_UUID = re.compile(r"^[0-9a-fA-F]{8}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{12}$")
_HEX_ID = re.compile(r"^[0-9a-fA-F]{16,}$")


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _list(value: object) -> list[Mapping[str, object]]:
    if not isinstance(value, (list, tuple)):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def _text(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _safe_tag(namespace: str, value: object) -> str | None:
    word = _text(value)
    if word is None or not _SAFE_ID.fullmatch(word):
        return None
    if _UUID.fullmatch(word) or _HEX_ID.fullmatch(word) or re.search(r"[0-9a-fA-F]{16,}", word):
        return None
    # A long decimal run is normally a native instance/account ID, never a
    # stable card, enemy, option or room class.
    if re.search(r"\d{10,}", word):
        return None
    return f"{namespace}:{word}"


def _action_target_tag(value: object) -> str | None:
    word = _text(value)
    if word is None:
        return None
    for prefix, namespace in (("CARD.", "card"), ("RELIC.", "relic"),
                              ("POTION.", "potion")):
        if word.startswith(prefix):
            return _safe_tag(namespace, word)
    return _safe_tag("target", word)


def _number(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)) and isfinite(value):
        return float(value)
    return None


def _sum_known(values: Iterable[object]) -> float | None:
    total = 0.0
    for raw in values:
        value = _number(raw)
        if value is None:
            return None
        total += value
    return total


def _key(value: object) -> tuple[int, object]:
    # Stable ordering for numeric IDs and strings without teaching their
    # numerical values to the model.
    if isinstance(value, int) and not isinstance(value, bool):
        return (0, value)
    return (1, str(value))


@dataclass(frozen=True, slots=True)
class _Row:
    kind: str
    tags: tuple[str, ...]
    numbers: Mapping[str, object]


def _row(kind: str, tags: Iterable[str | None] = (), **numbers: object) -> _Row:
    return _Row(kind, tuple(sorted(set(tag for tag in tags if tag is not None))), numbers)


def _card_tags(card: Mapping[str, object], *, zone: str | None = None) -> list[str | None]:
    tags: list[str | None] = [_safe_tag("card", card.get("model_id"))]
    if zone is not None:
        tags.append(_safe_tag("zone", zone))
    tags.append(_safe_tag("affliction", card.get("affliction_id")))
    tags.append(_safe_tag("enchantment", card.get("enchantment_id")))
    keywords = card.get("keywords")
    if isinstance(keywords, (list, tuple)):
        tags.extend(_safe_tag("keyword", keyword) for keyword in keywords)
    enchantment = _mapping(card.get("enchantment_display"))
    tags.append(_safe_tag("enchantment_icon", enchantment.get("icon_appearance")))
    return tags


def _card_row(card: Mapping[str, object], *, zone: str, schema: int) -> _Row:
    display = _mapping(card.get("display")) if schema >= 2 else {}
    enchantment = _mapping(card.get("enchantment_display")) if schema >= 4 else {}
    return _row(
        "card", _card_tags(card, zone=zone),
        upgrade=card.get("upgrade_level") if schema >= 2 else None,
        affliction_count=card.get("affliction_count"),
        # The legacy raw energy_cost is a nullable override, not the visible
        # current cost.  v2-v4 display is UI cost; v5 Hand is native cost.
        energy_cost=display.get("energy_cost") if zone in ("Hand", "Choice") else None,
        star_cost=display.get("star_cost") if zone in ("Hand", "Choice") else None,
        costs_x=display.get("costs_x") if zone in ("Hand", "Choice") else None,
        visible_counter=enchantment.get("visible_amount"),
    )


def _relic_row(relic: Mapping[str, object], *, schema: int) -> _Row:
    # Raw stack_count/status/display_amount from old observations are not
    # verified public presentation.  Never read them.
    display = _mapping(relic.get("display")) if schema >= 2 else {}
    return _row(
        "relic", (
            _safe_tag("relic", relic.get("model_id")),
            _safe_tag("relic_icon", display.get("icon_status")),
            "relic_melted" if display.get("is_melted") is True else None,
            "relic_wax" if display.get("is_wax") is True else None,
        ),
        visible_counter=display.get("visible_counter"),
    )


def _potion_row(potion: Mapping[str, object]) -> _Row:
    return _row("potion", (_safe_tag("potion", potion.get("model_id")),),
                potion_slot=potion.get("slot_index"))


def _outside_choice_card(observation: Mapping[str, object],
                         option: Mapping[str, object]) -> Mapping[str, object]:
    """Join a public deck choice to its already-observed card attributes."""
    deck_index = option.get("deck_index")
    if deck_index is None:
        return option
    for player in _list(observation.get("players")):
        for card in _list(player.get("deck")):
            if card.get("deck_index") == deck_index and card.get("model_id") == option.get("model_id"):
                return {**card, **option}
    raise ValueError("outside choice candidate is absent from the observed deck")


def _map_rows(points: object) -> list[_Row]:
    rows: list[_Row] = []
    for point in _list(points):
        coord = _mapping(point.get("coordinate"))
        rows.append(_row(
            "map_point", (_safe_tag("point_type", point.get("point_type")),),
            row=coord.get("row"), column=coord.get("column"),
            visited=point.get("visited"),
        ))
        children = sorted(_list(point.get("children")),
                          key=lambda child: (_key(child.get("row")), _key(child.get("column"))))
        for child in children:
            rows.append(_row(
                "map_edge", (_safe_tag("point_type", point.get("point_type")),),
                row=coord.get("row"), column=coord.get("column"),
                child_row=child.get("row"), child_column=child.get("column"),
            ))
    return rows


def _player_rows(player: Mapping[str, object], *, combat: bool, schema: int) -> list[_Row]:
    rows = [_row(
        "player", (
            _safe_tag("character", player.get("character_id")),
            _safe_tag("phase", player.get("phase")) if combat else None,
        ),
        current_hp=player.get("current_hp") if not combat else None,
        max_hp=player.get("max_hp") if not combat else None,
        energy=player.get("energy") if combat else None,
        stars=player.get("stars") if combat else None,
        gold=player.get("gold") if (not combat or schema >= 2) else None,
        turn=player.get("turn_number") if combat else None,
        orb_capacity=player.get("orb_capacity") if combat and schema >= 2 else None,
    )]
    if combat:
        for pile in _list(player.get("piles")):
            zone = _text(pile.get("pile_type")) or "Unknown"
            cards = _list(pile.get("cards"))
            rows.extend(_card_row(card, zone=zone, schema=schema) for card in cards)
        for orb in _list(player.get("orbs")):
            rows.append(_row("orb", (_safe_tag("orb", orb.get("model_id")),),
                             orb_passive=orb.get("passive"), orb_evoke=orb.get("evoke")))
    else:
        rows.extend(_card_row(card, zone="Deck", schema=schema)
                    for card in _list(player.get("deck")))
    rows.extend(_relic_row(relic, schema=schema) for relic in _list(player.get("relics")))
    rows.extend(_potion_row(potion) for potion in _list(player.get("potions")))
    return rows


def _observation_rows(domain: str, observation: Mapping[str, object],
                      run_context: Mapping[str, object] | None = None) -> list[_Row]:
    schema = observation.get("schema_version")
    if type(schema) is not int or not 1 <= schema <= 5:
        raise ValueError("observation schema_version must be 1..5")
    if domain not in ("combat", "outside_combat"):
        raise ValueError(f"unsupported decision domain {domain!r}")
    rc = _mapping(run_context)
    rows: list[_Row]
    if domain == "combat":
        rows = [_row(
            "global", (
                "domain:combat", _safe_tag("side", observation.get("current_side")),
                _safe_tag("room_type", rc.get("room_type")),
                _safe_tag("room", rc.get("room_model_id")),
            ),
            round=observation.get("round_number"),
            act=rc.get("act_index"), act_floor=rc.get("act_floor"),
            floor=rc.get("total_floor"), ascension=rc.get("ascension_level"),
        )]
        for player in _list(observation.get("players")):
            rows.extend(_player_rows(player, combat=True, schema=schema))
        creatures = _list(observation.get("creatures"))
        for creature_slot, creature in enumerate(creatures):
            owner = creature.get("player_id") is not None
            tags = ["friendly" if owner else "enemy",
                    _safe_tag("monster", creature.get("monster_id")),
                    f"creature_slot:{creature_slot}"]
            rows.append(_row("creature", tags,
                             current_hp=creature.get("current_hp"),
                             max_hp=creature.get("max_hp"), block=creature.get("block")))
            for power in _list(creature.get("powers")):
                rows.append(_row("power", [
                    _safe_tag("power", power.get("model_id")),
                    _safe_tag("monster", creature.get("monster_id")),
                    f"creature_slot:{creature_slot}",
                    "friendly" if owner else "enemy",
                ], power_amount=power.get("amount")))
        if schema >= 2:
            for companion in _list(observation.get("companions")):
                rows.append(_row("companion", [
                    _safe_tag("companion", companion.get("model_id")), "friendly",
                ], current_hp=companion.get("current_hp"),
                    max_hp=companion.get("max_hp"), block=companion.get("block")))
                for power in _list(companion.get("powers")):
                    rows.append(_row("power", [
                        _safe_tag("power", power.get("model_id")),
                        _safe_tag("companion", companion.get("model_id")), "friendly",
                    ], power_amount=power.get("amount")))
            for intent in _list(observation.get("enemy_intents")):
                visibility = intent.get("visibility")
                creature_slot = next((index for index, creature in enumerate(creatures)
                                      if creature.get("combat_id") == intent.get("creature_combat_id")), None)
                creature = creatures[creature_slot] if creature_slot is not None else {}
                owner_tags = [f"creature_slot:{creature_slot}" if creature_slot is not None else None,
                              _safe_tag("monster", creature.get("monster_id"))]
                if visibility == "visible":
                    for item in _list(intent.get("intents")):
                        rows.append(_row("intent", [
                            "intent_visible", _safe_tag("intent", item.get("kind")),
                            *owner_tags,
                        ], current_hp=creature.get("current_hp"),
                            block=creature.get("block"),
                            intent_damage=item.get("total_damage"),
                            intent_hits=item.get("hits")))
                else:
                    rows.append(_row("intent", [
                        _safe_tag("intent_visibility", visibility),
                        *owner_tags,
                    ], current_hp=creature.get("current_hp"),
                        block=creature.get("block")))
        choice = _mapping(observation.get("active_choice"))
        if choice:
            # Older experimental captures put the teacher name in this field.
            # Retain only the selector semantics; source attribution belongs
            # to the audit report, not to a policy input feature.
            choice_source = choice.get("source")
            if choice_source == "mcts_card_choice":
                choice_source = "card_selector"
            rows.append(_row("choice", [
                _safe_tag("choice_source", choice_source),
            ], choice_min=choice.get("min_selections"),
                choice_max=choice.get("max_selections"),
                can_cancel=choice.get("can_cancel")))
            rows.extend(_card_row(card, zone="Choice", schema=schema)
                        for card in _list(choice.get("cards")))
        for pending in _list(observation.get("pending_manual_actions")):
            pending_tags: list[str | None] = [
                _safe_tag("pending_kind", pending.get("kind")),
            ]
            pending_card = _find_combat_card(observation,
                                             pending.get("combat_card_index"),
                                             require_hand=False)
            if pending_card is not None:
                pending_tags.extend(_card_tags(pending_card))
            pending_potion = _find_potion(observation, pending.get("potion_index"))
            if pending_potion is not None:
                pending_tags.append(_safe_tag("potion", pending_potion.get("model_id")))
            rows.append(_row("pending_action", pending_tags))
    else:
        choice = _mapping(observation.get("choice_context"))
        rows = [_row(
            "global", (
                "domain:outside_combat",
                _safe_tag("surface", observation.get("surface")),
                _safe_tag("room_type", observation.get("room_type")),
                _safe_tag("room", observation.get("room_model_id")),
                _safe_tag("choice_phase", choice.get("phase")),
            ), act=observation.get("act_index"),
            act_floor=observation.get("act_floor"),
            floor=observation.get("total_floor"),
            ascension=observation.get("ascension_level"),
            choice_min=choice.get("min_selections"),
            choice_max=choice.get("max_selections"),
            choice_selected=choice.get("selected_count"),
            can_cancel=choice.get("cancelable"),
            requires_confirmation=choice.get("requires_confirmation"),
        )]
        for player in _list(observation.get("players")):
            rows.extend(_player_rows(player, combat=False, schema=schema))
        rows.extend(_map_rows(observation.get("map_points")))
        if schema >= 3:
            board = _mapping(observation.get("crystal_sphere"))
            if board:
                rows.append(_row("choice", [
                    _safe_tag("crystal_tool", board.get("selected_tool")),
                ], divinations=board.get("divinations_remaining"),
                    board_width=board.get("width"),
                    board_height=board.get("height"),
                    is_finished=board.get("is_finished")))
                for cell in _list(board.get("cells")):
                    hidden = cell.get("is_hidden")
                    rows.append(_row("crystal_cell", [
                        _safe_tag("crystal_item", cell.get("revealed_item_kind"))
                        if hidden is False else None,
                    ], row=cell.get("y"), column=cell.get("x"),
                        hidden=hidden, highlighted=cell.get("is_highlighted")))
        if schema >= 5:
            rows.extend(_card_row(_outside_choice_card(observation, card),
                                  zone="Choice", schema=schema)
                        for card in _list(observation.get("card_selection_options")))
    return sorted(rows, key=lambda row: (row.kind, row.tags,
                                         tuple((name, str(row.numbers.get(name)))
                                               for name, _ in ENTITY_NUMBERS)))


def _find_combat_card(observation: Mapping[str, object], native_id: object,
                      *, require_hand: bool) -> Mapping[str, object] | None:
    for player in _list(observation.get("players")):
        for pile in _list(player.get("piles")):
            if require_hand and pile.get("pile_type") != "Hand":
                continue
            for card in _list(pile.get("cards")):
                if card.get("combat_card_index") == native_id:
                    return card
    return None


def _find_choice_card(observation: Mapping[str, object], native_id: object,
                      option_index: object = None) -> Mapping[str, object] | None:
    choice = _mapping(observation.get("active_choice"))
    for card in _list(choice.get("cards")):
        if native_id is not None and card.get("combat_card_index") == native_id:
            return card
        if native_id is None and option_index is not None and card.get("option_index") == option_index:
            return card
    return None


def _find_potion(observation: Mapping[str, object], slot: object) -> Mapping[str, object] | None:
    for player in _list(observation.get("players")):
        for potion in _list(player.get("potions")):
            if potion.get("slot_index") == slot:
                return potion
    return None


def _find_target(observation: Mapping[str, object], native_id: object) -> Mapping[str, object] | None:
    for creature in _list(observation.get("creatures")):
        if creature.get("combat_id") == native_id:
            return creature
    return None


def _action_row(domain: str, observation: Mapping[str, object],
                action: Mapping[str, object]) -> _Row:
    kind = _text(action.get("kind")) or UNKNOWN
    tags: list[str | None] = []
    numbers: dict[str, object] = {"is_template": action.get("is_selection_template") is True}
    if domain == "combat":
        if action.get("selected_model_ids") is not None:
            raise ValueError("selected_model_ids actions need an audited feature mapping")
        card_id = action.get("combat_card_index")
        if card_id is not None:
            card = _find_combat_card(observation, card_id, require_hand=kind == "play_card")
            if card is None:
                raise ValueError("combat action references a card absent from the observation")
            tags.extend(_card_tags(card))
            display = _mapping(card.get("display"))
            numbers.update(source_upgrade=card.get("upgrade_level"),
                           source_energy_cost=display.get("energy_cost"),
                           source_star_cost=display.get("star_cost"),
                           source_costs_x=display.get("costs_x"))
        slot = action.get("potion_index")
        if slot is not None:
            potion = _find_potion(observation, slot)
            if potion is None:
                raise ValueError("combat action references a potion slot absent from the observation")
            tags.append(_safe_tag("potion", potion.get("model_id")))
            numbers["source_potion_slot"] = slot
        target_id = action.get("target_creature_id")
        if target_id is not None:
            target = _find_target(observation, target_id)
            if target is None:
                raise ValueError("combat action references a creature absent from the observation")
            tags.append(_safe_tag("monster", target.get("monster_id")))
            target_slot = next(index for index, creature in
                               enumerate(_list(observation.get("creatures")))
                               if creature.get("combat_id") == target_id)
            tags.append(f"creature_slot:{target_slot}")
            numbers.update(target_hp=target.get("current_hp"),
                           target_max_hp=target.get("max_hp"),
                           target_block=target.get("block"))
        selected = action.get("selected_combat_card_ids")
        if isinstance(selected, (list, tuple)):
            numbers["selected_count"] = len(selected)
            selected_cards: list[Mapping[str, object]] = []
            for native_id in selected:
                choice_card = _find_choice_card(observation, native_id)
                if choice_card is None:
                    raise ValueError("selected combat card is absent from active choice")
                selected_cards.append(choice_card)
                tags.extend(_card_tags(choice_card))
            numbers["source_upgrade"] = _sum_known(
                card.get("upgrade_level") for card in selected_cards)
            numbers["source_energy_cost"] = _sum_known(
                _mapping(card.get("display")).get("energy_cost")
                for card in selected_cards)
            numbers["source_star_cost"] = _sum_known(
                _mapping(card.get("display")).get("star_cost")
                for card in selected_cards)
        if not selected and action.get("option_index") is not None:
            choice_card = _find_choice_card(observation, None, action.get("option_index"))
            if choice_card is not None:
                tags.extend(_card_tags(choice_card))
        choice = _mapping(observation.get("active_choice"))
        if choice:
            numbers["choice_min"] = choice.get("min_selections")
            numbers["choice_max"] = choice.get("max_selections")
    elif domain == "outside_combat":
        target_id = action.get("target_id")
        tags.append(_action_target_tag(target_id))
        numbers["cost"] = action.get("cost")
        if kind in ("use_potion", "discard_potion"):
            slot = action.get("potion_slot_index")
            potion = _find_potion(observation, slot)
            if not isinstance(slot, int) or isinstance(slot, bool) or potion is None:
                raise ValueError("outside potion action references a slot absent from the observation")
            if potion.get("model_id") != target_id:
                raise ValueError("outside potion action model does not match the observed slot")
            tags.append(_safe_tag("potion", potion.get("model_id")))
            numbers["source_potion_slot"] = slot
        coord = _mapping(action.get("map_coordinate"))
        if coord:
            numbers["row"] = coord.get("row")
            numbers["column"] = coord.get("column")
            for point in _list(observation.get("map_points")):
                if _mapping(point.get("coordinate")) == coord:
                    tags.append(_safe_tag("point_type", point.get("point_type")))
                    break
        deck_index = action.get("target_deck_index")
        if deck_index is not None:
            found_deck_card = False
            for player in _list(observation.get("players")):
                for card in _list(player.get("deck")):
                    if card.get("deck_index") == deck_index:
                        tags.extend(_card_tags(card))
                        numbers["source_upgrade"] = card.get("upgrade_level")
                        found_deck_card = True
                        break
            if not found_deck_card:
                raise ValueError("outside action references a deck card absent from the observation")
        selected_cards = action.get("selected_cards")
        if isinstance(selected_cards, (list, tuple)):
            numbers["selected_count"] = len(selected_cards)
            observed_cards: list[Mapping[str, object]] = []
            for card in _list(selected_cards):
                observed_card = _outside_choice_card(observation, card)
                observed_cards.append(observed_card)
                tags.extend(_card_tags(observed_card))
            numbers["source_upgrade"] = _sum_known(
                card.get("upgrade_level") for card in observed_cards)
            numbers["source_energy_cost"] = _sum_known(
                _mapping(card.get("display")).get("energy_cost")
                for card in observed_cards)
            numbers["source_star_cost"] = _sum_known(
                _mapping(card.get("display")).get("star_cost")
                for card in observed_cards)
        bundle = action.get("bundle_cards")
        if isinstance(bundle, (list, tuple)):
            numbers["selected_count"] = len(bundle)
            for card in _list(bundle):
                tags.extend(_card_tags(card))
        choice = _mapping(observation.get("choice_context"))
        numbers["choice_min"] = choice.get("min_selections")
        numbers["choice_max"] = choice.get("max_selections")
    else:
        raise ValueError(f"unsupported decision domain {domain!r}")
    return _row(kind, tags, **numbers)


@dataclass(frozen=True, slots=True)
class RawFeatureSpec:
    """Fitted, bounded categorical vocabulary and immutable numeric layout."""

    tokens: tuple[str, ...]
    action_kinds: tuple[str, ...]
    version: str = FEATURE_VERSION

    @classmethod
    def fit(cls, decision_payloads: Iterable[Mapping[str, object]], *,
            max_vocabulary_size: int = 512) -> "RawFeatureSpec":
        if type(max_vocabulary_size) is not int or max_vocabulary_size < 1:
            raise ValueError("max_vocabulary_size must be a positive integer")
        frequencies: Counter[str] = Counter()
        action_kinds: set[str] = set()
        for source in decision_payloads:
            decision = _mapping(source.get("payload", source))
            domain = decision.get("domain")
            if not isinstance(domain, str):
                raise ValueError("decision requires a domain")
            observation = _mapping(decision.get("observation"))
            context = _mapping(decision.get("context"))
            run_context = _mapping(context.get("run_context"))
            for row in _observation_rows(domain, observation, run_context):
                frequencies.update(row.tags)
            for action in _list(decision.get("legal_actions")):
                row = _action_row(domain, observation, action)
                action_kinds.add(row.kind)
                frequencies.update(row.tags)
        ranked = sorted(frequencies, key=lambda word: (-frequencies[word], word))
        return cls((UNKNOWN, *ranked[:max_vocabulary_size - 1]),
                   (UNKNOWN, *sorted(action_kinds - {UNKNOWN})))

    def __post_init__(self) -> None:
        if self.version != FEATURE_VERSION:
            raise ValueError(f"unsupported feature version {self.version!r}")
        if not self.tokens or self.tokens[0] != UNKNOWN or len(set(self.tokens)) != len(self.tokens):
            raise ValueError("feature vocabulary needs a unique leading UNK token")
        if not self.action_kinds or self.action_kinds[0] != UNKNOWN or len(set(self.action_kinds)) != len(self.action_kinds):
            raise ValueError("action kinds need a unique leading UNK kind")

    @property
    def entity_feature_dim(self) -> int:
        return len(ENTITY_KINDS) + len(self.tokens) + 2 * len(ENTITY_NUMBERS)

    @property
    def action_feature_dim(self) -> int:
        return len(self.action_kinds) + len(self.tokens) + 2 * len(ACTION_NUMBERS)

    def to_dict(self) -> dict[str, object]:
        return {
            "version": self.version,
            "tokens": list(self.tokens),
            "action_kinds": list(self.action_kinds),
            "entity_kinds": list(ENTITY_KINDS),
            "entity_numbers": [[name, scale] for name, scale in ENTITY_NUMBERS],
            "action_numbers": [[name, scale] for name, scale in ACTION_NUMBERS],
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> "RawFeatureSpec":
        version = payload.get("version")
        tokens = payload.get("tokens")
        actions = payload.get("action_kinds")
        if (version != FEATURE_VERSION or not isinstance(tokens, list)
                or not all(isinstance(word, str) for word in tokens)
                or not isinstance(actions, list)
                or not all(isinstance(word, str) for word in actions)):
            raise ValueError("invalid raw feature specification")
        result = cls(tuple(tokens), tuple(actions))
        if result.to_dict() != dict(payload):
            raise ValueError("raw feature layout differs from this encoder")
        return result

    def sha256(self) -> str:
        return sha256(json.dumps(self.to_dict(), sort_keys=True,
                                 separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class RawSetCandidates:
    features: Tensor
    candidate_keys: tuple[tuple[object, ...], ...]
    min_select: int
    max_select: int


class RawFeatureEncoder:
    def __init__(self, spec: RawFeatureSpec) -> None:
        self.spec = spec
        self._tokens = {token: i for i, token in enumerate(spec.tokens)}
        self._actions = {kind: i for i, kind in enumerate(spec.action_kinds)}
        self._entity_kinds = {kind: i for i, kind in enumerate(ENTITY_KINDS)}

    def _encode_row(self, row: _Row, *, entity: bool) -> Tensor:
        kinds = self._entity_kinds if entity else self._actions
        fields = ENTITY_NUMBERS if entity else ACTION_NUMBERS
        indexes = _ENTITY_INDEX if entity else _ACTION_INDEX
        width = self.spec.entity_feature_dim if entity else self.spec.action_feature_dim
        result = torch.zeros(width, dtype=torch.float32)
        result[kinds.get(row.kind, 0)] = 1
        offset = len(kinds)
        for tag in row.tags:
            result[offset + self._tokens.get(tag, 0)] = 1
        offset += len(self.spec.tokens)
        for name, raw in row.numbers.items():
            index = indexes.get(name)
            if index is None:
                continue
            value = _number(raw)
            if value is not None:
                scale = fields[index][1]
                result[offset + index * 2] = asinh(value / scale)
                result[offset + index * 2 + 1] = 1
        return result

    def encode_observation(self, domain: str, observation: Mapping[str, object],
                           run_context: Mapping[str, object] | None = None) -> Tensor:
        rows = _observation_rows(domain, observation, run_context)
        return torch.stack([self._encode_row(row, entity=True) for row in rows])

    def encode_actions(self, domain: str, observation: Mapping[str, object],
                       legal_actions: Sequence[Mapping[str, object]]) -> Tensor:
        if not legal_actions:
            raise ValueError("decision needs at least one legal action")
        return torch.stack([
            self._encode_row(_action_row(domain, observation, action), entity=False)
            for action in legal_actions
        ])

    def encode_executed_action(self, domain: str, observation: Mapping[str, object],
                               selected_action: Mapping[str, object]) -> Tensor:
        return self._encode_row(_action_row(domain, observation, selected_action), entity=False)

    def encode_set_candidates(self, domain: str,
                              observation: Mapping[str, object]) -> RawSetCandidates | None:
        schema = observation.get("schema_version")
        if type(schema) is not int or not 1 <= schema <= 5:
            raise ValueError("observation schema_version must be 1..5")
        if domain == "combat":
            choice = _mapping(observation.get("active_choice"))
            cards = _list(choice.get("cards"))
            if not cards:
                return None
            min_select = choice.get("min_selections")
            max_select = choice.get("max_selections")
            keys = tuple((card.get("combat_card_index"), card.get("model_id"),
                          card.get("option_index")) for card in cards)
        elif domain == "outside_combat":
            if schema < 5:
                return None
            cards = _list(observation.get("card_selection_options"))
            if not cards:
                return None
            choice = _mapping(observation.get("choice_context"))
            min_select = choice.get("min_selections")
            max_select = choice.get("max_selections")
            keys = tuple((card.get("option_index"), card.get("model_id"),
                          card.get("deck_index")) for card in cards)
        else:
            raise ValueError(f"unsupported decision domain {domain!r}")
        if (type(min_select) is not int or type(max_select) is not int
                or not 0 <= min_select <= max_select <= len(cards)):
            raise ValueError("selection bounds are missing or invalid")
        if any(not isinstance(card.get("model_id"), str) or not card.get("model_id")
               for card in cards):
            raise ValueError("selection candidate is missing a model ID")
        option_indexes = [card.get("option_index") for card in cards]
        if any(index is not None for index in option_indexes):
            if option_indexes != list(range(len(cards))):
                raise ValueError("selection option indexes are not contiguous")
        elif domain == "outside_combat":
            raise ValueError("outside selection requires option indexes")
        native_ids = [card.get("combat_card_index") for card in cards]
        if domain == "combat" and len(set(item for item in native_ids if item is not None)) != sum(item is not None for item in native_ids):
            raise ValueError("combat selection has duplicate native card IDs")
        deck_indexes = [card.get("deck_index") for card in cards]
        if domain == "outside_combat" and len(set(item for item in deck_indexes if item is not None)) != sum(item is not None for item in deck_indexes):
            raise ValueError("outside selection has duplicate deck card indexes")
        if len(set(keys)) != len(keys):
            raise ValueError("selection candidate identities are ambiguous")
        features = torch.stack([
            self._encode_row(_card_row(
                _outside_choice_card(observation, card)
                if domain == "outside_combat" else card,
                zone="Choice", schema=schema), entity=True)
            for card in cards
        ])
        return RawSetCandidates(features, keys, min_select, max_select)

    def encode_selected_set(self, domain: str, observation: Mapping[str, object],
                            selected_action: Mapping[str, object],
                            candidates: RawSetCandidates) -> Tensor:
        if domain == "combat":
            selected = selected_action.get("selected_combat_card_ids")
            if not isinstance(selected, (list, tuple)):
                raise ValueError("combat set submission has no selected native card IDs")
            if any(key[0] is None for key in candidates.candidate_keys):
                raise ValueError("combat set candidates need native IDs for audit matching")
            identifiers = [key[0] for key in candidates.candidate_keys]
            chosen = list(selected)
        elif domain == "outside_combat":
            selected = selected_action.get("selected_cards")
            if not isinstance(selected, (list, tuple)):
                raise ValueError("outside set submission has no selected_cards")
            identifiers = list(candidates.candidate_keys)
            chosen = [(card.get("option_index"), card.get("model_id"),
                       card.get("deck_index")) for card in _list(selected)]
            if len(chosen) != len(selected):
                raise ValueError("outside selected_cards contains a malformed item")
        else:
            raise ValueError(f"unsupported decision domain {domain!r}")
        if len(set(chosen)) != len(chosen) or any(item not in identifiers for item in chosen):
            raise ValueError("selected set is not a unique subset of the candidates")
        if not candidates.min_select <= len(chosen) <= candidates.max_select:
            raise ValueError("selected set cardinality is outside the native bounds")
        return torch.tensor([item in chosen for item in identifiers], dtype=torch.bool)


__all__ = ["FEATURE_VERSION", "RawFeatureSpec", "RawFeatureEncoder", "RawSetCandidates"]
