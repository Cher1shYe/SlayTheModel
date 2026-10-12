#!/usr/bin/env python3
"""Readable digest of a Spire Codex replay journal (NDJSON).

Usage:
    python3 preview_replay.py data_samples/01_ironclad_a8_win_f711c572.ndjson
    python3 preview_replay.py <file> --head 80          # more opening events
    python3 preview_replay.py <file> --all-decisions    # every decision/outcome

Read-only: takes a path as an argument, writes nothing.
"""
import json
import sys
import collections
import argparse


def load(path):
    rows = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def fmt_event(e):
    """One-line human rendering of a replay event."""
    t = e.get("t", "?")
    fl = e.get("floor", "?")
    up = "+" if e.get("up") else ""
    if t == "room":
        return f"f{fl:<3} [ROOM]    {e.get('kind')} id={e.get('id')} coord={e.get('coord')}"
    if t == "room_exit":
        return f"f{fl:<3} [LEAVE]   {e.get('kind')}"
    if t == "draw":
        ts = " (turn start)" if e.get("turn_start") else ""
        return f"f{fl:<3}   draw    {e.get('id')}{ts}"
    if t == "play":
        auto = " [auto]" if e.get("auto") else ""
        return (f"f{fl:<3}   PLAY    {e.get('id')}{up} cost={e.get('cost_paid')}"
                f" -> {e.get('result_pile')} turn={e.get('turn')}{auto}")
    if t == "hit":
        return (f"f{fl:<3}   hit     {e.get('src')} -> {e.get('dst')} "
                f"dmg={e.get('dmg')} type={e.get('dmg_type')} blocked={e.get('blocked')}"
                f"{' KILL' if e.get('killed') else ''}")
    if t in ("power", "power_lost"):
        sign = "+" if t == "power" else "-"
        return f"f{fl:<3}   {t:<7} {e.get('id')} {sign}{e.get('amount')} on {e.get('tgt')}"
    if t == "energy":
        return f"f{fl:<3}   energy  {e.get('energy')}/{e.get('max')} src={e.get('src')}"
    if t == "block":
        return f"f{fl:<3}   block   {e.get('src')} +{e.get('n')} ({e.get('reason')})"
    if t == "intent":
        return f"f{fl:<3}   intent  {e.get('src')} -> {e.get('intents')} dmg={e.get('dmg')}"
    if t == "move":
        return f"f{fl:<3}   move    {e.get('src')} -> {e.get('intents')}"
    if t == "turn":
        return f"f{fl:<3}   TURN    round={e.get('round')} side={e.get('side')}"
    if t == "end_turn":
        return f"f{fl:<3}   endturn round={e.get('round')} side={e.get('side')}"
    if t == "death":
        return f"f{fl:<3}  DEATH    {e.get('tgt')} killed_by={e.get('killed_by')}"
    if t == "decision":
        return (f"f{fl:<3}  DECIDE   #{e.get('decision_id')} {e.get('decision_type')} "
                f"page={e.get('page_key')} presented={e.get('n_presented')}")
    if t == "outcome":
        return (f"f{fl:<3}  CHOSE    #{e.get('decision_id')} option_index={e.get('option_index')} "
                f"{e.get('option_id')} after {e.get('ms')}ms")
    if t == "pick":
        return f"f{fl:<3}   pick    {e.get('n_picked')} via {e.get('selector')} cards={e.get('cards')}"
    if t == "resolve":
        return f"f{fl:<3}   reward  {e.get('reward_kind')} gold={e.get('gold')}"
    if t == "gold":
        return f"f{fl:<3}   gold    {e.get('gold')}"
    if t == "upgrade":
        return f"f{fl:<3}   upgrade {e.get('id')}"
    if t == "shuffle":
        return f"f{fl:<3}   shuffle n_draw={e.get('n_draw')} order_c={e.get('order_c')}"
    if t == "exhaust":
        return f"f{fl:<3}   exhaust {e.get('id')}"
    if t == "deck":
        return f"f{fl:<3}   DECK    {len(e.get('cards', []))} cards"
    return f"f{fl:<3}   {t:<7} {json.dumps({k: v for k, v in e.items() if k not in ('t', 's', 'ms', 'act', 'floor')}, ensure_ascii=False)[:150]}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("path")
    ap.add_argument("--head", type=int, default=45, help="how many opening events to render")
    ap.add_argument("--all-decisions", action="store_true")
    args = ap.parse_args()

    rows = load(args.path)
    head = rows[0]
    events = rows[1:]

    print("=" * 78)
    print("HEADER")
    print("=" * 78)
    for k in ("character", "ascension", "seed", "build_id", "build_id_full", "game_mode",
              "starting_max_hp", "replay_version", "run_schema_version", "mod_version"):
        if k in head:
            print(f"  {k:<20} {head[k]}")
    mods = head.get("mods", [])
    gameplay = [m for m in mods if m.get("affects_gameplay")]
    print(f"  {'mods':<20} {len(mods)} loaded, {len(gameplay)} affect gameplay")
    for m in gameplay:
        print(f"      ! GAMEPLAY MOD: {m.get('id')} {m.get('version')}")

    counts = collections.Counter(e.get("t", "?") for e in events)
    print()
    print("=" * 78)
    print(f"EVENT TYPES  (total {len(events)} events)")
    print("=" * 78)
    for t, c in counts.most_common():
        print(f"  {t:<16} {c:>6}")

    print()
    print("=" * 78)
    print(f"OPENING EVENTS (first {args.head})")
    print("=" * 78)
    for e in events[:args.head]:
        print("  " + fmt_event(e))

    # decisions ------------------------------------------------------------
    decisions = {e["decision_id"]: e for e in events if e.get("t") == "decision"}
    outcomes = {}
    for e in events:
        if e.get("t") == "outcome" and e.get("outcome") == "chosen":
            outcomes.setdefault(e.get("decision_id"), e)
    print()
    print("=" * 78)
    print(f"DECISION POINTS  ({len(decisions)} presented, {len(outcomes)} chosen)")
    print("=" * 78)
    shown = list(decisions.items()) if args.all_decisions else list(decisions.items())[:8]
    for did, d in shown:
        o = outcomes.get(did, {})
        print(f"  #{did} floor {d.get('floor')} {d.get('decision_type')} "
              f"page={d.get('page_key')} presented={d.get('n_presented')} "
              f"selectable={d.get('n_selectable')}")
        for opt in d.get("options", [])[:6]:
            mark = ">>" if opt.get("option_index") == o.get("option_index") else "  "
            print(f"     {mark} [{opt.get('option_index')}] {opt.get('option_id')}")
        if o:
            print(f"     chose option_index={o.get('option_index')} after {o.get('ms')}ms")

    # one full combat ------------------------------------------------------
    plays = [i for i, e in enumerate(events) if e.get("t") == "play"]
    if plays:
        first = plays[0]
        start = first
        while start > 0 and events[start].get("t") not in ("turn", "room"):
            start -= 1
        end = plays[min(len(plays) - 1, 18)]
        end = min(len(events), end + 12)
        print()
        print("=" * 78)
        print(f"SAMPLE COMBAT (events {start}..{end})")
        print("=" * 78)
        for e in events[start:end]:
            print("  " + fmt_event(e))


if __name__ == "__main__":
    sys.exit(main())
