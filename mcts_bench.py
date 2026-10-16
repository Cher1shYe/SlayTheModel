"""Compatibility entry point for the tested combat-search implementation.

Use sts2-rl-agent/scripts/benchmark_mcts.py for paired timing, or
scripts/benchmark_mcts_batch.py for parallel sampling throughput.
"""
import argparse
from pathlib import Path
import sys
from time import perf_counter
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent / 'sts2-rl-agent'))
from sts2_env.search.clone import clone_state
from sts2_env.search.mcts import STS2CombatEnv, apply_action, hp_value, legal_actions, search

clone = fast_copy = clone_state


def run_search(root_state, n_sims, c_puct, rollout_depth, rng):
    result = search(root_state, n_sims, rollout_depth,
                    seed=int(rng.integers(0, 2**32)), exploration=c_puct)
    return result.action, result.root


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sims', type=int, nargs='+', default=[64, 256])
    parser.add_argument('--episodes', type=int, default=3)
    parser.add_argument('--rollout-depth', type=int, default=40)
    parser.add_argument('--cpuct', type=float, default=1.4)
    parser.add_argument('--seed', type=int, default=0)
    parser.add_argument('--mode', choices=['auto', 'reference', 'replay'], default='auto')
    parser.add_argument('--max-decisions', type=int, default=400)
    parser.add_argument('--clone', choices=['safe', 'fast'], default='safe',
                        help='Both names use safe copies; unsafe deepcopy was removed')
    args = parser.parse_args()
    if args.episodes < 1 or args.max_decisions < 1 or any(n < 1 for n in args.sims):
        parser.error('episodes, max-decisions and sims must be positive')
    if args.rollout_depth < 0 or args.cpuct < 0:
        parser.error('rollout-depth and cpuct must be nonnegative')
    print(f'mode={args.mode}; safe clone; rollout depth={args.rollout_depth}; perfect-information benchmark')
    print(' sims/move    ms/move   sims/sec   moves   W/L/capped')
    for budget in args.sims:
        rng = np.random.default_rng(args.seed)
        wins = losses = capped = moves = simulations = 0
        started = perf_counter()
        for episode in range(args.episodes):
            env = STS2CombatEnv()
            env.reset(seed=args.seed * 1000 + episode)
            for _ in range(args.max_decisions):
                if env.combat.is_over:
                    break
                result = search(env.combat, budget, args.rollout_depth,
                                int(rng.integers(0, 2**32)), args.cpuct, args.mode)
                simulations += result.simulations
                if result.action is None:
                    break
                apply_action(env.combat, result.action)
                moves += 1
            if env.combat.is_over:
                wins += bool(env.combat.player_won)
                losses += not env.combat.player_won
            else:
                capped += 1
        elapsed = perf_counter() - started
        print(f'{budget:10} {1000*elapsed/max(moves,1):10.1f} {simulations/elapsed:10.1f} '
              f'{moves:7} {wins}/{losses}/{capped}', flush=True)


if __name__ == '__main__':
    main()
