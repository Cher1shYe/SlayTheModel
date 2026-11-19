"""Observation: one entity set for in-combat and out-of-combat decisions.

Starting point for the new network (docs/plan.md, docs/observation-checklist.md); written
on 2026-11-16 for the unified network and kept through the 2026-11-18 cleanup. To be
extended with the features of the observation checklist.

Built in Python from the two C++ observations:

* out of combat: ``RunContext.macro_observation()`` unchanged;
* in combat: the run-level part of ``macro_observation()`` (GLOBAL, CONTEXT, deck, relics,
  map nodes and edges, boss, ...; physical potion entities dropped because the combat
  carries its own) followed by ``BattleContext.entity_observation()``. The run-level
  entities are constant during the fight (the network caches their encoding per combat):
  the GLOBAL entity's fight-varying columns (HP fraction, HP, max HP, potion count) are
  zeroed; the direct GLOBAL row given to the heads is patched with the current values
  from the combat PLAYER row, so nothing the network sees is stale.

Entity kinds: macro kinds 0..12, combat kinds 13..25. Numeric rows are padded to 96.
Candidate types: run action types 0..31, combat action types 32..36. Candidate numeric
features padded to 5. Two raw rows go straight to the network heads: the GLOBAL row (80)
and the combat PLAYER row (96; zeros out of combat).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .sim import sim

MACRO_KINDS = 13
COMBAT_KINDS = int(sim.COMBAT_ENTITY_KINDS)
KINDS = MACRO_KINDS + COMBAT_KINDS
MACRO_NUM = int(sim.MACRO_ENTITY_NUM)          # 80
COMBAT_NUM = int(sim.COMBAT_ENTITY_NUM)        # 96
NUM = max(MACRO_NUM, COMBAT_NUM)
RUN_TYPES = int(sim.RUN_ACTION_TYPES)          # 32
COMBAT_TYPES = int(sim.COMBAT_ACTION_TYPES)
CAND_TYPES = RUN_TYPES + COMBAT_TYPES
CAND_NUM = max(int(sim.MACRO_CAND_NUM), int(sim.COMBAT_CAND_NUM))
K_GLOBAL, K_POTION = 0, 4
# GLOBAL row columns patched in combat, and their source in the combat PLAYER row
G_HPFRAC, G_HP, G_MAXHP, G_POTIONS = 0, 1, 2, 14
P_HPFRAC, P_HP, P_MAXHP, P_POTIONS = 0, 1, 2, 39
FIGHT_VARYING = (G_HPFRAC, G_HP, G_MAXHP, G_POTIONS)
# GLOBAL columns used by the value labels
G_FLOOR, G_ACT0 = 4, 5


def vocab_sizes() -> list[int]:
    return [max(1, int(v)) for v in list(sim.macro_vocab()) + list(sim.combat_id_vocab())]


@dataclass
class UObs:
    kind: np.ndarray          # [N] int64, 0..KINDS-1
    id: np.ndarray            # [N] int64 (per-kind id; vocabulary offsets applied at collate time)
    num: np.ndarray           # [N, NUM] float32
    edges: np.ndarray         # [E, 2] int64 entity indices (map parent -> child)
    global_row: np.ndarray    # [MACRO_NUM] float32
    player_row: np.ndarray    # [COMBAT_NUM] float32 (zeros out of combat)
    cand_type: np.ndarray     # [C] int64, 0..CAND_TYPES-1
    cand_index: np.ndarray    # [C] int64 RunAction index for rc.step (macro); -1 in combat
    cand_t1: np.ndarray       # [C] int64 entity index or -1
    cand_t2: np.ndarray       # [C] int64 entity index or -1
    cand_num: np.ndarray      # [C, CAND_NUM] float32
    in_combat: bool
    n_ctx: int = -1           # entities [0, n_ctx) are run-level (all of them out of combat)

    def __post_init__(self):
        if self.n_ctx < 0:
            self.n_ctx = len(self.kind)

    @property
    def act(self) -> int:
        return int(np.argmax(self.global_row[G_ACT0:G_ACT0 + 3]))

    @property
    def floor(self) -> int:
        return int(round(float(self.global_row[G_FLOOR]) * 49))


def _pad(a: np.ndarray, width: int) -> np.ndarray:
    a = np.asarray(a, np.float32)
    if a.ndim == 1:
        a = a.reshape(0, width) if a.size == 0 else a[None]
    if a.shape[1] == width:
        return a
    out = np.zeros((a.shape[0], width), np.float32)
    out[:, :a.shape[1]] = a
    return out


@dataclass
class RunContextPart:
    """Run-level entities for a combat (constant during the fight except the patched row)."""
    kind: np.ndarray
    id: np.ndarray
    num: np.ndarray           # [M, NUM]
    edges: np.ndarray
    global_row: np.ndarray    # unpatched


def run_context(m: dict) -> RunContextPart:
    """The macro observation's run-level part for use inside a combat (potions dropped)."""
    kind = np.asarray(m["kind"], np.int64)
    keep = kind != K_POTION
    remap = -np.ones(len(kind), np.int64)
    remap[keep] = np.arange(int(keep.sum()))
    e = np.asarray(m["edges"], np.int64).reshape(-1, 2)
    if len(e):
        e = remap[e]
        e = e[(e >= 0).all(1)]
    num = _pad(np.asarray(m["num"], np.float32).reshape(len(kind), MACRO_NUM)[keep], NUM)
    g = num[np.where(kind[keep] == K_GLOBAL)[0][0], :MACRO_NUM].copy()
    return RunContextPart(kind[keep], np.asarray(m["id"], np.int64)[keep], num, e, g)


def macro_obs(m: dict) -> UObs:
    """Out-of-combat decision: the macro observation as is."""
    kind = np.asarray(m["kind"], np.int64)
    num = _pad(np.asarray(m["num"], np.float32).reshape(len(kind), MACRO_NUM), NUM)
    g = num[np.where(kind == K_GLOBAL)[0][0], :MACRO_NUM].copy()
    cn = _pad(np.asarray(m["cand_num"], np.float32).reshape(len(m["cand_type"]), -1), CAND_NUM)
    return UObs(kind, np.asarray(m["id"], np.int64), num, np.asarray(m["edges"], np.int64).reshape(-1, 2), g,
                np.zeros(COMBAT_NUM, np.float32), np.asarray(m["cand_type"], np.int64),
                np.asarray(m["cand_index"], np.int64), np.asarray(m["cand_target"], np.int64), np.asarray(m["cand_target2"], np.int64), cn, False)


def combat_obs(ctx: RunContextPart, c: dict) -> UObs:
    """In-combat decision: run context + combat entities (``BattleContext.entity_observation()``
    or one leaf of ``net_search_advance``)."""
    ck = np.asarray(c["kind"], np.int64)
    cnum = np.asarray(c["num"], np.float32).reshape(len(ck), COMBAT_NUM)
    player = cnum[0].copy() if len(ck) else np.zeros(COMBAT_NUM, np.float32)
    g = ctx.global_row.copy()
    g[G_HPFRAC], g[G_HP], g[G_MAXHP], g[G_POTIONS] = player[P_HPFRAC], player[P_HP], player[P_MAXHP], player[P_POTIONS]
    m = len(ctx.kind)
    num = np.concatenate([ctx.num, _pad(cnum, NUM)])
    # The run-level entities must stay constant during the fight (their encoding is cached
    # per combat), so the GLOBAL entity carries no fight-varying values: those come from
    # the patched direct row and the PLAYER entity.
    gi = np.where(ctx.kind == K_GLOBAL)[0][0]
    num[gi, list(FIGHT_VARYING)] = 0.0
    t1 = np.asarray(c["cand_target"], np.int64)
    t2 = np.asarray(c["cand_target2"], np.int64)
    nc = len(c["cand_type"])                     # 0 for a won-fight search leaf
    cn = (_pad(np.asarray(c["cand_num"], np.float32).reshape(nc, -1), CAND_NUM) if nc
          else np.zeros((0, CAND_NUM), np.float32))
    return UObs(np.concatenate([ctx.kind, ck + MACRO_KINDS]), np.concatenate([ctx.id, np.asarray(c["id"], np.int64)]),
                num, ctx.edges, g, player, np.asarray(c["cand_type"], np.int64) + RUN_TYPES,
                np.full(len(c["cand_type"]), -1, np.int64),
                np.where(t1 >= 0, t1 + m, -1), np.where(t2 >= 0, t2 + m, -1), cn, True, m)


def observe(rc, ctx: RunContextPart | None = None) -> UObs:
    """The unified observation of the current decision of ``rc`` (a RunContext).
    In combat, pass the combat's ``run_context`` to avoid recomputing it."""
    if rc.screen == sim.RunScreen.COMBAT:
        if ctx is None:
            ctx = run_context(rc.macro_observation())
        return combat_obs(ctx, rc.battle.entity_observation())
    return macro_obs(rc.macro_observation())
