"""Shared helpers for the native STS2 simulator.

All simulation runs in the C++ extension ``sts2_sim``; this module only wires
Python-side controllers to it.
"""
from __future__ import annotations

import pathlib
import hashlib
import sys

import numpy as np

_SIM_DIR = pathlib.Path(__file__).resolve().parents[1] / "simulator"
if str(_SIM_DIR) not in sys.path:
    sys.path.insert(0, str(_SIM_DIR))

import sts2_sim as sim  # noqa: E402

# Record the imported artifact before a concurrent rebuild could replace it.
LOADED_SIMULATOR_SHA256 = hashlib.sha256(pathlib.Path(sim.__file__).read_bytes()).hexdigest()

RUN_OBS_DIM = sim.RUN_OBS_DIM
CARD_FEAT_DIM = sim.CARD_FEAT_DIM
COMBAT_OBS_DIM = sim.COMBAT_OBS_DIM
ACTION_FEAT_DIM = sim.ACTION_FEAT_DIM
PUBLIC_OBS_DIM = sim.PUBLIC_OBS_DIM
PUBLIC_COMBAT_OBS_DIM = sim.PUBLIC_COMBAT_OBS_DIM
PUBLIC_OBS_VERSION = sim.PUBLIC_OBS_VERSION
ACTION_SCHEMA_VERSION = sim.ACTION_SCHEMA_VERSION
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
    """Legacy compact run observation (kept for old checkpoints)."""
    return np.asarray(rc.observation(), dtype=np.float32)


def public_observation(rc) -> np.ndarray:
    """Versioned public observation (schema PUBLIC_OBS_VERSION)."""
    return np.asarray(rc.observe_public(), dtype=np.float32)


def public_combat_observation(bc) -> np.ndarray:
    """Versioned public in-combat observation."""
    return np.asarray(bc.observation_public(), dtype=np.float32)


def reward_action(rc):
    """Choose an available reward while keeping the card choice explicit."""
    legal = legal_run_actions(rc)
    for kind in (RACT.TAKE_GOLD_REWARD, RACT.TAKE_RELIC_REWARD,
                 RACT.TAKE_POTION_REWARD, RACT.TAKE_STOLEN_CARD_REWARD, RACT.OPEN_CARD_REWARD,
                 RACT.LEAVE_REWARDS):
        for action in legal:
            if action[0] == int(kind):
                return action
    raise RuntimeError("no legal reward action")


def card_grid_action(rc):
    """Complete mandatory grids without toggling an already selected card off."""
    legal = legal_run_actions(rc)
    for action in legal:
        if action[0] == int(RACT.CONFIRM_GRID_CARDS):
            return action
    selected = rc.card_grid_selected
    for action in legal:
        if action[0] == int(RACT.SELECT_GRID_CARD) and not selected[action[1]]:
            return action
    raise RuntimeError("no progressing card-grid action")


def completed_run_status(rc) -> str:
    """Classify an ended run without treating the safety cutoff as a loss."""
    return "terminated" if rc.screen == SCREEN.RUN_OVER and not rc.truncated else "truncated"


def skip_card_action(rc):
    """Prefer Pael's Wing sacrifice when it is an available alternative."""
    legal = legal_run_actions(rc)
    for kind in (RACT.SACRIFICE_CARD_REWARD, RACT.SKIP_CARD):
        for action in legal:
            if action[0] == int(kind):
                return action
    raise RuntimeError("no legal card reward skip action")


def screen_action(rc):
    """A legal action for any non-combat screen.

    Trainers previously hard-coded event option 0 and broke out of the episode
    when it was illegal (e.g. Stone of All Time without potions).  Every choice
    here comes from ``rc.legal_actions()``.
    """
    legal = legal_run_actions(rc)
    if not legal:
        raise RuntimeError(f"no legal run action on screen {rc.screen.name}")
    if rc.card_grid_kind:
        return card_grid_action(rc)
    if rc.screen == SCREEN.REWARDS:
        return reward_action(rc)
    if rc.screen == SCREEN.CARD_REWARD:
        take = [a for a in legal if a[0] == int(RACT.TAKE_CARD)]
        return take[0] if take and rc.deck_count < 15 else skip_card_action(rc)
    if rc.screen == SCREEN.REST:
        heal = [a for a in legal if a[0] == int(RACT.REST_HEAL)]
        if heal and rc.hp * 10 < rc.max_hp * 6:
            return heal[0]
        clones = [a for a in legal if a[0] == int(RACT.REST_CLONE)]
        if clones:
            return clones[0]
        upgrades = [a for a in legal if a[0] == int(RACT.REST_UPGRADE)]
        return upgrades[0] if upgrades else legal[0]
    if rc.screen == SCREEN.SHOP:
        leave = [a for a in legal if a[0] == int(RACT.LEAVE_SHOP)]
        return leave[0] if leave else legal[0]
    if rc.screen == SCREEN.EVENT:
        return legal[0]
    if rc.screen == SCREEN.TREASURE:
        collect = [a for a in legal if a[0] == int(RACT.COLLECT)]
        return collect[0] if collect else legal[0]
    if rc.screen == SCREEN.MAP:
        nodes = rc.available_map_nodes()
        return (int(RACT.MOVE), int(nodes[0])) if nodes else legal[0]
    return legal[0]


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
    status = "error"
    try:
        while rc.screen != SCREEN.RUN_OVER and steps < max_steps:
            steps += 1
            if rc.screen == SCREEN.COMBAT:
                if not rc.step_combat(*combat_fn(rc.battle, rng)):
                    break
                continue
            action = card_fn(rc) if rc.screen == SCREEN.CARD_REWARD and not rc.card_grid_kind else screen_action(rc)
            if not rc.step(*action):
                break
        else:
            status = completed_run_status(rc)
    except RuntimeError:
        status = "error"
    return {"won": bool(rc.won), "floor": int(rc.floor), "hp": int(rc.hp),
            "steps": steps, "status": status}
