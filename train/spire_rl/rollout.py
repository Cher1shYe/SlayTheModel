"""Simulator environments and worker processes for PPO sampling.

Each worker process owns several games. Per decision it observes the public state, lets the
driver apply its guards, auto-applies decisions with a single allowed candidate (their reward
carries into the next sample) and ships the encoded input to the trainer, which runs the
network for all games at once on the GPU.

Encoded inputs are ~98% zeros, so they travel and are stored sparse (``pack`` / ``unpack``).
"""
from __future__ import annotations

import os
import random
import traceback
from dataclasses import dataclass

import numpy as np

_DENSE = ("num", "global_row", "player_row", "cand_num")
_PLAIN = ("kind", "id", "edges", "cand_type", "cand_index", "cand_t1", "cand_t2")


def pack(o) -> dict:
    out = {k: getattr(o, k) for k in _PLAIN}
    for k in _DENSE:
        a = np.asarray(getattr(o, k), np.float32)
        flat = a.reshape(-1)
        idx = np.flatnonzero(flat).astype(np.int32)
        out[k] = (a.shape, idx, flat[idx])
    out["in_combat"], out["n_ctx"], out["schema_id"] = o.in_combat, o.n_ctx, o.schema_id
    return out


def unpack(d):
    from .obs import UObs
    kw = {k: d[k] for k in _PLAIN}
    for k in _DENSE:
        shape, idx, vals = d[k]
        a = np.zeros(int(np.prod(shape)), np.float32)
        a[idx] = vals
        kw[k] = a.reshape(shape)
    o = UObs(**kw, in_combat=d["in_combat"], n_ctx=d["n_ctx"])
    o.schema_id = d["schema_id"]
    return o


@dataclass
class Step:
    """What the trainer receives for one game after the previous action."""
    obs: dict | None        # packed input of the next decision
    allowed: np.ndarray | None
    reward: float           # reward since the previous sample (auto-applied steps included)
    done: bool              # the previous sample ended the game (obs is then the new game's)
    info: dict | None       # finished-game summary when done


class Game:
    def __init__(self, seed: int, ascension: int, reward_weights=None):
        from .driver import Driver
        from .rewards import Reward
        self.rng = random.Random(seed)
        self.ascension = ascension
        self.driver = Driver()
        self.reward = Reward(reward_weights)
        self.errors = 0
        self._new_game()

    def _new_game(self):
        from .sim import sim
        from . import rewards
        self.rc = sim.RunContext()
        self.seed = self.rng.randrange(1 << 62)
        self.rc.init(self.seed, self.ascension)
        self.driver.reset()
        self.elites = self.bosses = 0
        self.ret = 0.0
        self.parts = {}
        self.prog = rewards.progress(self.rc, 0, 0)

    def _advance(self, state, index):
        """Apply a candidate; track elite / boss wins; return the reward of the step."""
        from .sim import sim
        from . import public_obs as p, rewards
        rc = self.rc
        in_combat = rc.screen == sim.RunScreen.COMBAT
        elite, boss = in_combat and rc.combat_is_elite, in_combat and rc.combat_is_boss
        self.driver.chose(index)
        handle = p.candidate_handle(state, index)
        ok = rc.step_combat(*handle) if state.facts["combat"] is not None else rc.step(*handle)
        if not ok:
            raise RuntimeError(f"simulator rejected candidate {state.actions[index].key}")
        if in_combat and rc.screen != sim.RunScreen.COMBAT and rc.hp > 0:
            self.elites += bool(elite)
            self.bosses += bool(boss)
        return self._score(rewards.progress(rc, self.elites, self.bosses))

    def _score(self, new):
        r, parts = self.reward(self.prog, new)
        self.prog = new
        self.ret += r
        for k, v in parts.items():
            self.parts[k] = self.parts.get(k, 0.0) + v
        return r

    def _finish(self, reason):
        from .rewards import Progress
        r = 0.0
        if reason in ("stall", "cap", "error"):        # lost: scored as a death
            x = self.prog
            r = self._score(Progress(x.floor, x.hp, x.max_hp, x.elites, x.bosses, True, False))
        info = {"return": self.ret, "floor": self.prog.floor, "act": int(self.rc.act), "won": self.prog.won,
                "reason": reason, "decisions": self.driver.decisions, "elites": self.elites,
                "bosses": self.bosses, "parts": self.parts}
        self._new_game()
        return r, info

    def next_decision(self, carried: float = 0.0) -> Step:
        """Run until a decision needs the network (or the game ends)."""
        from . import public_obs as p
        reward, done, info = carried, False, None
        while True:
            try:
                if self.rc.is_terminal:
                    r, info = self._finish("won" if self.rc.won else "died")
                    reward += r; done = True
                    continue
                state = p.from_simulator(self.rc)
                if not state.actions:
                    r, info = self._finish("no_actions")
                    reward += r; done = True
                    continue
                d = self.driver.decide(state)
                if d.verdict:
                    r, info = self._finish(d.verdict)
                    reward += r; done = True
                    continue
                if d.forced is not None:
                    r = self._advance(state, d.forced)
                    if not done:                        # a new game's opening steps start at zero
                        reward += r
                    continue
                self._state = state
                return Step(pack(d.obs), d.allowed, reward, done, info)
            except Exception as exc:  # keep long runs alive; counted and logged by the trainer
                self.errors += 1
                r, info = self._finish("error")
                info["error"] = "".join(traceback.format_exception_only(type(exc), exc)).strip()[:400]
                reward += r; done = True

    def act(self, index: int) -> Step:
        try:
            r = self._advance(self._state, index)
        except Exception as exc:
            self.errors += 1
            r, info = self._finish("error")
            info["error"] = "".join(traceback.format_exception_only(type(exc), exc)).strip()[:400]
            step = self.next_decision()
            return Step(step.obs, step.allowed, r + step.reward, True, info)
        return self.next_decision(r)


def worker_main(conn, seeds, ascension, reward_weights):
    os.environ.setdefault("OMP_NUM_THREADS", "1")
    games = [Game(s, ascension, reward_weights) for s in seeds]
    while True:
        msg = conn.recv()
        if msg[0] == "reset":
            conn.send([g.next_decision() for g in games])
        elif msg[0] == "act":
            conn.send([g.act(int(i)) for g, i in zip(games, msg[1])])
        elif msg[0] == "close":
            conn.close()
            return


class Pool:
    """``workers`` processes x ``games`` games each, stepped in lockstep."""

    def __init__(self, workers: int, games: int, seed: int, ascension: int = 10, reward_weights=None):
        import multiprocessing as mp
        ctx = mp.get_context("spawn")
        self.conns, self.procs = [], []
        rng = random.Random(seed)
        for _ in range(workers):
            a, b = ctx.Pipe()
            proc = ctx.Process(target=worker_main, args=(b, [rng.randrange(1 << 62) for _ in range(games)],
                                                         ascension, reward_weights), daemon=True)
            proc.start()
            self.conns.append(a); self.procs.append(proc)
        self.games = games

    def reset(self) -> list[Step]:
        for c in self.conns:
            c.send(("reset",))
        return [s for c in self.conns for s in c.recv()]

    def act(self, actions) -> list[Step]:
        for w, c in enumerate(self.conns):
            c.send(("act", actions[w * self.games:(w + 1) * self.games]))
        return [s for c in self.conns for s in c.recv()]

    def close(self):
        for c in self.conns:
            try:
                c.send(("close",))
            except (BrokenPipeError, OSError):
                pass
        for proc in self.procs:
            proc.join(timeout=5)
