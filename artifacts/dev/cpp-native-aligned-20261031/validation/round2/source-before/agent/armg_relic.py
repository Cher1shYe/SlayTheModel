"""Optional relic priorities for the ArmG non-combat policy.

The rules only select among actions the simulator already marks legal. The
simulator retains responsibility for prices, capacity, stock and side effects.
STS2 Ancients do not use STS1's boss-relic screen, so the energy preference
applies only to a visible Ancient offer that really supplies energy in the
current simulator. Enabling these rules changes the policy distribution and
should be evaluated against the unmodified ArmG on matched seeds.
"""
from __future__ import annotations

from .common import RACT, SCREEN, sim


ANCIENT_EVENTS = frozenset({"NEOW", "DARV", "OROBAS", "PAEL", "TEZCATARA",
                            "NONUPEIPE", "TANX", "VAKUU"})

# Mirrors run_energy_bonus in simulator/src/relics.cpp. Pumpkin Candle lasts
# only the current act; all the other listed relics add energy each turn while
# owned. Several also have important downsides, which this energy-first
# baseline intentionally does not attempt to model.
ENERGY_RELIC_NAMES = (
    "ECTOPLASM", "BLESSED_ANTLER", "BLOOD_SOAKED_ROSE",
    "PHILOSOPHERS_STONE", "PRISMATIC_GEM", "SPIKED_GAUNTLETS",
    "VELVET_CHOKER", "WHISPERING_EARRING", "SOZU", "PUMPKIN_CANDLE",
)
ENERGY_RELIC_IDS = frozenset(int(getattr(sim.RelicId, name)) for name in ENERGY_RELIC_NAMES)


def relic_action(rc, actions, logits=None):
    """Return a preferred legal action, or ``None`` to use the network.

    In a shop, prefer an affordable, unsold relic. At an Ancient's relic-choice
    page, prefer an offered energy relic. Multiple matching actions use the
    highest network score if ``logits`` is supplied, else their given order.
    The input action list and optional one-dimensional scores must align.
    Active card grids are never overridden.
    """
    if not actions or rc.card_grid_kind:
        return None
    if logits is not None and len(logits) != len(actions):
        raise ValueError("logits must align with legal actions")
    legal = [(int(action[0]), int(action[1])) for action in actions]
    candidates = []
    if rc.screen == SCREEN.SHOP:
        items = rc.shop_relics
        for i, (kind, slot) in enumerate(legal):
            if kind != int(RACT.BUY_RELIC) or not 0 <= slot < len(items):
                continue
            relic_id, price, sold = items[slot]
            if int(relic_id) > 0 and not sold and 0 <= int(price) <= int(rc.gold):
                candidates.append(i)
    elif (rc.screen == SCREEN.EVENT and rc.event_name in ANCIENT_EVENTS
          and int(rc.event_page) == 0 and not rc.event_card_selection):
        offered = rc.event_relics
        for i, (kind, slot) in enumerate(legal):
            if (kind == int(RACT.EVENT_CHOICE) and 0 <= slot < len(offered)
                    and int(offered[slot]) in ENERGY_RELIC_IDS):
                candidates.append(i)
    if not candidates:
        return None
    chosen = candidates[0] if logits is None else max(candidates, key=lambda i: float(logits[i]))
    return legal[chosen]
