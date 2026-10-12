"""Single-player MCTS with one root copy per simulation.

The replay tree stores statistics, not combat snapshots. Simulator RNG is copied
exactly: this is a perfect-information planning benchmark, not an ISMCTS agent.
Use processes rather than threads: the simulator's card ID allocator is global.
"""

from dataclasses import dataclass, field
from math import sqrt
from time import perf_counter
from typing import Callable

import numpy as np

# Import the environment first to preserve the simulator's registration order.
from sts2_env.gym_env.combat_env import STS2CombatEnv  # noqa: F401
import sts2_env.powers  # noqa: F401
from sts2_env.cards import base as card_base
from sts2_env.core.constants import ACTION_END_TURN
from sts2_env.gym_env.action_space import (
    action_to_card_and_target, action_to_potion_and_target,
    get_action_mask, is_potion_action,
)
from sts2_env.search.clone import clone_state


def legal_actions(state):
    return np.flatnonzero(get_action_mask(state)).tolist()


def apply_action(state, action):
    if state.pending_choice is not None:
        success = state.resolve_pending_choice(None if action == ACTION_END_TURN else action - 1)
    elif action == ACTION_END_TURN:
        state.end_player_turn()
        return
    elif is_potion_action(action):
        slot, target = action_to_potion_and_target(action)
        success = slot is not None and state.use_potion(slot, target_index=target)
    else:
        hand, target = action_to_card_and_target(action)
        success = hand is not None and state.play_card(hand, target)
    if not success:
        raise ValueError(f"Search attempted invalid action {action}")


def hp_value(state):
    if state.is_over:
        return 1.0 if state.player_won else -1.0
    return 0.5 * state.player.current_hp / max(state.player.max_hp, 1)


@dataclass(slots=True)
class Node:
    action: int | None = None
    visits: int = 0
    total_value: float = 0.0
    children: list = field(default_factory=list)
    untried: list | None = None
    terminal: bool = False
    # Only the reference implementation retains these snapshots.
    state: object = None
    next_card_id: int = 0

    def initialize(self, state):
        self.terminal = state.is_over
        self.untried = [] if self.terminal else legal_actions(state)

    def select(self, exploration):
        scale = exploration * sqrt(self.visits)
        best = None
        best_score = -float("inf")
        for child in self.children:
            score = child.total_value / child.visits + scale / (1 + child.visits)
            if score > best_score:
                best, best_score = child, score
        return best


@dataclass(slots=True)
class SearchResult:
    action: int | None
    root: Node
    simulations: int
    elapsed: float
    clones: int
    transitions: int

    @property
    def simulations_per_second(self):
        return self.simulations / self.elapsed if self.elapsed else 0.0


def search(state, simulations=256, rollout_depth=40, seed=0, exploration=1.4,
           mode="auto", evaluator: Callable = hp_value):
    """Search with identical semantics in replay and snapshot-reference modes.

    `rollout_depth=0` calls evaluator on the leaf directly (e.g. a value net).
    This changes the evaluation algorithm; it is not a free speed optimization.
    The caller's RNG and global card allocator are preserved even on failure.
    """
    if simulations < 1 or rollout_depth < 0 or exploration < 0:
        raise ValueError("Require simulations >= 1, rollout_depth >= 0, exploration >= 0")
    if mode == "auto":
        mode = "reference" if rollout_depth == 0 else "replay"
    if mode not in ("replay", "reference"):
        raise ValueError("mode must be auto, replay or reference")
    started = perf_counter()
    rng = np.random.default_rng(seed)
    root = Node()
    root.initialize(state)
    saved_id = card_base._next_instance_id
    root.state = state if mode == "reference" else None
    root.next_card_id = saved_id
    clones = transitions = completed = 0
    try:
        for _ in range(0 if root.terminal else simulations):
            node = root
            path = [root]
            card_base._next_instance_id = saved_id
            working = clone_state(state) if mode == "replay" else None
            clones += mode == "replay"
            while node.children and not node.untried and not node.terminal:
                node = node.select(exploration)
                path.append(node)
                if mode == "replay":
                    apply_action(working, node.action)
                    transitions += 1
            if node.untried and not node.terminal:
                action = node.untried.pop(int(rng.integers(len(node.untried))))
                if mode == "reference":
                    working = clone_state(node.state)
                    clones += 1
                    card_base._next_instance_id = node.next_card_id
                apply_action(working, action)
                transitions += 1
                child = Node(action=action)
                child.initialize(working)
                child.next_card_id = card_base._next_instance_id
                if mode == "reference":
                    child.state = working
                node.children.append(child)
                node = child
                path.append(child)
            if mode == "reference":
                working = node.state
                card_base._next_instance_id = node.next_card_id
                if rollout_depth and not node.terminal:
                    working = clone_state(working)
                    clones += 1
            for _ in range(rollout_depth):
                if working.is_over:
                    break
                actions = legal_actions(working)
                if not actions:
                    break
                apply_action(working, actions[int(rng.integers(len(actions)))])
                transitions += 1
            # Terminal utility is fixed; a leaf evaluator cannot override it.
            value = hp_value(working) if working.is_over else float(evaluator(working))
            if not np.isfinite(value):
                raise ValueError("Leaf evaluator returned a non-finite value")
            for visited in path:
                visited.visits += 1
                visited.total_value += value
            completed += 1
    finally:
        card_base._next_instance_id = saved_id
    action = max(root.children, key=lambda child: child.visits).action if root.children else None
    return SearchResult(action, root, completed, perf_counter() - started, int(clones), transitions)
