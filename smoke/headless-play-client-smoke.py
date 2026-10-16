#!/usr/bin/env python3
"""Self-contained terminal client contract smoke; does not launch STS2 or touch saves.

Run from the repository root: python3 smoke/headless-play-client-smoke.py
"""

from __future__ import annotations

from contextlib import contextmanager
import importlib.util
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import threading
import unittest
from unittest.mock import Mock, patch


CLIENT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "headless-play.py"
SPEC = importlib.util.spec_from_file_location("headless_play", CLIENT_PATH)
assert SPEC and SPEC.loader
play = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(play)


def choice_state():
    return {
        "revision": 7, "status": "ready", "screen": "selection", "title": "原生选择",
        "player": {"name": "铁甲战士", "enName": "Ironclad", "hp": 50, "maxHp": 80, "energy": 3, "gold": 99},
        "entities": [
            {"id": "e1", "kind": "enemy", "name": "怪物", "hp": 20, "maxHp": 30, "intent": "攻击 6", "statuses": [{"name": "易伤", "amount": 2}]},
            {"id": "d2", "kind": "card", "pile": "draw", "name": "防御", "enName": "Defend", "modelId": "DEFEND_IRONCLAD", "cost": 1},
            {"id": "d1", "kind": "card", "pile": "draw", "name": "打击", "enName": "Strike", "modelId": "STRIKE_IRONCLAD", "cost": 1},
        ],
        "choices": {"min": 1, "max": 2, "actionId": "choose", "cards": [
            {"id": "c1", "name": "打击", "enName": "Strike", "cost": 1},
            {"id": "c2", "name": "防御", "enName": "Defend", "cost": 1},
            {"id": "c3", "name": "痛击", "enName": "Bash", "cost": 2},
        ]},
        "actions": [{"id": "choose", "kind": "ResolveChoice", "label": "确认选择"}],
    }


@contextmanager
def fake_runner(initial=None, busy_once=False, conflict_after=None):
    memory = {"state": initial or choice_state(), "requests": [], "gets": 0, "busy_once": busy_once}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def reply(self, status, body):
            encoded = json.dumps(body, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def do_GET(self):
            memory["gets"] += 1
            if self.path != "/api/state":
                self.reply(404, {"error": "unknown path"})
                return
            if memory["busy_once"]:
                memory["busy_once"] = False
                self.reply(200, {"revision": 6, "status": "busy", "screen": "combat", "actions": []})
                return
            self.reply(200, memory["state"])

        def do_POST(self):
            payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            memory["requests"].append((self.path, payload))
            if self.path == "/api/new":
                memory["state"] = choice_state()
                self.reply(200, {"state": memory["state"]})
                return
            if self.path != "/api/action":
                self.reply(404, {"error": "unknown path"})
                return
            if conflict_after is not None and len(memory["requests"]) > conflict_after:
                memory["state"] = {"revision": 9, "status": "ready", "screen": "map", "actions": []}
                self.reply(409, {"error": "状态已变化"})
                return
            if payload.get("revision") != memory["state"]["revision"]:
                self.reply(409, {"error": "状态已变化"})
                return
            memory["state"] = {"revision": 8, "status": "ready", "screen": "combat", "actions": [{"id": "end", "kind": "EndTurn", "label": "结束回合"}]}
            self.reply(200, {"ok": True})

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", memory
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


class TerminalClientSmoke(unittest.TestCase):
    def test_busy_wait_requires_two_consecutive_matching_ready_polls(self):
        busy = {"revision": 1, "status": "busy"}
        snapshots = [
            {"revision": 2, "status": "ready"},
            {"revision": 3, "status": "ready"},
            {"revision": 3, "status": "busy"},
            {"revision": 3, "status": "ready"},
            {"revision": 3, "status": "ready"},
        ]
        client = Mock()
        client.state.side_effect = snapshots
        with patch.object(play.time, "sleep") as sleep:
            state = play.wait_ready(client, busy, play.Renderer(lambda _: None), 0.5, 120)
        self.assertIs(state, snapshots[-1])
        self.assertEqual(client.state.call_count, 5)
        self.assertEqual(sleep.call_args_list, [unittest.mock.call(0.5)] * 5)

    def test_ready_refresh_and_native_errors_do_not_wait(self):
        for state in ({"revision": 2, "status": "ready"}, {"status": "busy", "error": "native failure"}):
            with self.subTest(state=state), patch.object(play.time, "sleep") as sleep:
                client = Mock()
                result = play.wait_ready(client, state, play.Renderer(lambda _: None), 0.5, 120)
                self.assertIs(result, state)
                client.state.assert_not_called()
                sleep.assert_not_called()
        for error in ({"status": "error"}, {"status": "busy", "error": "native failure"}):
            with self.subTest(error=error), patch.object(play.time, "sleep") as sleep:
                client = Mock()
                client.state.return_value = error
                result = play.wait_ready(client, {"status": "busy"}, play.Renderer(lambda _: None), 0.5, 120)
                self.assertIs(result, error)
                client.state.assert_called_once()
                sleep.assert_called_once_with(0.5)

    def test_ready_stabilization_keeps_original_wait_deadline(self):
        client = Mock()
        client.state.side_effect = [{"revision": 2, "status": "ready"}, {"revision": 3, "status": "ready"}]
        output = []
        with patch.object(play.time, "sleep"), patch.object(play.time, "monotonic", side_effect=[0, 0, 119, 120]):
            state = play.wait_ready(client, {"status": "busy"}, play.Renderer(output.append), 0.5, 120)
        self.assertEqual(state["revision"], 3)
        self.assertEqual(client.state.call_count, 2)
        self.assertIn("等待了 120 秒", "\n".join(output))

    def test_transport_preserves_revision_and_native_ids(self):
        with fake_runner() as (url, memory):
            client = play.Client(url)
            state = client.state()
            response = client.action(state, state["actions"][0], ["c3", "c1"])
            self.assertIsNone(response)
            self.assertEqual(memory["requests"], [("/api/action", {"revision": 7, "actionId": "choose", "selectedIds": ["c3", "c1"]})])
            self.assertEqual(client.state()["revision"], 8)

    def test_interactive_menu_busy_multiselect_and_conflict(self):
        with fake_runner(busy_once=True, conflict_after=1) as (url, memory):
            args = play.arguments(["--url", url, "--poll-interval", "0.001"])
            inputs = iter(["h", "draw", "1 1,1", "1 1,3", "1", "q"])
            output = []
            result = play.interact(play.Client(url), args, play.Renderer(output.append), lambda _prompt: next(inputs))
            self.assertEqual(result, 0)
            self.assertEqual(len(memory["requests"]), 2, "invalid selection and stale action must not be replayed")
            self.assertEqual(memory["requests"][0][1]["selectedIds"], ["c1", "c3"])
            self.assertEqual(memory["requests"][1][1], {"revision": 8, "actionId": "end"})
            self.assertGreaterEqual(memory["gets"], 4)
            text = "\n".join(output)
            for fragment in ("正在结算", "抽牌堆", "不能重复选择", "状态已变化", "攻击 6", "易伤", "Ironclad"):
                self.assertIn(fragment, text)

    def test_new_run_request(self):
        with fake_runner() as (url, memory):
            args = play.arguments(["--url", url, "--new", "--character", "ironclad", "--ascension", "2", "--seed", "TEST123", "--language", "zhs"])
            output = []
            play.interact(play.Client(url), args, play.Renderer(output.append), lambda _: "q")
            self.assertEqual(memory["requests"], [("/api/new", {"character": "IRONCLAD", "ascension": 2, "seed": "TEST123", "language": "zhs"})])

    def test_new_does_not_replace_an_active_run(self):
        with fake_runner() as (url, memory):
            args = play.arguments(["--url", url])
            inputs = iter(["new", "q"])
            output = []
            play.interact(play.Client(url), args, play.Renderer(output.append), lambda _: next(inputs))
            self.assertEqual(memory["requests"], [])
            self.assertIn("停止并重启测试进程", "\n".join(output))

    def test_selection_bounds_zero_and_instance_identity(self):
        choices = choice_state()["choices"]
        self.assertEqual(play.parse_selection("C3，C1", choices), ["c3", "c1"])
        for invalid in ("1,1", "4", "0", "", "1,2,3", "bad"):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                play.parse_selection(invalid, choices)
        choices["min"] = 0
        self.assertEqual(play.parse_selection("-", choices), [])

    def test_native_map_shop_event_board_and_hidden_information(self):
        state = choice_state()
        state.update({
            "screen": "event", "description": "[b]占卜[/b]\n请选择一个格子。",
            "map": {"nodes": [{"id": "n1", "x": 0, "y": 0, "kind": "event", "label": "事件", "available": True}, {"id": "n2", "x": 1, "y": 1, "kind": "merchant", "label": "商店"}], "edges": [{"from": "n1", "to": "n2"}]},
            "board": {"width": 2, "height": 1, "remaining": 2, "tool": "small", "cells": [{"x": 0, "y": 0, "hidden": True, "label": "DO_NOT_REVEAL"}, {"x": 1, "y": 0, "hidden": False, "label": "金币"}]},
            "actions": [{"id": "click", "kind": "ClickCell", "label": "点击格子", "x": 0, "y": 0}, {"id": "travel", "kind": "Travel", "targetId": "n1", "label": "前往事件"}],
        })
        state["entities"].extend([
            {"id": "buy", "kind": "shopItem", "name": "木札", "enName": "Kifuda", "price": 120, "description": "选择卡牌附魔。"},
            {"id": "p", "kind": "potion", "name": "火焰药水", "enName": "Fire Potion"},
            {"id": "r", "kind": "relic", "name": "燃烧之血", "enName": "Burning Blood", "count": 0},
        ])
        output = []
        play.Renderer(output.append).state(state)
        text = "\n".join(output)
        self.assertNotIn("DO_NOT_REVEAL", text)
        self.assertNotIn("[b]", text)
        for fragment in ("M1→M2", "操作2", "#1", "金币", "120 金", "Kifuda", "Fire Potion", "Burning Blood", "计数 0"):
            self.assertIn(fragment, text)

    def test_pile_presentation_is_order_independent(self):
        state = choice_state()
        first, second = [], []
        play.Renderer(first.append).pile(state, "draw")
        state["entities"].reverse()
        play.Renderer(second.append).pile(state, "draw")
        self.assertEqual(first, second)

    def test_native_click_choices_shop_and_bundles(self):
        output = []
        renderer = play.Renderer(output.append)
        card = {"id": "c1", "name": "痛击", "enName": "Bash", "description": "造成伤害。", "cost": 2}
        renderer.native_choices([{"index": 0, "selected": True, "card": card}], "card_selection")
        renderer.native_choices([{"index": 0, "cards": [card]}], "card_bundle")
        renderer.native_choices([{"index": 0, "title": "痛击", "cost": 70, "affordable": False, "card": card}], "merchant")
        text = "\n".join(output)
        for fragment in ("[已选中]", "卡包 C1", "70 金", "[金币不足]", "Bash", "造成伤害", "费用 2"):
            self.assertIn(fragment, text)

    def test_candidate_entities_render_once_without_hiding_inventory(self):
        card = {"id": "candidate", "kind": "card", "modelId": "BASH", "name": "痛击", "description": "唯一候选说明"}
        variants = [
            {"cards": [card], "min": 1, "max": 1},
            [{"index": 0, "card": card}],
            [{"index": 0, "cards": [card]}],
            [card],
        ]
        for choices in variants:
            with self.subTest(choices=choices):
                state = {"status": "ready", "screen": "card_reward", "choices": choices, "entities": [
                    card,
                    {"id": "another-instance", "kind": "card", "modelId": "BASH", "name": "痛击", "description": "另一张同型号卡"},
                    {"id": "owned-potion", "kind": "potion", "name": "已有药水"},
                    {"id": "owned-relic", "kind": "relic", "name": "已有遗物"},
                ]}
                output = []
                play.Renderer(output.append).state(state)
                text = "\n".join(output)
                self.assertEqual(text.count("唯一候选说明"), 1)
                for fragment in ("另一张同型号卡", "已有药水", "已有遗物"):
                    self.assertIn(fragment, text)

    def test_terminal_control_sequences_are_removed(self):
        self.assertEqual(play.clean("\x1b[2J[b]卡牌[/b]\x07"), "卡牌")

    def test_x_and_star_costs(self):
        output = []
        play.Renderer(output.append).entity({"name": "X费用牌", "cost": -1, "starCost": 2})
        text = "\n".join(output)
        self.assertIn("费用 X", text)
        self.assertIn("星星 2", text)
        self.assertNotIn("费用 -1", text)
        output.clear()
        play.Renderer(output.append).pile({"piles": {"draw": [
            {"id": "one", "name": "同名牌", "cost": 1, "starCost": 1},
            {"id": "two", "name": "同名牌", "cost": 1, "starCost": 2},
        ]}}, "draw")
        text = "\n".join(output)
        self.assertIn("星星 1", text)
        self.assertIn("星星 2", text)
        self.assertNotIn("2 × 同名牌", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
