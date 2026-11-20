"""AI driver layer: PublicState -> network input -> allowed candidates (docs/plan.md 6.2, DEVLOG 26).

Shared by training and the native client: it reads only ``PublicState`` and its own public
history, never the simulator or the game. It does not change any rule; it only decides which
of the legal candidates the AI may pick and when a game counts as lost:

* **loop guard**: the network's input is the whole decision, so a state it has seen before in
  the same scope looks identical and a greedy policy can cycle (skip / reopen a card reward,
  select / deselect, open / leave a shop). When the same encoded decision comes back a third
  time in a scope, the candidates already taken from it are removed (unless that would leave
  none). In combat a decision repeated within one player turn allows only End Turn.
* **stall**: in combat, if the enemies' total HP has not reached a new low for 20 player turns,
  the game is lost.
* **decision cap**: 5,000 decisions per game, then lost.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

import numpy as np

from . import public_obs as p

STALL_TURNS = 20
DECISION_CAP = 5000
REPEATS_BEFORE_MASK = 2


def decision_hash(o) -> bytes:
    """Hash of everything the network sees at this decision (its encoded input)."""
    h = hashlib.blake2b(digest_size=16)
    for a in (o.kind, o.id, o.num, o.global_row, o.player_row, o.cand_type, o.cand_t1, o.cand_t2, o.cand_num):
        h.update(np.ascontiguousarray(a).tobytes())
    return h.digest()


@dataclass
class Decision:
    obs: object                 # UObs for the network
    allowed: np.ndarray         # [C] bool: candidates the AI may pick
    verdict: str | None = None  # "stall" / "cap": the game is lost, do not act
    forced: int | None = None   # single allowed candidate: apply without asking the network


@dataclass
class Driver:
    decisions: int = 0
    _scope: tuple = ()
    _visits: dict = field(default_factory=dict)      # hash -> times seen in scope
    _taken: dict = field(default_factory=dict)       # hash -> candidate indices taken from it
    _combat_key: tuple | None = None
    _best_hp: float = float("inf")
    _best_turn: int = 0
    _last: bytes | None = None

    def reset(self):
        self.__init__()

    def decide(self, state: p.PublicState) -> Decision:
        """Encode the decision and apply the guards."""
        o = p.encode(state)
        f = state.facts
        n = len(state.actions)
        allowed = np.ones(n, bool)
        self.decisions += 1
        if self.decisions > DECISION_CAP:
            return Decision(o, allowed, verdict="cap")
        combat = f["combat"]
        run = f["run"]
        if combat is not None:
            key = (run["floor"], run["combatsFought"])
            hp = sum(e["hp"] + e["block"] for e in f["enemies"] if e["alive"])
            if key != self._combat_key:
                self._combat_key, self._best_hp, self._best_turn = key, hp, combat["turn"]
            elif hp < self._best_hp:
                self._best_hp, self._best_turn = hp, combat["turn"]
            elif combat["turn"] - self._best_turn >= STALL_TURNS:
                return Decision(o, allowed, verdict="stall")
            scope = ("combat", key, combat["turn"])
        else:
            scope = ("run", run["floor"], f["screen"] if f["screen"] in ("map",) else "room")
        if scope != self._scope:
            self._scope, self._visits, self._taken = scope, {}, {}
        h = decision_hash(o)
        seen = self._visits.get(h, 0)
        self._visits[h] = seen + 1
        self._last = h
        if seen:
            kinds = [a.key.kind for a in state.actions]
            if combat is not None and "end_turn" in kinds:
                allowed[:] = False                          # same decision again this turn
                allowed[kinds.index("end_turn")] = True
            elif seen >= REPEATS_BEFORE_MASK:
                taken = self._taken.get(h, set())
                trial = allowed.copy()
                trial[list(taken)] = False
                if trial.any():
                    allowed = trial
        forced = int(np.flatnonzero(allowed)[0]) if allowed.sum() == 1 else None
        return Decision(o, allowed, forced=forced)

    def chose(self, index: int):
        """Record the candidate taken from the last decision."""
        if self._last is not None:
            self._taken.setdefault(self._last, set()).add(int(index))
