"""Versioned rewards derived from verified game outcomes, outside the policy.

Training uses realized returns; deployment supplies a desired return separately.
This module does not classify a partial or abandoned run as a defeat.
"""

from __future__ import annotations

from typing import Any


WIN_RTG_SCHEME = "whole-run-win-v1"


def win_reward(outcome: str | None) -> float:
    """Return the reward for a transition: None is ongoing, win/defeat terminal.

    Callers must verify the native outcome and episode continuity before using
    a terminal label. Unknown/aborted/truncated outcomes are never zero labels.
    """

    if outcome is None or outcome == "defeat":
        return 0.0
    if outcome == "win":
        return 1.0
    raise ValueError(f"unsupported terminal outcome for {WIN_RTG_SCHEME}: {outcome!r}")


def win_returns_to_go(outcome: str, decision_count: int) -> tuple[float, ...]:
    """Compute undiscounted RTG *before* each action, up to the true run end.

    With zero intermediate reward and discount=1 every preterminal decision
    has the same realized return, even across tensor window boundaries.
    """

    if outcome not in ("win", "defeat"):
        raise ValueError("RTG requires a verified terminal win or defeat")
    if type(decision_count) is not int or decision_count < 1:
        raise ValueError("decision_count must be a positive integer")
    return (win_reward(outcome),) * decision_count


def win_reward_parameters() -> dict[str, Any]:
    """Parameters stored alongside shards for reproducible reward semantics."""

    return {
        "terminal_win": 1.0,
        "terminal_defeat": 0.0,
        "intermediate_reward": 0.0,
        "discount": 1.0,
        "normalization": "none",
        "incomplete_outcome": "reject",
        "raw_reward_version": "whole-run-v2",
    }


__all__ = [
    "WIN_RTG_SCHEME", "win_reward", "win_returns_to_go", "win_reward_parameters",
]
