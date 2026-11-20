"""Full B (action preview) audit against the simulator (DEVLOG 35-37).

Every play whose preview says known must match the engine exactly: energy, block, HP lost,
damage (enemies without special powers) and, when nothing is unknown, the end-turn loss after
it. Prints per-card counts and up to 3 examples of each mismatch.

    cd train && PYTHONPATH=.:.. python scripts/audit_action_preview.py FIRST_SEED END_SEED [CARDS] [RELICS]

CARDS / RELICS: comma-separated simulator names injected into every run (each card twice), e.g.
    python scripts/audit_action_preview.py 8000 8030 BLOODLETTING,SECOND_WIND ORNAMENTAL_FAN,GREMLIN_HORN
The four development groups: 7000-7060 plain; 8000-8030 with the 24 special cards of
tests/test_public_tactics.py (+ STOKE); 8100-8125 and 8200-8225 with those cards plus the two
relic groups listed in DEVLOG 35. Known simulator gaps are skipped (``simgap``).
"""
import sys, collections, random
sys.path.insert(0, "tests")
from test_public_tactics import hp_after_end_turn, simple_enemy_turn
from spire_rl import public_obs as p
from spire_rl import public_tactics as t
from spire_rl.sim import sim
QUIET = {"POWER.VULNERABLE_POWER","POWER.WEAK_POWER","POWER.STRENGTH_POWER","POWER.ARTIFACT_POWER","POWER.RITUAL_POWER","POWER.PLATING_POWER"}
CARDS = sys.argv[3].split(",") if len(sys.argv) > 3 and sys.argv[3] else []
RELICS = sys.argv[4].split(",") if len(sys.argv) > 4 and sys.argv[4] else []

def states(seeds, steps=1500, bias=0.9):
    for seed in seeds:
        rng = random.Random(seed)
        rc = sim.RunContext(); rc.init(seed, 10)
        for name in CARDS:
            for _ in range(2): rc.add_card(CARD_ID[name], rng.random() < 0.5)
        for name in RELICS:
            rc.add_relic(int(getattr(sim.RelicId, name)))
        for _ in range(steps):
            if rc.is_terminal: break
            try:
                s = p.from_simulator(rc)
            except RuntimeError as e:
                print("skip seed", seed, e); break
            if not s.actions: break
            if s.facts["screen"] == "combat": yield rc, s
            plays = [i for i, a in enumerate(s.actions) if a.key.kind == "play"]
            pool = plays if plays and rng.random() < bias else range(len(s.actions))
            p.step_simulator(rc, s, rng.choice(list(pool)))

CARD_ID = {sim.card_name(i).upper().replace(" ", "_").replace("'", "").replace("-", "_"): i for i in range(sim.card_count())}
stats = collections.defaultdict(collections.Counter); ex = collections.defaultdict(list)
for rc, s in states(range(int(sys.argv[1]), int(sys.argv[2]))):
    f = s.facts
    quiet = all({pw[0] for pw in e["powers"]} <= QUIET for e in f["enemies"] if e["alive"])
    pv_all = t.action_preview(s)
    for index, card, target in t._plays(s):
        pv = pv_all[index]; st = stats[card["modelId"]]; st["n"] += 1
        if not pv["known"]: st["unk"] += 1; continue
        if not quiet: st["noisy"] += 1; continue
        copy = rc.clone(); p.step_simulator(copy, s, index)
        if copy.is_terminal or copy.screen != sim.RunScreen.COMBAT: continue
        after = p.from_simulator(copy); a = after.facts
        if a["screen"] != "combat": continue
        def pv_kill(e, dmg=t._Play(card, target, f).run().damage):
            return e["hittable"] and dmg.get(e["order"], 0) >= e["hp"] + e["block"]
        d = {}
        if a["player"]["energy"] != pv["energy_after"]: d["energy"] = (pv["energy_after"], a["player"]["energy"])
        gb = a["player"]["block"] - f["player"]["block"]
        # Block may be spent by own HP-loss? (unblockable: no). Compare directly.
        if gb != pv["block"]: d["block"] = (pv["block"], gb)
        hl = f["player"]["hp"] - a["player"]["hp"]
        if hl != pv["self_hp_loss"]: d["selfhp"] = (pv["self_hp_loss"], hl)
        if len(a["enemies"]) == len(f["enemies"]):
            tot = sum((e["hp"]+e["block"]) - (max(x["hp"],0)+x["block"]) for e in f["enemies"] for x in a["enemies"] if x["order"]==e["order"] and e["hittable"])
            random_part = card["target"] == "RandomEnemy" or any(r["modelId"] in ("RELIC.KUSARIGAMA","RELIC.FORGOTTEN_SOUL") for r in f["relics"]) or any(pw[0]=="POWER.JUGGERNAUT_POWER" for pw in f["powers"])
            revived = any(x["order"] == e["order"] and x["alive"] and pv_kill(e) for e in f["enemies"] for x in a["enemies"])
            if not revived and (not random_part or sum(e["hittable"] for e in f["enemies"]) == 1) and abs(tot - pv["total_damage"]) > 1e-6:
                d["damage"] = (pv["total_damage"], tot)
        # Known simulator gaps (reported separately): Intimidating Helmet fires once per card instead of
        # once per replayed play.
        if "RELIC.INTIMIDATING_HELMET" in [r["modelId"] for r in f["relics"]] and (
                card["enchantedReplay"] or any(pw[0] in ("POWER.ONE_TWO_PUNCH_POWER", "POWER.DUPLICATION_POWER", "POWER.BURST_POWER") for pw in f["powers"])
                or any(r["modelId"] == "RELIC.THROWING_AXE" and r["status"] == "Active" for r in f["relics"])):
            st["simgap"] += 1; continue
        st["cmp"] += 1
        if card["modelId"] not in ("CARD.INFERNO", "CARD.CRIMSON_MANTLE") and not any(pw[0] == "POWER.CRIMSON_MANTLE_POWER" for pw in f["powers"]) and not pv["unknown"] and simple_enemy_turn(f) and after.facts["screen"] == "combat" and any(x.key.kind == "end_turn" for x in after.actions):
            actual = hp_after_end_turn(copy, after)
            if actual is not None:
                st["cmp_end"] += 1
                if actual != min(pv["end_turn_loss"], a["player"]["hp"]): d["end"] = (pv["end_turn_loss"], actual)
        for k in d: st[k] += 1
        if d and len(ex[card["modelId"]]) < 3:
            ex[card["modelId"]].append((d, [r["modelId"][6:] for r in f["relics"]], [(pw[0][6:], pw[1]) for pw in f["powers"]], card["enchantedReplay"], card["upgrade"]))
bad = {k: v for k, v in stats.items() if any(v[x] for x in ("energy","block","selfhp","damage","end"))}
n = sum(v["n"] for v in stats.values())
print("cards", len(stats), "plays", n, "compared", sum(v["cmp"] for v in stats.values()), "end", sum(v["cmp_end"] for v in stats.values()), "unknown", sum(v["unk"] for v in stats.values()))
print("unknown by card:", sorted(((k[5:], v["unk"]) for k, v in stats.items() if v["unk"]), key=lambda x: -x[1])[:25])
for k, v in sorted(bad.items(), key=lambda kv: -kv[1]["n"]):
    print("\n", k, dict(v))
    for e in ex[k]: print("    ", e)
