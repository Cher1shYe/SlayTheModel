"""Combat players for the combat-network experiments (see combat_net.py).

* ``play_rollout_mcts``: the existing hidden-information MCTS with random rollouts
  (same search as rc.play_combat_mcts), optionally recording each decision's entity
  observation, chosen action and root visit counts (training data).
* ``play_batch``: many combats at once from RunContext snapshots, played by
  - ``("mcts", budgets)``: rollout MCTS (threads; the C++ search releases the GIL),
  - ``("net", net)``: the network alone (most probable action),
  - ``("netsearch", net, budgets)``: PUCT search with the network's priors and leaf
    values, leaves of all combats evaluated in one forward per round.
  Every player starts from the same snapshot (same game RNG state), so results are paired.

Budgets are per combat kind: {"normal": n, "elite": n, "boss": n}.
The combat value is BattleContext.combat_value(): 0 on death, else
win_base + (1 - win_base) * (hp + potion_weight * potions) / max_hp.
"""
from __future__ import annotations

import concurrent.futures as cf
import time
from dataclasses import dataclass, field

import numpy as np
import torch

from .sim import sim

COMBAT = sim.RunScreen.COMBAT
SETTLE = (1, 0, 0, 0)            # Action{} (END_TURN): settles a decided battle into the run screen
WIN_BASE, POTION_WEIGHT = 0.4, 4.0


def combat_kind(rc) -> str:
    return "boss" if rc.combat_is_boss else ("elite" if rc.combat_is_elite else "normal")


@dataclass
class CombatResult:
    kind: str = ""
    act: int = 0
    floor: int = 0
    hp_before: int = 0
    max_hp: int = 0
    potions_before: int = 0
    died: bool = False
    won: bool = False
    hp_after: int = 0
    potions_after: int = 0
    value: float = 0.0
    decisions: int = 0
    forced: int = 0
    simulations: int = 0
    seconds: float = 0.0
    ok: bool = True
    # recording (training data): per searched decision
    obs: list = field(default_factory=list)
    actions: list = field(default_factory=list)
    visits: list = field(default_factory=list)
    meta: dict = field(default_factory=dict)


def _start(rc) -> CombatResult:
    bc = rc.battle
    return CombatResult(kind=combat_kind(rc), act=int(rc.act), floor=int(rc.floor), hp_before=int(bc.player_hp),
                        max_hp=int(bc.player_max_hp), potions_before=int(bc.potion_count))


def _finish(res: CombatResult, bc) -> None:
    res.won = bc.outcome == sim.Outcome.PLAYER_VICTORY
    res.died = not res.won
    res.hp_after = int(bc.player_hp)
    res.potions_after = int(bc.potion_count)
    res.value = float(bc.combat_value(WIN_BASE, POTION_WEIGHT))


def _settle_or_forced(rc, res: CombatResult):
    """Steps forced actions; returns the legal actions of the next real decision, or None when
    the combat is over (result filled in)."""
    while rc.screen == COMBAT:
        bc = rc.battle
        legal = bc.legal_actions()
        if not legal:
            _finish(res, bc)
            if not rc.step_combat(*SETTLE):
                res.ok = False
            return None
        if len(legal) > 1:
            return legal
        res.forced += 1
        if not rc.step_combat(*legal[0]):
            res.ok = False
            return None
    # The combat ended inside step_combat: rc.battle keeps the final battle state
    # (before after-combat run effects such as Burning Blood's heal).
    _finish(res, rc.battle)
    return None


def play_rollout_mcts(rc, budgets: dict, seed: int, record: bool = False, c: float = 4.242640687,
                      epsilon: float = 0.05) -> CombatResult:
    res = _start(rc)
    sims = int(budgets[res.kind])
    t0 = time.perf_counter()
    n = 0
    while True:
        legal = _settle_or_forced(rc, res)
        if legal is None:
            break
        bc = rc.battle
        obs = bc.entity_observation() if record else None
        acts, s, visits = bc.mcts_root(sims, c, (seed + 7919 * n) & 0xFFFFFFFF, True, epsilon, POTION_WEIGHT)
        n += 1
        res.simulations += s
        if not acts or tuple(acts[0]) not in [tuple(a) for a in legal]:
            res.ok = False
            break
        a = tuple(acts[0])
        if record:
            res.obs.append(obs)
            res.actions.append([tuple(x) for x in legal].index(a))
            res.visits.append(list(visits))
        if not rc.step_combat(*a):
            res.ok = False
            break
    res.decisions = n
    res.seconds = time.perf_counter() - t0
    return res


def make_mcts_hook(budgets: dict, sink: list, record: bool = True, snapshot: bool = False):
    """MacroEnv.combat_hook that plays with rollout MCTS and appends the CombatResult to ``sink``
    (``snapshot``: also keep the combat-start RunContext snapshot, about 0.6 MB each)."""
    def hook(env, seed):
        snap = env.rc.snapshot() if snapshot else None
        res = play_rollout_mcts(env.rc, budgets, seed, record=record)
        res.meta.update(game_seed=int(env.game_seed), combat_index=int(env.combat_index), snapshot=snap)
        sink.append(res)
        return res.decisions, res.forced, res.simulations, res.ok
    return hook


# --- batched play from snapshots ------------------------------------------------------------
def restore(snapshot: bytes):
    rc = sim.RunContext()
    if not rc.restore(snapshot):
        raise ValueError("snapshot restore failed")
    return rc


@torch.no_grad()
def _net_eval(net, packed_or_obs, packed: bool):
    from .combat_net import collate_obs, collate_packed
    b = collate_packed(packed_or_obs) if packed else collate_obs(packed_or_obs)
    logp, value = net(b)
    return logp.exp().numpy(), value.numpy()


def play_batch(snapshots: list[bytes], player: tuple, seed: int = 0, threads: int = 3,
               search_cfg: dict | None = None, record: bool = False, log=None) -> list[CombatResult]:
    kind = player[0]
    if kind == "mcts":
        budgets = player[1]

        def one(i):
            rc = restore(snapshots[i])
            return play_rollout_mcts(rc, budgets, (seed + 104729 * i) & 0xFFFFFFFF, record=record)
        with cf.ThreadPoolExecutor(max_workers=threads) as pool:
            return list(pool.map(one, range(len(snapshots))))

    net = player[1]
    net.eval()
    budgets = player[2] if kind == "netsearch" else None
    sc = dict(c_puct=1.5, fpu_reduction=0.2, dirichlet_alpha=0.3, dirichlet_frac=0.0)
    sc.update(search_cfg or {})
    rcs = [restore(s) for s in snapshots]
    results = [_start(rc) for rc in rcs]
    t0 = time.perf_counter()
    legal = [_settle_or_forced(rc, r) for rc, r in zip(rcs, results)]
    searches: list = [None] * len(rcs)
    counter = [0] * len(rcs)
    rounds = 0
    while True:
        active = [i for i in range(len(rcs)) if legal[i] is not None and results[i].ok]
        if not active:
            break
        if kind == "net":
            obs = [rcs[i].battle.entity_observation() for i in active]
            probs, _ = _net_eval(net, obs, packed=False)
            for row, i in enumerate(active):
                a = int(np.argmax(probs[row, :len(legal[i])]))
                if record:
                    results[i].obs.append(obs[row]); results[i].actions.append(a)
                results[i].decisions += 1
                if not rcs[i].step_combat(*legal[i][a]):
                    results[i].ok = False
                legal[i] = _settle_or_forced(rcs[i], results[i])
            continue
        # netsearch: (re)create searches for combats at a new decision
        for i in active:
            if searches[i] is None:
                sims = int(budgets[results[i].kind])
                s_seed = (seed + 104729 * i + 7919 * counter[i]) & 0xFFFFFFFF
                searches[i] = sim.NetSearch(rcs[i].battle, sims, seed=s_seed, potion_weight=POTION_WEIGHT,
                                            win_base=WIN_BASE, **sc)
        live = [searches[i] for i in active]
        d = sim.net_search_advance(live, 1)
        idx = list(d["index"])
        if idx:
            probs, values = _net_eval(net, d, packed=True)
            cl = np.asarray(d["cand_len"])
            pri = np.concatenate([probs[r, :cl[r]] for r in range(len(idx))]).astype(np.float64)
            sim.net_search_provide(live, idx, pri, cl.tolist(), values.astype(np.float64).tolist())
            rounds += 1
        waiting = set(idx)
        for pos, i in enumerate(active):
            if pos in waiting:
                continue
            s = searches[i]
            a = tuple(s.best_action())
            lg = [tuple(x) for x in legal[i]]
            if record:
                results[i].obs.append(rcs[i].battle.entity_observation())
                results[i].actions.append(lg.index(a))
                results[i].visits.append(list(s.root_visits()))
            results[i].simulations += s.simulations_done
            results[i].decisions += 1
            counter[i] += 1
            searches[i] = None
            if not rcs[i].step_combat(*a):
                results[i].ok = False
            legal[i] = _settle_or_forced(rcs[i], results[i])
        if log and rounds % 500 == 0 and idx:
            log(f"  rounds {rounds}, active {len(active)}, {time.perf_counter() - t0:.0f}s")
    wall = time.perf_counter() - t0
    for r in results:
        r.seconds = wall / max(1, len(results))
    return results


def summarize(results: list[CombatResult]) -> dict:
    out = {}
    for k in ("all", "normal", "elite", "boss"):
        rs = [r for r in results if k == "all" or r.kind == k]
        if not rs:
            continue
        out[k] = {"n": len(rs), "death": float(np.mean([r.died for r in rs])),
                  "hp_loss": float(np.mean([(r.hp_before - r.hp_after) / max(1, r.max_hp) for r in rs if r.won] or [np.nan])),
                  "value": float(np.mean([r.value for r in rs])),
                  "potions_used": float(np.mean([r.potions_before - r.potions_after for r in rs])),
                  "decisions": float(np.mean([r.decisions for r in rs])), "failed": int(sum(not r.ok for r in rs))}
    return out


def paired(a: list[CombatResult], b: list[CombatResult]) -> dict:
    """Mean difference a - b (value, death) with standard errors, per kind."""
    out = {}
    for k in ("all", "normal", "elite", "boss"):
        pairs = [(x, y) for x, y in zip(a, b) if k == "all" or x.kind == k]
        if len(pairs) < 2:
            continue
        dv = np.array([x.value - y.value for x, y in pairs])
        dd = np.array([float(x.died) - float(y.died) for x, y in pairs])
        out[k] = {"n": len(pairs), "value_diff": float(dv.mean()), "value_se": float(dv.std(ddof=1) / np.sqrt(len(dv))),
                  "death_diff": float(dd.mean()), "death_se": float(dd.std(ddof=1) / np.sqrt(len(dd)))}
    return out
