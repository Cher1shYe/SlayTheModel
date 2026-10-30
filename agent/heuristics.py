"""Simple heuristic policies used for validation and as a baseline.

They are deliberately small: the point is to demonstrate a complete, legal,
deterministic A0 climb with the native environment, not to be a strong bot.
"""
from __future__ import annotations

from agent.common import CARD_COUNT, RACT, SCREEN, card_grid_action, reward_action, sim, skip_card_action

CARD_FEAT_OFFSET_TYPE = CARD_COUNT + 1  # after card one-hot + cost


def _card_quality(rc, index: int) -> float:
    card_id, upgraded, _uid, cost = rc.offered[index]
    feats = sim.card_features(int(card_id), bool(upgraded), -1)
    type_idx = max(range(5), key=lambda i: feats[CARD_FEAT_OFFSET_TYPE + i])
    rarity_idx = max(range(5), key=lambda i: feats[CARD_FEAT_OFFSET_TYPE + 5 + i])
    type_score = (0.5, 1.0, 2.0, 2.5, 0.0)[type_idx]  # attack, skill, power, status, curse
    rarity_score = (0.0, 1.0, 2.0, 3.0, 3.5)[rarity_idx]
    return type_score + rarity_score - max(0, int(cost)) * 0.1


def _node_type(rc, idx: int) -> int:
    for node_idx, type_enum, _col, _row, _kids, _pars in rc.map_nodes():
        if node_idx == idx:
            return int(type_enum)
    return 0


def _event_choice(rc) -> int:
    """Pick a safe option per event id (ids match sts2_sim.event_info order)."""
    name = rc.event_name
    page = rc.event_page
    if name == "NEOW":
        return 0
    if name == "TABLET_OF_TRUTH":
        return 1 if page == 0 else 1  # smash / give up
    if name == "DENSE_VEGETATION":
        return 1 if page == 0 else 0  # rest, then fight
    if name in ("THIS_OR_THAT", "LOST_WISP", "HUNGRY_FOR_MUSHROOMS", "SPIRIT_GRAFTER"):
        return 1 if name == "THIS_OR_THAT" else 0
    if name == "ROOM_FULL_OF_CHEESE":
        return 1 if rc.hp > 30 else 0
    if name == "WELCOME_TO_WONGOS":
        if rc.gold >= 200:
            return 1
        if rc.gold >= 100:
            return 0
        return 3
    if name == "UNREST_SITE":
        return 0
    if name == "POTION_COURIER":
        return 0 if rc.potion_slots - len(rc.potions) >= 3 else 1
    if name == "WELLSPRING":
        return 0
    if name == "AROMA_OF_CHAOS":
        return 1
    if name == "SAPPHIRE_SEED":
        return 0
    if name == "REFLECTIONS":
        return 0
    if name == "BRAIN_LEECH":
        return 0
    if name == "STONE_OF_ALL_TIME":
        return 0 if rc.potions else 1
    return 0


def combat_policy(env, resample: bool = False, seed_override: int | None = None) -> tuple:
    """1-ply lookahead: try each legal action, score with a greedy rollout.

    ``resample=True`` redraws the hidden zones (draw/discard order and future
    RNG) of each clone before the rollout, so the policy only uses information
    the player has.  The default keeps the historical oracle behaviour and must
    not be reported as a player-usable strategy.
    """
    bc = env.battle
    legal = bc.legal_actions()
    if not legal:
        return tuple(bc.greedy_action(0.0, 0))
    if len(legal) == 1:
        return tuple(legal[0])
    # Use a potion once HP is low.
    if bc.player_hp * 3 < bc.player_max_hp:
        for a in legal:
            if int(a[0]) == int(sim.ActionType.USE_POTION):
                return tuple(a)
    seed = (env.rc.floor * 131 + bc.turn) & 0xFFFFFFFF
    if seed_override is not None:
        seed = seed_override & 0xFFFFFFFF
    best, best_value = None, -1e9
    for i, a in enumerate(legal):
        clone = bc.clone()
        if resample:
            clone.resample_hidden((seed + i * 7919) & 0xFFFFFFFF)
        if not clone.step(*a):
            continue
        value = clone.rollout(0.1, seed + i * 7919)
        # When every rollout loses, prefer acting over passing (a card that
        # blocks or deals damage is never worse than idling).
        if int(a[0]) != int(sim.ActionType.END_TURN):
            value += 1e-3
        if value > best_value:
            best, best_value = a, value
    if best is None:
        return tuple(bc.greedy_action(0.0, seed))
    return tuple(best)


def run_policy(env) -> tuple:
    """Deterministic policy for every non-combat screen.

    Accepts a RunEnv or a bare RunContext (the non-combat screens only read
    run state).
    """
    rc = getattr(env, "rc", env)
    screen = rc.screen
    legal = [(int(t), int(i)) for t, i in rc.legal_actions()]
    if rc.card_grid_kind:
        return card_grid_action(rc)
    if screen == SCREEN.REWARDS:
        return reward_action(rc)
    if screen == SCREEN.MAP:
        nodes = rc.available_map_nodes()
        # Prefer rest when hurt, avoid elites when hurt, prefer unknown otherwise.
        scored = []
        for idx in nodes:
            t = _node_type(rc, idx)
            score = 0.0
            if t == 4:  # REST
                score = 6.0 if rc.hp * 4 < rc.max_hp * 3 else 1.0
            elif t == 6:  # ELITE
                score = -6.0 if rc.hp * 4 < rc.max_hp * 3 else 2.0
            elif t == 2:  # SHOP
                score = 2.5 if rc.gold >= 150 else 0.5
            elif t == 3:  # TREASURE
                score = 3.0
            elif t == 1:  # UNKNOWN
                score = 1.5
            elif t == 7:  # BOSS
                score = 10.0
            else:  # MONSTER
                score = 1.0
            scored.append((score, idx))
        scored.sort(key=lambda x: (-x[0], x[1]))
        return (int(RACT.MOVE), scored[0][1])
    if screen == SCREEN.CARD_REWARD:
        best = (-1.0, None)
        for a in legal:
            if a[0] == int(RACT.TAKE_CARD):
                q = _card_quality(rc, a[1])
                if q > best[0]:
                    best = (q, a)
        if best[1] is not None and (best[0] >= 1.5 or rc.deck_count < 15):
            return best[1]
        return skip_card_action(rc)
    if screen == SCREEN.REST:
        if rc.hp * 100 < rc.max_hp * 80:
            return (int(RACT.REST_HEAL), 0)
        clones = [a for a in legal if a[0] == int(RACT.REST_CLONE)]
        if clones:
            return clones[0]
        upgrades = [a for a in legal if a[0] == int(RACT.REST_UPGRADE)]
        if upgrades:
            def up_value(a):
                card_id, upgraded, _uid, _cost = rc.deck[a[1]]
                feats = sim.card_features(int(card_id), bool(upgraded), -1)
                type_idx = max(range(5), key=lambda i: feats[CARD_FEAT_OFFSET_TYPE + i])
                base = 3.0 if int(card_id) == 6 else 0.0  # Bash
                return base + (1.0 if type_idx == 2 else 0.0) + (0.5 if type_idx == 0 else 0.0)
            upgrades.sort(key=lambda a: -up_value(a))
            return upgrades[0]
        return (int(RACT.REST_HEAL), 0)
    if screen == SCREEN.SHOP:
        relics_on_sale = [a for a in legal if a[0] == int(RACT.BUY_RELIC)]
        for a in relics_on_sale:
            if rc.gold >= rc.shop_relics[a[1]][1] + 40:
                return a
        potions = [a for a in legal if a[0] == int(RACT.BUY_POTION)]
        if potions and len(rc.potions) < rc.potion_slots and rc.gold >= 120:
            return potions[0]
        cards = [a for a in legal if a[0] == int(RACT.BUY_CARD)]
        if cards and rc.gold >= 150:
            return cards[0]
        if rc.gold >= rc.removal_price + 50:
            removals = [a for a in legal if a[0] == int(RACT.REMOVE_CARD)]
            if removals and rc.deck_count > 11:
                return removals[0]
        return (int(RACT.LEAVE_SHOP), 0)
    if screen == SCREEN.EVENT:
        selections = [a for a in legal if a[0] == int(RACT.EVENT_SELECT_CARD)]
        if selections:
            return selections[0]
        choice = _event_choice(rc)
        options = {a[1] for a in legal}
        if choice not in options:
            choice = legal[0][1]
        return (int(RACT.EVENT_CHOICE), choice)
    if screen == SCREEN.TREASURE:
        return (int(RACT.COLLECT), 0)
    return legal[0]
