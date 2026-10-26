#!/usr/bin/env python3
"""Drive real Steam with ArmG/random non-combat choices and exact-state MCTS combat.

CommunicationMod owns stdin/stdout. The learned policy handles map, card,
shop, rest, and event choices; both policies use the same MCTS combat search.
"""

import json
import os
import random
import re
import statistics
import sys
import time
from pathlib import Path

import torch

# This 116k-parameter scorer is faster and more stable without thread-pool fan-out.
torch.set_num_threads(1)
torch.set_num_interop_threads(1)

ROOT = Path(__file__).resolve().parents[1]
SIM = Path(os.environ.get(
    "STS_LIGHTSPEED_BUILD", ROOT.parent / "sts_lightspeed/build312")).expanduser()
sys.path[:0] = [str(SIM), str(ROOT / "agent"), str(Path(__file__).parent)]

import slaythespire as sts  # noqa: E402
import armG_train as AG  # noqa: E402
from real_replay_bridge import broll_battle_command  # noqa: E402
from steam_mcts import recommend as mcts_recommend  # noqa: E402

SEED = int(os.environ.get("STS_SEED", "24242"))
SEED_TOKEN = os.environ.get("STS_SEED_TOKEN", str(SEED))
POLICY = os.environ.get("STS_LIVE_POLICY", "learned").lower()
MODEL = ROOT / "weights/armG_model_G128x128_15k.pt"
LOG = Path(os.environ.get("STS_LIVE_LOG", ROOT / f"runs/{POLICY}-seed-{SEED}.jsonl"))
DELAY = float(os.environ.get("STS_LIVE_DELAY", "0.5"))
START_DELAY = float(os.environ.get("STS_START_DELAY", "0"))
MAX_DECISIONS = int(os.environ.get("STS_MAX_NONCOMBAT_DECISIONS", "0"))
STOP_AT_ACT1_CLEAR = os.environ.get("STS_STOP_AT_ACT1_CLEAR", "0") == "1"
STOP_AT_ACT_CLEAR = int(os.environ.get("STS_STOP_AT_ACT_CLEAR", "1" if STOP_AT_ACT1_CLEAR else "0"))
COMBAT_POLICY = os.environ.get("STS_COMBAT_POLICY", "mcts").lower()
MCTS_SIMULATIONS = int(os.environ.get("STS_MCTS_SIMULATIONS", "2000"))
MCTS_DETERMINIZATIONS = int(os.environ.get("STS_MCTS_DETERMINIZATIONS", "3"))
MAX_MCTS_ACTIONS = int(os.environ.get("STS_MAX_MCTS_ACTIONS", "0"))
STOP_AFTER_FIRST_BATTLE = os.environ.get("STS_STOP_AFTER_FIRST_BATTLE", "0") == "1"
MCTS_UNSUPPORTED = os.environ.get("STS_MCTS_UNSUPPORTED", "fail").lower()
LOG_MCTS_SNAPSHOT = os.environ.get("STS_LOG_MCTS_SNAPSHOT", "0") == "1"
NEOW_INDEX = int(os.environ.get("STS_NEOW_INDEX", "-1"))
RESUME_CURRENT = os.environ.get("STS_RESUME_CURRENT", "0") == "1"

CARD_ID_ALIASES = {"Strike_R": "STRIKE_RED", "Defend_R": "DEFEND_RED"}
ROOM_SYMBOL_IDX = {"M": 0, "E": 1, "R": 2, "$": 3, "?": 4, "T": 5, "B": 6}
REST_OPTION_IDX = {"rest": 0, "smith": 1, "recall": 2, "lift": 3, "toke": 4, "dig": 5, "leave": 6}
BOSS_INDEX = {"slimeboss": 0, "hexaghost": 1, "theguardian": 2,
              "champ": 3, "thechamp": 3, "automaton": 4, "bronzeautomaton": 4,
              "collector": 5, "thecollector": 5, "timeeater": 6,
              "donuanddeca": 7, "awakenedone": 8, "theheart": 9}
EVENT_IDS = (
    "INVALID", "MONSTER", "REST", "SHOP", "TREASURE", "Neow Event",
    "Accursed Blacksmith", "Addict", "Back to Basics", "Beggar", "Big Fish",
    "Bonfire Elementals", "Colosseum", "Cursed Tome", "Dead Adventurer", "Designer",
    "Drug Dealer", "Duplicator", "Face Trader", "Falling", "Forgotten Altar",
    "Fountain of Cleansing", "Ghosts", "Golden Idol", "Golden Shrine", "Golden Wing",
    "Knowing Skull", "Lab", "Liars Game", "Living Wall", "Masked Bandits",
    "Match and Keep", "MindBloom", "Mushrooms", "Mysterious Sphere", "Nest", "Nloth",
    "Note For Yourself", "Purifier", "Scrap Ooze", "Secret Portal", "Sensory Stone",
    "Shining Light", "The Cleric", "The Joust", "The Library", "The Mausoleum",
    "The Moai Head", "The Woman in Blue", "Tomb of Lord Red Mask", "Transmorgrifier",
    "Upgrade Shrine", "Vampires", "WeMeetAgain", "Wheel of Change", "Winding Halls",
    "World of Goop",
)


def normalize(value):
    return "".join(character.lower() for character in str(value) if character.isalnum())


EVENT_INDEX = {normalize(value): index for index, value in enumerate(EVENT_IDS)}


def emit(command):
    sys.stdout.write(command + "\n")
    sys.stdout.flush()


def log(record):
    LOG.parent.mkdir(parents=True, exist_ok=True)
    record.setdefault("ts", time.time())
    with LOG.open("a", encoding="utf-8") as output:
        output.write(json.dumps(record, ensure_ascii=False) + "\n")


def card_enum_key(identifier):
    if identifier in CARD_ID_ALIASES:
        return CARD_ID_ALIASES[identifier]
    value = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", identifier.replace(" ", "_"))
    return value.upper()


def make_card(data):
    key = card_enum_key(data.get("id") or data.get("name") or "")
    try:
        card = sts.Card(getattr(sts.CardId, key))
    except AttributeError as exc:
        raise ValueError(f"unsupported card id: {data.get('id')} -> {key}") from exc
    for _ in range(int(data.get("upgrades") or 0)):
        card.upgrade()
    return card


def blank(kind):
    descriptor = AG._blank()
    descriptor[AG.OFF_DTYPE + kind] = 1.0
    return descriptor


def node_lookup(game_state):
    return {(int(node["x"]), int(node["y"])): node for node in game_state.get("map") or []}


def add_room_counts(node, lookup, descriptor, offset):
    children = []
    for coords in node.get("children") or []:
        child = lookup.get((int(coords["x"]), int(coords["y"])))
        if not child:
            continue
        children.append(child)
        index = ROOM_SYMBOL_IDX.get(child.get("symbol"))
        if index is not None:
            descriptor[offset + index] += 1.0
    return children


def map_choices(game_state):
    screen = game_state.get("screen_state") or {}
    nodes = screen.get("next_nodes") or []
    labels = game_state.get("choice_list") or []
    lookup = node_lookup(game_state)
    descriptors, display, commands = [], [], []
    for index, target in enumerate(nodes):
        descriptor = blank(AG.DT_MAP)
        room = ROOM_SYMBOL_IDX.get(target.get("symbol"))
        if room is not None:
            descriptor[AG.OFF_MROOM + room] = 1.0
        full_target = lookup.get((int(target["x"]), int(target["y"])), target)
        children = add_room_counts(full_target, lookup, descriptor, AG.OFF_MLA1)
        for child in children:
            add_room_counts(child, lookup, descriptor, AG.OFF_MLA2)
        descriptors.append(descriptor)
        raw = labels[index] if index < len(labels) else target.get("symbol", "?")
        display.append(f"路线 x={target['x']} · {raw}")
        commands.append(f"CHOOSE {index}")
    if not descriptors:
        return "map", [], [], [], ["map candidates not ready"]
    return "map", display, descriptors, commands, []


def card_choices(game_state, available):
    screen = game_state.get("screen_state") or {}
    cards = screen.get("cards") or []
    labels, descriptors, commands = [], [], []
    for index, data in enumerate(cards):
        card = make_card(data)
        label = AG.card_name(card)
        descriptor = blank(AG.DT_CARD)
        descriptor[AG.OFF_CARD + AG.card_idx(label)] = 1.0
        labels.append(data.get("name") or label)
        descriptors.append(descriptor)
        commands.append(f"CHOOSE {index}")
    if screen.get("skip_available") or "return" in available:
        descriptor = blank(AG.DT_CARD)
        descriptor[AG.OFF_PASS] = 1.0
        labels.append("跳过")
        descriptors.append(descriptor)
        commands.append("SKIP")
    if not descriptors:
        return "card", [], [], [], ["card candidates not ready"]
    return "card", labels, descriptors, commands, []


def rest_choices(game_state):
    labels = game_state.get("choice_list") or []
    descriptors, warnings = [], []
    for label in labels:
        descriptor = blank(AG.DT_REST)
        option = REST_OPTION_IDX.get(normalize(label))
        if option is None:
            warnings.append(f"unknown rest option: {label}")
            option = min(len(descriptors), AG.W_REST - 1)
        descriptor[AG.OFF_REST + option] = 1.0
        descriptors.append(descriptor)
    return "rest", labels, descriptors, [f"CHOOSE {i}" for i in range(len(labels))], warnings


def event_choices(game_state):
    screen = game_state.get("screen_state") or {}
    labels = game_state.get("choice_list") or []
    event_key = normalize(screen.get("event_id") or screen.get("event_name") or "")
    event_index = EVENT_INDEX.get(event_key, 0)
    warnings = [] if event_key in EVENT_INDEX else [f"unknown event id: {screen.get('event_id')}"]
    descriptors = []
    for index, _ in enumerate(labels):
        descriptor = blank(AG.DT_EVENT)
        descriptor[AG.OFF_EVID + min(event_index, AG.EVENT_CAP - 1)] = 1.0
        descriptor[AG.OFF_EOPT + min(index, AG.EOPT_CAP - 1)] = 1.0
        descriptors.append(descriptor)
    return "event", labels, descriptors, [f"CHOOSE {i}" for i in range(len(labels))], warnings


def shop_choices(game_state, available):
    labels = game_state.get("choice_list") or []
    screen = game_state.get("screen_state") or {}
    pools = {"card": list(screen.get("cards") or []),
             "relic": list(screen.get("relics") or []),
             "potion": list(screen.get("potions") or [])}
    descriptors, display, commands, warnings = [], [], [], []
    for choice_index, label in enumerate(labels):
        descriptor = blank(AG.DT_SHOP)
        item = item_type = None
        if normalize(label) == "purge":
            descriptor[AG.OFF_SITEM + AG.SITEM_IDX[sts.RewardsActionType.CARD_REMOVE]] = 1.0
            display_label = f"删牌服务 · {screen.get('purge_cost') or 0} 金"
        else:
            for candidate_type, items in pools.items():
                match = next((entry for entry in items
                              if normalize(entry.get("name")) == normalize(label)), None)
                if match is not None:
                    item, item_type = match, candidate_type
                    items.remove(match)
                    break
            if item_type == "card":
                card = make_card(item)
                descriptor[AG.OFF_SITEM + AG.SITEM_IDX[sts.RewardsActionType.CARD]] = 1.0
                descriptor[AG.OFF_CARD + AG.card_idx(AG.card_name(card))] = 1.0
                price = item.get("price") or 0
                descriptor[AG.OFF_SPRICE] = min(price, AG.GOLD_MAX) / AG.GOLD_MAX
                display_label = f"购买 {item.get('name')} · {price} 金"
            elif item_type == "relic":
                descriptor[AG.OFF_SITEM + AG.SITEM_IDX[sts.RewardsActionType.RELIC]] = 1.0
                display_label = f"购买遗物 {item.get('name')} · {item.get('price', 0)} 金"
            elif item_type == "potion":
                descriptor[AG.OFF_SITEM + AG.SITEM_IDX[sts.RewardsActionType.POTION]] = 1.0
                display_label = f"购买药水 {item.get('name')} · {item.get('price', 0)} 金"
            else:
                display_label = str(label)
                warnings.append(f"unmatched shop choice: {label}")
        descriptors.append(descriptor)
        display.append(display_label)
        commands.append(f"CHOOSE {choice_index}")
    leave_command = "LEAVE" if "leave" in available else "RETURN" if "return" in available else None
    if leave_command:
        descriptor = blank(AG.DT_SHOP)
        descriptor[AG.OFF_SITEM + AG.SITEM_IDX[sts.RewardsActionType.SKIP]] = 1.0
        descriptor[AG.OFF_PASS] = 1.0
        descriptors.append(descriptor)
        display.append("离开商店")
        commands.append(leave_command)
    return "shop", display, descriptors, commands, warnings


def build_live_choices(game_state, available):
    screen = game_state.get("screen_type")
    builders = {"MAP": map_choices, "REST": rest_choices, "EVENT": event_choices}
    if screen in builders:
        return builders[screen](game_state)
    if screen == "CARD_REWARD":
        return card_choices(game_state, available)
    if screen == "SHOP_SCREEN":
        return shop_choices(game_state, available)
    raise ValueError(f"unsupported learned screen: {screen}")


class LivePolicy:
    def __init__(self, policy=POLICY, seed=SEED):
        if policy not in {"learned", "random"}:
            raise ValueError(f"STS_LIVE_POLICY must be learned or random, got {policy}")
        self.policy = policy
        self.rng = random.Random(seed ^ 0xA11CE)
        self.net = None
        if policy == "learned":
            self.net = AG.Scorer((128, 128))
            self.net.load_state_dict(torch.load(MODEL, weights_only=True))
            self.net.eval()
            with torch.inference_mode():
                self.net.score(torch.zeros(AG.OBS_DIM), [AG._blank()])
        self.shadow = sts.GameContext(sts.CharacterClass.IRONCLAD, seed, 0)
        self.observation_warnings = []

    def sync_observation(self, game_state):
        self.shadow.cur_hp = int(game_state.get("current_hp") or 0)
        self.shadow.max_hp = int(game_state.get("max_hp") or 0)
        self.shadow.gold = int(game_state.get("gold") or 0)
        self.shadow.floor_num = int(game_state.get("floor") or 0)
        current = (game_state.get("screen_state") or {}).get("current_node") or {}
        if "x" in current:
            self.shadow.cur_map_node_x = int(current["x"])
        if "y" in current:
            self.shadow.cur_map_node_y = int(current["y"])
        deck = game_state.get("deck") or []
        for index in range(len(self.shadow.deck) - 1, -1, -1):
            self.shadow.remove_card(index)
        for data in deck:
            self.shadow.obtain_card(make_card(data))

    def observation(self, game_state):
        self.sync_observation(game_state)
        observation = AG.obs_vec(self.shadow)
        self.observation_warnings = []

        # NNInterface layout: four scalars, ten bosses, 220 cards, 178 relics.
        observation[4:14] = [0.0] * 10
        boss = BOSS_INDEX.get(normalize(game_state.get("act_boss")))
        if boss is not None:
            observation[4 + boss] = 1.0
        else:
            self.observation_warnings.append(f"unknown boss: {game_state.get('act_boss')}")

        observation[234:412] = [0.0] * 178
        for relic in game_state.get("relics") or []:
            try:
                relic_id = sts.relic_id_from_name(relic.get("id") or relic.get("name") or "")
            except ValueError:
                self.observation_warnings.append(f"unknown relic: {relic.get('id')}")
                continue
            index = int(relic_id)
            if index < 178:
                observation[234 + index] = 1.0
        return observation

    def choose(self, game_state, descriptors):
        started = time.perf_counter()
        if self.policy == "random":
            count = len(descriptors)
            scores = [0.0] * count
            probabilities = [1.0 / count] * count
            selected = self.rng.randrange(count)
        else:
            observation = self.observation(game_state) if game_state else AG.obs_vec(self.shadow)
            with torch.no_grad():
                scores_tensor = self.net.score(
                    torch.tensor(observation, dtype=torch.float32), descriptors)
                probabilities_tensor = torch.softmax(scores_tensor, dim=0)
            scores = [float(value) for value in scores_tensor]
            probabilities = [float(value) for value in probabilities_tensor]
            selected = max(range(len(probabilities)), key=probabilities.__getitem__)
        return scores, probabilities, selected, (time.perf_counter() - started) * 1000


def packed_decision(policy, kind, labels, scores, probabilities, selected, latency_ms, warnings=None):
    return {"status": "model_decision", "policy": policy, "kind": kind,
            "choices": [{"label": label, "score": round(float(score), 3),
                         "probability": round(float(probability), 4)}
                        for label, score, probability in zip(labels, scores, probabilities)],
            "selected": selected, "latency_ms": round(latency_ms, 3),
            "warnings": warnings or []}


def fixed_grid_command(state):
    available = set(state.get("available_commands") or [])
    if "confirm" in available:
        return "CONFIRM"
    if "choose" in available:
        return "CHOOSE 0"
    if "return" in available:
        return "RETURN"
    return "WAIT 60"


def grid_followup_command(state, waiting, expected_selected):
    available = set(state.get("available_commands") or [])
    game_state = state.get("game_state") or {}
    selected = len((game_state.get("screen_state") or {}).get("selected_cards") or [])
    if "confirm" in available:
        return "CONFIRM", False, 0
    if "choose" in available:
        if waiting and selected < expected_selected:
            return "WAIT 60", True, expected_selected
        return "CHOOSE 0", True, selected + 1
    return "WAIT 20", waiting, expected_selected


def fixed_hand_select_command(state):
    available = set(state.get("available_commands") or [])
    if "confirm" in available:
        return "CONFIRM"
    if "choose" in available:
        return "CHOOSE 0"
    return "WAIT 20"


def planned_select_command(state, pending):
    available = set(state.get("available_commands") or [])
    if "confirm" in available:
        return "CONFIRM"
    if "choose" in available and pending:
        return f"CHOOSE {pending.pop(0)}"
    return fixed_hand_select_command(state)


def shop_room_command(floor, available, entered_shop_floors):
    if floor in entered_shop_floors:
        if "proceed" in available:
            return "PROCEED", "leave visited shop room"
        return "WAIT 20", "wait after leaving shop"
    if "choose" in available:
        entered_shop_floors.add(floor)
        return "CHOOSE 0", "enter shop once"
    return "WAIT 20", "wait for shop entrance"


def empty_screen_command(screen, available):
    if "proceed" in available:
        return "PROCEED", f"advance after empty {screen.lower()}"
    if screen == "SHOP_SCREEN" and "leave" in available:
        return "LEAVE", "leave empty shop"
    if screen == "CARD_REWARD" and "skip" in available:
        return "SKIP", "skip empty card reward"
    if "confirm" in available:
        return "CONFIRM", f"confirm empty {screen.lower()}"
    return "WAIT 20", f"wait for {screen.lower()} candidates"


def combat_reward_command(game_state, available):
    rewards = (game_state.get("screen_state") or {}).get("rewards") or []
    preferred = ("GOLD", "RELIC")
    for reward_type in preferred:
        index = next((i for i, reward in enumerate(rewards)
                      if reward.get("reward_type") == reward_type), None)
        if index is not None:
            return f"CHOOSE {index}", f"collect {reward_type.lower()} reward"
    potion_index = next((i for i, reward in enumerate(rewards)
                         if reward.get("reward_type") == "POTION"), None)
    has_empty_slot = any(potion.get("id") == "Potion Slot"
                         for potion in game_state.get("potions") or [])
    if potion_index is not None and has_empty_slot:
        return f"CHOOSE {potion_index}", "collect potion reward"
    card_index = next((i for i, reward in enumerate(rewards)
                       if reward.get("reward_type") == "CARD"), None)
    if card_index is not None:
        return f"CHOOSE {card_index}", "collect card reward"
    if "proceed" in available:
        return "PROCEED", "skip unsupported or full-slot rewards"
    return "WAIT 20", "wait for combat rewards"


def is_combat_command_state(combat, available):
    """CommunicationMod can retain stale combat_state during reward transitions."""
    return bool(combat and {"play", "end"} & available)


def shop_transport_followup(kind, label):
    """A purchase does not emit a new state; request one so the model can keep shopping."""
    return "STATE" if kind == "shop" and label.startswith("购买") else None


def event_transport_followup(kind, game_state):
    """These events show a non-strategic leave page without emitting a new state."""
    event_id = (game_state.get("screen_state") or {}).get("event_id")
    needs_leave = {normalize("Ghosts"), normalize("Cursed Tome")}
    return "CHOOSE 0" if kind == "event" and normalize(event_id) in needs_leave else None


def boss_reward_command(game_state):
    relics = (game_state.get("screen_state") or {}).get("relics") or []
    ranked = [(sts.boss_relic_ordering(sts.relic_id_from_name(
        relic.get("id") or relic.get("name"))), index) for index, relic in enumerate(relics)]
    _, index = min(ranked)
    return f"CHOOSE {index}", f"simulator boss relic policy: {relics[index].get('id') or relics[index].get('name')}"


def main():
    if COMBAT_POLICY not in {"broll", "mcts"}:
        raise ValueError(f"STS_COMBAT_POLICY must be broll or mcts, got {COMBAT_POLICY}")
    policy = LivePolicy()
    if LOG.exists():
        LOG.unlink()
    log({"status": "session_start", "policy": POLICY, "seed": SEED,
         "seed_token": SEED_TOKEN,
         "model": str(MODEL) if POLICY == "learned" else None})
    started = left_neow = finished = False
    decisions = 0
    combat_actions = 0
    entered_combat = False
    combat_turn = None
    combat_counters = {"cards": 0, "attacks": 0, "skills": 0}
    entered_shop_floors = set()
    grid_waiting = False
    grid_expected_selected = 0
    pending_mcts_selects = []
    emit("ready")
    for line in sys.stdin:
        state = json.loads(line)
        if not state.get("ready_for_command"):
            emit("WAIT 20")
            continue
        available = set(state.get("available_commands") or [])
        game_state = state.get("game_state") or {}
        screen = game_state.get("screen_type")
        choices = game_state.get("choice_list") or []
        combat = game_state.get("combat_state")
        if screen != "GRID":
            grid_waiting = False
            grid_expected_selected = 0
        command, reason, decision, combat_search, mcts_fallback = "WAIT 60", "transition", None, None, None
        followup = None
        followup_status = None
        try:
            if not state.get("in_game"):
                if finished:
                    break
                if RESUME_CURRENT:
                    command, reason = "WAIT 5", "wait for manual continue"
                elif "start" in available and not started:
                    if START_DELAY:
                        time.sleep(START_DELAY)
                    command, reason, started = f"START IRONCLAD 0 {SEED_TOKEN}", "fixed-seed start", True
            elif STOP_AFTER_FIRST_BATTLE and entered_combat and screen in {"COMBAT_REWARD", "GAME_OVER"}:
                log({"status": "battle_complete", "policy": POLICY, "seed": SEED,
                     "floor": game_state.get("floor"), "combat_actions": combat_actions})
                return 0
            elif screen == "GAME_OVER":
                log({"status": "complete", "policy": POLICY, "seed": SEED,
                     "floor": game_state.get("floor"),
                     "victory": (game_state.get("screen_state") or {}).get("victory"),
                     "decisions": decisions})
                return 0
            elif STOP_AT_ACT_CLEAR and screen == "BOSS_REWARD" and game_state.get("act") == STOP_AT_ACT_CLEAR:
                log({"status": "capture_complete", "policy": POLICY, "seed": SEED,
                     "result": f"act{STOP_AT_ACT_CLEAR}_cleared", "floor": game_state.get("floor"),
                     "decisions": decisions})
                return 0
            elif screen == "EVENT" and choices == ["对话"]:
                command, reason = "CHOOSE 0", "open Neow dialogue"
            elif (screen == "EVENT" and game_state.get("floor") == 0 and NEOW_INDEX >= 0
                  and choices != ["离开"]):
                command, reason = f"CHOOSE {NEOW_INDEX}", f"fixed shared Neow option {NEOW_INDEX}"
            elif screen == "EVENT" and any("最大生命值" in choice for choice in choices):
                index = next(i for i, choice in enumerate(choices) if "最大生命值" in choice)
                command, reason = f"CHOOSE {index}", "fixed +8 max HP setup"
            elif screen == "EVENT" and choices == ["离开"] and not left_neow:
                command, reason, left_neow = "CHOOSE 0", "leave Neow", True
            elif screen == "MAP" and choices == ["boss"] and "choose" in available:
                command, reason = "CHOOSE 0", "mandatory boss path"
            elif screen == "HAND_SELECT":
                command = planned_select_command(state, pending_mcts_selects)
                reason = "MCTS planned hand selection"
            elif screen == "GRID" and combat:
                command = planned_select_command(state, pending_mcts_selects)
                reason = "MCTS planned grid selection"
            elif is_combat_command_state(combat, available):
                entered_combat = True
                if COMBAT_POLICY == "mcts":
                    turn = combat.get("turn")
                    if turn != combat_turn:
                        combat_turn = turn
                        combat_counters = {"cards": 0, "attacks": 0, "skills": 0}
                    try:
                        combat_search = mcts_recommend(
                            game_state, MCTS_SIMULATIONS, MCTS_DETERMINIZATIONS, combat_counters)
                        command = combat_search["command"]
                        pending_mcts_selects = []
                        for followup_action in combat_search.get("followups") or []:
                            if followup_action["action_type"] == int(sts.SearchActionType.SINGLE_CARD_SELECT):
                                pending_mcts_selects.append(followup_action["select_idx"])
                            else:
                                pending_mcts_selects.extend(followup_action["selected_idxs"])
                        reason = f"real Steam snapshot MCTS@{MCTS_SIMULATIONS}"
                    except Exception as exc:
                        if MCTS_UNSUPPORTED != "broll": raise
                        command = broll_battle_command(combat)
                        reason = "MCTS mapping collection fallback; not performance evidence"
                        mcts_fallback = str(exc)
                    if command.startswith("PLAY "):
                        card_index = int(command.split()[1]) - 1
                        card_type = (combat.get("hand") or [])[card_index].get("type")
                        combat_counters["cards"] += 1
                        if card_type == "ATTACK": combat_counters["attacks"] += 1
                        if card_type == "SKILL": combat_counters["skills"] += 1
                    combat_actions += 1
                else:
                    command = broll_battle_command(combat)
                    reason = "shared combat B-roll heuristic; ArmG never trained combat"
            elif screen == "COMBAT_REWARD" and "choose" in available:
                command, reason = combat_reward_command(game_state, available)
            elif screen in {"MAP", "CARD_REWARD", "REST", "EVENT", "SHOP_SCREEN"}:
                kind, labels, descriptors, commands, warnings = build_live_choices(game_state, available)
                if not descriptors:
                    command, reason = empty_screen_command(screen, available)
                else:
                    scores, probabilities, selected, latency_ms = policy.choose(game_state, descriptors)
                    command, reason = commands[selected], f"{POLICY} {kind} decision"
                    decision = packed_decision(POLICY, kind, labels, scores, probabilities,
                                               selected, latency_ms,
                                               warnings + policy.observation_warnings)
                    followup = shop_transport_followup(kind, labels[selected])
                    if followup:
                        followup_status = "shop_transport_followup"
                    else:
                        followup = event_transport_followup(kind, game_state)
                        if followup:
                            followup_status = "event_transport_followup"
                    decisions += 1
            elif screen == "SHOP_ROOM":
                command, reason = shop_room_command(
                    game_state.get("floor"), available, entered_shop_floors)
            elif screen == "GRID":
                command, grid_waiting, grid_expected_selected = grid_followup_command(
                    state, grid_waiting, grid_expected_selected)
                reason = "fixed grid follow-up; ArmG did not train per-card grid selection"
            elif screen == "BOSS_REWARD" and "choose" in available:
                command, reason = boss_reward_command(game_state)
            elif screen == "CHEST" and "choose" in available:
                command, reason = "CHOOSE 0", "fixed chest plumbing"
            elif "proceed" in available:
                command, reason = "PROCEED", "advance"
            elif "confirm" in available:
                command, reason = "CONFIRM", "confirm"
            elif "key" in available:
                command, reason = "KEY Confirm", "dismiss popup"

            record = {"status": "command", "policy": POLICY, "command": command,
                      "reason": reason, "floor": game_state.get("floor"),
                      "act": game_state.get("act"), "screen": screen,
                      "steam_seed": game_state.get("seed"), "requested_seed": SEED,
                      "requested_seed_token": SEED_TOKEN,
                      "hp": game_state.get("current_hp"), "gold": game_state.get("gold"),
                      "choices": choices, "available": sorted(available)}
            if decision:
                record["decision"] = decision
            if combat_search:
                record["combat_search"] = {key: value for key, value in combat_search.items()
                                           if key != "snapshot"}
                if LOG_MCTS_SNAPSHOT:
                    record["mcts_snapshot"] = combat_search["snapshot"]
            if mcts_fallback:
                record["mcts_fallback"] = mcts_fallback
            if combat:
                player = combat.get("player") or {}
                record["combat_context"] = {
                    "turn": combat.get("turn"), "energy": player.get("energy"),
                    "block": player.get("block"),
                    "hand": [card.get("name") for card in combat.get("hand") or []],
                    "monsters": [{"name": monster.get("name"), "hp": monster.get("current_hp"),
                                  "intent": monster.get("intent")}
                                 for monster in combat.get("monsters") or []
                                 if not monster.get("is_gone")],
                }
            log(record)
            time.sleep(DELAY)
            emit(command)
            if followup:
                time.sleep(1)
                log({"status": followup_status, "policy": POLICY,
                     "floor": game_state.get("floor"), "after": command,
                     "command": followup})
                emit(followup)
            if MAX_DECISIONS and decisions >= MAX_DECISIONS:
                log({"status": "stopped", "reason": "max decisions", "decisions": decisions})
                return 0
            if MAX_MCTS_ACTIONS and combat_actions >= MAX_MCTS_ACTIONS:
                log({"status": "stopped", "reason": "max MCTS actions",
                     "combat_actions": combat_actions})
                return 0
        except Exception as exc:
            log({"status": "diverged", "policy": POLICY, "error": str(exc),
                 "floor": game_state.get("floor"), "screen": screen, "choices": choices})
            emit("WAIT 100")
            return 2
    return 0


def self_test():
    model = LivePolicy("learned", 24242)
    model.shadow.screen_state = sts.ScreenState.MAP_SCREEN
    model.shadow.cur_map_node_y = -1
    _, descriptors, _ = AG.build_choices(model.shadow)
    _, probabilities, selected, _ = model.choose({}, descriptors)
    expected = [0.479, 0.136, 0.385]
    assert selected == 0
    assert all(abs(actual - target) < 0.002 for actual, target in zip(probabilities, expected))
    observation = model.observation({"current_hp": 80, "max_hp": 80, "gold": 99,
                                     "floor": 0, "act_boss": "Slime Boss", "deck": [],
                                     "relics": [{"id": "Burning Blood"}]})
    assert observation[4] == 1.0
    assert observation[234 + int(sts.RelicId.BURNING_BLOOD)] == 1.0
    assert not model.observation_warnings

    synthetic_map = {"screen_type": "MAP", "choice_list": ["monster", "event"],
        "map": [{"x": 0, "y": 0, "symbol": "M", "children": [{"x": 0, "y": 1}]},
                {"x": 1, "y": 0, "symbol": "?", "children": [{"x": 1, "y": 1}]},
                {"x": 0, "y": 1, "symbol": "R", "children": []},
                {"x": 1, "y": 1, "symbol": "E", "children": []}],
        "screen_state": {"next_nodes": [{"x": 0, "y": 0, "symbol": "M"},
                                           {"x": 1, "y": 0, "symbol": "?"}]}}
    kind, labels, descriptors, commands, warnings = build_live_choices(synthetic_map, {"choose"})
    assert kind == "map" and len(labels) == len(descriptors) == len(commands) == 2 and not warnings
    assert descriptors[0][AG.OFF_MROOM + ROOM_SYMBOL_IDX["M"]] == 1.0
    assert descriptors[0][AG.OFF_MLA1 + ROOM_SYMBOL_IDX["R"]] == 1.0

    # Compact fixture from the first real Steam MAP state requested with seed 24242.
    # Steam reports its internal seed as 3175342; this topology intentionally differs
    # from the simulator's numeric-seed map used by the equivalence gate above.
    real_map = {"screen_type": "MAP", "choice_list": ["x=0", "x=2", "x=5"],
        "map": [
            {"x": 0, "y": 0, "symbol": "M", "children": [{"x": 1, "y": 1}]},
            {"x": 2, "y": 0, "symbol": "M", "children": [{"x": 3, "y": 1}]},
            {"x": 5, "y": 0, "symbol": "M", "children": [{"x": 6, "y": 1}]},
            {"x": 1, "y": 1, "symbol": "?", "children": [{"x": 0, "y": 2}, {"x": 1, "y": 2}, {"x": 2, "y": 2}]},
            {"x": 3, "y": 1, "symbol": "M", "children": [{"x": 2, "y": 2}]},
            {"x": 6, "y": 1, "symbol": "M", "children": [{"x": 5, "y": 2}]},
            {"x": 0, "y": 2, "symbol": "M", "children": []},
            {"x": 1, "y": 2, "symbol": "?", "children": []},
            {"x": 2, "y": 2, "symbol": "$", "children": []},
            {"x": 5, "y": 2, "symbol": "M", "children": []},
        ],
        "screen_state": {"next_nodes": [{"x": 0, "y": 0, "symbol": "M"},
                                         {"x": 2, "y": 0, "symbol": "M"},
                                         {"x": 5, "y": 0, "symbol": "M"}]}}
    _, _, descriptors, _, warnings = build_live_choices(real_map, {"choose", "return"})
    assert not warnings
    assert descriptors[0][AG.OFF_MLA1 + ROOM_SYMBOL_IDX["?"]] == 1.0
    assert descriptors[0][AG.OFF_MLA2 + ROOM_SYMBOL_IDX["M"]] == 1.0
    assert descriptors[0][AG.OFF_MLA2 + ROOM_SYMBOL_IDX["?"]] == 1.0
    assert descriptors[0][AG.OFF_MLA2 + ROOM_SYMBOL_IDX["$"]] == 1.0
    starter_deck = ([{"id": "Strike_R"}] * 5 + [{"id": "Defend_R"}] * 4
                    + [{"id": "Bash"}])
    real_state = {"current_hp": 88, "max_hp": 88, "gold": 99, "floor": 0,
                  "act_boss": "The Guardian", "deck": starter_deck,
                  "relics": [{"id": "Burning Blood"}]}
    _, real_probabilities, real_selected, _ = model.choose(real_state, descriptors)
    assert real_selected == 1
    assert all(abs(actual - target) < 0.002 for actual, target in
               zip(real_probabilities, [0.1386, 0.8182, 0.0431]))

    rest = {"screen_type": "REST", "choice_list": ["rest", "smith", "recall"]}
    _, _, descriptors, _, _ = build_live_choices(rest, {"choose"})
    assert [d[AG.OFF_REST:AG.OFF_REST + AG.W_REST].index(1.0) for d in descriptors] == [0, 1, 2]

    event = {"screen_type": "EVENT", "choice_list": ["eat", "leave"],
             "screen_state": {"event_id": "Big Fish"}}
    _, _, descriptors, _, warnings = build_live_choices(event, {"choose"})
    assert descriptors[0][AG.OFF_EVID + EVENT_INDEX[normalize("Big Fish")]] == 1.0 and not warnings

    shop = {"screen_type": "SHOP_SCREEN", "choice_list": ["purge", "愤怒", "锚"],
            "screen_state": {"purge_cost": 75,
                             "cards": [{"id": "Anger", "name": "愤怒", "price": 50}],
                             "relics": [{"name": "锚", "price": 150}], "potions": []}}
    kind, labels, descriptors, commands, warnings = build_live_choices(shop, {"choose", "leave"})
    assert kind == "shop" and len(labels) == len(commands) == 4 and commands[-1] == "LEAVE"
    assert not warnings and descriptors[1][AG.OFF_CARD + AG.card_idx("Anger")] == 1.0

    baseline = LivePolicy("random", 24242)
    _, probabilities, selected, _ = baseline.choose({}, descriptors)
    assert probabilities == [0.25] * 4 and 0 <= selected < 4
    entered = set()
    assert shop_room_command(3, {"choose", "proceed"}, entered) == ("CHOOSE 0", "enter shop once")
    assert shop_room_command(3, {"choose", "proceed"}, entered) == ("PROCEED", "leave visited shop room")
    assert empty_screen_command("REST", {"proceed", "wait"}) == ("PROCEED", "advance after empty rest")
    assert empty_screen_command("SHOP_SCREEN", {"leave", "wait"}) == ("LEAVE", "leave empty shop")
    assert fixed_hand_select_command({"available_commands": ["choose"]}) == "CHOOSE 0"
    assert fixed_hand_select_command({"available_commands": ["confirm"]}) == "CONFIRM"
    grid_state = {"available_commands": ["choose"],
                  "game_state": {"screen_state": {"selected_cards": []}}}
    assert grid_followup_command(grid_state, False, 0) == ("CHOOSE 0", True, 1)
    assert grid_followup_command(grid_state, True, 1) == ("WAIT 60", True, 1)
    grid_state["game_state"]["screen_state"]["selected_cards"] = [{"id": "Strike_R"}]
    assert grid_followup_command(grid_state, True, 1) == ("CHOOSE 0", True, 2)
    full_potions = {"screen_state": {"rewards": [{"reward_type": "POTION"}]},
                    "potions": [{"id": "Weak Potion"}] * 3}
    assert combat_reward_command(full_potions, {"choose", "proceed"}) == (
        "PROCEED", "skip unsupported or full-slot rewards")
    open_potions = {"screen_state": {"rewards": [{"reward_type": "POTION"}]},
                    "potions": [{"id": "Potion Slot"}]}
    assert combat_reward_command(open_potions, {"choose", "proceed"}) == (
        "CHOOSE 0", "collect potion reward")
    assert is_combat_command_state({"turn": 2}, {"play", "end", "state"})
    assert not is_combat_command_state({"turn": 2}, {"choose", "skip", "state"})
    assert shop_transport_followup("shop", "购买 耸肩无视 · 48 金") == "STATE"
    assert shop_transport_followup("shop", "删牌服务 · 75 金") is None
    assert event_transport_followup("event", {"screen_state": {"event_id": "Ghosts"}}) == "CHOOSE 0"
    assert event_transport_followup("event", {"screen_state": {"event_id": "Cursed Tome"}}) == "CHOOSE 0"
    assert event_transport_followup("event", {"screen_state": {"event_id": "Big Fish"}}) is None
    boss_rewards = {"screen_state": {"relics": [
        {"id": "Astrolabe"}, {"id": "Empty Cage"}, {"id": "Calling Bell"}]}}
    assert boss_reward_command(boss_rewards) == ("CHOOSE 0", "simulator boss relic policy: Astrolabe")
    print("SELF_TEST_OK", {"simulator_gate": [round(value, 3) for value in expected],
                           "real_steam_fixture": [round(value, 3) for value in real_probabilities]})


def benchmark(iterations=1000):
    model = LivePolicy("learned", 24242)
    model.shadow.screen_state = sts.ScreenState.MAP_SCREEN
    model.shadow.cur_map_node_y = -1
    _, descriptors, _ = AG.build_choices(model.shadow)
    for _ in range(100):
        model.choose({}, descriptors)
    samples = []
    for _ in range(iterations):
        started = time.perf_counter()
        model.choose({}, descriptors)
        samples.append((time.perf_counter() - started) * 1000)
    mean_ms = statistics.mean(samples)
    p95_ms = statistics.quantiles(samples, n=100)[94]
    print(json.dumps({"iterations": iterations, "candidates": len(descriptors),
                      "mean_latency_ms": round(mean_ms, 4),
                      "median_latency_ms": round(statistics.median(samples), 4),
                      "p95_latency_ms": round(p95_ms, 4),
                      "decisions_per_second": round(1000 / mean_ms, 1)}, ensure_ascii=False))


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        self_test()
    elif "--benchmark" in sys.argv:
        benchmark()
    else:
        raise SystemExit(main())
