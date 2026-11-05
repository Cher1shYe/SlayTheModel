"""Shared candidate scorer for every legal non-combat run decision.

The input is limited to public run observations and visible action details;
combat's hidden draw order and RNG state are never used as policy features.
"""
from __future__ import annotations

import numpy as np
import torch
from torch import nn
from torch.nn import functional as F

from .common import (
    CARD_COUNT, CARD_FEAT_DIM, PUBLIC_COMBAT_OBS_DIM, PUBLIC_OBS_DIM,
    RACT, SCREEN, legal_run_actions, public_observation, sim,
)

ARMG_OBS_DIM = PUBLIC_OBS_DIM - PUBLIC_COMBAT_OBS_DIM
ARMG_FEATURE_VERSION = 3
_ACTIONS = max(int(x) for x in RACT.__members__.values()) + 1
_RELICS = max(int(x) for x in sim.RelicId.__members__.values()) + 1
_POTIONS = max(int(x) for x in sim.PotionId.__members__.values()) + 1
_MAP_TYPES = max(int(x) for x in sim.MapPointType.__members__.values()) + 1
_SLOTS = sim.MAX_DECK

# Action + selected slot + up to three cards (Scroll Boxes) + relic + potion +
# destination/next two map layers + price/selected/enchantment metadata.
_ACTION_OFF = 0
_SLOT_OFF = _ACTION_OFF + _ACTIONS
_CARD_OFF = _SLOT_OFF + _SLOTS
_RELIC_OFF = _CARD_OFF + 3 * CARD_FEAT_DIM
_POTION_OFF = _RELIC_OFF + _RELICS
_MAP_OFF = _POTION_OFF + _POTIONS
_META_OFF = _MAP_OFF + 3 * _MAP_TYPES
ARMG_ACTION_DIM = _META_OFF + 8


class ArmGScorer(nn.Module):
    """Score each (public run state, legal action) with the same MLP."""

    def __init__(self, hidden=(128, 128)):
        super().__init__()
        layers = []
        prev = ARMG_OBS_DIM + ARMG_ACTION_DIM
        for width in hidden:
            layers.extend((nn.Linear(prev, width), nn.ReLU()))
            prev = width
        layers.append(nn.Linear(prev, 1))
        self.net = nn.Sequential(*layers)

    def forward(self, obs: torch.Tensor, candidates: torch.Tensor) -> torch.Tensor:
        # obs [batch, state], candidates [batch, legal actions, features]
        # Factor the first linear layer so the (large) state is projected once
        # per decision, rather than replicated and multiplied once per action.
        first = self.net[0]
        states = F.linear(obs, first.weight[:, :ARMG_OBS_DIM], first.bias)
        actions = F.linear(candidates, first.weight[:, ARMG_OBS_DIM:])
        return self.net[1:](states.unsqueeze(1) + actions).squeeze(-1)


def _one_hot(row: np.ndarray, offset: int, index: int, length: int) -> None:
    if 0 <= index < length:
        row[offset + index] = 1.0


def _card(row: np.ndarray, card, slot: int = 0, price: int = -1, enchantment=None) -> None:
    card_id, upgraded, _uid, cost = card
    start = _CARD_OFF + slot * CARD_FEAT_DIM
    features = np.asarray(sim.card_features(int(card_id), bool(upgraded), int(price)), dtype=np.float32)
    if cost is not None:
        features[CARD_COUNT] = 1.0 if int(cost) < 0 else int(cost) / 3.0
    if enchantment is not None:
        ench_id, amount, disabled = enchantment
        features[-3:] = (int(ench_id) / 5.0, int(amount) / 10.0, float(disabled))
    row[start:start + CARD_FEAT_DIM] = features


def build_candidates(rc):
    """Return public run observation, legal actions, and their feature rows.

    The action list is taken directly from the engine; it is not filtered or
    reordered, so selection/confirmation/cancellation remain legal choices.
    """
    if rc.screen in (SCREEN.COMBAT, SCREEN.RUN_OVER):
        raise ValueError("ArmG requires a non-combat decision screen")
    actions = legal_run_actions(rc)
    observation = public_observation(rc)[:ARMG_OBS_DIM].copy()
    rows = np.zeros((len(actions), ARMG_ACTION_DIM), dtype=np.float32)
    if not actions:
        return observation, actions, rows

    # Read each binding once; most screens do not need all of these.
    deck = rc.deck
    deck_enchants = rc.deck_enchantments
    offers = rc.offered if rc.screen == SCREEN.CARD_REWARD else []
    shop = rc.shop if rc.screen == SCREEN.SHOP else []
    shop_relics = rc.shop_relics if rc.screen == SCREEN.SHOP else []
    shop_potions = rc.shop_potions if rc.screen == SCREEN.SHOP else []
    relic_rewards = rc.reward_relics if rc.screen == SCREEN.REWARDS else []
    potion_rewards = rc.reward_potions if rc.screen == SCREEN.REWARDS else []
    stolen = {x[0]: x for x in rc.reward_stolen_cards} if rc.screen == SCREEN.REWARDS else {}
    potions = rc.potions
    grid_kind = int(rc.card_grid_kind)
    grid_cards = rc.card_grid_cards if grid_kind in (1, 2, 5) else []
    selected = rc.card_grid_selected if grid_kind else []
    event_relics = rc.event_relics if rc.screen == SCREEN.EVENT else []
    nodes = {x[0]: x for x in rc.map_nodes()} if rc.screen == SCREEN.MAP else {}

    for row, (kind, index) in zip(rows, actions):
        _one_hot(row, _ACTION_OFF, kind, _ACTIONS)
        _one_hot(row, _SLOT_OFF, index, _SLOTS)
        row[_META_OFF] = index / max(1, _SLOTS - 1)
        row[_META_OFF + 1] = grid_kind / 5.0
        if kind == int(RACT.MOVE) and index in nodes:
            node = nodes[index]
            _one_hot(row, _MAP_OFF, int(node[1]), _MAP_TYPES)
            for child in node[4]:
                if child not in nodes:
                    continue
                row[_MAP_OFF + _MAP_TYPES + int(nodes[child][1])] += 1.0
                for grandchild in nodes[child][4]:
                    if grandchild in nodes:
                        row[_MAP_OFF + 2 * _MAP_TYPES + int(nodes[grandchild][1])] += 1.0
            row[_META_OFF + 2] = node[2] / 6.0
            row[_META_OFF + 3] = node[3] / 16.0
        elif kind == int(RACT.TAKE_CARD) and index < len(offers):
            _card(row, offers[index])
        elif kind in (int(RACT.REST_UPGRADE), int(RACT.REMOVE_CARD), int(RACT.EVENT_SELECT_CARD)) and index < len(deck):
            _card(row, deck[index], enchantment=deck_enchants[index])
            if kind == int(RACT.REMOVE_CARD):
                row[_META_OFF + 4] = rc.removal_price / 300.0
        elif kind == int(RACT.SELECT_GRID_CARD):
            row[_META_OFF + 5] = float(index < len(selected) and selected[index])
            if grid_kind in (3, 4, 6, 7, 8, 9, 10, 11, 12) and index < len(deck):
                _card(row, deck[index], enchantment=deck_enchants[index])
            elif grid_kind == 5:
                for i in range(3):
                    if index * 3 + i < len(grid_cards):
                        _card(row, grid_cards[index * 3 + i], i)
            elif index < len(grid_cards):
                _card(row, grid_cards[index])
        elif kind == int(RACT.BUY_CARD) and index < len(shop):
            card_id, price, _sold = shop[index]
            _card(row, (card_id, False, 0, None), price=price)
            row[_META_OFF + 4] = price / 300.0
        elif kind == int(RACT.BUY_RELIC) and index < len(shop_relics):
            item, price, _sold = shop_relics[index]
            _one_hot(row, _RELIC_OFF, int(item), _RELICS)
            row[_META_OFF + 4] = price / 300.0
        elif kind == int(RACT.BUY_POTION) and index < len(shop_potions):
            item, price, _sold = shop_potions[index]
            _one_hot(row, _POTION_OFF, int(item), _POTIONS)
            row[_META_OFF + 4] = price / 300.0
        elif kind == int(RACT.EVENT_CHOICE) and index < len(event_relics):
            _one_hot(row, _RELIC_OFF, int(event_relics[index]), _RELICS)
        elif kind == int(RACT.TAKE_RELIC_REWARD) and index < len(relic_rewards):
            _one_hot(row, _RELIC_OFF, int(relic_rewards[index][0]), _RELICS)
        elif kind == int(RACT.TAKE_POTION_REWARD) and index < len(potion_rewards):
            _one_hot(row, _POTION_OFF, int(potion_rewards[index]), _POTIONS)
        elif kind in (int(RACT.DISCARD_POTION), int(RACT.USE_POTION)) and index < len(potions):
            _one_hot(row, _POTION_OFF, int(potions[index]), _POTIONS)
        elif kind in (int(RACT.TAKE_STOLEN_CARD_REWARD), int(RACT.SKIP_STOLEN_CARD_REWARD)) and index in stolen:
            _, card_id, upgraded, uid, ench_id, amount = stolen[index]
            _card(row, (card_id, upgraded, uid, None),
                  enchantment=(ench_id, amount, False))
        elif kind == int(RACT.TAKE_GOLD_REWARD):
            row[_META_OFF + 6] = (rc.reward_gold if index == 0 else rc.reward_recovered_gold) / 300.0
    return observation, actions, rows
