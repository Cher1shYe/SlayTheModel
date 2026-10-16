#!/usr/bin/env python3
"""Drive one native terminal-host run and preserve every public decision.

This is a reproducible gameplay trace for probe comparison, not training JSONL.
It reads only /api/state and submits listed legal actions through /api/action.
"""

import argparse
import importlib.util
import json
import re
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("headless_play", ROOT / "scripts/headless-play.py")
client_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(client_module)


def pick(state):
    actions = [action for action in state.get("actions", []) if not action.get("disabled")]
    if not actions:
        return None
    by_kind = lambda kind: [action for action in actions if action.get("kind") == kind]
    label = lambda action: (str(action.get("label") or "") + " " + str(action.get("enLabel") or "")).lower()
    title = str(state.get("title") or "").lower()
    screen = str(state.get("screen") or "").lower()
    player = state.get("player") or {}
    if screen != "combat" and all(action.get("kind") == "potion" for action in actions):
        # The rest/reward animation briefly exposes only the potion menu.
        return None

    if "neow" in str(state.get("surfaceModelId") or "").lower():
        return next((action for action in actions if "scroll boxes" in label(action)), actions[0])
    if by_kind("map"):
        hp = player.get("hp") or 0
        max_hp = player.get("maxHp") or 1
        priorities = (("rest", "休息"), ("treasure", "宝箱"), ("shop", "商店"),
                      ("unknown", "未知"), ("monster", "普通战斗"), ("elite", "精英"), ("boss", "首领"))
        if hp > max_hp * .75:
            priorities = (("treasure", "宝箱"), ("shop", "商店"), ("unknown", "未知"),
                          ("monster", "普通战斗"), ("rest", "休息"), ("elite", "精英"), ("boss", "首领"))
        for words in priorities:
            match = next((action for action in by_kind("map") if any(word in label(action) for word in words)), None)
            if match:
                return match
        return by_kind("map")[0]
    if screen == "combat" and by_kind("potion") and ((player.get("hp") or 0) <= 30 or
                              any("boss" in str(item.get("modelId") or "").lower()
                                  for item in state.get("entities", []) if isinstance(item, dict))):
        return by_kind("potion")[0]
    if by_kind("usePotion"):
        return by_kind("usePotion")[0]
    if by_kind("play") or by_kind("endTurn"):
        enemies = {item.get("id"): item for item in state.get("entities", [])
                   if isinstance(item, dict) and item.get("kind") == "enemy"}
        cards = {item.get("id"): item for item in state.get("entities", [])
                 if isinstance(item, dict) and item.get("kind") == "card"}
        def score(action):
            card = cards.get(action.get("entityId"), {})
            name = str(card.get("enName") or action.get("enLabel") or action.get("label") or "").lower()
            desc = str(card.get("description") or "").lower()
            enemy = enemies.get(action.get("targetId"), {})
            enemy_hp = enemy.get("hp") or 999
            block = enemy.get("block") or 0
            damage = max((int(x) for x in re.findall(r"deal (\d+) damage", desc)), default=0)
            block_gain = max((int(x) for x in re.findall(r"gain (\d+) block", desc)), default=0)
            # Spend energy on attacks first, but value draw, vulnerable and block.
            value = damage * .9 + block_gain * .55
            if damage and damage >= enemy_hp + block:
                value += 14
            if "vulnerable" in desc:
                value += 8
            if "draw" in desc:
                value += 6
            if "strength" in desc or "demon form" in name:
                value += 7
            if "anger" in name:
                value += 3
            if "strike" in name:
                value -= 1
            return (value, -enemy_hp, name)
        plays = by_kind("play")
        if plays:
            return max(plays, key=score)
        return by_kind("endTurn")[0]
    if "selection" in screen:
        selected = sum(bool(choice.get("selected")) for choice in state.get("choices", [])
                       if isinstance(choice, dict))
        minimum = 1
        match = re.search(r"(?:选择数量|select)\D*(\d+)", str(state.get("description") or ""), re.I)
        if match:
            minimum = int(match.group(1))
        if selected >= minimum:
            confirm = next((action for action in actions if re.search("confirm|continue|确认|继续", label(action))), None)
            if confirm:
                return confirm
        select = next((action for action in actions if action.get("kind") in ("selectCard", "select_card")
                       and not re.search("deselect|取消选择", label(action))), None)
        if select:
            return select
    for kind in ("choose_bundle", "choose_card", "choose_relic", "choose_reward_card", "take_relic", "reward_card"):
        if by_kind(kind):
            return by_kind(kind)[0]
    if by_kind("reward"):
        return by_kind("reward")[0]
    if "merchant" in screen or "merchant" in title:
        buy = [action for action in actions if action.get("kind") == "buy"]
        if buy and (player.get("gold") or 0) >= 100:
            return buy[0]
    if by_kind("reveal_cell"):
        return by_kind("reveal_cell")[0]
    for word in ("use", "使用", "heal", "rest", "continue", "继续", "confirm", "确认",
                 "take", "拿取", "claim", "领取", "open", "打开", "leave", "离开",
                 "skip", "跳过", "proceed"):
        match = next((action for action in actions if word in label(action)), None)
        if match:
            return match
    return actions[0]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:18777")
    parser.add_argument("--output", default=str(ROOT / "artifacts/headless/agent-run-trace.jsonl"))
    parser.add_argument("--max-actions", type=int, default=400)
    parser.add_argument("--max-seconds", type=int, default=1800)
    parser.add_argument("--append", action="store_true")
    args = parser.parse_args()
    client = client_module.Client(args.url)
    path = Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    start = time.monotonic()
    count = 0
    previous = None
    repeat = 0
    with path.open("a" if args.append else "w", encoding="utf-8") as output:
        def record(entry):
            output.write(json.dumps(entry, ensure_ascii=False, separators=(",", ":")) + "\n")
            output.flush()
        while count < args.max_actions and time.monotonic() - start < args.max_seconds:
            state = client.state()
            if state.get("status") == "finished" or str(state.get("screen") or "").lower() in ("victory", "defeat"):
                record({"type": "terminal", "state": state})
                print("TERMINAL", state.get("screen"), state.get("player"), flush=True)
                return
            if state.get("error") or state.get("status") == "error":
                record({"type": "error", "state": state})
                raise RuntimeError(state.get("error") or "Native host error")
            if client_module.is_busy(state) or not state.get("actions"):
                time.sleep(.3)
                continue
            # One more stable revision avoids acting on stale room UI during map transitions.
            time.sleep(.3)
            fresh = client.state()
            if fresh.get("revision") != state.get("revision"):
                continue
            state = fresh
            action = pick(state)
            if action is None:
                time.sleep(.3)
                continue
            signature = (state.get("screen"), state.get("title"), (state.get("player") or {}).get("floor"),
                         action.get("kind"), action.get("label"))
            repeat = repeat + 1 if signature == previous else 0
            if repeat >= 5:
                record({"type": "error", "reason": "repeated action", "state": state, "action": action})
                raise RuntimeError("Repeated the same action without visible progress")
            entry = {"type": "decision", "index": count, "state": state, "action": action}
            try:
                client.action(state, action)
            except client_module.ApiError as exc:
                record({"type": "action_error", **entry, "error": str(exc)})
                if exc.status == 409:
                    time.sleep(.3)
                    continue
                raise
            record(entry)
            player = state.get("player") or {}
            print(f"{count:03d} F{player.get('floor')} HP{player.get('hp')} {state.get('screen')} "
                  f"{action.get('kind')} {action.get('label')}", flush=True)
            count += 1
            previous = signature
            time.sleep(2.5 if action.get("kind") == "map" else .4)
        record({"type": "limit", "actions": count, "state": client.state()})
    print("LIMIT", count, path, flush=True)


if __name__ == "__main__":
    main()
