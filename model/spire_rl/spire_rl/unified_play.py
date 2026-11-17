"""Combats played by the unified network (docs/claude-unified-net-design-20261116.md, steps 4-5).

``CombatBatch`` plays many combats at once (each its own RunContext) and evaluates all their
search leaves in one network call per round (GPU or CPU):
* ``mode="net"``: the policy alone (most probable action);
* ``mode="norm"``: PUCT search (``NetSearch``), network priors, leaf value U (design
  section 3) with the in-tree min / max normalisation (``normalize_q``); a won fight is a
  leaf the network values (``eval_terminal_wins``), a lost one is 0;
* ``mode="rate"``: the same search, leaf value from the "exchange rates": at the start of
  each combat the network gives U and how much U changes per point of HP and per potion
  (finite differences); a leaf is worth (1 - P(death)) x (U0 + rate_hp x HP change +
  rate_potion x potion change), with HP / potions at the end of the fight predicted by the
  auxiliary head (exact for a won fight). Also normalised in the tree.
The run context of each combat is encoded once and reused for every leaf.

Users:
* ``play_batch``: a fixed list of combat-start snapshots (evaluation);
* ``CombatServer``: whole runs (self-play). ``MacroEnv`` threads hand their combats to one
  server thread through ``hook`` and wait; the server plays every open combat together, so
  the network sees one batch of leaves from all of them.
Recording (``record=True``) keeps, per searched decision, the combat entity observation, the
chosen action and the root visits in legal-action order (``unified_data.pack`` format).
"""
from __future__ import annotations

import queue
import threading
import time

import numpy as np
import torch

from . import combat_play as cp
from . import unified_obs as uo
from .sim import sim
from .unified_net import UnifiedNet, ValueWeights, collate, combine


def _split_packed(d: dict) -> list[dict]:
    el, cl = np.asarray(d["ent_len"]), np.asarray(d["cand_len"])
    eo, co = np.concatenate([[0], np.cumsum(el)]), np.concatenate([[0], np.cumsum(cl)])
    num = np.asarray(d["num"]).reshape(int(eo[-1]), -1)
    cn = np.asarray(d["cand_num"], np.float32)
    cnum = cn.reshape(int(co[-1]), -1) if co[-1] else np.zeros((0, 1), np.float32)   # all leaves may be won fights
    kind, ids = np.asarray(d["kind"]), np.asarray(d["id"])
    ct, t1, t2 = np.asarray(d["cand_type"]), np.asarray(d["cand_target"]), np.asarray(d["cand_target2"])
    return [{"kind": kind[eo[i]:eo[i + 1]], "id": ids[eo[i]:eo[i + 1]], "num": num[eo[i]:eo[i + 1]],
             "cand_type": ct[co[i]:co[i + 1]], "cand_target": t1[co[i]:co[i + 1]],
             "cand_target2": t2[co[i]:co[i + 1]], "cand_num": cnum[co[i]:co[i + 1]]} for i in range(len(el))]


def _with_hp_potions(o: uo.UObs, d_hp: float, d_pot: float) -> uo.UObs:
    """The same in-combat state with HP (absolute, in points) and potion count shifted, in the
    direct rows and the PLAYER entity."""
    g, p, num = o.global_row.copy(), o.player_row.copy(), o.num.copy()
    maxhp = max(1.0, float(p[uo.P_MAXHP]) * 100)
    hp = float(np.clip(p[uo.P_HP] * 100 + d_hp, 1.0, maxhp))
    pots = max(0.0, float(p[uo.P_POTIONS]) * 5 + d_pot)
    for row, (cf, ch, cp_) in ((g, (uo.G_HPFRAC, uo.G_HP, uo.G_POTIONS)), (p, (uo.P_HPFRAC, uo.P_HP, uo.P_POTIONS))):
        row[cf], row[ch], row[cp_] = hp / maxhp, hp / 100.0, pots / 5.0
    num[o.n_ctx, :uo.COMBAT_NUM] = p                      # first combat entity = PLAYER
    return uo.UObs(o.kind, o.id, num, o.edges, g, p, o.cand_type, o.cand_index, o.cand_t1, o.cand_t2, o.cand_num,
                   o.in_combat, o.n_ctx)


def device_of(net: torch.nn.Module) -> torch.device:
    return next(net.parameters()).device


class _Ctx:
    """Per-combat cache: run context (and the raw macro observation), its encoding on the
    network's device, and the exchange rates."""

    def __init__(self, net: UnifiedNet, rc, vw: ValueWeights, mode: str):
        dev = device_of(net)
        self.macro = rc.macro_observation()
        self.ctx = uo.run_context(self.macro)
        root = uo.observe(rc, self.ctx)
        self.act = root.act
        with torch.no_grad():
            self.enc = net.encode_context(collate([root]).to(dev))
            if mode == "rate":
                obs = [root, _with_hp_potions(root, +5, 0), _with_hp_potions(root, -5, 0), _with_hp_potions(root, 0, +1)]
                out = net(collate(obs).to(dev), ctx=(self.enc[0].expand(4, -1, -1), self.enc[1].expand(4, -1)))
                u = combine(torch.sigmoid(out["q_logit"]), torch.full((4,), self.act, device=dev), vw).cpu().numpy()
                self.u0 = float(u[0])
                self.rate_hp = max(0.0, float(u[1] - u[2]) / 10.0)
                self.rate_pot = max(0.0, float(u[3] - u[0]))
                self.hp0 = float(root.player_row[uo.P_HP]) * 100
                self.pot0 = float(root.player_row[uo.P_POTIONS]) * 5


def _forward_with_cache(net: UnifiedNet, obs: list[uo.UObs], caches: list[_Ctx]) -> tuple[dict, object]:
    dev = device_of(net)
    b = collate(obs).to(dev)
    m = b.kind.shape[1]
    enc = torch.zeros(len(obs), m, net.cfg.dim, device=dev)
    mask = torch.zeros(len(obs), m, dtype=torch.bool, device=dev)
    for i, c in enumerate(caches):
        k = c.enc[0].shape[1]
        enc[i, :k] = c.enc[0][0]; mask[i, :k] = c.enc[1][0]
    return net(b, ctx=(enc, mask)), b


def _leaf_values(out: dict, b, obs: list[uo.UObs], caches: list[_Ctx], vw: ValueWeights, mode: str) -> np.ndarray:
    q = torch.sigmoid(out["q_logit"])
    if mode != "rate":
        return combine(q, b.act, vw).cpu().numpy()
    aux = out["aux"].float().cpu().numpy()
    p_dead = 1.0 / (1.0 + np.exp(-aux[:, 0]))
    vals = []
    for i, (o, c) in enumerate(zip(obs, caches)):
        if len(o.cand_type) == 0:                         # won fight: exact HP and potions
            pd, hp, pots = 0.0, float(o.player_row[uo.P_HP]) * 100, float(o.player_row[uo.P_POTIONS]) * 5
        else:
            pd = float(p_dead[i])
            hp = float(np.clip(aux[i, 1], 0, 1)) * float(o.player_row[uo.P_MAXHP]) * 100
            pots = float(o.player_row[uo.P_POTIONS]) * 5 - max(0.0, float(aux[i, 2]))
        vals.append((1 - pd) * max(0.0, c.u0 + c.rate_hp * (hp - c.hp0) + c.rate_pot * (pots - c.pot0)))
    return np.asarray(vals)


class _Combat:
    __slots__ = ("rc", "res", "cache", "legal", "search", "counter", "seed", "tag")

    def __init__(self, rc, res, cache, seed, tag):
        self.rc, self.res, self.cache, self.seed, self.tag = rc, res, cache, seed, tag
        self.legal = None
        self.search = None
        self.counter = 0


class CombatBatch:
    """Open combats played together; ``add`` one, call ``round`` until it reports it done."""

    def __init__(self, net: UnifiedNet, budgets: dict | None, mode: str = "norm", vw: ValueWeights = ValueWeights(),
                 c_puct: float = 1.5, dirichlet_frac: float = 0.0, record: bool = False, cpp_threads: int = 1):
        if mode not in ("net", "norm", "rate"):
            raise ValueError(f"mode {mode!r}")
        self.net, self.budgets, self.mode, self.vw = net, budgets, mode, vw
        self.c_puct, self.dirichlet_frac, self.record, self.cpp_threads = c_puct, dirichlet_frac, record, cpp_threads
        self.active: list[_Combat] = []
        self.rounds = self.leaves = 0
        self.infer_seconds = 0.0

    @torch.no_grad()
    def add(self, rc, seed: int, tag=None) -> _Combat:
        """``rc`` must be at the start of a combat (``rc.screen == COMBAT``)."""
        self.net.eval()
        c = _Combat(rc, cp._start(rc), _Ctx(self.net, rc, self.vw, self.mode), int(seed), tag)
        c.legal = cp._settle_or_forced(rc, c.res)
        self.active.append(c)
        return c

    def _decide(self, c: _Combat, a: tuple, visits: list | None) -> None:
        if self.record:
            lg = [tuple(x) for x in c.legal]
            c.res.obs.append(c.rc.battle.entity_observation())
            c.res.actions.append(lg.index(a))
            c.res.visits.append(visits if visits is not None else [int(i == lg.index(a)) for i in range(len(lg))])
        c.res.decisions += 1
        c.counter += 1
        if not c.rc.step_combat(*a):
            c.res.ok = False
        c.legal = cp._settle_or_forced(c.rc, c.res)

    @torch.no_grad()
    def round(self) -> list[_Combat]:
        """One step for every open combat (net mode: one decision each; search modes: one
        simulation each, a decision when a search finishes). Returns the combats that ended
        and removes them."""
        done = [c for c in self.active if c.legal is None or not c.res.ok]
        self.active = [c for c in self.active if c.legal is not None and c.res.ok]
        if not self.active:
            return done
        t0 = time.perf_counter()
        if self.mode == "net":
            obs = [uo.observe(c.rc, c.cache.ctx) for c in self.active]
            out, _ = _forward_with_cache(self.net, obs, [c.cache for c in self.active])
            probs = out["logp"].exp().float().cpu().numpy()
            self.infer_seconds += time.perf_counter() - t0
            for row, c in enumerate(self.active):
                a = tuple(c.legal[int(np.argmax(probs[row, :len(c.legal)]))])
                self._decide(c, a, None)
            self.rounds += 1
            return done + self._drop_finished()
        for i, c in enumerate(self.active):
            if c.search is None:
                c.search = sim.NetSearch(c.rc.battle, int(self.budgets[c.res.kind]),
                                         seed=(c.seed + 7919 * c.counter) & 0xFFFFFFFF,
                                         c_puct=self.c_puct, dirichlet_frac=self.dirichlet_frac,
                                         normalize_q=True, eval_terminal_wins=True)
        live = [c.search for c in self.active]
        d = sim.net_search_advance(live, self.cpp_threads)
        idx = list(d["index"])
        if idx:
            owners = [self.active[j] for j in idx]
            obs = [uo.combat_obs(c.cache.ctx, lf) for c, lf in zip(owners, _split_packed(d))]
            t1 = time.perf_counter()
            out, b = _forward_with_cache(self.net, obs, [c.cache for c in owners])
            probs = out["logp"].exp().float().cpu().numpy()
            values = _leaf_values(out, b, obs, [c.cache for c in owners], self.vw, self.mode)
            self.infer_seconds += time.perf_counter() - t1
            cl = [len(o.cand_type) for o in obs]
            pri = np.concatenate([probs[r, :cl[r]] for r in range(len(idx))]).astype(np.float64) if sum(cl) else np.zeros(0)
            sim.net_search_provide(live, idx, pri, cl, values.astype(np.float64).tolist())
            self.leaves += len(idx)
        self.rounds += 1
        waiting = set(idx)
        for pos, c in enumerate(self.active):
            if pos in waiting:
                continue
            s = c.search
            a = tuple(s.best_action())
            visits = None
            if self.record:
                by_action = {tuple(x): int(v) for x, v in zip(s.root_actions(), s.root_visits())}
                visits = [by_action.get(tuple(x), 0) for x in c.legal]
            c.res.simulations += s.simulations_done
            c.search = None
            self._decide(c, a, visits)
        return done + self._drop_finished()

    def _drop_finished(self) -> list[_Combat]:
        out = [c for c in self.active if c.legal is None or not c.res.ok]
        if out:
            self.active = [c for c in self.active if c.legal is not None and c.res.ok]
        return out


def play_batch(snapshots: list[bytes], net: UnifiedNet, budgets: dict | None, mode: str = "norm", seed: int = 0,
               vw: ValueWeights = ValueWeights(), c_puct: float = 1.5, dirichlet_frac: float = 0.0,
               record: bool = False, log=None, cpp_threads: int = 1) -> list[cp.CombatResult]:
    """Plays every snapshot's combat once; results in snapshot order."""
    batch = CombatBatch(net, budgets, mode, vw, c_puct, dirichlet_frac, record, cpp_threads)
    combats = [batch.add(cp.restore(s), seed + 104729 * i, tag=i) for i, s in enumerate(snapshots)]
    t0 = time.perf_counter()
    while batch.active:
        batch.round()
        if log and batch.rounds % 500 == 0:
            log(f"  rounds {batch.rounds}, active {len(batch.active)}, leaves {batch.leaves}, "
                f"{time.perf_counter() - t0:.0f}s (network {batch.infer_seconds:.0f}s)")
    wall = time.perf_counter() - t0
    for c in combats:
        c.res.seconds = wall / max(1, len(combats))
    return [c.res for c in combats]


class CombatServer:
    """Self-play combats for many MacroEnv threads at once (one server thread, one batch).

    ``hook`` is the ``MacroEnv.combat_hook``: it hands the combat to the server and blocks
    until it is over; the finished ``CombatResult`` (with ``meta`` game_seed, combat_index and
    ``ctx`` = the macro observation at the combat start) goes to ``sink``."""

    def __init__(self, batch: CombatBatch, sink: list):
        self.batch, self.sink = batch, sink
        self.inbox: queue.Queue = queue.Queue()
        self.lock = threading.Lock()
        self.error: BaseException | None = None
        self.combats = 0
        self._stop = threading.Event()
        self.thread = threading.Thread(target=self._loop, name="combat-server", daemon=True)
        self.thread.start()

    def hook(self, env, seed):
        if self.error is not None:
            raise RuntimeError("combat server failed") from self.error
        item = {"env": env, "seed": int(seed), "event": threading.Event()}
        self.inbox.put(item)
        while not item["event"].wait(1.0):
            if self.error is not None:
                raise RuntimeError("combat server failed") from self.error
        if "error" in item:
            raise RuntimeError("combat server failed") from item["error"]
        res = item["res"]
        res.meta.update(game_seed=int(env.game_seed), combat_index=int(env.combat_index), ctx=item["ctx"])
        with self.lock:
            self.sink.append(res)
        return res.decisions, res.forced, res.simulations, res.ok

    def _take(self, block: bool) -> list:
        items = []
        try:
            items.append(self.inbox.get(timeout=0.05) if block else self.inbox.get_nowait())
            while True:
                items.append(self.inbox.get_nowait())
        except queue.Empty:
            pass
        return items

    def _loop(self):
        pending: list = []
        try:
            while not self._stop.is_set():
                for item in self._take(block=not self.batch.active):
                    try:
                        c = self.batch.add(item["env"].rc, item["seed"], tag=item)
                    except BaseException as e:            # this combat only
                        item["error"] = e; item["event"].set()
                        continue
                    pending.append(item)
                    self.combats += 1
                    item["ctx"] = c.cache.macro
                for c in self.batch.round():
                    item = c.tag
                    item["res"] = c.res
                    pending.remove(item)
                    item["event"].set()
        except BaseException as e:
            self.error = e
            for item in pending + self._take(block=False):
                item["error"] = e; item["event"].set()

    def close(self):
        self._stop.set()
        self.thread.join(timeout=10)
