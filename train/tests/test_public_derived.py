"""Derived public features (checklist E, C, A5): exact math, layout and NoSL."""
from fractions import Fraction
from itertools import permutations
import random

import numpy as np
import pytest

from spire_rl import public_derived as d
from spire_rl import public_obs as p
from spire_rl.sim import sim


def card(kind="Attack", known=-1, pile="draw", **extra):
    base = {"type": kind, "knownTopPosition": known, "pile": pile, "keywords": (), "costX": False, "cost": 1,
            "damage": 6 if kind == "Attack" else 0, "block": 5 if kind == "Skill" else 0}
    base.update(extra)
    return base


def brute_force(draw, discard, window, predicate):
    """Enumerate every hidden order consistent with the revealed top positions."""
    n = len(draw)
    fixed = {c["knownTopPosition"]: c for c in draw if c["knownTopPosition"] >= 0}
    free = [c for c in draw if c["knownTopPosition"] < 0]
    free_slots = [i for i in range(n) if i not in fixed]
    outcomes = []
    for order in permutations(range(len(free))):
        pile = [None] * n
        for i, c in fixed.items():
            pile[i] = c
        for slot, j in zip(free_slots, order):
            pile[slot] = free[j]
        tails = [()] if window <= n else list(permutations(discard))
        for tail in tails:
            drawn = (pile + list(tail))[:window]
            outcomes.append(sum(bool(predicate(c)) for c in drawn))
    total = len(outcomes)
    return Fraction(sum(x > 0 for x in outcomes), total), Fraction(sum(outcomes), total)


@pytest.mark.parametrize("window", [1, 2, 3, 5])
def test_draw_odds_match_enumeration_with_known_tops_and_reshuffle(window):
    rng = random.Random(window)
    for trial in range(40):
        n = rng.randrange(0, 5)
        draw = [card(rng.choice(d.DRAW_TYPES)) for _ in range(n)]
        for pos in rng.sample(range(n), rng.randrange(0, n + 1)) if n else []:
            draw[rng.choice([i for i, c in enumerate(draw) if c["knownTopPosition"] < 0])]["knownTopPosition"] = pos
        discard = [card(rng.choice(d.DRAW_TYPES), pile="discard") for _ in range(rng.randrange(0, 4))]
        for kind in ("Attack", "Curse"):
            pred = lambda c, k=kind: c["type"] == k
            got_p, got_e = d.next_draw_odds(draw, discard, window, pred)
            want_p, want_e = brute_force(draw, discard, window, pred)
            assert got_p == pytest.approx(float(want_p)), (trial, kind)
            assert got_e == pytest.approx(float(want_e)), (trial, kind)


def test_known_card_deeper_than_window_never_fills_a_top_slot():
    draw = [card("Curse", known=2), card("Attack"), card("Attack")]
    p_any, expected = d.next_draw_odds(draw, [], 2, lambda c: c["type"] == "Curse")
    assert p_any == 0 and expected == 0


def point(row, col, kind, *children):
    return {"row": row, "col": col, "type": kind, "children": [{"row": r, "col": c} for r, c in children]}


def test_route_summary_on_a_small_map():
    #   row0: M(0,0) -> E(1,0) -> R(2,0) -> B(3,0)
    #              \-> M(1,1) -> E(2,1) -/
    points = [point(0, 0, "Monster", (1, 0), (1, 1)), point(1, 0, "Elite", (2, 0)), point(1, 1, "Monster", (2, 1)),
              point(2, 0, "RestSite", (3, 0)), point(2, 1, "Elite", (3, 0)), point(3, 0, "Boss")]
    routes = d.route_summary(points)
    start = routes[(0, 0)]
    assert start[0:2] == [1.0, 3 / 16]                       # boss 3 steps away
    assert start[2:4] == [1.0, 2 / 16]                       # nearest rest 2 steps (via the elite)
    assert start[4] == 0.0                                   # no shop ahead
    assert start[8:12] == [1 / 5, 1 / 5, 2 / 10, 3 / 10]     # elites/fights before the next rest (or boss)
    assert start[12:14] == [1 / 5, 1 / 5]                    # exactly one elite on every path
    assert start[19] == 2 / 1000                             # two paths
    assert routes[(2, 0)][2:4] == [1.0, 0.0]                 # standing on a rest site


def first_combat():
    rc = sim.RunContext(); rc.init_seed("PARITY0001", 10)
    for _ in range(12):
        if rc.screen == sim.RunScreen.COMBAT:
            return rc
        s = p.from_simulator(rc)
        p.step_simulator(rc, s, next((i for i, a in enumerate(s.actions)
                                      if a.key.kind == "neow_relic" and a.key.args[0] == "GOLDEN_PEARL"), 0))
    raise AssertionError("no combat")


def test_encoded_layout_and_starting_deck_values():
    rc = first_combat()
    state = p.from_simulator(rc)
    obs = p.encode(state)
    deck = obs.global_row[d.DECK_OFFSET:d.DECK_OFFSET + d.DECK_WIDTH]
    assert deck[0] == pytest.approx(11 / 50)                 # A10 Ironclad: 10 starters + Ascender's Bane
    assert deck[22] == pytest.approx(5 / 10) and deck[23] == pytest.approx(4 / 10)
    assert deck[5] == pytest.approx(1 / 20)                  # one curse
    draw = obs.player_row[d.DRAW_OFFSET:d.DRAW_OFFSET + d.DRAW_WIDTH]
    n_draw = sum(c["pile"] == "draw" for c in state.facts["cards"])
    assert draw[0] == pytest.approx(n_draw / 30)
    np.testing.assert_array_equal(obs.global_row, obs.num[0])
    maps = [i for i, k in enumerate(obs.kind) if k == 5]
    assert maps and all(obs.num[i, d.ROUTE_OFFSET] == 1.0 for i in maps if obs.num[i, 0] < 16 / 18)


def test_derived_features_ignore_hidden_draw_order():
    rc = first_combat()
    base = p.encode(p.from_simulator(rc))
    original, changed = list(rc.battle.draw), False
    for seed in range(1, 8):
        copy = rc.clone(); copy.battle.resample_hidden(seed)
        changed |= list(copy.battle.draw) != original
        other = p.encode(p.from_simulator(copy))
        np.testing.assert_array_equal(base.player_row, other.player_row)
        np.testing.assert_array_equal(base.global_row, other.global_row)
    assert changed


def test_random_runs_keep_derived_features_finite_and_bounded():
    rng = random.Random(3)
    for seed in range(3):
        rc = sim.RunContext(); rc.init(910 + seed, 10)
        for _ in range(400):
            if rc.is_terminal:
                break
            s = p.from_simulator(rc)
            if not s.actions:
                break
            o = p.encode(s)
            for block in (o.global_row[d.DECK_OFFSET:d.DECK_OFFSET + d.DECK_WIDTH],
                          o.player_row[d.DRAW_OFFSET:d.DRAW_OFFSET + d.DRAW_WIDTH],
                          o.num[o.kind == 5][:, d.ROUTE_OFFSET:d.ROUTE_OFFSET + d.ROUTE_WIDTH]):
                assert np.isfinite(block).all() and np.abs(block).max(initial=0) <= 5
            p.step_simulator(rc, s, rng.randrange(len(s.actions)))


def test_checkpoint_with_other_feature_version_is_rejected(tmp_path, monkeypatch):
    from spire_rl.net import UnifiedNet, UnifiedNetConfig, save, load
    net = UnifiedNet(UnifiedNetConfig(dim=32, ctx_layers=1, combat_layers=1, heads=2, observation_schema=p.SCHEMA_ID))
    save(tmp_path / "a.pt", net)
    load(tmp_path / "a.pt")
    monkeypatch.setattr(p, "FEATURE_VERSION", p.FEATURE_VERSION + 1)
    with pytest.raises(ValueError):
        load(tmp_path / "a.pt")


# ------------------------------------------------------------- D: act encounters

ACTS, TAGS = p._CATALOG["acts"], p._CATALOG["encounterTags"]


def run_facts(normal, elite=(), act="ACT.OVERGROWTH"):
    return {"currentAct": act, "actNormalEncounters": tuple(normal), "actEliteEncounters": tuple(elite)}


def test_weak_phase_excludes_drawn_and_regular_phase_respects_previous_tags():
    E = lambda name: "ENCOUNTER." + name
    _, rows = d.act_encounters(run_facts([E("SLIMES_WEAK")]), ACTS, TAGS)
    nxt = {k: v[5] for k, v in rows.items() if v[5] > 0}
    assert nxt == {E(x): pytest.approx(1 / 3) for x in ("FUZZY_WURM_CRAWLER_WEAK", "NIBBITS_WEAK", "SHRINKER_BEETLE_WEAK")}
    # First regular pick after a Slimes-tagged weak fight: Slimes-tagged regulars are excluded.
    history = [E("NIBBITS_WEAK"), E("SHRINKER_BEETLE_WEAK"), E("SLIMES_WEAK")]
    summary, rows = d.act_encounters(run_facts(history), ACTS, TAGS)
    nxt = {k for k, v in rows.items() if v[5] > 0}
    assert nxt == set(ACTS["ACT.OVERGROWTH"]["normal"]) - {E("SLIMES_NORMAL"), E("FLYCONID_NORMAL"), E("SLITHERING_STRANGLER_NORMAL")}
    assert summary[3] == 0.0 and summary[2] == 0.0          # weak phase over
    assert sum(v[5] for v in rows.values()) == pytest.approx(1.0)


def test_elite_bag_refills_after_a_full_cycle():
    E = lambda name: "ENCOUNTER." + name
    elites = ACTS["ACT.OVERGROWTH"]["elite"]
    _, rows = d.act_encounters(run_facts([], elites), ACTS, TAGS)
    nxt = {k: v[6] for k, v in rows.items() if v[6] > 0}
    # New bag: everything except the immediately previous elite.
    assert set(nxt) == set(elites) - {elites[-1]}
    _, rows = d.act_encounters(run_facts([], elites[:2]), ACTS, TAGS)
    assert {k for k, v in rows.items() if v[6] > 0} == {elites[2]}


def test_legacy_capture_marks_history_unknown_and_live_states_require_it():
    summary, rows = d.act_encounters({"currentAct": "ACT.OVERGROWTH", "actNormalEncounters": None,
                                      "actEliteEncounters": None}, ACTS, TAGS)
    assert summary[15] == 1.0 and rows == {}
    rc = sim.RunContext(); rc.init_seed("PARITY0001", 10)
    raw = sim.public_model_state(rc)
    assert raw["run"]["actNormalEncounters"] == [] and raw["run"]["actEliteEncounters"] == []


def test_every_entered_encounter_was_predicted_possible():
    """Over random simulator runs, the encounter actually entered next always had positive
    predicted probability, and each prediction is a distribution (C++ bag vs shared rules)."""
    rng = random.Random(11)
    checked = {"normal": 0, "elite": 0}
    for seed in range(40):
        rc = sim.RunContext(); rc.init(7000 + seed, 10)
        prev = None
        for _ in range(1500):
            if rc.is_terminal:
                break
            s = p.from_simulator(rc)
            if not s.actions:
                break
            run = s.facts["run"]
            if prev is not None and prev[0]["act"] == run["act"]:
                for kind, key, col in (("normal", "actNormalEncounters", 5), ("elite", "actEliteEncounters", 6)):
                    before, after = prev[0][key], run[key]
                    if len(after) == len(before) + 1:
                        odds = {k: v[col] for k, v in prev[1].items()}
                        assert sum(odds.values()) == pytest.approx(1.0)
                        assert odds.get(after[-1], 0.0) > 0, (seed, kind, before, after[-1])
                        checked[kind] += 1
            prev = (run, d.act_encounters(run, ACTS, TAGS)[1])
            plays = [i for i, a in enumerate(s.actions) if a.key.kind == "play"]
            moves = [i for i, a in enumerate(s.actions) if a.key.kind == "move"
                     and any(pt["row"] == a.key.args[1] and pt["col"] == a.key.args[0] and pt["type"] == "Elite"
                             for pt in s.facts["map"])]
            pool = plays if plays and rng.random() < 0.85 else (moves if moves and rng.random() < 0.5 else range(len(s.actions)))
            p.step_simulator(rc, s, rng.choice(list(pool)))
    assert checked["normal"] > 40 and checked["elite"] > 3, checked


# ------------------------------------------------------------- A6: selection purpose

def test_selection_purpose_tables_match_and_reach_the_encoding():
    import re
    from pathlib import Path
    src = (Path(__file__).resolve().parents[2] / "sim/bindings/public_view.inc").read_text()
    exported = re.findall(r'"((?:combat|deck)\.[a-z_]+)"', src)
    assert set(exported) | {"none"} == set(p.PURPOSES) and len(set(exported)) == len(exported), \
        "C++ purpose strings must equal public_obs.PURPOSES (append-only)"
    # Every ChoiceOp enumerator maps to its own combat purpose (enumerators may share a line).
    header = (Path(__file__).resolve().parents[2] / "sim/include/sts2/battle.h").read_text()
    body = re.sub(r"//[^\n]*", "", re.search(r"enum class ChoiceOp[^{]*\{(.*?)\};", header, re.S)[1])
    names = [w.strip() for w in body.split(",") if w.strip()]
    purposes = sim.choice_purposes()
    assert len(purposes) == len(names) and len(set(purposes)) == len(purposes), (names, purposes)
    assert purposes[0] == "none" and all(x in p.PURPOSES for x in purposes)
    assert dict(zip(names, purposes))["GAMBLING_CHIP"] == "combat.gambling_chip"
    assert dict(zip(names, purposes))["KNOWLEDGE_CURSE"] == "combat.knowledge_curse"
    rng = random.Random(9)
    seen = set()
    for seed in range(25):
        rc = sim.RunContext(); rc.init(8000 + seed, 10)
        for _ in range(1200):
            if rc.is_terminal:
                break
            s = p.from_simulator(rc)
            if not s.actions:
                break
            if s.facts["decision"] is not None:
                purpose = s.facts["decision"]["purpose"]
                o = p.encode(s)
                ctx = o.num[1]
                assert ctx[360 + p.PURPOSES.index(purpose)] == 1 and ctx[360:424].sum() == 1
                assert ctx[424 + s.facts["decision"]["service"]] == 1
                seen.add(purpose)
            p.step_simulator(rc, s, rng.randrange(len(s.actions)))
    assert {"combat.upgrade", "deck.transform"} <= seen, seen
