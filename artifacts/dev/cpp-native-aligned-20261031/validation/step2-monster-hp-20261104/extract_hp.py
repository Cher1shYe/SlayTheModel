"""Extract MonsterModel Min/MaxInitialHp from the local decompile and diff
against simulator/content/monsters.json sampled HP ranges.

The decompile is the local build 0861bfa1 (same release label v0.111.0 /
41cef1ea); it is *not* the target DLL 9cb4f1ad.  Results are labelled
accordingly and never presented as target-DLL differential evidence.

Usage:  python -I extract_hp.py <decompiled.cs> <monsters.json>
"""
from __future__ import annotations

import json
import re
import sys

ASC_TOUGH = 8


class Unknown(Exception):
    pass


def class_blocks(src: str):
    """Yield (name, base, body) for top-level class declarations."""
    pat = re.compile(r"^(\t)public (?:sealed |abstract |static |partial )*class (\w+)(?:<[^>]*>)? : ([\w.]+)", re.M)
    for m in pat.finditer(src):
        start = m.start()
        i = src.index("{", m.end())
        depth = 0
        j = i
        while j < len(src):
            c = src[j]
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        yield m.group(2), m.group(3), src[start:j + 1]


def prop_expr(body: str, name: str) -> str | None:
    m = re.search(r"override int " + name + r"\s*=>\s*([^;]+);", body)
    return m.group(1).strip() if m else None


TOKEN = re.compile(r"\s*(?:(\d+)|([A-Za-z_][A-Za-z0-9_.]*)|(.))")


def tokenize(expr: str):
    out = []
    pos = 0
    while pos < len(expr):
        m = TOKEN.match(expr, pos)
        if not m:
            raise Unknown(f"tokenize fail at {expr[pos:]!r}")
        pos = m.end()
        if m.group(1) is not None:
            out.append(("int", int(m.group(1))))
        elif m.group(2) is not None:
            out.append(("id", m.group(2)))
        elif m.group(3) is not None:
            if m.group(3) not in "+-*/(),":
                raise Unknown(f"bad char {m.group(3)!r} in {expr!r}")
            out.append(("op", m.group(3)))
    return out


class Evaluator:
    def __init__(self, classes: dict[str, str], bases: dict[str, str], asc: int):
        self.classes = classes
        self.bases = bases
        self.asc = asc
        self.stack: list[str] = []

    def value(self, cls: str, name: str) -> int:
        if (cls, name) in self.stack or cls not in self.classes:
            raise Unknown(f"unresolved {cls}.{name}")
        self.stack.append((cls, name))
        try:
            body = self.classes[cls]
            if name in ("MinInitialHp", "MaxInitialHp"):
                e = prop_expr(body, name)
                if e is None:
                    base = self.bases.get(cls)
                    if base in self.classes:
                        return self.value(base, name)
                    raise Unknown(f"no {name} in {cls}")
                return self.eval(e, cls)
            if name == "StockAmount" and "_stockOverrideAmount ?? 2" in body:
                # Axebot: default StockAmount is 2 when no encounter override.
                return 2
            # other int properties: `private int Foo => expr;`
            m = re.search(r"(?:private|public|protected|internal) int " + name +
                          r"\s*=>\s*([^;]+);", body)
            if m:
                return self.eval(m.group(1).strip(), cls)
            # simple constant fields
            m = re.search(r"private const int " + name + r"\s*=\s*(\d+);", body)
            if m:
                return int(m.group(1))
            raise Unknown(f"{cls}.{name} not found")
        finally:
            self.stack.pop()

    def eval(self, expr: str, cls: str) -> int:
        toks = tokenize(expr)
        pos = 0

        def peek():
            return toks[pos] if pos < len(toks) else (None, None)

        def take():
            nonlocal pos
            t = toks[pos]
            pos += 1
            return t

        def parse_expr():
            v = parse_term()
            while peek() == ("op", "+") or peek() == ("op", "-"):
                op = take()[1]
                r = parse_term()
                v = v + r if op == "+" else v - r
            return v

        def parse_term():
            v = parse_atom()
            while peek() == ("op", "*") or peek() == ("op", "/"):
                op = take()[1]
                r = parse_atom()
                v = v * r if op == "*" else v // r
            return v

        def parse_atom():
            k, val = take()
            if k == "int":
                return val
            if k == "op" and val == "(":
                v = parse_expr()
                t = take()
                if t != ("op", ")"):
                    raise Unknown(f"expected ) in {expr!r}")
                return v
            if k == "id":
                if val == "AscensionHelper.GetValueIfAscension":
                    t = take()
                    if t != ("op", "("):
                        raise Unknown("bad ascension call")
                    lvl = take()[1]
                    take()  # comma
                    a = parse_expr()
                    take()  # comma
                    b = parse_expr()
                    t = take()
                    if t != ("op", ")"):
                        raise Unknown("bad ascension call close")
                    if lvl == "AscensionLevel.ToughEnemies":
                        return a if self.asc >= ASC_TOUGH else b
                    raise Unknown(f"unhandled ascension level {lvl}")
                if "." in val:
                    raise Unknown(f"qualified id {val}")
                return self.value(cls, val)
            raise Unknown(f"unexpected token {k}:{val} in {expr!r}")

        v = parse_expr()
        if pos != len(toks):
            raise Unknown(f"trailing tokens in {expr!r}")
        return v


def camel_to_snake(name: str) -> str:
    s = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", name)
    s = re.sub(r"(?<=[A-Z])(?=[A-Z][a-z])", "_", s)
    return s.upper()


def main() -> None:
    src = open(sys.argv[1], encoding="utf-8-sig").read()
    dm = json.load(open(sys.argv[2], encoding="utf-8"))
    monsters = dm["monsters"]
    classes = {}
    bases = {}
    for name, base, body in class_blocks(src):
        classes[name] = body
        bases[name] = base
    by_key = {}
    for name, body in classes.items():
        by_key.setdefault(camel_to_snake(name), (name, body))

    print(f"classes with HP override: {sum(1 for b in classes.values() if 'override int MinInitialHp' in b)}")
    rows = []
    unmatched = []
    for key in sorted(monsters):
        hit = by_key.get(key)
        if hit is None:
            unmatched.append(key)
            continue
        cname, body = hit
        ev = Evaluator(classes, bases, 0)
        try:
            lo0, hi0 = ev.value(cname, "MinInitialHp"), ev.value(cname, "MaxInitialHp")
            ev8 = Evaluator(classes, bases, ASC_TOUGH)
            lo8, hi8 = ev8.value(cname, "MinInitialHp"), ev8.value(cname, "MaxInitialHp")
        except Unknown as e:
            unmatched.append(f"{key}: {e}")
            continue
        old = monsters[key]["hp"]
        old0 = old.get("A0") or old.get("A8")
        old8 = old.get("A8") or old0
        diff = old0 != [lo0, hi0] or old8 != [lo8, hi8]
        rows.append((key, old0, old8, [lo0, hi0], [lo8, hi8], diff))

    print(f"matched: {len(rows)} / {len(monsters)}; differing: {sum(1 for r in rows if r[5])}")
    for key, o0, o8, n0, n8, diff in rows:
        if diff:
            print(f"{key:32s} old A0={o0} A8={o8}  new A0={n0} A8={n8}")
    print("\nunmatched keys:")
    for u in unmatched:
        print(" ", u)

    if "--write" in sys.argv:
        for key, _o0, _o8, n0, n8, _diff in rows:
            monsters[key]["hp"] = {"A0": n0, "A8": n8}
            monsters[key]["hp_source"] = "decompiled_local_0861bfa1"
        with open(sys.argv[2], "w", encoding="utf-8", newline="\n") as f:
            json.dump(dm, f, indent=1, ensure_ascii=False)
            f.write("\n")
        print(f"\nwrote {len(rows)} HP ranges to {sys.argv[2]}")


if __name__ == "__main__":
    main()
