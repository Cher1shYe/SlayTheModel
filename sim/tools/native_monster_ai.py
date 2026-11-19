"""Parse the native v0.111.0 monster state machines (Models/Monsters/*.cs,
GenerateMoveStateMachine) into a plain structure, and compare it with content/monsters.json.

Native semantics (MonsterMoves/MonsterMoveStateMachine/*.cs):
* MoveState(id, fn, intents...): FollowUpState / FollowUpStateId; executes a move.
* RandomBranchState(id).AddBranch(state, [cooldown,] repeatType|maxRepeats[, weight]):
  weight defaults to 1; one MonsterAi NextFloat per traversal (see monsters.cpp).
* ConditionalBranchState(id).AddState(state, () => condition): first true wins, no RNG.
* MonsterMoveStateMachine(list, initial): the initial state is logged; the first RollMove
  keeps an initial MoveState, and traverses from an initial branch state.

Usage:
  python sim/tools/native_monster_ai.py --dump out.json      # parsed native structure
  python sim/tools/native_monster_ai.py --compare            # report differences with monsters.json
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]
NATIVE = ROOT.parent / "artifacts" / "native-source" / "v0.111.0" / "MegaCrit" / "sts2" / "Core"
STATE_TYPES = ("MoveState", "RandomBranchState", "ConditionalBranchState")
REPEAT = {"CanRepeatForever": "CAN_REPEAT_FOREVER", "CanRepeatXTimes": "CAN_REPEAT_X_TIMES",
          "CannotRepeat": "CANNOT_REPEAT", "UseOnlyOnce": "USE_ONLY_ONCE"}


def slug(name: str) -> str:
    out = []
    for i, ch in enumerate(name):
        if ch.isupper() and i > 0 and name[i - 1].isalnum():
            out.append("_")
        out.append(ch)
    return re.sub(r"[^A-Z0-9_]", "", "".join(out).upper())


def method_body(src: str, name: str) -> str | None:
    m = re.search(r"\b" + name + r"\(\)\s*\{", src)
    if not m:
        return None
    i, depth = m.end(), 1
    while depth and i < len(src):
        depth += {"{": 1, "}": -1}.get(src[i], 0)
        i += 1
    return src[m.end():i - 1]


def split_args(s: str) -> list[str]:
    out, depth, cur = [], 0, []
    for ch in s:
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        if ch == "," and depth == 0:
            out.append("".join(cur).strip())
            cur = []
        else:
            cur.append(ch)
    if "".join(cur).strip():
        out.append("".join(cur).strip())
    return out


def call_args(text: str, start: int) -> tuple[str, int]:
    """Arguments of the call whose '(' is at text[start]; returns (inside, end index)."""
    depth, i = 0, start
    while i < len(text):
        depth += {"(": 1, ")": -1}.get(text[i], 0)
        if depth == 0:
            return text[start + 1:i], i
        i += 1
    return text[start + 1:], len(text)


def int_props(src: str, cls_chain: list[str]) -> dict:
    """int properties: constants or AscensionHelper.GetValueIfAscension(level, asc, base)."""
    props = {}
    for text in cls_chain:
        for name, expr in re.findall(r"\bint (\w+)\s*=>\s*(.*?);", text):
            e = expr.strip()
            m = re.fullmatch(r"AscensionHelper\.GetValueIfAscension\(AscensionLevel\.(\w+),\s*(-?\d+),\s*(-?\d+)\)", e)
            if m:
                props.setdefault(name, {"level": m.group(1), "asc": int(m.group(2)), "base": int(m.group(3))})
            elif re.fullmatch(r"-?\d+", e):
                props.setdefault(name, {"level": None, "asc": int(e), "base": int(e)})
            else:
                props.setdefault(name, {"expr": e})
    return props


def parse_intent(text: str) -> dict:
    m = re.match(r"new (\w+)Intent\((.*)\)$", text.strip(), re.S)
    if not m:
        return {"type": "?", "src": text.strip()}
    kind, args = m.group(1), split_args(m.group(2))
    out = {"type": kind}
    if kind in ("SingleAttack", "MultiAttack", "DeathBlow"):
        out["damage"] = args[0] if args else None
        if kind == "MultiAttack":
            out["hits"] = args[1] if len(args) > 1 else None
    elif args:
        out["args"] = args
    return out


def parse_machine(body: str) -> dict:
    states: dict[str, dict] = {}
    var_state: dict[str, str] = {}
    order: list[str] = []
    initial = None

    def new_state(kind: str, sid: str, args: list[str]):
        st = {"kind": kind}
        if kind == "MoveState":
            st["intents"] = [parse_intent(a) for a in args[2:] if a.startswith("new ") and "Intent(" in a]
            st["fn"] = args[1] if len(args) > 1 else None
            st["follow"] = None
            st["must_once"] = False
        else:
            st["branches"] = []
        states.setdefault(sid, st)
        if sid not in order:
            order.append(sid)
        return sid

    def value_of(expr: str) -> str | None:
        """State id an expression evaluates to (innermost new state or trailing variable)."""
        news = list(re.finditer(r"new (" + "|".join(STATE_TYPES) + r")\(\"([^\"]+)\"", expr))
        if news:
            return news[-1].group(2)
        m = re.search(r"(\w+)\s*\)*\s*$", expr.strip())
        return var_state.get(m.group(1)) if m else None

    for raw in body.split(";"):
        stmt = " ".join(raw.split())
        if not stmt:
            continue
        # every `new XState("ID", ...)` in the statement creates a state
        for m in re.finditer(r"new (" + "|".join(STATE_TYPES) + r")\(", stmt):
            inside, _ = call_args(stmt, m.end() - 1)
            args = split_args(inside)
            if args and args[0].startswith('"'):
                new_state(m.group(1), args[0].strip('"'), args)
        # `T v = ...`, or a property assignment `BeastCryState = new MoveState(...)`
        decl = re.match(r"(?:\w*State )?(\w+) = (.*)$", stmt)
        if decl and not stmt.startswith("List<") and "." not in decl.group(1):
            sid = value_of(decl.group(2))
            if sid:
                var_state[decl.group(1)] = sid
        target_expr = decl.group(2) if decl else stmt
        val = value_of(target_expr.split("=")[-1]) if "FollowUpState =" in stmt else None
        for m in re.finditer(r"(\w+)\.FollowUpState\s*=", stmt):
            v = var_state.get(m.group(1))
            if v and val:
                states[v]["follow"] = val
        for m in re.finditer(r"(\w+)\.FollowUpStateId\s*=\s*\"([^\"]+)\"", stmt):
            v = var_state.get(m.group(1))
            if v:
                states[v]["follow"] = m.group(2)
        if "MustPerformOnceBeforeTransitioning = true" in stmt:
            news = list(re.finditer(r"new MoveState\(\"([^\"]+)\"", stmt))
            if news:
                states[news[-1].group(1)]["must_once"] = True
        for m in re.finditer(r"(\w+)\.MustPerformOnceBeforeTransitioning\s*=\s*true", stmt):
            if var_state.get(m.group(1)):
                states[var_state[m.group(1)]]["must_once"] = True
        m = re.search(r"\bDeadState\s*=\s*", stmt)
        if m:
            var_state["DeadState"] = value_of(stmt[m.end():])
        for m in re.finditer(r"(\w+)\.AddBranch\(", stmt):
            owner = var_state.get(m.group(1))
            inside, _ = call_args(stmt, m.end() - 1)
            args = split_args(inside)
            if not owner or not args:
                continue
            br = {"state": var_state.get(args[0], args[0]), "repeat": "CAN_REPEAT_FOREVER", "max": 1,
                  "weight": "1", "cooldown": 0}
            rest = args[1:]
            ints = []
            for a in rest:
                rm = re.fullmatch(r"MoveRepeatType\.(\w+)", a)
                if rm:
                    br["repeat"] = REPEAT[rm.group(1)]
                elif re.fullmatch(r"-?\d+", a):
                    ints.append(int(a))
                else:
                    lw = re.fullmatch(r"(?:\(\)\s*=>\s*)?(-?\d+(?:\.\d+)?)f?", a)
                    br["weight"] = lw.group(1) if lw else a
            # overloads: (s, cooldown, repeatType[, w]) / (s, cooldown, maxRepeats, w) /
            # (s, maxRepeats[, w]) / (s, repeatType[, w])
            if br["repeat"] != "CAN_REPEAT_FOREVER" or any(re.fullmatch(r"MoveRepeatType\.CanRepeatForever", a) for a in rest):
                if ints:
                    br["cooldown"] = ints[0]
            elif len(ints) == 2:
                br["cooldown"], br["max"], br["repeat"] = ints[0], ints[1], "CAN_REPEAT_X_TIMES"
            elif len(ints) == 1:
                br["max"], br["repeat"] = ints[0], "CAN_REPEAT_X_TIMES"
            states[owner]["branches"].append(br)
        for m in re.finditer(r"(\w+)\.AddState\(", stmt):
            owner = var_state.get(m.group(1))
            inside, _ = call_args(stmt, m.end() - 1)
            args = split_args(inside)
            if owner and args:
                states[owner]["branches"].append({"state": var_state.get(args[0], args[0]),
                                                  "cond": args[1] if len(args) > 1 else "true"})
        m = re.search(r"return new MonsterMoveStateMachine\(", stmt) or re.search(r"=> new MonsterMoveStateMachine\(", stmt)
        if m:
            inside, _ = call_args(stmt, m.end() - 1)
            args = split_args(inside)
            init_expr = args[1] if len(args) > 1 else ""
            initial = var_state.get(init_expr.strip(), None) or {"expr": init_expr,
                                                                  "vars": {v: var_state[v] for v in re.findall(r"\w+", init_expr) if v in var_state}}
        if re.match(r"return \(", stmt) and "MonsterMoveStateMachine" in stmt:
            initial = {"expr": stmt, "vars": {v: var_state[v] for v in re.findall(r"\w+", stmt) if v in var_state}}
    return {"states": states, "order": order, "initial": initial}


def parse_all() -> dict:
    out = {}
    files = {f.stem: f.read_text() for f in (NATIVE / "Models" / "Monsters").glob("*.cs")}
    for name, src in sorted(files.items()):
        chain = [src]
        base = re.search(r"class \w+ : (\w+)", src)
        while base and base.group(1) in files:
            chain.append(files[base.group(1)])
            base = re.search(r"class \w+ : (\w+)", files[base.group(1)])
        # Concrete subclasses (MysteriousKnight, the three Decimillipede
        # segments) can inherit the entire state machine and its numeric values.
        body = next((body for text in chain if (body := method_body(text, "GenerateMoveStateMachine")) is not None), None)
        if body is None:
            continue
        mach = parse_machine(body)
        mach["props"] = int_props(src, chain)
        out[slug(name)] = mach
    return out


def resolve(value, props, asc) -> int | None:
    """Value of an int property at an ascension level (bool kept for old callers: True = A9)."""
    if asc is True:
        asc = 9
    elif asc is False:
        asc = 0
    if value is None:
        return None
    v = str(value).strip()
    if re.fullmatch(r"-?\d+", v):
        return int(v)
    p = props.get(v)
    if not p or "expr" in p:
        return None
    if p["level"] == "ToughEnemies" and asc >= 8:
        return p["asc"]
    if p["level"] == "DeadlyEnemies" and asc >= 9:
        return p["asc"]
    if p["level"] not in (None, "ToughEnemies", "DeadlyEnemies"):
        return None
    return p["base"]


def compare(native: dict) -> list[str]:
    ours = json.loads((ROOT / "content" / "monsters.json").read_text())["monsters"]
    lines = []
    for key, mon in sorted(ours.items()):
        nkey = {"DECIMILLIPEDE_SEGMENT": "DECIMILLIPEDE_SEGMENT"}.get(key, key)
        n = native.get(nkey)
        if n is None:
            lines.append(f"{key}: no native state machine")
            continue
        issues = []
        ns, os_ = n["states"], mon["states"]
        only_ours = [s for s in os_ if s not in ns]
        only_native = [s for s in ns if s not in os_]
        if only_ours or only_native:
            issues.append(f"states only ours {only_ours} only native {only_native}")
        for sid, st in ns.items():
            o = os_.get(sid)
            if o is None:
                continue
            nk = {"MoveState": "move", "RandomBranchState": "random", "ConditionalBranchState": "cond"}[st["kind"]]
            if nk != o["kind"]:
                issues.append(f"{sid}: kind ours {o['kind']} native {nk}")
                continue
            if nk == "move":
                if (st.get("follow") or None) != (o.get("follow") or None):
                    issues.append(f"{sid}: follow ours {o.get('follow')} native {st.get('follow')}")
                na = [i for i in st["intents"] if "damage" in i]
                oa = [i for i in o.get("intents", []) if "ATTACK" in i["type"] or i["type"] == "DEATH_BLOW"]
                for a, b in zip(na, oa):
                    d = resolve(a["damage"], n["props"], False)
                    h = resolve(a.get("hits", 1), n["props"], False) if a["type"] == "MultiAttack" else 1
                    if d is not None and d != b["damage"]:
                        issues.append(f"{sid}: A0 damage ours {b['damage']} native {d}")
                    if h is not None and b.get("hits") is not None and h != b["hits"]:
                        issues.append(f"{sid}: hits ours {b['hits']} native {h}")
                if len(na) != len(oa):
                    issues.append(f"{sid}: attack intents ours {len(oa)} native {len(na)}")
            elif nk == "random":
                nb = [(b["state"], b["repeat"], b["max"] if b["repeat"] == "CAN_REPEAT_X_TIMES" else 1, b["weight"], b["cooldown"]) for b in st["branches"]]
                ob = [(b["state"], b["repeat"], b["max"] if b["repeat"] == "CAN_REPEAT_X_TIMES" else 1, str(b["weight"]).rstrip("0").rstrip(".") if "." in str(b["weight"]) else str(b["weight"]), b["cooldown"]) for b in o["branches"]]
                norm = lambda w: re.sub(r"f$", "", str(w)).rstrip("0").rstrip(".") if re.fullmatch(r"-?\d+(\.\d+)?f?", str(w)) else str(w)
                nb = [(a, r, m, norm(w), c) for a, r, m, w, c in nb]
                ob = [(a, r, m, norm(w), c) for a, r, m, w, c in ob]
                if nb != ob:
                    issues.append(f"{sid}: branches ours {ob} native {nb}")
            else:
                nt = [b["state"] for b in st["branches"]]
                ot = [b["state"] for b in o["branches"]]
                if nt != ot:
                    issues.append(f"{sid}: cond targets ours {ot} native {nt}")
        init = n["initial"]
        our_init = [s for s, _w in mon["initial"]]
        if isinstance(init, str):
            nst = ns.get(init, {})
            if nst.get("kind") == "MoveState":
                if our_init != [init]:
                    issues.append(f"initial: native MoveState {init}, ours {mon['initial']}")
            else:
                issues.append(f"initial: native {nst.get('kind')} {init}, ours sampled {mon['initial']}")
        else:
            issues.append(f"initial: native expression {init['expr'][:120]!r} vars {init.get('vars')}, ours {mon['initial']}")
        if issues:
            lines.append(f"{key}:")
            lines += [f"    {i}" for i in issues]
    return lines


def method_text(src: str, fn: str) -> str | None:
    m = re.search(r"\b(?:private|protected|public)[^\n]*\bTask\s+" + re.escape(fn) + r"\(", src)
    if not m:
        return None
    i = src.index("{", m.end())
    depth, j = 1, i + 1
    while depth and j < len(src):
        depth += {"{": 1, "}": -1}.get(src[j], 0)
        j += 1
    return src[i + 1:j - 1]


def native_effects(body: str, props: dict, asc: int = 0) -> list:
    """Effect ops of a native move body, in order, in the monsters.json op format
    (values at ascension `asc`; unresolved expressions are left as strings)."""
    ops = []
    text = " ".join(body.split())
    for m in re.finditer(r"PowerCmd\.Apply<(\w+)Power>\(|CreatureCmd\.GainBlock\(|CardPileCmd\.AddToCombatAndPreview<(\w+)>\(|CreatureCmd\.Heal\(", text):
        inside, _ = call_args(text, m.end() - 1)
        args = split_args(inside)
        if m.group(0).startswith("PowerCmd"):
            if len(args) < 3:
                ops.append(["power?", m.group(1), inside]); continue
            tgt = args[1]
            role = "S" if tgt in ("base.Creature", "Creature") else ("P" if tgt in ("targets", "base.Targets") or "Player" in tgt else "O")
            ops.append(["power", role, slug(m.group(1)), value(args[2], props, asc)])
        elif m.group(0).startswith("CreatureCmd.GainBlock"):
            ops.append(["block", value(args[1], props, asc) if len(args) > 1 else None])
        elif m.group(0).startswith("CardPileCmd"):
            pile = re.search(r"PileType\.(\w+)", inside)
            count = value(args[2], props, asc) if len(args) > 2 else 1
            ops.append(["card", (pile.group(1).lower() if pile else "?"), slug(m.group(2)), count])
        else:
            ops.append(["heal", value(args[1], props, asc) if len(args) > 1 else None])
    return ops


def value(expr: str, props: dict, asc: int = 0):
    if expr.strip().startswith("-") and not re.fullmatch(r"-\d+(\.\d+)?m?", expr.strip()):
        v = value(expr.strip()[1:], props, asc)
        return -v if isinstance(v, int) else expr.strip()
    e = expr.strip().rstrip("m")
    if re.fullmatch(r"-?\d+(\.\d+)?", e):
        return int(float(e))
    v = resolve(expr.strip(), props, asc)
    return v if v is not None else expr.strip()


def compare_effects(native_src: dict) -> list[str]:
    ours = json.loads((ROOT / "content" / "monsters.json").read_text())["monsters"]
    lines, same, diff = [], 0, 0
    for key, mon in sorted(ours.items()):
        n = native_src.get(key)
        if not n:
            continue
        for sid, st in n["mach"]["states"].items():
            if st["kind"] != "MoveState" or not st.get("fn"):
                continue
            body = method_text(n["src"], st["fn"])
            if body is None:
                continue
            nat = native_effects(body, n["mach"]["props"])
            our = []
            for op in mon.get("moves", {}).get(f"{sid}@A0") or []:
                if op[0] == "card" and our and our[-1][0] == "card" and our[-1][2] == op[2] and our[-1][1] == op[1]:
                    our[-1][3] += 1
                    continue
                our.append(list(op))
            ours_norm = [o for o in our if o[0] in ("power", "block", "card", "heal")]
            if sid not in mon["states"]:
                continue
            if ours_norm == nat:
                same += 1
            else:
                diff += 1
                lines.append(f"{key}.{sid}: ours {ours_norm} native {nat}")
    lines.append(f"moves with same effects {same}, different {diff}")
    return lines


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dump", type=pathlib.Path)
    ap.add_argument("--compare", action="store_true")
    ap.add_argument("--effects", action="store_true")
    args = ap.parse_args()
    native = parse_all()
    if args.dump:
        args.dump.write_text(json.dumps(native, indent=1))
    if args.compare:
        print("\n".join(compare(native)))
    if args.effects:
        srcs = {}
        for f in (NATIVE / "Models" / "Monsters").glob("*.cs"):
            if slug(f.stem) in native:
                srcs[slug(f.stem)] = {"src": f.read_text(), "mach": native[slug(f.stem)]}
        print("\n".join(compare_effects(srcs)))


if __name__ == "__main__":
    main()
