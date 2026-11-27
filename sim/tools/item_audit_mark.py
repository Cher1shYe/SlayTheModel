#!/usr/bin/env python3
"""Record line-by-line audit verdicts in docs/item-audit.json (DEVLOG 57+).

    python sim/tools/item_audit_mark.py relic ok AKABEKO ANCHOR ... [--note "..."]
    python sim/tools/item_audit_mark.py relic fixed TEA_OF_DISCOURTESY --note "random insert"
    python sim/tools/item_audit_mark.py power ok VIGOR_POWER     # power ledger (next audit)
    python sim/tools/item_audit_mark.py summary

status: ok (effect matches native line by line), fixed (differed, simulator corrected),
native-kept (looks odd but matches native), not-implemented, out-of-scope (cannot be obtained /
no effect), open (known difference not yet fixed).
"""
import json, sys, datetime
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
PATH = ROOT / "docs/item-audit.json"
STATUSES = {"ok", "fixed", "native-kept", "not-implemented", "out-of-scope", "open"}

def load():
    if PATH.exists():
        return json.loads(PATH.read_text())
    return {"schema": "item-audit/1", "native": "v0.111.0 / 41cef1ea", "items": {"relic": {}, "card": {}, "potion": {}}}

def main(argv):
    d = load()
    if argv[0] == "summary":
        for kind, items in d["items"].items():
            counts = {}
            for v in items.values():
                counts[v["status"]] = counts.get(v["status"], 0) + 1
            print(kind, len(items), counts)
        return
    kind, status, *rest = argv
    note = ""
    if "--note" in rest:
        i = rest.index("--note"); note = rest[i + 1]; rest = rest[:i] + rest[i + 2:]
    assert status in STATUSES, status
    ruleset = json.loads((ROOT / "sim/PORT_SOURCE.json").read_text()).get("engine_ruleset", "")
    assert kind in ("relic", "card", "potion", "power"), kind
    d["items"].setdefault(kind, {})
    for key in rest:
        d["items"][kind][key] = {"status": status, "date": datetime.date.today().isoformat(),
                                 "ruleset": ruleset, **({"note": note} if note else {})}
    d["items"][kind] = dict(sorted(d["items"][kind].items()))
    PATH.write_text(json.dumps(d, indent=1, ensure_ascii=False) + "\n")

if __name__ == "__main__":
    main(sys.argv[1:])
