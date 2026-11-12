"""The Future of Potions: trade each kind of potion and record what is offered.

Native v0.111.0 (Models/Events/TheFutureOfPotions.cs):
  card rarity  Rare/Event potion -> Rare, Uncommon -> Uncommon, Common/Token -> Common
  card type    Rng.NextItem over [Attack, Skill, Power]; Common/Token potions drop Power
  reward       3 distinct cards of that rarity and type from the character pool, all upgraded

Usage (from the port root):  python validation/future-potions-fix-20261111/probe.py [seeds]
Prints one line per potion: trades that succeeded / raised, and the (rarity, type) of the offered cards.
"""
import collections
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "simulator"))
import sts2_sim as sim  # noqa: E402

rows = re.findall(r'\{CardId::\w+,\s*"[^"]*",\s*"[^"]*",\s*CardPool::(\w+),\s*-?\d+,\s*-?\d+,\s*CardType::(\w+),'
                  r'\s*TargetType::\w+,\s*Rarity::(\w+),', (ROOT / "simulator/include/sts2/cards_generated.inc").read_text())
CARD = {i: (rarity, ctype, pool) for i, (pool, ctype, rarity) in enumerate(rows)}
EVENT = next(e for e in range(sim.event_count()) if sim.event_info(e)[0] == "THE_FUTURE_OF_POTIONS")
AT = sim.RunActionType
seeds = int(sys.argv[1]) if len(sys.argv) > 1 else 300

print("ruleset", sim.ENGINE_RULESET_ID, "| seeds per potion", seeds)
for name in ("FoulPotion", "GlowwaterPotion", "PotionShapedRock", "BlockPotion", "Clarity", "CosmicConcoction"):
    pid = int(getattr(sim.PotionId, name))
    ok = raised = 0
    kinds = collections.Counter()
    upgraded = total = 0
    message = ""
    for seed in range(1, seeds + 1):
        rc = sim.RunContext()
        rc.init(seed, 0)
        rc.add_potion(pid)
        rc.add_potion(pid)
        assert rc.begin_event(EVENT)
        try:
            assert rc.step(int(AT.EVENT_CHOICE), 0)          # trade the first potion
        except RuntimeError as ex:
            raised += 1
            message = str(ex)
            continue
        ok += 1
        assert rc.step(int(AT.OPEN_CARD_REWARD), 0)
        cards = rc.offered
        ids = {int(c[0]) if isinstance(c, (tuple, list)) else int(c) for c in cards}
        assert len(cards) == 3 and len(ids) == 3, cards
        for c in cards:
            cid = int(c[0]) if isinstance(c, (tuple, list)) else int(c)
            rarity, ctype, pool = CARD[cid]
            assert pool == "IRONCLAD"
            kinds[(rarity, ctype)] += 1
            total += 1
            if isinstance(c, (tuple, list)) and len(c) > 1:
                upgraded += int(bool(c[1]))
    rarity = sim.potion_def(pid)
    print(f"{name:18s} table={rarity} ok={ok} raised={raised} {message}")
    print("   offered (rarity, type):", dict(sorted(kinds.items())), "| upgraded", upgraded, "of", total)
