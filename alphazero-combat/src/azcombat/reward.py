"""Win-first bounded utility for completed combat trajectories."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import math


class Outcome(str, Enum):
    WIN = "win"
    LOSS = "loss"
    UNRESOLVED = "unresolved"
    INVALID = "invalid"


@dataclass(frozen=True)
class TerminalResult:
    outcome: Outcome
    player_entry_hp: int
    player_final_hp: int
    enemy_hp_lost: int
    enemy_hp_total: int
    evidence_valid: bool = True


def score_result(result: TerminalResult) -> float:
    """Return a value where every win outranks every non-win.

    Win utility follows the existing MCTS shape and rewards lower net player HP
    loss. Loss/unresolved utility uses enemy HP damage as progress. Invalid runs
    are rejected: they are not pseudo-terminal learning labels.
    """
    if not result.evidence_valid or result.outcome is Outcome.INVALID:
        raise ValueError("invalid or incomplete evidence cannot receive a terminal reward")
    if min(result.player_entry_hp, result.player_final_hp, result.enemy_hp_lost, result.enemy_hp_total) < 0:
        raise ValueError("HP values must be non-negative")
    progress = min(result.enemy_hp_lost / max(result.enemy_hp_total, 1), 1.0)
    if result.outcome is Outcome.WIN:
        # Match the existing MCTS win curve: every victory is strictly positive,
        # and less net HP loss produces a higher value.
        return 0.5 + math.atan(
            (result.player_final_hp - result.player_entry_hp) / 20.0
        ) / math.pi
    if result.outcome is Outcome.UNRESOLVED:
        # Keep any win above any unresolved rollout, while exposing progress.
        return -0.5 + 0.25 * progress
    if result.outcome is Outcome.LOSS:
        # A defeat is the lowest class; within defeats, enemy damage ranks progress.
        return -1.0 + 0.25 * progress
    raise ValueError(f"unsupported outcome: {result.outcome}")
