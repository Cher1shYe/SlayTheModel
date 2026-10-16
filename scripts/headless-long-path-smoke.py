#!/usr/bin/env python3
"""Drive a visible native run through the terminal host for a long-path smoke test.

This is a deliberately simple public-state policy, not a game-playing agent.
Start a fresh host before using --new; the native host does not replace a live run.
"""

import argparse
import importlib.util
import json
import re
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("headless_play", ROOT / "scripts/headless-play.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def choose(state):
    actions = [a for a in state.get("actions", []) if not a.get("disabled")]
    screen = state.get("screen", "")
    if not actions:
        return None
    by_kind = lambda kind: [a for a in actions if a.get("kind") == kind]
    label = lambda a: str(a.get("label", "")) + " " + str(a.get("enLabel", ""))

    if screen == "map":
        order = ("休息", "宝箱", "商店", "未知", "普通", "古代", "精英", "首领")
        for word in order:
            match = next((a for a in by_kind("map") if word in label(a)), None)
            if match:
                return match
    if screen == "combat":
        plays = by_kind("play")
        if plays:
            # Prefer damage on the lowest-HP enemy, then block. These are public observations.
            enemies = {e.get("id"): e for e in state.get("entities", [])
                       if isinstance(e, dict) and e.get("kind") == "enemy"}
            def score(a):
                text = label(a).lower()
                target = enemies.get(a.get("targetId"), {})
                priority = 10 if any(s in text for s in ("猛击", "bash", "打击", "strike", "重击", "bludgeon")) else 0
                priority += 5 if any(s in text for s in ("防御", "defend", "耸肩", "shrug")) else 0
                hp = target.get("hp")
                return (priority, -(hp if isinstance(hp, int) else 999), text)
            return max(plays, key=score)
        return next((a for a in actions if a.get("kind") == "endTurn"), None)
    if screen in ("handSelection", "card_selection"):
        selected = sum(bool(c.get("selected")) for c in state.get("choices", []) if isinstance(c, dict))
        minimum = 1
        match = re.search(r"选择数量：(\d+)", str(state.get("description", "")))
        if match:
            minimum = int(match.group(1))
        if selected >= minimum:
            confirms = [a for a in actions if a.get("kind") in ("confirm", "native_button", "button")
                        and re.search("确认|confirm|继续", label(a), re.I)]
            if confirms:
                return confirms[0]
        return next((a for a in actions if a.get("kind") in ("selectCard", "select_card")
                     and not label(a).startswith("取消选择")), None)
    for kind in ("choose_bundle", "choose_card", "choose_relic", "choose_reward_card", "take_relic", "reward_card"):
        candidates = by_kind(kind)
        if candidates:
            return candidates[0]
    if screen == "merchant":
        nonbuy = [a for a in actions if a.get("kind") != "buy"]
        actions = nonbuy or actions
    if screen == "crystal_sphere":
        reveals = by_kind("reveal_cell")
        if reveals:
            return reveals[0]
    for word in ("继续", "确认", "拿取", "领取", "打开", "离开", "跳过", "返回"):
        found = next((a for a in actions if word in label(a)), None)
        if found:
            return found
    for kind in ("event", "reward", "button", "native_button"):
        candidates = by_kind(kind)
        if candidates:
            return candidates[0]
    return actions[0]


def public_summary(state):
    p = state.get("player") or {}
    return {"revision": state.get("revision"), "status": state.get("status"),
            "screen": state.get("screen"), "title": state.get("title"),
            "floor": p.get("floor"), "act": p.get("act"), "hp": p.get("hp"),
            "maxHp": p.get("maxHp"), "gold": p.get("gold")}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:18777")
    parser.add_argument("--output", default=str(ROOT / "artifacts/headless/long-path-trace.jsonl"))
    parser.add_argument("--max-actions", type=int, default=350)
    parser.add_argument("--max-seconds", type=int, default=900)
    parser.add_argument("--new", action="store_true")
    parser.add_argument("--append", action="store_true")
    parser.add_argument("--seed", default="STM-WHOLE-RUN-SPEED-1")
    args = parser.parse_args()
    client = module.Client(args.url)
    if args.new:
        client.new("IRONCLAD", 0, args.seed, "zhs")
    start = time.monotonic()
    previous = None
    repeat = 0
    count = 0
    last_revision = None
    stable_samples = 0
    last_progress = start
    target = Path(args.output)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a" if args.append else "w", encoding="utf-8") as out:
        def record(kind, payload):
            entry = {"type": kind, "elapsed": round(time.monotonic()-start, 2), **payload}
            out.write(json.dumps(entry, ensure_ascii=False) + "\n")
            out.flush()
            if kind != "wait":
                print(json.dumps(entry, ensure_ascii=False), flush=True)

        last_state = None
        while count < args.max_actions and time.monotonic()-start < args.max_seconds:
            try:
                state = client.state()
            except module.ApiError as error:
                record("error", {"error": str(error)})
                break
            last_state = state
            summary = public_summary(state)
            if state.get("status") == "error" or state.get("error"):
                record("error", {**summary, "error": state.get("error"), "state": state})
                break
            if state.get("status") == "finished" or state.get("screen") in ("victory", "defeat"):
                record("terminal", summary)
                break
            revision = state.get("revision")
            stable_samples = stable_samples + 1 if revision == last_revision else 0
            last_revision = revision
            if module.is_busy(state) or not state.get("actions") or stable_samples < 1:
                if time.monotonic() - last_progress > 60:
                    record("error", {**summary, "error": "no usable decision for 60 seconds", "state": state})
                    break
                if time.monotonic()-start > 30 and count == 0:
                    record("wait", summary)
                time.sleep(.35)
                continue
            action = choose(state)
            if not action:
                record("error", {**summary, "error": "no selectable action", "actions": state.get("actions")})
                break
            signature = (state.get("screen"), state.get("title"), state.get("description"),
                         summary["floor"], summary["hp"], action.get("kind"), action.get("label"))
            pending_repeat = repeat + 1 if signature == previous else 0
            if pending_repeat >= 4:
                record("error", {**summary, "error": "same action repeated without visible progress",
                                 "action": action, "actions": state.get("actions"), "choices": state.get("choices")})
                break
            record("action", {"index": count, **summary, "action": action})
            try:
                client.action(state, action)
            except module.ApiError as error:
                record("action_error", {"index": count, **summary, "error": str(error), "action": action})
                if error.status == 409:
                    time.sleep(.25)
                    continue
                break
            repeat = pending_repeat
            previous = signature
            count += 1
            last_progress = time.monotonic()
            last_revision = None
            stable_samples = 0
            time.sleep(2.5 if action.get("kind") == "map" else .35)
        else:
            record("limit", {"actions": count, "seconds": round(time.monotonic()-start, 2),
                             "state": public_summary(last_state or {})})
    print(f"TRACE={target}", flush=True)


if __name__ == "__main__":
    main()
