"""Fail-closed native/simulator decision routing with a legacy public snapshot.

Rewards, potions, selectors, shops, rest sites, treasure and audited event pages
use stable native model metadata (see action_contract/event_contract). The small
public_state snapshot is retained for historical first-combat recordings; the
versioned policy observation lives in train.spire_rl.public_obs and requires its
own full comparison. No localized label or generic event-index fallback is used.

Native object/action IDs and simulator UIDs are transport handles only. Action
keys use public positions and card fingerprints; every legal semantic action
must pair before a selected policy candidate can be submitted.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import math
import json
from typing import Any


class UnsupportedSemanticState(ValueError):
    """An adapter cannot establish the requested action's meaning safely."""


class ParityMismatch(ValueError):
    """Both adapters understood the states, but their public results differ."""


@dataclass(frozen=True)
class ActionKey:
    kind: str
    args: tuple = ()


@dataclass(frozen=True)
class BoundAction:
    key: ActionKey
    # Native: actionId. Simulator: exact legal action tuple.
    handle: str | tuple[int, ...]


@dataclass
class Projection:
    source: str
    screen: str
    public_state: dict[str, Any]
    actions: tuple[BoundAction, ...]
    revision: int | None = None
    ignored_navigation: tuple[str, ...] = ()

    def by_key(self) -> dict[ActionKey, BoundAction]:
        result = {a.key: a for a in self.actions}
        if len(result) != len(self.actions):
            raise UnsupportedSemanticState(f"{self.source}: ambiguous duplicate semantic actions")
        return result


# Exposed so a parity report cannot mistake the narrow snapshot for full NoSL
# policy observation parity. Adding each field requires both adapters and tests.
UNCOVERED_STATE = (
    "full card modifiers, enchantments and afflictions",
    "player/enemy powers and structured intent effects",
    "relic counters and activation state",
    "draw/discard/exhaust card instances beyond public pile counts",
    "complete reward/shop/event descriptions and selector constraints (see public_obs)",
)


def _required(obj: dict, key: str, where: str):
    if key not in obj or obj[key] is None:
        raise UnsupportedSemanticState(f"{where}: missing {key}")
    return obj[key]


def _integer(obj: dict, key: str, where: str) -> int:
    value = _required(obj, key, where)
    if isinstance(value, bool) or not isinstance(value, int):
        raise UnsupportedSemanticState(f"{where}.{key}: expected integer, got {value!r}")
    return value


def _scaled_integer(value, scale: int, where: str) -> int:
    """Decode a known integer feature, rejecting NaN and shifted/fractional data."""
    raw = float(value) * scale
    if not math.isfinite(raw) or abs(raw - round(raw)) > 1e-4:
        raise UnsupportedSemanticState(f"{where}: not an encoded integer: {value!r}")
    return int(round(raw))


def model_entry(value: Any, category: str) -> str:
    """Native ModelId.ToString is CATEGORY.ENTRY; never infer from display text."""
    if not isinstance(value, str) or not re.fullmatch(r"[A-Z0-9_]+\.[A-Z0-9_]+", value):
        raise UnsupportedSemanticState(f"expected native {category}.ENTRY, got {value!r}")
    prefix, entry = value.split(".")
    if prefix != category:
        raise UnsupportedSemanticState(f"expected category {category}, got {value!r}")
    return entry


def _enemy(model: str, hp: int, max_hp: int, block: int, order: int, slot: str | None,
           reviving: bool = False) -> tuple:
    if order < 0 or (slot is not None and not isinstance(slot, str)):
        raise UnsupportedSemanticState("invalid public enemy position")
    if hp <= 0 and not reviving:
        raise UnsupportedSemanticState("dead/reviving enemy transition is outside the initial contract")
    result = order, slot, model, int(hp), int(max_hp), int(block)
    # The frozen v11 living-enemy keys remain byte-for-byte compatible. A dead
    # creature is admitted only with explicit public revival evidence.
    return (*result, "reviving") if reviving else result


def _unique_enemies(enemies: list[tuple], where: str) -> None:
    orders = [e[0] for e in enemies]
    slots = [e[1] for e in enemies if e[1] is not None]
    if sorted(orders) != list(range(len(enemies))) or len(set(slots)) != len(slots):
        raise UnsupportedSemanticState(f"{where}: ambiguous_target or incomplete public enemy positions")


def _native_card(card: dict, allow_modifiers: bool = False) -> tuple:
    where = f"native card {card.get('id', '?')}"
    if card.get("enchantmentId") and not allow_modifiers:
        raise UnsupportedSemanticState(f"{where}: enchanted cards are outside the initial contract")
    return (model_entry(_required(card, "modelId", where), "CARD"),
            _integer(card, "upgradeLevel", where))


def _native_hand(card: dict, allow_modifiers: bool = False) -> tuple:
    where = f"native hand card {card.get('id', '?')}"
    slot = _integer(card, "slotIndex", where)
    if slot < 0:
        raise UnsupportedSemanticState(f"{where}: negative public hand slot")
    return (slot, *_native_card(card, allow_modifiers), _integer(card, "cost", where))


def project_native(frame: dict) -> Projection:
    """Project one ready host JSON frame, rejecting missing semantics explicitly."""
    if frame.get("error"):
        raise UnsupportedSemanticState(f"native reported an error: {frame['error']}")
    if frame.get("status") != "ready":
        raise UnsupportedSemanticState(f"native is not ready: {frame.get('status')!r}")
    revision = _integer(frame, "revision", "native")
    raw_screen = _required(frame, "screen", "native")
    from .action_contract import native_screen, native_extra_key
    screen = native_screen(frame)
    if screen not in ("neow", "map", "combat", "rewards", "card_reward", "rest", "shop", "shop_entry",
                      "event", "card_selection", "combat_selection", "hand_selection", "choose_card", "treasure",
                      "crystal_sphere", "relic_selection", "card_bundle"):
        raise UnsupportedSemanticState(f"native: unsupported screen {raw_screen!r}")
    player = _required(frame, "player", "native")
    public = {key: _integer(player, source, "native.player") for key, source in (
        ("hp", "hp"), ("max_hp", "maxHp"), ("gold", "gold"), ("act", "act"),
        ("act_floor", "floor"), ("total_floor", "totalFloor"))}
    acts = _required(frame, "actOrder", "native")
    if not isinstance(acts, list) or not 0 <= public["act"] - 1 < len(acts):
        raise UnsupportedSemanticState("native: current act type is missing")
    # Only the currently visible biome is admitted; future act order is not a
    # policy feature of this adapter.
    public["act_type"] = acts[public["act"] - 1]
    entities = _required(frame, "entities", "native")
    ids = [e.get("id") for e in entities]
    if None in ids or len(set(ids)) != len(ids):
        raise UnsupportedSemanticState("native: missing or duplicate entity transport IDs")
    rich = frame.get("publicObservation") is not None
    public["deck"] = tuple(sorted(_native_card(e, rich) for e in entities
                                  if e.get("kind") == "card" and e.get("pile") == "deck"))
    public["relics"] = tuple(sorted(model_entry(e.get("modelId"), "RELIC") for e in entities
                                    if e.get("kind") == "relic" and e.get("pile") != "choice"))
    hands, enemies = {}, {}
    if screen in ("combat", "combat_selection"):
        hands = {e["id"]: _native_hand(e, rich) for e in entities
                 if e.get("kind") == "card" and e.get("pile") == "hand"}
        if len({h[0] for h in hands.values()}) != len(hands):
            raise UnsupportedSemanticState("native: duplicate public hand slotIndex")
        for e in entities:
            if e.get("kind") == "enemy":
                public_enemy = next((v for v in (frame.get("publicObservation") or {}).get("enemies", [])
                                     if v.get("transportId") == e["id"]), {})
                enemies[e["id"]] = _enemy(model_entry(e.get("modelId"), "MONSTER"),
                    _integer(e, "hp", "native enemy"), _integer(e, "maxHp", "native enemy"),
                    _integer(e, "block", "native enemy"),
                    _integer(e, "enemyOrderIndex", "native enemy"), e.get("slotName"),
                    reviving=public_enemy.get("reviving") is True)
        _unique_enemies(list(enemies.values()), "native")
        public.update(hand=tuple(sorted(hands.values())), enemies=tuple(sorted(enemies.values())),
                      block=_integer(player, "block", "native.player"),
                      energy=_integer(player, "energy", "native.player"),
                      turn=_integer(player, "combatTurn", "native.player"))
        public["pile_counts"] = tuple(sum(e.get("kind") == "card" and e.get("pile") == pile
                                            for e in entities) for pile in ("draw", "discard", "exhaust"))
    elif screen == "map":
        nodes = _required(_required(frame, "map", "native"), "nodes", "native.map")
        public["available_map_nodes"] = tuple(sorted(
            (_integer(n, "x", "map node"), _integer(n, "y", "map node"))
            for n in nodes if n.get("available") is True))
    actions, ignored = [], []
    for action in _required(frame, "actions", "native"):
        if action.get("disabled") is True:
            continue
        aid = _required(action, "id", "native action")
        kind = _required(action, "kind", "native action")
        if kind == "back" and screen == "map":
            ignored.append(aid)  # UI navigation only, explicitly surfaced to caller.
            continue
        if screen == "neow" and kind == "event":
            if action.get("optionIsProceed") is True:
                if action.get("optionModelId") is not None:
                    raise UnsupportedSemanticState("native: Neow Proceed unexpectedly carries a relic")
                key = ActionKey("neow_proceed")
            else:
                key = ActionKey("neow_relic", (model_entry(action.get("optionModelId"), "RELIC"),))
        elif screen == "map" and kind == "map":
            key = ActionKey("move", (_integer(action, "x", "native map action"),
                                      _integer(action, "y", "native map action")))
        elif screen == "combat" and kind == "endTurn":
            key = ActionKey("end_turn")
        elif screen == "combat" and kind == "play":
            card_id = _required(action, "entityId", "native play")
            if card_id not in hands:
                raise UnsupportedSemanticState(f"native play: entity {card_id!r} is not a hand card")
            target_id = action.get("targetId")
            if target_id is not None and target_id not in enemies:
                raise UnsupportedSemanticState(f"native play: unsupported target {target_id!r}")
            key = ActionKey("play", (hands[card_id], enemies.get(target_id)))
        else:
            key = native_extra_key(frame, screen, action, enemies)
        actions.append(BoundAction(key, aid))
    projection = Projection("native", screen, public, tuple(actions), revision, tuple(ignored))
    projection.by_key()
    return projection


@dataclass(frozen=True)
class SimulatorCatalog:
    """Numeric card IDs from the generated enum, not JSON list/display-name guesses."""
    cards: dict[int, str]

    @classmethod
    def from_repo(cls, root: str | Path | None = None) -> "SimulatorCatalog":
        root = Path(root) if root is not None else Path(__file__).resolve().parents[1]
        source = (root / "sim/include/sts2/cards_generated.inc").read_text()
        match = re.search(r"enum class CardId[^\{]*\{(.*?)\};", source, re.S)
        if not match:
            raise UnsupportedSemanticState("cannot read generated CardId enum")
        result, current = {}, -1
        for piece in match.group(1).split(","):
            piece = re.sub(r"//[^\n]*", "", piece).strip()
            if not piece:
                continue
            item = re.fullmatch(r"([A-Z][A-Z0-9_]*)(?:\s*=\s*(\d+))?", piece)
            if not item:
                raise UnsupportedSemanticState(f"unrecognized CardId enum member {piece!r}")
            current = int(item[2]) if item[2] is not None else current + 1
            if item[1] not in ("INVALID", "COUNT"):
                result[current] = item[1]
        aliases_path = root / "train/spire_rl/public_catalog.json"
        if aliases_path.exists():
            aliases = json.loads(aliases_path.read_text())["simCardIds"]
            result = {ident: model_entry(aliases.get("CARD." + key, "CARD." + key), "CARD")
                      for ident, key in result.items() if aliases.get("CARD." + key, "CARD." + key) is not None}
        return cls(result)

    def card(self, ident: int) -> str:
        try:
            return self.cards[int(ident)]
        except KeyError as exc:
            raise UnsupportedSemanticState(f"unknown simulator card ID {ident}") from exc


def project_simulator(rc, sim, catalog: SimulatorCatalog | None = None) -> Projection:
    """Project current public simulator data; never read draw order or RNG state."""
    catalog = catalog or SimulatorCatalog.from_repo()
    from .action_contract import simulator_screen, simulator_extra_key, simulator_choice_keys
    screen = simulator_screen(rc, sim)
    if screen is None:
        raise UnsupportedSemanticState(f"simulator: unsupported screen {rc.screen}")
    if any(int(e[0]) for e in rc.deck_enchantments) and not hasattr(sim, "public_model_state"):
        raise UnsupportedSemanticState("simulator: enchanted deck outside initial contract")
    public = dict(hp=int(rc.hp), max_hp=int(rc.max_hp), gold=int(rc.gold), act=int(rc.act) + 1,
                  act_floor=int(rc.act_floor), total_floor=int(rc.floor),
                  act_type=rc.act_types[int(rc.act)].name,
                  deck=tuple(sorted((catalog.card(c[0]), int(c[1])) for c in rc.deck)),
                  relics=tuple(sorted(str(sim.relic_info(r)[0]) for r in rc.relics)))
    actions = []
    if screen in ("combat", "combat_selection"):
        bc = rc.battle
        if any(int(e[0]) for e in bc.hand_enchantments) and not hasattr(sim, "public_model_state"):
            raise UnsupportedSemanticState("simulator: enchanted hand outside initial contract")
        # This initial adapter pins the existing public observation layout. Field
        # additions/version changes must update the adapter, never guess offsets.
        if (int(sim.COMBAT_OBS_VERSION), int(sim.COMBAT_ENTITY_NUM)) not in ((4, 96), (5, 112)):
            raise UnsupportedSemanticState("simulator combat observation schema is unsupported")
        if getattr(sim, "MONSTER_POSITION_VERSION", None) != 1:
            raise UnsupportedSemanticState("simulator public enemy position schema is unsupported")
        obs = bc.entity_observation()
        legal = list(bc.legal_actions())
        if len(legal) != len(obs["cand_type"]):
            raise UnsupportedSemanticState("simulator candidate/legal-action length mismatch")
        numerics = obs["num"].reshape(len(obs["kind"]), -1)
        cnum = obs["cand_num"].reshape(len(legal), -1)
        hand = list(bc.hand)
        positions = list(bc.monster_positions)
        monsters = list(bc.monsters)
        if len(positions) != len(monsters):
            raise UnsupportedSemanticState("simulator: public enemy position count mismatch")
        enemies = {}
        for i, m in enumerate(monsters):
            position = positions[i]
            if not m[7] and not position.get("reviving"):
                continue
            if position.get("index") != i:
                raise UnsupportedSemanticState("simulator: public enemy index mismatch")
            native_id = position.get("native_model_id")
            entry = model_entry(native_id, "MONSTER") if native_id is not None else str(sim.monster_info(m[0])[0])
            enemies[i] = _enemy(entry, m[1], m[2], m[3],
                                _integer(position, "enemy_order_index", "simulator enemy"),
                                position.get("slot_name"), reviving=bool(position.get("reviving")))
        _unique_enemies(list(enemies.values()), "simulator")
        # combat_obs.cpp v3 emits 67 card scalars: playable=67, actual cost=68,
        # public hand position=69. (Its CARD_NUMERIC capacity bound overcounts
        # by two; it is not the emitted cursor.) Never substitute card_cost.
        hands = {}
        for row_index, kind in enumerate(obs["kind"]):
            if int(kind) != 3:  # CombatEntity.HAND_CARD, v3
                continue
            row = numerics[row_index]
            slot = _scaled_integer(row[69], 10, "simulator hand slot")
            if slot not in range(len(hand)) or slot in hands:
                raise UnsupportedSemanticState("simulator public hand position is invalid")
            card = hand[slot]
            if int(obs["id"][row_index]) != int(card[0]):
                raise UnsupportedSemanticState("simulator hand entity/model mismatch")
            if _scaled_integer(row[26], 1, "simulator upgrade flag") != int(card[2]):
                raise UnsupportedSemanticState("simulator hand entity/upgrade mismatch")
            expected_playable = int(any(int(a[0]) == int(sim.ActionType.PLAY_CARD) and int(a[1]) == slot for a in legal))
            if _scaled_integer(row[67], 1, "simulator playable flag") != expected_playable:
                raise UnsupportedSemanticState("simulator hand entity/playability mismatch")
            hands[slot] = (slot, catalog.card(card[0]), int(card[2]),
                           _scaled_integer(row[68], 3, "simulator combat cost"))
        if len(hands) != len(hand):
            raise UnsupportedSemanticState("simulator public hand entities are incomplete")
        for i, a in enumerate(legal):
            if int(a[0]) != int(obs["cand_type"][i]):
                raise UnsupportedSemanticState("simulator candidate/action type mismatch")
            if int(a[0]) == int(sim.ActionType.PLAY_CARD):
                if hands[int(a[1])][3] != _scaled_integer(cnum[i][1], 3, "simulator candidate cost"):
                    raise UnsupportedSemanticState("simulator hand/candidate combat-cost mismatch")
        public.update(hp=int(bc.player_hp), max_hp=int(bc.player_max_hp), gold=int(bc.gold),
                      block=int(bc.player_block), energy=int(bc.energy), turn=int(bc.turn),
                      hand=tuple(sorted(hands.values())), enemies=tuple(sorted(enemies.values())),
                      pile_counts=(int(bc.draw_count), int(bc.discard_count), int(bc.exhaust_count)))
        choice_keys = simulator_choice_keys(rc, sim) if int(bc.pending_info[0]) else {}
        for i, raw in enumerate(legal):
            a = tuple(map(int, raw))
            if a[0] == int(sim.ActionType.END_TURN):
                key = ActionKey("end_turn")
            elif a[0] == int(sim.ActionType.PLAY_CARD):
                if a[1] not in hands:
                    raise UnsupportedSemanticState("simulator play has invalid hand index")
                target = None
                if int(obs["cand_target2"][i]) >= 0:
                    if a[2] not in enemies:
                        raise UnsupportedSemanticState("simulator play has invalid enemy target")
                    target = enemies[a[2]]
                key = ActionKey("play", (hands[a[1]], target))
            elif a[0] == int(sim.ActionType.CHOOSE):
                entity = int(obs["cand_target"][i])
                if entity < 0:
                    raise UnsupportedSemanticState("simulator choice lacks a public card entity")
                fp = (catalog.card(int(obs["id"][entity])),
                      _scaled_integer(numerics[entity][26], 1, "simulator choice upgrade"))
                fp = choice_keys.get(str(a[3]), fp)
                pending_ids = list(bc.pending_options)
                if a[3] not in pending_ids:
                    raise UnsupportedSemanticState("simulator choice UID is absent from its pending candidates")
                selected_uids = set(getattr(bc, "pending_selected_uids", []))
                if int(bc.pending_info[1]) == 1 and not hasattr(bc, "pending_selected_uids"):
                    raise UnsupportedSemanticState("simulator hand choice is missing public selected state")
                selected = [uid in selected_uids for uid in pending_ids]
                chosen = bool(selected[pending_ids.index(a[3])])
                occurrence = 0
                for previous in range(i):
                    other = tuple(map(int, legal[previous]))
                    if other[0] != int(sim.ActionType.CHOOSE):
                        continue
                    other_entity = int(obs["cand_target"][previous])
                    other_fp = (catalog.card(int(obs["id"][other_entity])),
                                _scaled_integer(numerics[other_entity][26], 1, "simulator choice upgrade"))
                    other_fp = choice_keys.get(str(other[3]), other_fp)
                    if other_fp == fp and bool(selected[pending_ids.index(other[3])]) == chosen:
                        occurrence += 1
                key = ActionKey("deselect_card" if chosen else "select_card", (*fp, occurrence))
            else:
                # Potion action.target is an unused zero for self/AOE potions.
                # Only the public candidate target entity establishes targeting.
                targets = enemies if int(obs["cand_target2"][i]) >= 0 else {}
                key = simulator_extra_key(rc, sim, catalog, a, targets)
            actions.append(BoundAction(key, a))
    else:
        nodes = {int(n[0]): (int(n[2]), int(n[3])) for n in rc.map_nodes()} if screen == "map" else {}
        if screen == "map":
            public["available_map_nodes"] = tuple(sorted(nodes[int(i)] for i in rc.available_map_nodes()))
        for raw in rc.legal_actions():
            a = tuple(map(int, raw))
            if screen == "map" and a[0] == int(sim.RunActionType.MOVE):
                key = ActionKey("move", nodes[a[1]])
            elif screen == "neow" and a[0] == int(sim.RunActionType.EVENT_CHOICE):
                if rc.event_page == 127:
                    if a[1] != 0:
                        raise UnsupportedSemanticState("simulator: invalid Neow Proceed option")
                    actions.append(BoundAction(ActionKey("neow_proceed"), a))
                    continue
                relics = list(rc.event_relics)
                if not 0 <= a[1] < len(relics) or int(relics[a[1]]) <= 0:
                    raise UnsupportedSemanticState("simulator Neow option lacks offered relic ID")
                key = ActionKey("neow_relic", (str(sim.relic_info(relics[a[1]])[0]),))
            else:
                key = simulator_extra_key(rc, sim, catalog, a)
            actions.append(BoundAction(key, a))
    projection = Projection("simulator", screen, public, tuple(actions))
    projection.by_key()
    return projection


def compare_public_state(left: Projection, right: Projection) -> dict[str, dict]:
    """Return exact differences only within the documented partial coverage."""
    differences = {}
    if left.screen != right.screen:
        differences["screen"] = {left.source: left.screen, right.source: right.screen}
    for field in sorted(left.public_state.keys() | right.public_state.keys()):
        if left.public_state.get(field) != right.public_state.get(field):
            differences[field] = {left.source: left.public_state.get(field), right.source: right.public_state.get(field)}
    return differences


def pair_actions(simulator: Projection, native: Projection) -> dict[tuple[int, ...], str]:
    """Pair every legal action by semantics; no index/label/count fallback."""
    if simulator.source != "simulator" or native.source != "native":
        raise ValueError("expected simulator then native projections")
    if simulator.screen != native.screen:
        raise ParityMismatch(f"screen mismatch: {simulator.screen} vs {native.screen}")
    left, right = simulator.by_key(), native.by_key()
    if left.keys() != right.keys():
        raise ParityMismatch(f"legal actions differ; simulator-only={left.keys() - right.keys()}; native-only={right.keys() - left.keys()}")
    return {left[key].handle: right[key].handle for key in left}


def native_request_for_simulator_action(simulator: Projection, native: Projection,
                                        action: tuple[int, ...]) -> dict:
    """Translate a selected policy action only after state and action agreement.

    The request remains tied to the native revision; callers must recapture after
    every action. Full policy-feature parity still requires UNCOVERED_STATE work.
    """
    differences = compare_public_state(simulator, native)
    if differences:
        raise ParityMismatch(f"public state differs: {differences!r}")
    bindings = pair_actions(simulator, native)
    try:
        action_id = bindings[tuple(action)]
    except KeyError as exc:
        raise UnsupportedSemanticState(f"selected simulator action is not currently legal: {action!r}") from exc
    if native.revision is None:
        raise UnsupportedSemanticState("native revision is required")
    return {"revision": native.revision, "actionId": action_id}


def native_request_for_candidate(simulator: Projection, native: Projection,
                                 candidate_index: int) -> dict:
    """Route the current simulator policy candidate to its native semantic match.

    project_simulator retains the simulator's legal-candidate order (the same
    order exported by macro_observation/entity_observation). The index selects
    only that local candidate. Native action order is never used for matching.
    """
    if isinstance(candidate_index, bool) or not isinstance(candidate_index, int):
        raise UnsupportedSemanticState("policy candidate index must be an integer")
    if not 0 <= candidate_index < len(simulator.actions):
        raise UnsupportedSemanticState(f"policy candidate index out of range: {candidate_index}")
    return native_request_for_simulator_action(simulator, native, simulator.actions[candidate_index].handle)
