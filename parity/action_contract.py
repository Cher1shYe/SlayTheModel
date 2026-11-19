"""Source-keyed decisions beyond the original first-combat contract.

Keys never contain localized text, native object IDs, simulator UIDs or hidden
reward cards. Those values may route a selected candidate locally, but cannot
establish that two choices mean the same thing.
"""
from __future__ import annotations

from functools import lru_cache
import json
from pathlib import Path
import re


def _api():
    from .semantic import ActionKey, UnsupportedSemanticState, model_entry
    return ActionKey, UnsupportedSemanticState, model_entry


@lru_cache(maxsize=1)
def _potion_names():
    root = Path(__file__).resolve().parents[1]
    rows = json.loads((root / "sim/content/potions.json").read_text())
    source = (root / "sim/include/sts2/potions_generated.inc").read_text()
    entries = re.search(r"enum PotionId[^\{]*\{(.*?)\};", source, re.S).group(1)
    values = [part.strip().split("=")[0].strip() for part in entries.split(",")]
    names = {}
    for row in rows:
        symbol = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", row["id"]).upper()
        # StringHelper.Slugify separates adjacent capitals too (FairyInABottle).
        native = re.sub(r"(?<=[A-Za-z0-9])(?=[A-Z])", "_", row["id"]).upper()
        if symbol not in values:
            raise _api()[1](f"potion enum is missing {symbol}")
        names[values.index(symbol)] = native
    return names


def potion_name(ident):
    try:
        return _potion_names()[int(ident)]
    except KeyError as exc:
        raise _api()[1](f"unknown simulator potion ID {ident}") from exc


def native_navigation_request(frame):
    """One explicit, effect-free view-opening transaction before policy input.

    No simulator state is consulted. Opening merchant inventory only reveals the
    existing public merchandise; buying, removing, and leaving remain decisions.
    The caller must log the request and recapture a new revision afterwards.
    """
    Key, Error, _ = _api()
    if frame.get("status") != "ready":
        return None
    navigation = [a for a in frame.get("actions", []) if not a.get("disabled")
                  and (a.get("metadata") or {}).get("role") == "open_shop"
                  and (a.get("metadata") or {}).get("transportOnly") is True]
    if not navigation:
        return None
    if len(navigation) != 1:
        raise Error("ambiguous native merchant navigation")
    return {"revision": frame["revision"], "actionId": navigation[0]["id"]}


def native_screen(frame):
    raw = frame.get("screen")
    screens = {"NRewardsScreen": "rewards", "card_reward": "card_reward",
               "NRestSiteRoom": "rest", "merchant": "shop", "NMerchantInventory": "shop",
               "NMerchantRoom": "shop_entry", "card_selection": "card_selection",
               "choose_card": "choose_card", "handSelection": "hand_selection",
               "treasure": "treasure", "NTreasureRoom": "treasure",
               "crystal_sphere": "crystal_sphere", "relic_selection": "relic_selection",
               "card_bundle": "card_bundle"}
    if raw in ("event", "NEventRoom"):
        return "neow" if frame.get("surfaceModelId") == "EVENT.NEOW" else "event"
    screen = screens.get(raw, raw)
    if screen == "crystal_sphere" and (frame.get("board") or {}).get("finished"):
        return "event"
    if screen in ("card_selection", "hand_selection", "choose_card"):
        return "combat_selection" if (frame.get("player") or {}).get("combatTurn", 0) > 0 else "card_selection"
    return screen


def card_key(card, source="native"):
    Key, Error, model = _api()
    if not isinstance(card, dict):
        raise Error("native selection is missing its public card metadata")
    ident = model(card.get("modelId"), "CARD")
    upgrade = card.get("upgradeLevel", card.get("upgrade"))
    if isinstance(upgrade, bool):
        upgrade = int(upgrade)
    if not isinstance(upgrade, int):
        raise Error("native selection card is missing upgrade level")
    if "baseCost" in card:
        from spire_rl.public_obs import card_semantic_fingerprint, ObservationCoverageError
        try:
            fingerprint = card_semantic_fingerprint(card, source)
        except ObservationCoverageError as exc:
            raise Error(f"{source} card action fingerprint: {exc}") from exc
        canonical = dict(fingerprint)["modelId"]
        return model(canonical, "CARD"), upgrade, fingerprint
    # Historical captures lack the rich DTO; they remain the documented narrow
    # contract. Current host choices always carry the complete public card.
    return ident, upgrade


def _choice_card(frame, action):
    Key, Error, model = _api()
    choices = frame.get("choices") or (frame.get("decision") or {}).get("choices") or []
    for choice in choices:
        card = choice.get("card", {})
        if card.get("id", card.get("transportId")) == action.get("entityId"):
            return (action.get("metadata") or {}).get("card", choice.get("publicCard", card)), choice
    card = (action.get("metadata") or {}).get("card")
    if card is not None:
        return card, {"index": action.get("choiceIndex")}
    for card in frame.get("entities", []):
        if card.get("id") == action.get("entityId"):
            return card, {"index": action.get("choiceIndex")}
    raise Error("native selection action does not name a public candidate")


def _occurrence(frame, action, fingerprint):
    """Ordinal among publicly displayed identical candidate cards, not all cards."""
    Key, Error, _ = _api()
    choices = frame.get("choices") or (frame.get("decision") or {}).get("choices") or []
    selected = action.get("kind") == "deselectCard"
    own = next((c for c in choices if c.get("card", {}).get("id", c.get("card", {}).get("transportId")) == action.get("entityId")), {})
    selected = bool(own.get("selected", selected))
    rich = {a.get("entityId"): (a.get("metadata") or {}).get("card") for a in frame.get("actions", [])
            if (a.get("metadata") or {}).get("card") is not None}
    matching = [c for c in choices if "card" in c and card_key(rich.get(c["card"].get("id"), c.get("publicCard", c["card"]))) == fingerprint
                and bool(c.get("selected", False)) == selected]
    for ordinal, choice in enumerate(matching):
        card = choice["card"]
        if card.get("id", card.get("transportId")) == action.get("entityId"):
            return ordinal
    if len(matching) <= 1:
        return 0
    raise Error("ambiguous public duplicate card choice")


def simulator_choice_keys(rc, sim):
    """UID-indexed public picker cards. UIDs are used only to route locally."""
    if not hasattr(sim, "public_model_state"):
        return {}
    return {str(c["transportId"]): card_key(c, "simulator")
            for c in sim.public_model_state(rc).get("choices", [])}


def native_extra_key(frame, screen, action, enemies):
    Key, Error, model = _api()
    kind, data = action.get("kind"), action.get("metadata") or {}
    role = data.get("role")
    if kind in ("use_potion", "discard_potion"):
        slot, ident = data.get("slot"), model(data.get("modelId"), "POTION")
        if not isinstance(slot, int) or slot < 0:
            raise Error("potion action is missing its physical belt slot")
        if kind == "discard_potion":
            return Key(kind, (slot, ident))
        target = action.get("targetId")
        if target is not None and target not in enemies:
            raise Error("potion action has an unsupported target")
        return Key(kind, (slot, ident, enemies.get(target)))
    if kind == "reward":
        subtype, ordinal = data.get("rewardType"), data.get("ordinal")
        if not isinstance(ordinal, int) or ordinal < 0:
            raise Error("native reward lacks public reward ordinal")
        if subtype == "GoldReward":
            amount = data.get("amount")
            if not isinstance(amount, int):
                raise Error("gold reward lacks its public amount")
            return Key("take_gold", (bool(data.get("recovered")), amount, ordinal))
        if subtype == "PotionReward":
            return Key("take_potion", (model(data.get("modelId"), "POTION"), ordinal))
        if subtype == "RelicReward":
            return Key("take_relic_reward", (model(data.get("modelId"), "RELIC"), ordinal))
        if subtype == "CardReward":
            return Key("open_card_reward", (ordinal,))
        if subtype == "SpecialCardReward":
            return Key("take_special_card", (model(data.get("modelId"), "CARD"), data.get("upgradeLevel"), ordinal))
        if subtype == "CardRemovalReward":
            return Key("open_card_removal_reward", (ordinal,))
        raise Error(f"unsupported native reward type {subtype!r}")
    if kind == "choose_reward_card":
        card, choice = _choice_card(frame, action)
        fp = card_key(card)
        return Key("take_card", (*fp, _occurrence(frame, action, fp)))
    if kind in ("select_card", "selectCard", "deselectCard", "choose_card"):
        card, choice = _choice_card(frame, action)
        fp = card_key(card)
        operation = "deselect_card" if kind == "deselectCard" or choice.get("selected") else "select_card"
        return Key(operation, (*fp, _occurrence(frame, action, fp)))
    if kind == "confirm":
        return Key("confirm_selection")
    if kind == "buy":
        ident, price = data.get("modelId"), data.get("cost")
        if not isinstance(price, int):
            raise Error("merchant offer is missing its public price")
        if ident == "CARD_REMOVAL":
            return Key("open_remove_card", (price,))
        if not isinstance(ident, str) or ident.split(".")[0] not in ("CARD", "RELIC", "POTION"):
            raise Error("merchant offer is missing its native model ID")
        category = ident.split(".")[0]
        return Key("buy_" + category.lower(), (model(ident, category), price))
    if kind == "take_relic":
        entities = [e for e in frame.get("entities", []) if e.get("id") == action.get("entityId")]
        if len(entities) != 1:
            raise Error("treasure action lacks a unique public relic")
        return Key("take_treasure_relic", (model(entities[0].get("modelId"), "RELIC"),))
    if kind == "choose_relic":
        entities = [e for e in frame.get("entities", []) if e.get("id") == action.get("entityId")]
        if len(entities) != 1:
            raise Error("relic selector action lacks a unique public relic")
        return Key("select_relic", (model(entities[0].get("modelId"), "RELIC"),))
    if kind == "choose_bundle":
        cards = data.get("cards")
        if not isinstance(cards, list):
            raise Error("bundle action lacks its public card contents")
        return Key("select_bundle", (tuple(card_key(c) for c in cards),))
    if kind == "event":
        event = model(data.get("eventId"), "EVENT")
        if action.get("optionIsProceed") or data.get("isProceed"):
            return Key("event_proceed", (event,))
        page, option = data.get("pageKey"), data.get("optionKey")
        if not isinstance(page, str) or not isinstance(option, str):
            raise Error("event action lacks explicit native page/option keys")
        # Event ID and TextKey are authoritative. The displayed page is also
        # captured and validated by event_contract; it is never an array fallback.
        return Key("event_option", (event, option))
    if role == "rest":
        if data.get("optionId") not in ("HEAL", "SMITH", "DIG", "LIFT", "CLONE", "HATCH", "COOK", "KINDLE", "MEND"):
            raise Error("unknown native rest option ID")
        return Key("rest", (data["optionId"],))
    if role == "proceed" and screen == "event":
        return Key("event_proceed", (model(frame.get("surfaceModelId"), "EVENT"),))
    if role == "leave_shop" or kind == "leave_shop":
        return Key("leave_shop")
    if role == "proceed":
        return Key({"rewards": "leave_rewards", "rest": "rest_proceed", "treasure": "leave_treasure"}.get(screen, "proceed"))
    if role == "open_treasure":
        return Key("open_treasure")
    if role == "card_reward_alternative":
        option = data.get("optionId")
        known = {"Skip": "skip_card", "SACRIFICE": "sacrifice_card_reward", "REROLL": "reroll_card_reward", "HEAL": "heal_card_reward"}
        if option not in known:
            raise Error(f"unsupported native card reward alternative {option!r}")
        return Key(known[option])
    if role in ("confirm_selection", "cancel_preview", "cancel_selection", "skip_selection"):
        return Key(role)
    if role == "back" and screen == "shop":
        return Key("leave_shop")
    if kind == "reveal_cell":
        tool = data.get("tool")
        return Key("reveal_cell", (tool, action.get("x"), action.get("y")))
    if role in ("small_divination", "big_divination"):
        return Key(role)
    raise Error(f"native {screen}: unsupported legal action {kind!r} with metadata {data!r}")


def simulator_screen(rc, sim):
    if rc.screen == sim.RunScreen.COMBAT:
        return "combat_selection" if int(rc.battle.pending_info[0]) else "combat"
    if getattr(rc, "card_grid_kind", 0):
        return "card_selection"
    if rc.screen == sim.RunScreen.EVENT:
        if rc.event_name == "CRYSTAL_SPHERE" and rc.event_page == 1:
            return "crystal_sphere"
        if rc.event_name == "FAKE_MERCHANT" and rc.event_page == 0:
            return "shop"
        if rc.event_name == "NEOW" and rc.event_page in (0, 127):
            return "neow"
        if rc.event_card_selection:
            return "card_selection"
        return "event"
    return {sim.RunScreen.MAP: "map", sim.RunScreen.REWARDS: "rewards",
            sim.RunScreen.CARD_REWARD: "card_reward", sim.RunScreen.REST: "rest",
            sim.RunScreen.SHOP: "shop", sim.RunScreen.TREASURE: "treasure"}.get(rc.screen)


def simulator_extra_key(rc, sim, catalog, action, enemies=None):
    Key, Error, _ = _api()
    action_type, index = int(action[0]), int(action[1])
    enum = sim.ActionType if rc.screen == sim.RunScreen.COMBAT else sim.RunActionType
    names = [name for name in dir(enum) if name.isupper() and int(getattr(enum, name)) == action_type]
    if len(names) != 1:
        raise Error(f"unknown simulator action type {action_type}")
    name = names[0]
    ctx = rc.battle if rc.screen == sim.RunScreen.COMBAT else rc
    if name in ("USE_POTION", "DISCARD_POTION"):
        belt = list(ctx.potion_belt)
        if not 0 <= index < len(belt) or not belt[index]:
            raise Error("simulator potion action has an empty physical slot")
        ident = potion_name(belt[index])
        if name == "DISCARD_POTION":
            return Key("discard_potion", (index, ident))
        target = (enemies or {}).get(int(action[2])) if len(action) > 2 else None
        return Key("use_potion", (index, ident, target))
    if name == "TAKE_GOLD_REWARD":
        amounts = [(False, int(rc.reward_gold)), (True, int(rc.reward_recovered_gold))]
        amounts += [(False, int(v)) for v in (sim.pending_extra_gold_rewards(rc) if hasattr(sim, "pending_extra_gold_rewards") else [])]
        if not 0 <= index < len(amounts) or amounts[index][1] <= 0:
            raise Error("simulator gold reward lacks its public amount")
        ordinal = sum(amount > 0 for _, amount in amounts[:index])
        return Key("take_gold", (*amounts[index], ordinal))
    if name == "TAKE_POTION_REWARD":
        values = list(rc.reward_potions)
        return Key("take_potion", (potion_name(values[index]), sum(bool(v) for v in values[:index])))
    if name == "TAKE_RELIC_REWARD":
        values = list(rc.reward_relics)
        return Key("take_relic_reward", (str(sim.relic_info(values[index][0])[0]), sum(not v[1] for v in values[:index])))
    if name == "OPEN_CARD_REWARD":
        return Key("open_card_reward", (sum(bool(v) for v in list(rc.reward_card_slots)[:index]),))
    if name == "OPEN_CARD_REMOVAL_REWARD":
        return Key("open_card_removal_reward", (index,))
    if name == "TAKE_SPECIAL_CARD_REWARD":
        values = list(rc.reward_special_cards)
        match = [(i,c) for i,c in enumerate(values) if int(c[0]) == index]
        if len(match) != 1:
            raise Error("missing simulator explicit special card reward")
        ordinal, card = match[0]
        return Key("take_special_card", (catalog.card(card[1]), int(card[2]), ordinal))
    if name == "TAKE_STOLEN_CARD_REWARD":
        values = list(rc.reward_stolen_cards)
        match = [(i,c) for i,c in enumerate(values) if int(c[0]) == index]
        if len(match) != 1:
            raise Error("missing simulator special card reward")
        ordinal, card = match[0]
        ordinal += len(getattr(rc, "reward_special_cards", []))
        return Key("take_special_card", (catalog.card(card[1]), int(card[2]), ordinal))
    if name == "TAKE_CARD":
        cards = list(rc.offered)
        card = cards[index]
        public_keys = simulator_choice_keys(rc, sim)
        key_for = lambda c: public_keys.get(str(c[2]), (catalog.card(c[0]), int(c[1])))
        fp = key_for(card)
        return Key("take_card", (*fp, sum(key_for(c) == fp for c in cards[:index])))
    fixed = {"SKIP_CARD": "skip_card", "SACRIFICE_CARD_REWARD": "sacrifice_card_reward",
             "REROLL_CARD_REWARD": "reroll_card_reward",
             "LEAVE_REWARDS": "leave_rewards", "LEAVE_SHOP": "leave_shop", "REST_PROCEED": "rest_proceed",
             "CONFIRM_GRID_CARDS": "confirm_selection", "CANCEL_GRID_PREVIEW": "cancel_preview",
             "CANCEL_GRID_SELECTION": "cancel_selection", "CONFIRM_CHOICE": "confirm_selection", "CONFIRM": "confirm_selection",
             "LEAVE_TREASURE": "leave_treasure"}
    if name in fixed:
        if name == "CONFIRM" and int(ctx.pending_info[1]) == 4:
            return Key("skip_selection")
        if name == "CONFIRM_GRID_CARDS" and int(rc.card_grid_kind) in (13, 16):
            return Key("skip_selection")
        return Key(fixed[name])
    rests = {"REST_HEAL": "HEAL", "REST_UPGRADE": "SMITH", "REST_DIG": "DIG", "REST_LIFT": "LIFT", "REST_CLONE": "CLONE", "REST_HATCH": "HATCH", "REST_KINDLE": "KINDLE"}
    if name in rests:
        return Key("rest", (rests[name],))
    if name in ("BUY_CARD", "BUY_RELIC", "BUY_POTION"):
        values = getattr(rc, {"BUY_CARD": "shop", "BUY_RELIC": "shop_relics", "BUY_POTION": "shop_potions"}[name])
        value = values[index]
        ident = catalog.card(value[0]) if name == "BUY_CARD" else (str(sim.relic_info(value[0])[0]) if name == "BUY_RELIC" else potion_name(value[0]))
        return Key(name.lower(), (ident, int(value[1])))
    if name == "REMOVE_CARD":
        return Key("open_remove_card", (int(rc.removal_price),))
    if name == "EVENT_CHOICE":
        if rc.event_page == 127:
            return Key("event_proceed", (rc.event_name,))
        from .event_contract import simulator_event_option
        option = simulator_event_option(rc, index, sim)
        if rc.event_name == "FAKE_MERCHANT":
            if option == "LEAVE_SHOP":
                return Key("leave_shop")
            if option.startswith("BUY_RELIC:"):
                _, ident, price = option.split(":")
                return Key("buy_relic", (ident, int(price)))
        return Key("event_option", (rc.event_name, option))
    if name in ("SELECT_GRID_CARD", "EVENT_SELECT_CARD"):
        cards = list(rc.card_grid_cards) if name == "SELECT_GRID_CARD" else list(rc.deck)
        if name == "SELECT_GRID_CARD" and not cards and int(rc.card_grid_kind) in (3, 4, 6, 7, 8, 9, 10, 11, 12, 15, 17, 18, 19, 20, 21, 22):
            cards = list(rc.deck)
        if not cards:
            raise Error(f"simulator card grid {rc.card_grid_kind} has no public cards binding")
        card = cards[index]
        public_keys = simulator_choice_keys(rc, sim)
        key_for = lambda c: public_keys.get(str(c[2]), (catalog.card(c[0]), int(c[1])))
        if name == "SELECT_GRID_CARD" and int(rc.card_grid_kind) == 5:
            return Key("select_bundle", (tuple(key_for(c) for c in cards[index * 3:index * 3 + 3]),))
        fp = key_for(card)
        selected = list(rc.card_grid_selected) if name == "SELECT_GRID_CARD" else []
        operation = "deselect_card" if selected and selected[index] else "select_card"
        return Key(operation, (*fp, sum(key_for(c) == fp
            and (not selected or bool(selected[i]) == bool(selected[index])) for i,c in enumerate(cards[:index]))))
    if name in ("CRYSTAL_SPHERE_SMALL", "CRYSTAL_SPHERE_BIG"):
        return Key("reveal_cell", ("Small" if name.endswith("SMALL") else "Big", index // 11, index % 11))
    if name == "COLLECT":
        if not hasattr(sim.RunActionType, "TAKE_TREASURE_RELIC"):
            raise Error("legacy simulator COLLECT skips the native treasure choice")
        return Key("open_treasure")
    if name == "TAKE_TREASURE_RELIC":
        ident = getattr(rc, "treasure_relic", None)
        if ident is None:
            raise Error("missing public treasure relic binding")
        return Key("take_treasure_relic", (str(sim.relic_info(ident)[0]),))
    raise Error(f"simulator action {name} lacks a source-verified semantic mapping")
