"""Simulator environments and worker processes for PPO sampling.

Each worker process owns several games. Per decision it observes the public state, lets the
driver apply its guards, auto-applies decisions with a single allowed candidate (their reward
carries into the next sample) and ships the encoded input to the trainer, which runs the
network for all games at once on the GPU.

Practice fights (docs/plan.md 6.2): full games save the state just before each combat is entered.
A practice slot restores such a state, replaces only the combat RNG streams and takes the same
entering action, so the normal combat setup re-deals the opening hand and hidden randomness. It
plays that one fight: a loss scores like a death; a win ends the episode and the trainer adds the
discounted value of the post-combat state. The policy input carries no practice marker.

Encoded inputs are ~98% zeros, so they travel and are stored sparse (``pack`` / ``unpack``).
"""
from __future__ import annotations

import os
import random
import signal
import traceback
import zlib
from collections import deque
from dataclasses import dataclass

import numpy as np

_DENSE = ("num", "global_row", "player_row", "cand_num")
_PLAIN = ("kind", "id", "edges", "cand_type", "cand_index", "cand_t1", "cand_t2")

HIDDEN_CARDS = 10       # top of the draw pile shown to the training-only value input
HIDDEN_VOCAB = 1200     # 0 = none, else 1 + 2 * card id + upgraded


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
    boot: dict | None = None        # practice win: packed post-combat input to bootstrap from
    hidden: np.ndarray | None = None  # training-only value input (never given to the policy)
    floor: int = 0          # floor of the decision in ``obs`` (time unit of the discount, DEVLOG 52)
    fight: int = 0          # combats entered so far in this game: tells consecutive fights apart


class PracticePool:
    """Recent pre-combat states of one worker. Capacities keep the 15 : 5 : 4 fight mix, so the
    type weights give the planned share (boss 44%, elite 28%, normal 28%) once full."""
    CAPACITY = {"normal": 240, "elite": 80, "boss": 64}
    TYPE_WEIGHT = {"normal": 1.0, "elite": 3.0, "boss": 6.0}
    EMA = 0.05

    def __init__(self, seed: int):
        self.rng = random.Random(seed)
        self.entries = {k: deque(maxlen=n) for k, n in self.CAPACITY.items()}
        self.stats = {}         # encounter -> [death rate, HP lost / max HP]

    def add(self, kind: str, encounter: int, snapshot: bytes, handle: tuple):
        self.entries[kind].append((kind, encounter, zlib.compress(snapshot, 1), handle))

    def observe(self, encounter: int, died: bool, hp_lost: float):
        x = self.stats.setdefault(encounter, [float(died), hp_lost])
        x[0] += self.EMA * (float(died) - x[0])
        x[1] += self.EMA * (hp_lost - x[1])

    def weight(self, entry) -> float:
        death, lost = self.stats.get(entry[1], (0.5, 0.5))
        return self.TYPE_WEIGHT[entry[0]] * (0.25 + death + lost)

    def sample(self):
        items = [e for q in self.entries.values() for e in q]
        return self.rng.choices(items, [self.weight(e) for e in items])[0] if items else None


class Game:
    def __init__(self, seed: int, ascension: int, reward_weights=None, pool: PracticePool | None = None,
                 practice: bool = False, hidden: bool = False, seed_queue: deque | None = None):
        from .driver import Driver
        from .rewards import Reward
        self.rng = random.Random(seed)
        self.ascension = ascension
        self.driver = Driver()
        self.reward = Reward(reward_weights)
        self.pool, self.practice, self.want_hidden = pool, practice, hidden
        self.seed_queue = seed_queue    # fixed evaluation seeds; the game idles when they run out
        self.idle = False
        self.errors = 0
        self._new_game()

    def _new_game(self):
        from .sim import sim
        from . import rewards
        self.driver.reset()
        self.elites = self.bosses = 0
        self.ret = 0.0
        self.parts = {}
        self.mode, self.fight_kind, self.encounter, self._fight = "full", None, None, None
        self.room = None                # kind of the combat in progress (kept when the game is lost in it)
        self.fought = {"normal": 0, "elite": 0, "boss": 0}
        if self.practice and self._start_practice():
            self.prog = rewards.progress(self.rc, 0, 0)
            return
        if self.seed_queue is not None:
            if not self.seed_queue:
                self.idle = True
                return
            self.seed = self.seed_queue.popleft()
        else:
            self.seed = self.rng.randrange(1 << 62)
        self.rc = sim.RunContext()
        self.rc.init(self.seed, self.ascension)
        self.prog = rewards.progress(self.rc, 0, 0)

    def _start_practice(self) -> bool:
        from .sim import sim
        entry = self.pool.sample() if self.pool is not None else None
        if entry is None:
            return False
        kind, encounter, blob, handle = entry
        rc = sim.RunContext()
        try:        # a re-deal that cannot start falls back to a full game; never kill the worker
            if not rc.restore(zlib.decompress(blob)):
                return False
            rc.reseed_combat_streams(self.rng.randrange(1 << 62))
            if not rc.step(*handle) or rc.screen != sim.RunScreen.COMBAT or rc.battle.encounter_id != encounter:
                return False
        except Exception:
            return False
        self.rc, self.seed = rc, rc.seed
        self.mode, self.fight_kind, self.encounter = "practice", kind, encounter
        self._fight = (encounter, int(rc.hp))
        self.room = kind
        self.fought[kind] += 1
        return True

    def _close_fight(self, died: bool):
        if self._fight is not None and self.pool is not None:
            encounter, hp0 = self._fight
            self.pool.observe(encounter, died, max(0, hp0 - int(self.rc.hp)) / max(1, int(self.rc.max_hp)))
        self._fight = None

    def _advance(self, state, index):
        """Apply a candidate; track elite / boss wins; return the reward of the step."""
        from .sim import sim
        from . import public_obs as p, rewards
        rc = self.rc
        in_combat = rc.screen == sim.RunScreen.COMBAT
        elite, boss = in_combat and rc.combat_is_elite, in_combat and rc.combat_is_boss
        before = rc.snapshot() if self.pool is not None and self.mode == "full" and not in_combat else None
        self.driver.chose(index)
        handle = p.candidate_handle(state, index)
        ok = rc.step_combat(*handle) if state.facts["combat"] is not None else rc.step(*handle)
        if not ok:
            raise RuntimeError(f"simulator rejected candidate {state.actions[index].key}")
        if not in_combat and rc.screen == sim.RunScreen.COMBAT:
            self.encounter = int(rc.battle.encounter_id)
            kind = "boss" if rc.combat_is_boss else "elite" if rc.combat_is_elite else "normal"
            self.room = kind
            self.fought[kind] += 1
            if self.pool is not None:
                self.pool.add(kind, self.encounter, before, tuple(handle))
                self._fight = (self.encounter, int(rc.hp))
        if in_combat and (rc.screen != sim.RunScreen.COMBAT or rc.is_terminal):
            self._close_fight(rc.hp <= 0)
        if in_combat and rc.screen != sim.RunScreen.COMBAT and rc.hp > 0:
            self.elites += bool(elite)
            self.bosses += bool(boss)
            self.room = None
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
        self._close_fight(True)     # still open only when the game was lost by a guard or an error
        if reason in ("stall", "cap", "error"):        # lost: scored as a death
            x = self.prog
            r = self._score(Progress(x.floor, x.hp, x.max_hp, x.elites, x.bosses, True, False))
        info = {"return": self.ret, "floor": self.prog.floor, "act": int(self.rc.act), "won": self.prog.won,
                "reason": reason, "decisions": self.driver.decisions, "elites": self.elites,
                "bosses": self.bosses, "parts": self.parts, "mode": self.mode, "fight": self.fight_kind,
                "encounter": self.encounter, "seed": self.seed, "fought": dict(self.fought),
                "death_room": None if reason in ("won", "practice_win") else (self.room or "noncombat")}
        self._new_game()
        return r, info

    def _hidden(self):
        from .sim import sim
        out = np.zeros(HIDDEN_CARDS, np.int32)
        if self.want_hidden and self.rc.screen == sim.RunScreen.COMBAT:
            top = self.rc.battle.hidden_draw_order(HIDDEN_CARDS)
            out[:len(top)] = np.asarray(top, np.int32) + 1
        return out

    def next_decision(self, carried: float = 0.0) -> Step:
        """Run until a decision needs the network (or the game ends)."""
        from .sim import sim
        from . import public_obs as p
        reward, done, info, boot = carried, False, None, None
        while True:
            if self.idle:
                return Step(None, None, reward, done, info, boot)
            try:
                if self.rc.is_terminal:
                    r, info = self._finish("won" if self.rc.won else "died")
                    reward += r; done = True
                    continue
                state = p.from_simulator(self.rc)
                if self.mode == "practice" and self.rc.screen != sim.RunScreen.COMBAT:
                    boot = pack(p.encode(state)) if state.actions else None
                    r, info = self._finish("practice_win")
                    reward += r; done = True
                    continue
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
                return Step(pack(d.obs), d.allowed, reward, done, info, boot,
                            self._hidden() if self.want_hidden else None,
                            int(self.rc.floor), sum(self.fought.values()))
            except Exception as exc:  # keep long runs alive; counted and logged by the trainer
                self.errors += 1
                r, info = self._finish("error")
                info["error"] = "".join(traceback.format_exception_only(type(exc), exc)).strip()[:400]
                reward += r; done = True; boot = None

    def act(self, index: int) -> Step:
        if self.idle:
            return Step(None, None, 0.0, False, None)
        try:
            r = self._advance(self._state, index)
        except Exception as exc:
            self.errors += 1
            r, info = self._finish("error")
            info["error"] = "".join(traceback.format_exception_only(type(exc), exc)).strip()[:400]
            step = self.next_decision()     # keep the new game's fields (hidden input, floor, fight)
            return Step(step.obs, step.allowed, r + step.reward, True, info, step.boot, step.hidden, step.floor, step.fight)
        return self.next_decision(r)


def worker_main(conn, seeds, ascension, reward_weights, practice=0.0, hidden=False, fixed_seeds=None):
    os.environ.setdefault("OMP_NUM_THREADS", "1")
    signal.signal(signal.SIGINT, signal.SIG_IGN)    # Ctrl-C reaches the whole group; the trainer stops us
    queue = deque(fixed_seeds) if fixed_seeds is not None else None
    pool = PracticePool(seeds[0]) if practice > 0 else None
    slots = round(practice * len(seeds))
    games = [Game(s, ascension, reward_weights, pool, i < slots, hidden, queue) for i, s in enumerate(seeds)]
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
    """``workers`` processes x ``games`` games each, stepped in lockstep. ``practice`` is the share
    of games playing practice fights; ``fixed_seeds`` plays exactly those seeds, then idles."""

    def __init__(self, workers: int, games: int, seed: int, ascension: int = 10, reward_weights=None,
                 practice: float = 0.0, hidden: bool = False, fixed_seeds=None):
        import multiprocessing as mp
        ctx = mp.get_context("spawn")
        self.conns, self.procs = [], []
        rng = random.Random(seed)
        for w in range(workers):
            a, b = ctx.Pipe()
            fixed = None if fixed_seeds is None else list(fixed_seeds[w::workers])
            proc = ctx.Process(target=worker_main, args=(b, [rng.randrange(1 << 62) for _ in range(games)],
                                                         ascension, reward_weights, practice, hidden, fixed), daemon=True)
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
