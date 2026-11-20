"""Derived observation features computed only from PublicState facts.

Observation checklist (docs/observation-checklist.md) items E (deck summary), C (draw
odds) and A5 (route summary). Every function here takes the public fact dict produced by
``public_obs._common`` for either backend (C++ simulator or native host) and nothing
else, so the simulator and the native client compute identical values with this one
shared implementation. Nothing here reads hidden order: the draw pile is used as a
multiset plus the explicitly revealed ``knownTopPosition`` entries.

Layout (append-only; ``FEATURE_VERSION`` in public_obs bumps with any change):
* deck summary -> global row columns ``DECK_OFFSET``..
* draw odds    -> combat player row columns ``DRAW_OFFSET``..
* route summary -> each map point row columns ``ROUTE_OFFSET``..
"""
from __future__ import annotations

from math import comb

DRAW_TYPES = ("Attack", "Skill", "Power", "Status", "Curse")
DRAW_WINDOWS = (1, 2, 5)  # next card, next two, a standard Ironclad hand

DECK_OFFSET = 32
DECK_WIDTH = 32
DRAW_OFFSET = 32
DRAW_WIDTH = 64
ROUTE_OFFSET = 18
ROUTE_WIDTH = 24


# --------------------------------------------------------------------------- E: deck

def deck_summary(cards) -> list[float]:
    """Composition of the permanent deck (pile == "deck"), all from visible card facts."""
    deck = [c for c in cards if c["pile"] == "deck"]
    n = len(deck)
    out = [0.0] * DECK_WIDTH
    out[0] = n / 50
    if not n:
        return out
    for i, kind in enumerate(DRAW_TYPES):
        count = sum(c["type"] == kind for c in deck)
        out[1 + i] = count / 20
        out[6 + i] = count / n
    unplayable = [c for c in deck if "Unplayable" in c["keywords"]]
    x_cost = [c for c in deck if c["costX"]]
    costed = [c for c in deck if not c["costX"] and "Unplayable" not in c["keywords"] and c["cost"] >= 0]
    out[11] = len(unplayable) / n
    out[12] = len(x_cost) / 10
    out[13] = (sum(c["cost"] for c in costed) / len(costed) / 3) if costed else 0.0
    out[14] = sum(c["cost"] == 0 for c in costed) / n
    out[15] = sum(c["cost"] >= 2 for c in costed) / n
    upgradable = [c for c in deck if c["maxUpgrade"] > 0]
    out[16] = (sum(c["upgrade"] > 0 for c in upgradable) / len(upgradable)) if upgradable else 0.0
    out[17] = sum(c["upgrade"] > 0 for c in deck) / 20
    # Printed damage/block (base + permanent bonuses already in the fact); the
    # combat-time modified values are checklist item A1, not this summary.
    out[18] = sum(c["damage"] for c in deck) / n / 10
    out[19] = sum(c["block"] for c in deck) / n / 10
    out[20] = sum(c["damage"] > 0 for c in deck) / n
    out[21] = sum(c["block"] > 0 for c in deck) / n
    out[22] = sum("Strike" in c["tags"] for c in deck) / 10
    out[23] = sum("Defend" in c["tags"] for c in deck) / 10
    out[24] = sum(c["target"] == "AllEnemies" for c in deck) / n
    out[25] = sum("Exhaust" in c["keywords"] for c in deck) / n
    out[26] = sum("Ethereal" in c["keywords"] for c in deck) / n
    out[27] = sum("Innate" in c["keywords"] for c in deck) / 10
    out[28] = sum("Retain" in c["keywords"] for c in deck) / 10
    out[29] = sum(c["enchantment"] is not None for c in deck) / 10
    out[30] = sum(bool(c["afflictions"]) for c in deck) / 10
    out[31] = sum(c["rarity"] == "Rare" for c in deck) / 10
    return out


# --------------------------------------------------------------------- C: draw odds

def _p_none(pool: int, hits: int, draws: int) -> float:
    """P(no hit) drawing ``draws`` cards without replacement from ``pool`` with ``hits`` hits."""
    if draws <= 0 or hits <= 0:
        return 1.0
    if draws > pool:
        draws = pool
    if pool - hits < draws:
        return 0.0
    return comb(pool - hits, draws) / comb(pool, draws)


def next_draw_odds(draw, discard, window: int, predicate):
    """(P(at least one), expected count) of cards satisfying ``predicate`` among the next
    ``window`` draws.

    ``draw`` / ``discard`` are visible card facts. Draw order is hidden except for cards
    with ``knownTopPosition >= 0`` (revealed from the top). Unknown draw slots are a
    uniform sample of the unknown draw cards. If the window runs past the draw pile, the
    rest comes from the shuffled discard pile (as the game reshuffles it into the draw
    pile). Cards created or moved during the draws are not modelled.
    """
    n = len(draw)
    from_draw = min(window, n)
    known = [c for c in draw if 0 <= c["knownTopPosition"] < from_draw]
    # Cards revealed deeper than the window cannot fill a top slot.
    unknown = [c for c in draw if c["knownTopPosition"] < 0]
    sure_hits = sum(bool(predicate(c)) for c in known)
    slots = from_draw - len(known)
    u_hits = sum(bool(predicate(c)) for c in unknown)
    expected = sure_hits + (slots * u_hits / len(unknown) if unknown and slots > 0 else 0.0)
    p_none = 1.0 if sure_hits == 0 else 0.0
    p_none *= _p_none(len(unknown), u_hits, slots)
    rest = window - from_draw
    if rest > 0 and discard:
        d_hits = sum(bool(predicate(c)) for c in discard)
        take = min(rest, len(discard))
        expected += take * d_hits / len(discard)
        p_none *= _p_none(len(discard), d_hits, take)
    return 1.0 - p_none, expected


def draw_odds(facts) -> list[float]:
    out = [0.0] * DRAW_WIDTH
    cards = facts["cards"]
    draw = [c for c in cards if c["pile"] == "draw"]
    discard = [c for c in cards if c["pile"] == "discard"]
    exhaust = [c for c in cards if c["pile"] == "exhaust"]
    out[0:3] = [len(draw) / 30, len(discard) / 30, len(exhaust) / 30]
    out[3] = sum(0 <= c["knownTopPosition"] for c in draw) / 5
    for i, kind in enumerate(DRAW_TYPES):
        out[4 + i] = sum(c["type"] == kind for c in draw) / 10
        out[9 + i] = sum(c["type"] == kind for c in discard) / 10
    playable = lambda c: "Unplayable" not in c["keywords"]
    predicates = [lambda c, k=k: c["type"] == k for k in DRAW_TYPES]
    predicates += [lambda c: c["damage"] > 0, lambda c: c["block"] > 0,
                   lambda c: playable(c) and not c["costX"] and c["cost"] == 0]
    pos = 14
    for window in DRAW_WINDOWS:
        for predicate in predicates:
            p_any, expected = next_draw_odds(draw, discard, window, predicate)
            out[pos:pos + 2] = [p_any, expected / window]
            pos += 2
    out[pos] = min(len(draw), 10) / 10  # cards left before the next reshuffle (capped)
    out[pos + 1] = float(len(draw) < 5)  # a standard 5-card draw would reshuffle
    return out


# ----------------------------------------------------------------- A5: route summary

_INF = 99


_ROUTE_CACHE: dict = {}
_ROUTE_CACHE_LIMIT = 256


def route_summary(points) -> dict[tuple[int, int], list[float]]:
    """Per map point, path statistics from that point (inclusive) to the end of the act.

    Uses only the visible map graph. Distances are in map steps; "before the next rest"
    counts nodes strictly before the first rest site on the path (the rest site itself
    excluded), or up to the boss when no rest site lies ahead. The result depends only on
    point types and edges, so it is cached on exactly those (visited/current/quests are
    not inputs); callers must not mutate the returned rows.
    """
    key = tuple((p["row"], p["col"], p["type"], tuple((c["row"], c["col"]) for c in p["children"])) for p in points)
    cached = _ROUTE_CACHE.get(key)
    if cached is None:
        if len(_ROUTE_CACHE) >= _ROUTE_CACHE_LIMIT:
            _ROUTE_CACHE.clear()
        cached = _ROUTE_CACHE[key] = _route_summary(points)
    return cached


def _route_summary(points):
    by_pos = {(p["row"], p["col"]): p for p in points}
    memo: dict[tuple[int, int], dict] = {}

    def stats(key):
        if key in memo:
            return memo[key]
        p = by_pos[key]
        t = p["type"]
        kids = [stats((c["row"], c["col"])) for c in p["children"] if (c["row"], c["col"]) in by_pos]
        is_rest, is_shop = t == "RestSite", t == "Shop"
        elite, monster, unknown = int(t == "Elite"), int(t == "Monster"), int(t == "Unknown")

        def best(field, fn, default):
            return fn(k[field] for k in kids) if kids else default
        s = {
            "boss": 0 if t == "Boss" else 1 + best("boss", min, _INF),
            "rest": 0 if is_rest else 1 + best("rest", min, _INF),
            "shop": 0 if is_shop else 1 + best("shop", min, _INF),
            "treasure": 0 if t == "Treasure" else 1 + best("treasure", min, _INF),
            "elite_rest_min": 0 if is_rest else elite + best("elite_rest_min", min, 0),
            "elite_rest_max": 0 if is_rest else elite + best("elite_rest_max", max, 0),
            "fight_rest_min": 0 if is_rest else monster + elite + best("fight_rest_min", min, 0),
            "fight_rest_max": 0 if is_rest else monster + elite + best("fight_rest_max", max, 0),
            "elite_min": elite + best("elite_min", min, 0),
            "elite_max": elite + best("elite_max", max, 0),
            "monster_min": monster + best("monster_min", min, 0),
            "monster_max": monster + best("monster_max", max, 0),
            "unknown_max": unknown + best("unknown_max", max, 0),
            "rest_max": int(is_rest) + best("rest_max", max, 0),
            "shop_max": int(is_shop) + best("shop_max", max, 0),
            "paths": max(1, sum(k["paths"] for k in kids)) if kids else 1,
        }
        memo[key] = s
        return s

    out = {}
    for key in by_pos:
        s = stats(key)
        row = [0.0] * ROUTE_WIDTH
        for i, name in enumerate(("boss", "rest", "shop", "treasure")):
            reachable = s[name] < _INF
            row[2 * i] = float(reachable)
            row[2 * i + 1] = (s[name] / 16) if reachable else 0.0
        row[8:15] = [s["elite_rest_min"] / 5, s["elite_rest_max"] / 5, s["fight_rest_min"] / 10,
                     s["fight_rest_max"] / 10, s["elite_min"] / 5, s["elite_max"] / 5, s["monster_min"] / 10]
        row[15:19] = [s["monster_max"] / 10, s["unknown_max"] / 10, s["rest_max"] / 5, s["shop_max"] / 5]
        row[19] = min(s["paths"], 1000) / 1000
        out[key] = row
    return out


# ------------------------------------------------------------- D: act encounters

ACT_OFFSET = 64   # global row
ACT_WIDTH = 16


def _next_encounter_odds(seen, phases, tags):
    """Distribution of the next encounter drawn from an act room list.

    ``seen`` is the public, ordered history of encounters already entered from this
    list. ``phases`` is ``[(pool, length), ...]``: ActModel.GenerateRooms fills the list
    phase by phase from a grab bag per phase (refilled with the whole pool when empty),
    each pick uniform among bag items that are not the previous list entry and share no
    tag with it, falling back to any bag item. Returns ``({encounter: p}, remaining)``
    where ``remaining`` is the multiset left in the current bag (empty if unknown).
    """
    k = len(seen)
    start = 0
    for pool, length in phases:
        if length is None or k < start + length:
            break
        start += length
    else:
        return {}, []   # past the generated list (RoomSet wraps): not modelled
    if not pool:
        return {}, []
    cycle = start + ((k - start) // len(pool)) * len(pool)
    remaining = list(pool)
    for name in seen[cycle:k]:
        if name in remaining:
            remaining.remove(name)
    if not remaining:
        remaining = list(pool)
    previous = seen[k - 1] if k else None
    prev_tags = set(tags.get(previous, ())) if previous else set()
    eligible = [e for e in remaining if e != previous and not (prev_tags & set(tags.get(e, ())))]
    if not eligible:
        eligible = remaining
    odds = {}
    for e in eligible:
        odds[e] = odds.get(e, 0.0) + 1.0 / len(eligible)
    return odds, remaining


_ACT_CACHE: dict = {}


def act_encounters(run, acts, tags):
    """Cached on the public history (the only input besides the static catalog); callers
    must not mutate the returned lists."""
    key = (run["currentAct"], run["actNormalEncounters"], run["actEliteEncounters"], id(acts), id(tags))
    cached = _ACT_CACHE.get(key)
    if cached is None:
        if len(_ACT_CACHE) >= 512:
            _ACT_CACHE.clear()
        cached = _ACT_CACHE[key] = _act_encounters(run, acts, tags)
    return cached


def _act_encounters(run, acts, tags):
    """Checklist D from public history + static pool rules (never the hidden bag).

    Returns (summary row, {encounter: entity features}) where the entity features are
    [seen count, last fought, weak, regular, elite, P(next normal), P(next elite), in current bag].
    """
    summary = [0.0] * ACT_WIDTH
    rows = {}
    normal, elite = run["actNormalEncounters"], run["actEliteEncounters"]
    if normal is None or elite is None:   # pre-D native capture (explicit legacy mode only)
        summary[15] = 1.0
        return summary, rows
    act = acts[run["currentAct"]]
    w = act["weakCount"]
    n_odds, n_left = _next_encounter_odds(normal, [(act["weak"], w), (act["normal"], None)], tags)
    e_odds, e_left = _next_encounter_odds(elite, [(act["elite"], None)], tags)
    summary[0:8] = [len(normal) / 15, len(elite) / 5, max(0, w - len(normal)) / 3, float(len(normal) < w),
                    len(n_left) / 12, len(e_left) / 3, len(n_odds) / 12, len(e_odds) / 3]
    last = {normal[-1] if normal else None, elite[-1] if elite else None}
    weak, regular, elites = set(act["weak"]), set(act["normal"]), set(act["elite"])
    for name in set(normal) | set(elite) | set(n_odds) | set(e_odds):
        rows[name] = [(normal.count(name) + elite.count(name)) / 3, float(name in last), float(name in weak),
                      float(name in regular), float(name in elites), n_odds.get(name, 0.0), e_odds.get(name, 0.0),
                      float(name in n_left or name in e_left)]
    return summary, rows
