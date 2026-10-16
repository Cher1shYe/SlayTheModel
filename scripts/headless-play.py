#!/usr/bin/env python3
"""Play the local native STS2 runner from a terminal (Python standard library only)."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
import os
import re
import sys
import time
import unicodedata
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


BUSY_STATUSES = {"busy", "starting", "processing", "loading", "resolving", "executing"}
PILE_LABELS = {"deck": "完整牌组", "draw": "抽牌堆", "discard": "弃牌堆", "exhaust": "消耗堆"}
SCREEN_LABELS = {
    "combat": "战斗", "map": "地图", "event": "事件", "merchant": "商店",
    "shop": "商店", "restsite": "休息点", "rest": "休息点", "rewards": "奖励",
    "reward": "奖励", "cardreward": "卡牌奖励", "treasure": "宝箱",
    "selection": "选择", "choice": "选择", "cardselection": "选牌", "handselection": "手牌选择",
    "cardbundle": "卡包选择", "relicselection": "遗物选择", "target": "选择目标", "crystalsphere": "占卜 · 水晶球",
    "victory": "胜利", "defeat": "败北", "menu": "准备", "idle": "准备",
}
CHARACTER_NAMES = {
    "IRONCLAD": "铁甲战士 · Ironclad", "SILENT": "静默猎手 · Silent",
    "REGENT": "储君 · Regent", "NECROBINDER": "亡灵契约师 · Necrobinder",
    "DEFECT": "故障机器人 · Defect",
}
BB_TAG = re.compile(r"\[/?(?:b|i|u|s|center|left|right|fill|color|font|font_size|outline_size|outline_color|url|wave|shake|rainbow|fade|pulse|img|jitter|fly_in|fly_out|hint|indent|p|table|cell|ul|ol|li)(?:[= ][^\]]*)?\]", re.I)
ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


def clean(value: Any) -> str:
    """Render native text as terminal text; do not execute control sequences."""
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        value = json.dumps(value, ensure_ascii=False)
    text = ANSI.sub("", str(value)).replace("[br]", "\n")
    text = BB_TAG.sub("", text)
    return "".join(char for char in text if char in "\n\t" or unicodedata.category(char) not in {"Cc", "Cf"}).strip()


def as_list(value: Any) -> list:
    return value if isinstance(value, list) else []


def key(value: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value or "").lower())


def number(value: Any, default: str = "—") -> str:
    return default if value is None else clean(value)


def width(text: str) -> int:
    return sum(0 if unicodedata.combining(c) else (2 if unicodedata.east_asian_width(c) in {"W", "F"} else 1) for c in text)


def pad(text: str, length: int) -> str:
    return text + " " * max(0, length - width(text))


def name(entity: dict) -> str:
    title = clean(entity.get("name") or entity.get("title") or entity.get("label") or entity.get("enName") or entity.get("modelId") or entity.get("id") or "未命名")
    english = clean(entity.get("enName"))
    model_id = clean(entity.get("modelId"))
    if english and english != title:
        title += f" · {english}"
    if model_id and model_id not in {clean(entity.get("name")), english}:
        title += f" [{model_id}]"
    return title


def status_text(statuses: Any) -> str:
    parts = []
    for status in as_list(statuses):
        if isinstance(status, dict):
            amount = status.get("amount", status.get("count", status.get("stacks")))
            parts.append(name(status) + (f" ×{number(amount)}" if amount is not None else ""))
        else:
            parts.append(clean(status))
    return " / ".join(parts)


def is_busy(state: dict) -> bool:
    return key(state.get("status")) in BUSY_STATUSES or state.get("busy") is True


def unwrap_state(data: Any) -> dict | None:
    if not isinstance(data, dict):
        return None
    if isinstance(data.get("state"), dict):
        return data["state"]
    if "revision" in data or "screen" in data or "actions" in data:
        return data
    return None


class ApiError(RuntimeError):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


class Client:
    def __init__(self, base_url: str, timeout: float = 30):
        parsed = urlparse(base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("--url 必须是完整的 http:// 或 https:// 地址。")
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def request(self, method: str, path: str, payload: dict | None = None) -> Any:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
        request = Request(self.base_url + path, data=body, method=method,
                          headers={"Accept": "application/json", "Content-Type": "application/json; charset=utf-8"})
        try:
            with urlopen(request, timeout=self.timeout) as response:
                raw = response.read()
        except HTTPError as exc:
            try:
                detail = exc.read().decode("utf-8", errors="replace")
            finally:
                exc.close()
            try:
                detail_data = json.loads(detail)
                if isinstance(detail_data, dict):
                    detail = detail_data.get("error") or detail_data.get("message") or detail
            except ValueError:
                pass
            raise ApiError(f"HTTP {exc.code}: {clean(detail) or exc.reason}", exc.code) from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise ApiError(f"无法连接 {self.base_url}：{clean(getattr(exc, 'reason', exc))}") from exc
        if not raw:
            return None
        try:
            result = json.loads(raw)
        except (ValueError, UnicodeError) as exc:
            raise ApiError("运行器返回的内容不是有效 JSON。") from exc
        if isinstance(result, dict) and result.get("ok") is False:
            raise ApiError(clean(result.get("error") or result.get("message") or "操作未成功。"))
        return result

    def state(self) -> dict:
        state = unwrap_state(self.request("GET", "/api/state"))
        if state is None:
            raise ApiError("/api/state 未返回有效状态。")
        return state

    def action(self, state: dict, action: dict, selected_ids: list | None = None) -> dict | None:
        if state.get("revision") is None:
            raise ApiError("当前状态缺少 revision，无法安全提交操作；请刷新。")
        if action.get("id") is None:
            raise ApiError("这个操作缺少 actionId，运行器需要补齐。")
        payload = {"revision": state["revision"], "actionId": action["id"]}
        if selected_ids is not None:
            payload["selectedIds"] = selected_ids
        return unwrap_state(self.request("POST", "/api/action", payload))

    def new(self, character: str, ascension: int, seed: str, language: str) -> dict | None:
        payload = {"character": character, "ascension": ascension, "seed": seed, "language": language}
        return unwrap_state(self.request("POST", "/api/new", payload))


class Renderer:
    def __init__(self, out: Callable[[str], None] = print, clear_screen: bool = False):
        self.out = out
        self.clear_screen = clear_screen

    def line(self, value: Any = "") -> None:
        self.out(clean(value))

    def section(self, title: str) -> None:
        self.line(f"\n── {title} ──")

    def description(self, value: Any, indent: str = "  ") -> None:
        for line in clean(value).splitlines():
            self.line(indent + line)

    def entity(self, item: dict, prefix: str = "", details: bool = True) -> None:
        cost = item.get("cost", item.get("energyCost"))
        cost_label = f"  费用 {'X' if cost == -1 else number(cost)}" if cost is not None else ""
        if item.get("starCost") is not None:
            star_cost = item["starCost"]
            cost_label += f"  星星 {'X' if star_cost == -1 else number(star_cost)}"
        if item.get("price") is not None:
            cost_label += f"  ◈ {number(item['price'])} 金"
        self.line(f"{prefix}{name(item)}{cost_label}")
        stats = []
        if item.get("hp") is not None:
            stats.append(f"生命 {number(item.get('hp'))}/{number(item.get('maxHp'))}")
        if item.get("block") is not None:
            stats.append(f"格挡 {number(item['block'])}")
        count = item.get("count", item.get("counter"))
        if count is not None:
            stats.append(f"计数 {number(count)}")
        if stats:
            self.line("  " + " | ".join(stats))
        intent = item.get("intent", item.get("intents"))
        if intent is not None:
            if isinstance(intent, list):
                intent = " / ".join(name(i) if isinstance(i, dict) else clean(i) for i in intent)
            elif isinstance(intent, dict):
                intent = name(intent) + (f" {intent['description']}" if intent.get("description") else "")
            self.line("  意图：" + clean(intent))
        statuses = status_text(item.get("statuses", item.get("powers")))
        if statuses:
            self.line("  状态：" + statuses)
        if details and item.get("description"):
            self.description(item["description"])

    def map(self, map_state: dict, actions: list[dict]) -> None:
        nodes = [n for n in as_list(map_state.get("nodes")) if isinstance(n, dict)]
        if not nodes:
            return
        self.section("地图  ● 已走过  ◉ 可前往  ○ 未到达")
        indexes = {str(node.get("id")): i + 1 for i, node in enumerate(nodes)}
        rows: dict[str, list] = defaultdict(list)
        for node in nodes:
            rows[str(node.get("y", "?"))].append(node)
        def sort_numeric(value: str) -> tuple:
            try:
                return (0, float(value))
            except ValueError:
                return (1, value)
        for row in sorted(rows, key=sort_numeric, reverse=True):
            cells = []
            for node in sorted(rows[row], key=lambda n: sort_numeric(str(n.get("x", 0)))):
                marker = "◉" if node.get("available") else "●" if node.get("visited") else "○"
                node_id = str(node.get("id"))
                label = clean(node.get("label") or node.get("kind") or "地点")
                matching = []
                for index, action in enumerate(actions, 1):
                    targets = {str(action.get(field)) for field in ("targetId", "entityId", "nodeId") if action.get(field) is not None}
                    same_xy = action.get("x") is not None and action.get("y") is not None and action["x"] == node.get("x") and action["y"] == node.get("y")
                    if node_id in targets or (same_xy and key(action.get("kind")) in {"map", "travel", "selectmapnode", "choosemapnode"}):
                        matching.append(str(index))
                action_hint = " → 操作" + "/".join(matching) if matching else ""
                cells.append(f"{marker} M{indexes[node_id]} {label}{action_hint}")
            self.line(f"  {row:>2} │ " + "    ".join(cells))
        edges = []
        for edge in as_list(map_state.get("edges")):
            if not isinstance(edge, dict):
                continue
            start, end = indexes.get(str(edge.get("from"))), indexes.get(str(edge.get("to")))
            if start is not None and end is not None:
                edges.append(f"M{start}→M{end}")
        if edges:
            self.line("  路线：" + "  ".join(edges))

    def board(self, board: dict, actions: list[dict]) -> None:
        self.section("水晶球棋盘")
        self.line(f"  剩余次数：{number(board.get('remaining'))}    工具：{number(board.get('tool'))}")
        cells = {(cell.get("x"), cell.get("y")): cell for cell in as_list(board.get("cells")) if isinstance(cell, dict)}
        try:
            board_width, board_height = int(board.get("width", 0)), int(board.get("height", 0))
        except (TypeError, ValueError):
            self.line("  棋盘尺寸无效；仍可使用下方原生操作列表。")
            return
        if not (0 < board_width <= 40 and 0 < board_height <= 40):
            self.line("  请使用下方格子操作列表。")
            return
        labels = {}
        for y in range(board_height):
            for x in range(board_width):
                cell = cells.get((x, y), {})
                # Never display a supplied hidden label, even if a future server accidentally includes it.
                label = "?" if cell.get("hidden", True) else clean(cell.get("label") or cell.get("revealedItem") or ("碎片" if cell.get("fragment") else "·"))
                matching = [str(i) for i, action in enumerate(actions, 1) if action.get("x") == x and action.get("y") == y]
                if matching:
                    label += " (#" + "/".join(matching) + ")"
                labels[x, y] = label.replace("\n", " ")
        cell_width = max(8, min(32, max(width(value) for value in labels.values()) + 2))
        self.line("      " + "".join(pad(str(x + 1), cell_width) for x in range(board_width)))
        for y in range(board_height):
            self.line(f"  {y + 1:>2}  " + "".join(pad(labels[x, y], cell_width) for x in range(board_width)))
        self.line("  ? = 尚未揭开；#数字 = 下方对应操作编号。")

    def native_choices(self, choices: list, screen: str) -> None:
        """Render the native click/toggle/confirm screens without inventing a set action."""
        if not choices:
            return
        merchant = key(screen) in {"merchant", "shop", "fakemerchant"}
        self.section("商店库存" if merchant else "原生选择候选")
        for fallback_index, choice in enumerate(choices, 1):
            if not isinstance(choice, dict):
                self.line(f"  C{fallback_index}. {clean(choice)}")
                continue
            chosen = " [已选中]" if choice.get("selected") else ""
            card = choice.get("card")
            cards = choice.get("cards")
            if merchant:
                affordable = " [金币不足]" if choice.get("affordable") is False else ""
                self.line(f"  商品 {fallback_index}. {name(choice)}  ◈ {number(choice.get('cost', choice.get('price')))} 金{affordable}")
                if isinstance(card, dict):
                    self.entity(card, "    ")
                elif choice.get("description"):
                    self.description(choice["description"], "    ")
            elif isinstance(cards, list):
                self.line(f"  卡包 C{fallback_index}{chosen} · {len(cards)} 张")
                for item in cards:
                    if isinstance(item, dict):
                        self.entity(item, "    · ")
            elif isinstance(card, dict):
                self.entity(card, f"  C{fallback_index}{chosen}. ")
            else:
                self.entity(choice, f"  C{fallback_index}{chosen}. ")
        if not merchant:
            self.line("  使用下方操作编号点击或取消候选，原生确认操作出现后再提交。")

    def pile(self, state: dict, pile_name: str) -> None:
        cards = pile_cards(state, pile_name)
        self.section(f"{PILE_LABELS.get(pile_name, pile_name)} · {len(cards)} 张 · 无序集合")
        if not cards:
            self.line("  当前状态未提供该牌堆，或牌堆为空。")
            return
        groups: Counter = Counter()
        details = {}
        for card in cards:
            label = (name(card), clean(card.get("cost", card.get("energyCost"))), clean(card.get("starCost")), clean(card.get("description")))
            groups[label] += 1
            details[label] = card
        for group in sorted(groups):
            self.entity(details[group], f"  {groups[group]} × ")

    def state(self, state: dict) -> list[dict]:
        if self.clear_screen:
            self.out("\x1b[2J\x1b[H")
        self.line("\n" + "═" * 66)
        screen = clean(state.get("screen", ""))
        title = clean(state.get("title") or SCREEN_LABELS.get(key(screen), screen) or "尖塔实验室")
        self.line(f"  {title}   [{SCREEN_LABELS.get(key(screen), screen) or '原生游戏'}]  rev {number(state.get('revision'))}")
        self.line("═" * 66)
        player = state.get("player") if isinstance(state.get("player"), dict) else {}
        if player:
            self.line(f"{name(player)}  |  进阶 {number(player.get('ascension'), '0')}")
            self.line(f"生命 {number(player.get('hp'))}/{number(player.get('maxHp'))}  格挡 {number(player.get('block'))}  能量 {number(player.get('energy'))}  金币 {number(player.get('gold'))}")
            if player.get("act") is not None or player.get("floor") is not None:
                self.line(f"第 {number(player.get('act'))} 幕 · 第 {number(player.get('floor'))} 层")
            statuses = status_text(player.get("statuses", player.get("powers")))
            if statuses:
                self.line("状态：" + statuses)
            for field, label in (("stars", "星星"), ("orbCapacity", "充能球槽")):
                if player.get(field) is not None:
                    self.line(f"{label}：{number(player[field])}")
        if state.get("description"):
            self.line()
            self.description(state["description"], "")
        if state.get("error"):
            self.line("\n[运行器报告] " + clean(state["error"]))
        actions = [action for action in as_list(state.get("actions")) if isinstance(action, dict)]
        if isinstance(state.get("map"), dict):
            self.map(state["map"], actions)
        if isinstance(state.get("board"), dict):
            self.board(state["board"], actions)
        entities = [item for item in as_list(state.get("entities")) if isinstance(item, dict)]
        choices = state.get("choices")
        candidate_ids = choice_entity_ids(choices)
        groups: dict[str, list] = defaultdict(list)
        for item in entities:
            if item.get("id") is not None and str(item["id"]) in candidate_ids:
                continue
            kind, pile = key(item.get("kind")), normalize_pile(item.get("pile"))
            if pile in PILE_LABELS:
                continue
            if pile == "hand" or kind in {"hand", "handcard"}:
                groups["手牌"].append(item)
            elif kind in {"enemy", "monster"}:
                groups["敌人"].append(item)
            elif kind in {"companion", "pet", "ally"}:
                groups["伙伴"].append(item)
            elif kind in {"potion", "potions"}:
                groups["药水"].append(item)
            elif kind in {"relic", "relics"}:
                groups["遗物"].append(item)
            elif kind in {"orb", "orbs"}:
                groups["充能球"].append(item)
            elif item.get("price") is not None or kind in {"shopitem", "merchandise", "product"}:
                groups["商品"].append(item)
            elif kind == "card" and key(screen) == "combat":
                groups["手牌"].append(item)
            else:
                groups["当前内容"].append(item)
        for label in ("敌人", "伙伴", "充能球", "手牌", "商品", "当前内容", "药水", "遗物"):
            if not groups[label]:
                continue
            self.section(f"{label} · {len(groups[label])}")
            for i, item in enumerate(groups[label], 1):
                self.entity(item, f"  {i}. ")
        piles = [f"{PILE_LABELS[pile]} {len(pile_cards(state, pile))}" for pile in PILE_LABELS if pile_cards(state, pile)]
        if piles:
            self.line("\n牌堆：" + " / ".join(piles) + "  （输入 deck / draw / discard / exhaust 查看）")
        if isinstance(choices, list):
            self.native_choices(choices, screen)
        elif isinstance(choices, dict) and isinstance(choices.get("cards"), list):
            minimum, maximum = choice_limits(choices)
            self.section(f"选择候选 · 选 {minimum}–{maximum} 项")
            for i, item in enumerate(choices["cards"], 1):
                if isinstance(item, dict):
                    self.entity(item, f"  C{i}. ")
            self.line("  输入：操作编号 选择编号，例如 2 1,3；空选用 2 -。")
        if actions:
            self.section(f"可执行操作 · {len(actions)}")
            entity_names = {str(item.get("id")): name(item) for item in entities}
            for i, action in enumerate(actions, 1):
                label = clean(action.get("label") or action.get("enLabel") or action.get("kind") or action.get("id"))
                english = clean(action.get("enLabel"))
                if english and english != label:
                    label += " · " + english
                target = action.get("targetId")
                if target is not None and str(target) in entity_names and entity_names[str(target)] not in label:
                    label += " → " + entity_names[str(target)]
                disabled = " [不可用]" if action.get("disabled") else ""
                self.line(f"  {i:>3}. {label}{disabled}")
                if action.get("description"):
                    self.description(action["description"], "       ")
        elif is_busy(state):
            self.line("\n游戏正在结算，请稍候。")
        else:
            self.line("\n当前没有可执行操作。输入 s 刷新，n 开始新局，h 查看帮助。")
        log = as_list(state.get("log"))
        if log:
            self.section("最近记录")
            for item in log[-6:]:
                if isinstance(item, dict):
                    item = item.get("message", item.get("text", item))
                self.description(item)
        self.line("\n输入操作编号 · h 帮助 · s 刷新 · q 退出")
        return actions


def normalize_pile(value: Any) -> str:
    return {"drawpile": "draw", "discardpile": "discard", "exhaustpile": "exhaust", "masterdeck": "deck", "handcards": "hand"}.get(key(value), key(value))


def pile_cards(state: dict, pile: str) -> list[dict]:
    piles = state.get("piles")
    if isinstance(piles, dict) and isinstance(piles.get(pile), list):
        return [item for item in piles[pile] if isinstance(item, dict)]
    return [item for item in as_list(state.get("entities")) if isinstance(item, dict) and normalize_pile(item.get("pile")) == pile]


def choice_entity_ids(choices: Any) -> set[str]:
    """Only deduplicate exact candidate instances, never names or model IDs."""
    if isinstance(choices, list):
        return set().union(*(choice_entity_ids(item) for item in choices))
    if not isinstance(choices, dict):
        return set()
    ids = {str(choices["id"])} if choices.get("id") is not None else set()
    for field in ("card", "cards"):
        ids.update(choice_entity_ids(choices.get(field)))
    return ids


def choice_limits(choices: dict) -> tuple[int, int]:
    count = len(as_list(choices.get("cards")))
    minimum = choices.get("min", 0)
    maximum = choices.get("max", count)
    try:
        return max(0, int(minimum)), min(count, max(0, int(maximum)))
    except (TypeError, ValueError):
        raise ValueError("运行器提供的选择数量限制无效。") from None


def is_set_action(state: dict, action: dict) -> bool:
    choices = state.get("choices")
    if not isinstance(choices, dict):
        return False
    if choices.get("actionId") is not None:
        return str(choices["actionId"]) == str(action.get("id"))
    if action.get("requiresSelection"):
        return True
    return key(action.get("kind")) in {
        "choosecardset", "removecardset", "resolvechoice", "confirmselection", "selectcards", "selectset", "cardselection",
    }


def parse_selection(raw: str, choices: dict) -> list:
    cards = as_list(choices.get("cards"))
    minimum, maximum = choice_limits(choices)
    raw = raw.strip().replace("，", ",").replace("、", ",")
    if raw.lower() in {"-", "none", "无", "空", "0"}:
        numbers = []
    else:
        parts = [part for part in re.split(r"[,\s]+", raw) if part]
        if not parts:
            raise ValueError("请输入候选编号；选择零项时输入 -。")
        try:
            numbers = [int(part.lstrip("Cc")) for part in parts]
        except ValueError:
            raise ValueError("候选编号需为整数，用逗号分隔，例如 1,3,4。") from None
    if len(set(numbers)) != len(numbers):
        raise ValueError("同一张候选不能重复选择。")
    if not minimum <= len(numbers) <= maximum:
        raise ValueError(f"需要选择 {minimum}–{maximum} 项，当前选了 {len(numbers)} 项。")
    if any(index < 1 or index > len(cards) for index in numbers):
        raise ValueError(f"候选编号必须在 1–{len(cards)} 之间。")
    selected = []
    for index in numbers:
        card = cards[index - 1]
        if not isinstance(card, dict) or card.get("id") is None:
            raise ValueError("候选缺少原生标识，不能提交；请检查运行器状态。")
        if card.get("disabled"):
            raise ValueError(f"候选 C{index} 当前不可选择。")
        selected.append(card["id"])
    return selected


def wait_ready(client: Client, initial: dict | None, renderer: Renderer, interval: float, max_wait: float) -> dict:
    state = initial if initial is not None else client.state()
    if not is_busy(state) or state.get("error"):
        return state
    started = time.monotonic()
    notice_at = started
    unset = object()
    ready_revision = unset
    while True:
        if state.get("error") or key(state.get("status")) == "error":
            return state
        if is_busy(state):
            ready_revision = unset
        else:
            # A native transition can briefly expose actions before animation cleanup
            # changes the revision. After busy, require two matching ready polls.
            revision = state.get("revision")
            if ready_revision is not unset and revision == ready_revision:
                return state
            ready_revision = revision
        now = time.monotonic()
        if now - started >= max_wait:
            renderer.line(f"\n仍在结算（等待了 {max_wait:g} 秒）。输入 s 可继续等待，q 退出终端。")
            return state
        if now >= notice_at:
            renderer.line("游戏正在结算… " + clean(state.get("title") or state.get("status")))
            notice_at = now + 5
        time.sleep(interval)
        state = client.state()


HELP = """
操作：
  3              执行当前列表的第 3 个操作。
  3 1,4,5        执行第 3 个集合选择操作，选候选 C1、C4、C5。
  3 -            提交空选择（仅在原生规则允许选零项时）。
  s / refresh    刷新；结算中会继续轮询。
  deck           查看完整牌组（无序集合）。
  draw           查看抽牌堆（无序集合，不显示抽牌顺序）。
  discard        查看弃牌堆（无序集合）。
  exhaust        查看消耗堆（无序集合）。
  n / new        空闲或终局时按启动参数开始新局；进行中的局需退出并重启测试进程。
  h / help       显示帮助。
  q / quit       退出终端客户端。运行器进程由启动脚本管理。

操作只使用当前原生合法动作列表。编号随状态刷新而变化。
收到状态已过期或请求超时时会先刷新，不自动重发原操作。
"""


def interact(client: Client, args: argparse.Namespace, renderer: Renderer, read: Callable[[str], str] = input) -> int:
    renderer.line("SlayTheModel · 原生尖塔终端")
    renderer.line(f"连接 {client.base_url}  |  {CHARACTER_NAMES.get(args.character, args.character)}  |  进阶 {args.ascension}")
    state = None
    if args.new:
        renderer.line("正在开始新的一局…")
        state = client.new(args.character, args.ascension, args.seed, args.language)
    need_refresh = True
    actions: list[dict] = []
    while True:
        if need_refresh:
            try:
                state = wait_ready(client, state, renderer, args.poll_interval, args.wait_timeout)
                actions = renderer.state(state)
            except ApiError as exc:
                renderer.line("\n[连接/运行器错误] " + str(exc))
                renderer.line("请确认运行器已启动。输入 s 重试，q 退出。")
                state, actions = None, []
            need_refresh = False
        raw = read("\n选择 > ").strip()
        if not raw:
            continue
        command, _, rest = raw.partition(" ")
        command = command.lower()
        if command in {"q", "quit", "exit", "退出"}:
            renderer.line("已退出终端客户端。")
            return 0
        if command in {"h", "help", "?", "帮助"}:
            renderer.line(HELP)
            continue
        if command in {"s", "refresh", "刷新"}:
            state, need_refresh = None, True
            continue
        if command in PILE_LABELS:
            if state:
                renderer.pile(state, command)
            else:
                renderer.line("还没有有效游戏状态，请先输入 s 连接。")
            continue
        if command in {"n", "new", "新局"}:
            if state and state.get("player") and key(state.get("status")) not in {"finished", "idle", "ended", "complete"} and key(state.get("screen")) not in {"victory", "defeat", "gameover", "ngameoverscreen", "menu", "idle"}:
                renderer.line("当前有一局进行中。请先输入 q 退出终端，再停止并重启测试进程来开始新局。")
                continue
            try:
                state = client.new(args.character, args.ascension, args.seed, args.language)
            except ApiError as exc:
                renderer.line("[新局请求错误] " + str(exc))
                state = None
            need_refresh = True
            continue
        if not state:
            renderer.line("还没有有效游戏状态，请先输入 s 连接。")
            continue
        if is_busy(state):
            renderer.line("原生逻辑仍在结算，当前不能提交新动作；输入 s 继续等待。")
            continue
        try:
            index = int(command)
        except ValueError:
            renderer.line("请输入操作编号，或输入 h 查看帮助。")
            continue
        if not 1 <= index <= len(actions):
            renderer.line(f"操作编号应在 1–{len(actions)} 之间。")
            continue
        action = actions[index - 1]
        if action.get("disabled"):
            renderer.line("原生逻辑当前不允许这个操作。")
            continue
        selected_ids = None
        if is_set_action(state, action):
            try:
                if not rest.strip():
                    rest = read("选择候选（如 1,3；零项输入 -；取消输入 q）> ").strip()
                    if rest.lower() in {"q", "cancel", "取消"}:
                        continue
                selected_ids = parse_selection(rest, state["choices"])
            except ValueError as exc:
                renderer.line("[选择无效] " + str(exc))
                continue
        elif rest.strip():
            renderer.line("这个操作不接受候选集合，请只输入操作编号。")
            continue
        try:
            renderer.line("提交：" + clean(action.get("label") or action.get("kind") or action.get("id")))
            state = client.action(state, action, selected_ids)
        except ApiError as exc:
            renderer.line("[操作请求错误] " + str(exc))
            if exc.status == 409:
                renderer.line("游戏状态已变化，将刷新操作列表。")
            else:
                renderer.line("将读取实际状态；本次操作不会自动重发。")
            state = None
        need_refresh = True


def arguments(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="使用终端游玩原生 STS2 headless 运行器；无需第三方 Python 包。")
    parser.add_argument("--url", default=os.environ.get("SLAY_THE_MODEL_HEADLESS_URL", "http://127.0.0.1:18777"), help="运行器 HTTP 地址（默认 http://127.0.0.1:18777）")
    parser.add_argument("--new", action="store_true", help="连接后开始新局；不指定则接入现有局")
    parser.add_argument("--character", type=str.upper, default="IRONCLAD", choices=list(CHARACTER_NAMES))
    parser.add_argument("--ascension", type=int, default=0)
    parser.add_argument("--seed", default="")
    parser.add_argument("--language", choices=("zhs", "eng"), default="zhs")
    parser.add_argument("--timeout", type=float, default=30, help="每次 HTTP 请求超时秒数")
    parser.add_argument("--poll-interval", type=float, default=0.5, help="结算期间轮询间隔秒数")
    parser.add_argument("--wait-timeout", type=float, default=120, help="连续等待结算的最大秒数，之后可手动刷新")
    parser.add_argument("--clear", action="store_true", help="刷新时清屏（默认保留终端历史）")
    args = parser.parse_args(argv)
    if not 0 <= args.ascension <= 10:
        parser.error("--ascension 必须在 0–10 之间。")
    if args.timeout <= 0 or args.poll_interval <= 0 or args.wait_timeout <= 0:
        parser.error("超时和轮询间隔必须大于零。")
    return args


def main(argv: list[str] | None = None) -> int:
    args = arguments(argv)
    renderer = Renderer(clear_screen=args.clear and sys.stdout.isatty())
    try:
        client = Client(args.url, args.timeout)
        return interact(client, args, renderer)
    except (KeyboardInterrupt, EOFError):
        renderer.line("\n已退出终端客户端；未重发待处理动作。")
        return 0
    except (ApiError, ValueError) as exc:
        renderer.line("\n[错误] " + str(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
