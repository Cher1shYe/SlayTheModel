"""Human-playable command line for the simulator (2026-11-18).

The player sees exactly what the shared actor contract ``spire.public/1`` exposes
(``public_obs.PublicState``) and chooses among exactly the candidates the network scores.
So nothing hidden (draw order, RNG, unrevealed rewards) is shown, and no real choice is
made automatically: picks, skips, confirms and full potion belts stay with the player.

The screen is rendered from PublicState only, never from simulator internals, so the
same front end can later drive another backend that produces PublicState (the native
host). Backends implement ``observe() -> PublicState`` and ``act(index)``.

Usage (repository root):
  KMP_DUPLICATE_LIB_OK=TRUE PYTHONPATH=.:train python -m spire_rl.play_cli --seed MYSEED --ascension 10
Type ``help`` at the prompt for commands (number = take that action).
"""
from __future__ import annotations

import argparse
import random
import string
import sys
from collections import Counter
from pathlib import Path

from . import public_obs as po

# ---------------------------------------------------------------- names and labels


def name(ident) -> str:
    """CARD.STRIKE_IRONCLAD / STRIKE_IRONCLAD -> Strike Ironclad."""
    if ident is None:
        return "-"
    text = str(ident)
    if "." in text and text.split(".", 1)[0].isupper():
        text = text.split(".", 1)[1]
    return text.replace("_", " ").title()


def _plus(upgrade) -> str:
    return "+" * int(upgrade) if isinstance(upgrade, int) and not isinstance(upgrade, bool) and upgrade > 0 else ""


def _fingerprint_card(value):
    """A frozen public card fingerprint (tuple of (field, value) pairs) as a dict, else None."""
    if isinstance(value, tuple) and value and all(isinstance(x, tuple) and len(x) == 2 and isinstance(x[0], str) for x in value):
        d = dict(value)
        if "modelId" in d:
            return d
    return None


def _cost(card) -> str:
    if card.get("costX"):
        return "X"
    cost = card.get("cost", card.get("localCost"))
    return "-" if cost is None or cost < 0 else str(cost)


def card_line(card) -> str:
    """One-line public description of a card dict (facts card or fingerprint)."""
    parts = [f"{name(card['modelId'])}{_plus(card.get('upgrade', 0))}", f"{_cost(card)}费", _zh_type(card.get("type"))]
    if card.get("damage"):
        parts.append(f"伤害{card['damage']}")
    if card.get("block"):
        parts.append(f"格挡{card['block']}")
    other = [f"{k}={v}" for k, v in card.get("dynamicVars", ()) if k not in ("Damage", "Block")]
    if other:
        parts.append(" ".join(other))
    keywords = sorted(set(card.get("keywords", ())) | set(card.get("localKeywords", ())))
    if card.get("retainThisTurn"):
        keywords.append("本回合保留")
    if keywords:
        parts.append("/".join(keywords))
    if card.get("enchantment"):
        eid, amount, disabled, _ = card["enchantment"]
        parts.append(f"附魔 {name(eid)} {amount}" + ("（失效）" if disabled else ""))
    for affliction, amount in card.get("afflictions", ()):
        parts.append(f"苦难 {name(affliction)} {amount}")
    if card.get("price", -1) >= 0:
        parts.append(f"价格 {card['price']}")
    return " · ".join(p for p in parts if p)


_TYPES = {"Attack": "攻击", "Skill": "技能", "Power": "能力", "Status": "状态", "Curse": "诅咒", "Quest": "任务"}
_INTENTS = {"Attack": "攻击", "Buff": "增益", "Debuff": "减益", "DebuffStrong": "强减益", "Defend": "防御",
            "Escape": "逃跑", "Heal": "回复", "Hidden": "未知", "Summon": "召唤", "Sleep": "睡眠", "Stun": "眩晕",
            "StatusCard": "塞牌", "CardDebuff": "卡牌减益", "DeathBlow": "致命一击", "Unknown": "未知"}
_MAP = {"Unassigned": "·", "Unknown": "?", "Shop": "$", "Treasure": "T", "RestSite": "R", "Monster": "M",
        "Elite": "E", "Boss": "B", "Ancient": "A"}
_MAP_ZH = {"Unknown": "未知", "Shop": "商店", "Treasure": "宝箱", "RestSite": "火堆", "Monster": "普通怪",
           "Elite": "精英", "Boss": "Boss", "Ancient": "先古"}
_REST = {"HEAL": "休息（回血）", "SMITH": "锻造（升级一张牌）", "DIG": "挖掘", "LIFT": "举重", "CLONE": "复制",
         "HATCH": "孵化", "COOK": "烹饪", "KINDLE": "点燃", "MEND": "修补"}
_SCREENS = {"neow": "Neow", "event": "事件", "map": "地图", "combat": "战斗", "combat_selection": "战斗中选牌",
            "rewards": "奖励", "card_reward": "卡牌奖励", "shop": "商店", "shop_entry": "商店门口", "rest": "火堆",
            "treasure": "宝箱", "card_selection": "选牌", "card_grid": "选牌", "crystal_sphere": "水晶球",
            "relic_selection": "选遗物", "card_bundle": "选卡包", "terminal": "结束"}


def _zh_type(value) -> str:
    return _TYPES.get(value, value or "")


def enemy_ref(target) -> str:
    """Enemy action key (order, slot, monster, hp, maxHp, ...) -> short label."""
    if target is None:
        return ""
    order, monster = target[0], target[2] if len(target) > 2 else "?"
    return f"{name(monster)}#{order}"


def _args_text(args) -> str:
    out = []
    for value in args:
        card = _fingerprint_card(value)
        if card is not None:
            out.append(name(card["modelId"]) + _plus(card.get("upgrade", 0)))
        elif isinstance(value, tuple):
            out.append("(" + _args_text(value) + ")")
        elif isinstance(value, str):
            out.append(name(value))
        else:
            out.append(str(value))
    return ", ".join(out)


def action_label(key, facts) -> str:
    """Readable Chinese label for one semantic ActionKey."""
    k, a = key.kind, key.args
    if k == "play":
        hand = a[0]
        text = f"打出 [{hand[0]}] {name(hand[1])}{_plus(hand[2])}（{hand[3] if hand[3] >= 0 else 'X'}费）"
        return text + (f" → {enemy_ref(a[1])}" if len(a) > 1 and a[1] is not None else "")
    if k == "end_turn":
        return "结束回合"
    if k == "move":
        col, row = a[0], a[1]
        kind = next((p["type"] for p in facts.get("map", ()) if p["row"] == row and p["col"] == col), "")
        return f"前往 第{row}行 第{col}列（{_MAP_ZH.get(kind, kind)}）"
    if k == "use_potion":
        target = a[2] if len(a) > 2 else None
        return f"使用药水 槽{a[0]} {name(a[1])}" + (f" → {enemy_ref(target)}" if target is not None else "")
    if k == "discard_potion":
        return f"丢弃药水 槽{a[0]} {name(a[1])}"
    if k == "take_gold":
        return f"领取 {a[1]} 金币" + ("（找回的）" if a[0] else "")
    if k == "take_potion":
        return f"领取药水 {name(a[0])}"
    if k in ("take_relic_reward", "take_treasure_relic", "neow_relic", "select_relic"):
        return {"neow_relic": "Neow：选遗物 ", "select_relic": "选遗物 "}.get(k, "领取遗物 ") + name(a[0])
    if k == "take_special_card":
        return f"领取卡牌 {name(a[0])}{_plus(a[1])}"
    if k in ("take_card", "select_card", "deselect_card"):
        card = _fingerprint_card(a[2]) if len(a) > 2 else None
        verb = {"take_card": "拿", "select_card": "选中", "deselect_card": "取消选中"}[k]
        if card is not None:
            return f"{verb} {card_line(card)}" + (f"（同名第{a[-1] + 1}张）" if a[-1] else "")
        return f"{verb} {name(a[0])}{_plus(a[1])}"
    if k == "select_bundle":
        return "选这一包：" + "、".join(name(c[0]) + _plus(c[1]) for c in a[0])
    if k in ("buy_card", "buy_relic", "buy_potion"):
        what = {"buy_card": "卡牌", "buy_relic": "遗物", "buy_potion": "药水"}[k]
        return f"购买{what} {name(a[0])}（{a[1]} 金币）"
    if k == "open_remove_card":
        return f"删一张牌（{a[0]} 金币）"
    if k == "rest":
        return _REST.get(a[0], a[0])
    if k == "event_option":
        return f"事件选项 {a[1]}"
    if k == "event_proceed":
        return "继续（离开事件）"
    if k == "reveal_cell":
        return f"揭开 ({a[1]},{a[2]})（{'小' if a[0] == 'Small' else '大'}工具）"
    fixed = {"neow_proceed": "继续", "open_card_reward": "打开卡牌奖励", "open_card_removal_reward": "打开删牌奖励",
             "skip_card": "跳过卡牌奖励", "sacrifice_card_reward": "牺牲卡牌奖励", "reroll_card_reward": "重掷卡牌奖励",
             "heal_card_reward": "放弃卡牌改回血", "leave_rewards": "离开奖励（继续）", "proceed": "继续",
             "leave_shop": "离开商店", "rest_proceed": "继续（离开火堆）", "open_treasure": "打开宝箱",
             "leave_treasure": "离开宝箱", "confirm_selection": "确认选择", "confirm": "确认", "cancel": "取消",
             "cancel_preview": "取消预览", "cancel_selection": "取消选择", "skip_selection": "跳过选择",
             "small_divination": "小占卜", "big_divination": "大占卜"}
    if k in fixed:
        return fixed[k] + (f"（{_args_text(a)}）" if a and k not in ("open_card_reward",) else "")
    return f"{k}({_args_text(a)})"


# ---------------------------------------------------------------- rendering


def _powers_text(powers) -> str:
    return "，".join(f"{name(p[0])} {p[2]}" for p in powers) or "无"


def render_header(facts) -> list[str]:
    p, r = facts["player"], facts["run"]
    bosses = " + ".join(name(b) for b in (r["boss"], r.get("secondBoss")) if b)
    lines = [f"═══ 第{r['act'] + 1}幕 第{r['floor']}层（本幕第{r['actFloor']}层） A{r['ascension']} │ "
             f"HP {p['hp']}/{p['maxHp']} │ 金币 {p['gold']} │ {_SCREENS.get(facts['screen'], facts['screen'])} │ Boss：{bosses}"]
    relics = sorted(facts["relics"], key=lambda x: x["position"])
    lines.append("遗物：" + ("，".join(name(x["modelId"]) + (f"({x['counter']})" if x["counterVisible"] else "")
                                        + ("[失效]" if x["status"] == "Disabled" else "") for x in relics) or "无"))
    belt = sorted(facts["potions"], key=lambda x: x["slot"])
    lines.append("药水：" + "  ".join(f"[{x['slot']}] {name(x['modelId']) if x['modelId'] else '空'}" for x in belt))
    return lines


def render_combat(facts) -> list[str]:
    p, c = facts["player"], facts["combat"]
    lines = [f"── 第{c['turn']}回合 │ 能量 {p['energy']}/{p['maxEnergy']} │ 格挡 {p['block']} │ 能力：{_powers_text(facts['powers'])}"]
    for e in facts["enemies"]:
        if not e["alive"] and not e["reviving"]:
            continue
        intents = "，".join(f"{_INTENTS.get(t, t)}" + (f" {d}×{h}" if t in ("Attack", "DeathBlow") else "")
                           for t, d, h in e["intents"]) if e["intentsVisible"] else "（看不到）"
        state = "（等待复活）" if e["reviving"] else ""
        lines.append(f"  敌 #{e['order']} {name(e['modelId'])}{state}  HP {e['hp']}/{e['maxHp']}  格挡 {e['block']}  "
                     f"意图：{intents}  能力：{_powers_text(e['powers'])}")
    hand = sorted((x for x in facts["cards"] if x["pile"] == "hand"), key=lambda x: x["position"])
    lines.append("手牌：")
    lines += [f"  [{x['position']}] {card_line(x)}" for x in hand] or ["  （空）"]
    counts = Counter(x["pile"] for x in facts["cards"])
    lines.append(f"抽牌堆 {counts['draw']} │ 弃牌堆 {counts['discard']} │ 消耗堆 {counts['exhaust']}"
                 + (f" │ 正在打出 {counts['play']}" if counts["play"] else ""))
    return lines


def render_map(facts) -> list[str]:
    points = facts["map"]
    if not points:
        return ["（没有地图）"]
    width = max(p["col"] for p in points) + 1
    grid = {(p["row"], p["col"]): p for p in points}
    lines = ["地图（下方为起点；[ ] 当前位置，小写为已去过；M普通 E精英 R火堆 $商店 T宝箱 ?未知 A先古 B Boss）："]
    rows = sorted({p["row"] for p in points}, reverse=True)
    for row in rows:
        if row != rows[0]:
            # connectors from this row up to row + 1 (adjacent columns only; the start
            # and Boss rows connect to many columns and are listed as actions instead)
            link = [" "] * (3 * width + 2)
            for col in range(width):
                point = grid.get((row, col))
                for child in (point or {}).get("children", ()):
                    if child["row"] != row + 1 or abs(child["col"] - col) > 1:
                        continue
                    x, mark = {0: (3 * col + 1, "|"), 1: (3 * col + 3, "/"), -1: (3 * col - 1, "\\")}[child["col"] - col]
                    if 0 <= x < len(link):
                        link[x] = "X" if link[x] not in (" ", mark) else mark
            lines.append("   " + "".join(link).rstrip())
        cells = []
        for col in range(width):
            point = grid.get((row, col))
            if point is None:
                cells.append("   ")
                continue
            mark = _MAP.get(point["type"], "?")
            if point["visited"]:
                mark = mark.lower()
            cells.append(f"[{mark}]" if point["current"] else f" {mark} ")
        lines.append(f"{row:2d} " + "".join(cells))
    lines.append("   " + "".join(f" {c} " for c in range(width)))
    return lines


def render_offers(facts) -> list[str]:
    lines = []
    for offer in facts["offers"]:
        what = name(offer["modelId"]) if offer["modelId"] else offer["kind"]
        extra = []
        if offer["amount"] is not None:
            extra.append(f"数量 {offer['amount']}")
        if offer["price"] >= 0:
            extra.append(f"价格 {offer['price']}")
        if not offer["available"]:
            extra.append("不可领取/买不起")
        lines.append(f"  · {offer['kind']}：{what}" + (f"（{'，'.join(extra)}）" if extra else ""))
    return (["可见奖励/货架："] + lines) if lines else []


def render_choices(facts) -> list[str]:
    lines = []
    if facts["choices"]:
        lines.append("候选牌：")
        lines += [f"  {i}. {card_line(c)}" + ("  ✓已选" if c.get("selected") else "")
                  for i, c in enumerate(facts["choices"])]
    d = facts["decision"]
    if d is not None:
        lines.append(f"选择要求：最少 {d['minSelect']} 张，最多 {d['maxSelect']} 张，已选 {d['selectedCount']} 张"
                     + ("，需手动确认" if d["requireManualConfirmation"] else "") + ("，可取消" if d["cancelable"] else ""))
    return lines


def render_board(facts) -> list[str]:
    board = facts["board"]
    if board is None:
        return []
    grid = {(c["x"], c["y"]): c for c in board["cells"]}
    lines = [f"水晶球：剩余 {board['remaining']} 次" + ("（已结束）" if board["finished"] else "")]
    for y in range(board["height"]):
        row = []
        for x in range(board["width"]):
            cell = grid.get((x, y))
            if cell is None:
                row.append("  ")
            elif cell["hidden"]:
                row.append("▒▒")
            else:
                item = cell["revealedItem"]
                row.append({None: "··", "CrystalSphereRelic": "遗", "CrystalSpherePotion": "药", "CrystalSphereCardReward": "牌",
                            "CrystalSphereCurse": "咒", "CrystalSphereGold": "金"}.get(item, "??"))
        lines.append(" ".join(row))
    return lines


def render(state) -> str:
    facts = state.facts
    lines = render_header(facts)
    if facts["eventPage"]:
        lines.append(f"事件页面：{facts['eventPage']}")
    if facts["combat"] is not None:
        lines += render_combat(facts)
    elif facts["screen"] == "map":
        lines += render_map(facts)
    lines += render_offers(facts) + render_choices(facts) + render_board(facts)
    lines.append("可选动作：")
    lines += [f"  {i:2d}) {action_label(a.key, facts)}" for i, a in enumerate(state.actions)]
    return "\n".join(lines)


def render_pile(facts, pile) -> str:
    cards = [c for c in facts["cards"] if c["pile"] == pile]
    title = {"deck": "牌组", "draw": "抽牌堆（不显示顺序，只列内容）", "discard": "弃牌堆", "exhaust": "消耗堆"}[pile]
    if not cards:
        return f"{title}：空"
    counted = Counter(card_line(c) for c in cards)
    lines = [f"{title}（{len(cards)} 张）："] + [f"  {n}× {text}" for text, n in sorted(counted.items())]
    known = sorted((c for c in cards if c.get("knownTopPosition", -1) >= 0), key=lambda c: c["knownTopPosition"])
    if pile == "draw" and known:
        lines.append("已知的顶部牌：" + "，".join(f"第{c['knownTopPosition'] + 1}张 {name(c['modelId'])}" for c in known))
    return "\n".join(lines)


# ---------------------------------------------------------------- backend and loop


class SimulatorBackend:
    """C++ simulator behind the public contract. Undo keeps clones, save/load use snapshots."""

    def __init__(self, seed: str | int, ascension: int):
        from .sim import sim
        self.sim = sim
        self.rc = sim.RunContext()
        if isinstance(seed, int):
            self.rc.init(seed, ascension)
        else:
            self.rc.init_seed(seed, ascension)
        self.history: list = []
        self.state = None

    @property
    def finished(self) -> bool:
        return bool(self.rc.is_terminal)

    def outcome(self) -> str:
        return "胜利" if self.rc.won else f"失败（第 {int(self.rc.floor)} 层）"

    def observe(self):
        self.state = po.from_simulator(self.rc)
        return self.state

    def act(self, index: int) -> None:
        if self.state is None:
            raise RuntimeError("observe before acting")
        self.history.append(self.rc.clone())
        del self.history[:-50]
        po.step_simulator(self.rc, self.state, index)
        self.state = None

    def undo(self) -> bool:
        if not self.history:
            return False
        self.rc = self.history.pop()
        self.state = None
        return True

    def save(self, path: Path) -> None:
        path.write_bytes(self.rc.snapshot())

    def load(self, path: Path) -> None:
        rc = self.sim.RunContext()
        if not rc.restore(path.read_bytes()):
            raise ValueError(f"{path}: not a snapshot of this simulator version")
        self.rc, self.history, self.state = rc, [], None


HELP = """命令：
  数字        执行该编号的动作
  deck / draw / discard / exhaust   查看牌组 / 抽牌堆（只列内容）/ 弃牌堆 / 消耗堆
  map         查看地图          state   重新显示当前局面
  undo        撤销上一步（最多 50 步；只用于调试，会看到同样的随机结果）
  save 文件   保存快照          load 文件   读取快照
  help        帮助              quit    退出"""


def play(backend, read=input, write=print) -> int:
    """Interactive loop. Returns 0 when the run ends or the player quits, 1 on a contract stop."""
    show = True
    while True:
        if backend.finished:
            write(f"本局结束：{backend.outcome()}")
            return 0
        try:
            state = backend.observe()
        except Exception as exc:  # contract stop: never guess an unsupported state
            write(f"公共接口不支持当前局面，已停止：{type(exc).__name__}: {exc}")
            write("可以 undo / load 回到之前的局面，或 quit。")
            state = None
        if state is not None and show:
            write(render(state))
        show = True
        try:
            line = read("> ").strip()
        except EOFError:
            return 0
        command, _, rest = line.partition(" ")
        if command.isdigit() and state is not None:
            index = int(command)
            if not 0 <= index < len(state.actions):
                write(f"没有编号 {index} 的动作（0–{len(state.actions) - 1}）")
                show = False
                continue
            backend.act(index)
        elif command in ("deck", "draw", "discard", "exhaust") and state is not None:
            write(render_pile(state.facts, command)); show = False
        elif command == "map" and state is not None:
            write("\n".join(render_map(state.facts))); show = False
        elif command == "state":
            pass
        elif command == "undo":
            write("已撤销一步。" if backend.undo() else "没有可撤销的步骤。")
        elif command == "save" and rest:
            backend.save(Path(rest)); write(f"已保存到 {rest}"); show = False
        elif command == "load" and rest:
            try:
                backend.load(Path(rest)); write(f"已读取 {rest}")
            except (OSError, ValueError) as exc:
                write(f"读取失败：{exc}"); show = False
        elif command in ("quit", "exit", "q"):
            return 0
        else:
            write(HELP); show = False


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="在命令行里手动玩模拟器（只显示公开信息）")
    parser.add_argument("--seed", help="游戏种子字符串（与原生相同的规范化）；不给则随机生成")
    parser.add_argument("--numeric-seed", type=int, help="直接用 64 位整数随机种子（模拟器旧接口）")
    parser.add_argument("--ascension", type=int, default=10, help="进阶 0–10，默认 10")
    parser.add_argument("--load", type=Path, help="从快照文件继续")
    args = parser.parse_args(argv)
    if not 0 <= args.ascension <= 10:
        parser.error("--ascension 须在 0–10")
    seed = args.numeric_seed if args.numeric_seed is not None else (
        args.seed or "".join(random.choice(string.ascii_uppercase + string.digits) for _ in range(10)))
    backend = SimulatorBackend(seed, args.ascension)
    if args.load:
        backend.load(args.load)
    else:
        print(f"种子 {seed}，进阶 A{args.ascension}，铁甲战士")
    print("输入 help 查看命令。")
    return play(backend)


if __name__ == "__main__":
    sys.exit(main())
