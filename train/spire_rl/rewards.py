"""Pluggable dense reward terms (docs/plan.md 6.2; Zero-Search values, all parameters).

Each term is one function of the run progress before and after a step plus a weight; add a
term by appending to ``TERMS`` or passing ``weights``. Progress comes from public run facts.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Progress:
    floor: int
    hp: int
    max_hp: int
    elites: int          # elite combats won
    bosses: int          # boss combats won
    over: bool
    won: bool


# win 1.6 (user 2026-11-24, DEVLOG 53): with 0.99 per floor a win is still worth about 1 seen from floor 1
DEFAULT_WEIGHTS = {"floor": 0.01, "elite": 0.02, "boss": 0.1, "win": 1.6, "death": -0.1, "hp": 0.1}


def _potential(x: Progress) -> float:
    return 0.0 if x.over else x.hp / max(1, x.max_hp)


TERMS = {
    "floor": lambda a, b: max(0, b.floor - a.floor),
    "elite": lambda a, b: max(0, b.elites - a.elites),
    "boss": lambda a, b: max(0, b.bosses - a.bosses),
    "win": lambda a, b: float(b.won and not a.won),
    "death": lambda a, b: float(b.over and not b.won and not a.over),
    "hp": lambda a, b: _potential(b) - _potential(a),   # potential-based; terminal potential 0
}


class Reward:
    def __init__(self, weights: dict | None = None):
        self.weights = dict(DEFAULT_WEIGHTS, **(weights or {}))
        unknown = set(self.weights) - set(TERMS)
        if unknown:
            raise ValueError(f"no reward term for {sorted(unknown)}")

    def __call__(self, before: Progress, after: Progress) -> tuple[float, dict]:
        parts = {k: w * TERMS[k](before, after) for k, w in self.weights.items() if w}
        return sum(parts.values()), parts


def progress(rc, elites: int, bosses: int) -> Progress:
    """Run progress from the simulator's public run fields (floor, HP, outcome)."""
    return Progress(int(rc.floor), int(rc.hp), int(rc.max_hp), elites, bosses,
                    bool(rc.is_terminal), bool(rc.won))
