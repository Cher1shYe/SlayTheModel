"""Shared helpers for the native STS2 simulator.

All simulation runs in the C++ extension ``sts2_sim``; this module only wires
Python-side controllers to it.
"""
from __future__ import annotations

import pathlib
import sys

import numpy as np

_SIM_DIR = pathlib.Path(__file__).resolve().parents[1] / "simulator"
if str(_SIM_DIR) not in sys.path:
    sys.path.insert(0, str(_SIM_DIR))

import sts2_sim as sim  # noqa: E402

RUN_OBS_DIM = sim.RUN_OBS_DIM
CARD_FEAT_DIM = sim.CARD_FEAT_DIM
COMBAT_OBS_DIM = sim.COMBAT_OBS_DIM
ACTION_FEAT_DIM = sim.ACTION_FEAT_DIM
CARD_COUNT = sim.CARD_COUNT

SCREEN = sim.RunScreen
RACT = sim.RunActionType
ACT = sim.ActionType
OUTCOME = sim.Outcome

CARD_NAMES = [sim.card_name(i) for i in range(CARD_COUNT)]


def new_run(seed: int, ascension: int = 0) -> "sim.RunContext":
    rc = sim.RunContext()
    rc.init(int(seed), int(ascension))
    return rc


def screen_name(rc) -> str:
    return rc.screen.name


def combat_action_arrays(bc):
    """Legal combat actions plus their float feature rows."""
    actions = bc.legal_actions()
    feats = np.asarray([bc.action_features(*a) for a in actions], dtype=np.float32)
    return actions, feats


def combat_observation(bc) -> np.ndarray:
    return np.asarray(bc.observation(), dtype=np.float32)


def run_observation(rc) -> np.ndarray:
    return np.asarray(rc.observation(), dtype=np.float32)


def card_feature_array(cards, prices=None) -> np.ndarray:
    """Feature rows for (id, upgraded, uid, cost) tuples from the binding."""
    rows = []
    for i, (card_id, upgraded, _uid, _cost) in enumerate(cards):
        price = -1 if prices is None else int(prices[i])
        rows.append(sim.card_features(int(card_id), bool(upgraded), price))
    return np.asarray(rows, dtype=np.float32)


def legal_run_actions(rc):
    return [(int(t), int(i)) for t, i in rc.legal_actions()]


def take_card(rc, index: int) -> bool:
    return rc.step(int(RACT.TAKE_CARD), int(index))


def skip_card(rc) -> bool:
    return rc.step(int(RACT.SKIP_CARD), 0)


def greedy_combat_action(bc, seed: int = 0, epsilon: float = 0.05):
    return bc.greedy_action(float(epsilon), int(seed) & 0xFFFFFFFF)


def play_run(rc, combat_fn, card_fn, seed: int = 0, max_steps: int = 5000) -> dict:
    """Drive one full run.

    combat_fn(bc, rng) -> action tuple
    card_fn(rc) -> run action (type, index)
    """
    rng = np.random.default_rng(seed)
    steps = 0
    while rc.screen != SCREEN.RUN_OVER and steps < max_steps:
        steps += 1
        if rc.screen == SCREEN.COMBAT:
            action = combat_fn(rc.battle, rng)
            if not rc.step_combat(*action):
                break
            continue
        if rc.screen == SCREEN.CARD_REWARD:
            action = card_fn(rc)
        elif rc.screen == SCREEN.REST:
            legal = legal_run_actions(rc)
            if rc.hp * 10 < rc.max_hp * 6:
                action = (int(RACT.REST_HEAL), 0)
            else:
                action = legal[-1]
        elif rc.screen == SCREEN.SHOP:
            action = (int(RACT.LEAVE_SHOP), 0)
        elif rc.screen == SCREEN.EVENT:
            action = (int(RACT.EVENT_CHOICE), 0)
        elif rc.screen == SCREEN.TREASURE:
            action = (int(RACT.COLLECT), 0)
        elif rc.screen == SCREEN.MAP:
            nodes = rc.available_map_nodes()
            action = (int(RACT.MOVE), nodes[0])
        else:
            break
        if not rc.step(*action):
            break
    return {"won": bool(rc.won), "floor": int(rc.floor), "hp": int(rc.hp), "steps": steps}
