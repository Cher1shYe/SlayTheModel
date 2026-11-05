"""STS2-specific card reward need overlay for the ArmG candidate scorer.

The categories below are deliberately small, hand-checked sets, not STS1's
card-ID lists: a name match between games does not prove identical effects.
The overlay scores only visible card reward choices and never modifies the
simulator's legal actions. Its weights are a starting hypothesis, not a claim
that STS1's measured win-rate transfers to STS2.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

import numpy as np
import torch

from .common import CARD_COUNT, RACT, SCREEN, sim


@dataclass(frozen=True)
class NeedConfig:
    scaling: float = 0.8
    block: float = 0.6
    strength: float = 0.4
    draw: float = 0.4
    aoe: float = 0.4
    sustain: float = 0.5
    balance: float = 0.5
    block_act3: float = 1.3
    energy: float = 0.0
    scale: float = 1.0
    junk_filter: bool = True


# Names are exactly those exposed by sim.card_name; entries were checked
# against this repository's simulator/content/cards.json descriptions.
SCALING = frozenset({"Aggression", "Barricade", "Corruption", "Dark Embrace",
                     "Demon Form", "Feel No Pain", "Inflame", "Juggernaut",
                     "Rupture", "Unmovable"})
BLOCK = frozenset({"Armaments", "Barricade", "Colossus", "Evil Eye",
                   "Expect a Fight", "Feel No Pain", "Flame Barrier",
                   "Impervious", "Iron Wave", "Rage", "Second Wind",
                   "Shrug It Off", "Stone Armor", "Taunt", "True Grit",
                   "Unmovable"})
STRENGTH = frozenset({"Brand", "Demon Form", "Dominate", "Fight Me!", "Inflame",
                      "Rupture", "Setup Strike"})
DRAW = frozenset({"Battle Trance", "Burning Pact", "Dark Embrace", "Offering",
                  "Pillage", "Pommel Strike", "Shrug It Off", "Vicious"})
AOE = frozenset({"Breakthrough", "Conflagration", "Howl from Beyond", "Inferno",
                 "Pact's End", "Stomp", "Thunderclap", "Whirlwind"})
SUSTAIN = frozenset({"Feed"})
ENERGY = frozenset({"Bloodletting", "Corruption", "Forgotten Ritual", "Offering", "Pyre"})
# Do not carry over STS1's subjective junk list (e.g. Anger/Havoc): their STS2
# balance and synergies differ. Only unequivocally unplayable adverse status
# cards are excluded, and only when a legal skip alternative exists.
JUNK = frozenset({"Burn", "Dazed", "Infection", "Soot", "Void", "Wound",
                  "Disintegration", "Mind Rot", "Waste Away"})


@lru_cache(maxsize=None)
def _card_info(card_id: int) -> tuple[str, int]:
    name = sim.card_name(card_id)
    features = sim.card_features(card_id, False, -1)
    types = features[CARD_COUNT + 1:CARD_COUNT + 6]
    return name, int(np.argmax(types))  # CardType: attack=0, skill=1


def _bonus(card_name: str, card_type: int, deck_names: list[str],
           attacks: int, act: int, config: NeedConfig) -> float:
    n = len(deck_names)
    count = lambda names: sum(name in names for name in deck_names)
    result = 0.0
    if card_name in SCALING and count(SCALING) == 0:
        result += config.scaling
    if card_name in BLOCK and count(BLOCK) < max(4.0, 0.2 * n):
        result += config.block * (config.block_act3 if act >= 2 else 1.0)
    if card_name in STRENGTH and count(STRENGTH) < 2:
        result += config.strength
    if card_name in DRAW and count(DRAW) < 2:
        result += config.draw
    if card_name in AOE and count(AOE) == 0:
        result += config.aoe
    if card_name in SUSTAIN and count(SUSTAIN) == 0:
        result += config.sustain
    if card_name in ENERGY and count(ENERGY) < 2:
        result += config.energy
    if n and attacks > 0.55 * n:
        if card_type == 0:
            result -= config.balance
        elif card_type == 1:
            result += 0.6 * config.balance
    return result * config.scale


def need_overlay(rc, actions, config: NeedConfig | None = None):
    """Return (additive bonuses, allowed mask, use_zscore) for actions.

    Only ordinary card rewards are modified, and action order is unchanged.
    The caller must apply the identical overlay when recomputing training
    log-probabilities; the returned arrays are safe to save in trajectories.
    """
    cfg = config or NeedConfig()
    bonus = np.zeros(len(actions), dtype=np.float32)
    allowed = np.ones(len(actions), dtype=np.bool_)
    if rc.screen != SCREEN.CARD_REWARD or rc.card_grid_kind:
        return bonus, allowed, False
    offered = rc.offered
    if not any(int(kind) == int(RACT.TAKE_CARD) for kind, _ in actions):
        return bonus, allowed, False
    deck = [_card_info(int(c[0])) for c in rc.deck]
    deck_names = [name for name, _ in deck]
    attacks = sum(kind == 0 for _, kind in deck)
    can_skip = any(int(kind) in (int(RACT.SKIP_CARD), int(RACT.SACRIFICE_CARD_REWARD))
                   for kind, _ in actions)
    for i, (kind, idx) in enumerate(actions):
        if int(kind) != int(RACT.TAKE_CARD) or not 0 <= idx < len(offered):
            continue
        name, card_type = _card_info(int(offered[idx][0]))
        bonus[i] = _bonus(name, card_type, deck_names, attacks, int(rc.act), cfg)
        if cfg.junk_filter and can_skip and name in JUNK:
            allowed[i] = False
    # Defensive fallback: never make all actions unselectable.
    if not allowed.any():
        allowed[:] = True
    return bonus, allowed, True


def apply_need_to_logits(logits: torch.Tensor, bonus, allowed, active: bool):
    """Apply the overlay to one decision, retaining gradients through z-score."""
    if not active:
        return logits
    mean = logits.mean()
    std = logits.std(unbiased=False)
    denom = torch.where(std > 1e-8, std, torch.ones_like(std))
    scores = (logits - mean) / denom + torch.as_tensor(
        bonus, dtype=logits.dtype, device=logits.device)
    mask = torch.as_tensor(allowed, dtype=torch.bool, device=logits.device)
    if not bool(mask.any()):
        raise ValueError("need overlay cannot mask every action")
    return scores.masked_fill(~mask, float("-inf"))
