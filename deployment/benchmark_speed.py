"""Throughput benchmark for the native STS2 engine.

Reports three things: Python-driven greedy runs/s, raw C++ MCTS simulations/s,
and self-play decisions/s with the network priors.
"""
from __future__ import annotations

import argparse
import pathlib
import subprocess
import time

import numpy as np
import torch

from agent.common import (
    new_run,
    sim,
    SCREEN,
    combat_action_arrays,
    combat_observation,
)
from agent.nets import CombatNet


def bench_runs(runs: int = 2000) -> dict:
    start = time.perf_counter()
    wins = 0
    combats = 0
    for seed in range(runs):
        rc = new_run(seed + 1)
        guard = 0
        while rc.screen != SCREEN.RUN_OVER and guard < 5000:
            guard += 1
            if rc.screen == SCREEN.COMBAT:
                if not rc.step_combat(*rc.battle.greedy_action(0.05, seed + 1)):
                    break
                if rc.screen != SCREEN.COMBAT:
                    combats += 1
            else:
                legal = rc.legal_actions()
                if not legal:
                    break
                if rc.screen == SCREEN.CARD_REWARD:
                    rc.step(int(sim.RunActionType.TAKE_CARD), 0) if rc.deck_count < 24 \
                        else rc.step(int(sim.RunActionType.SKIP_CARD), 0)
                elif rc.screen == SCREEN.REST:
                    rc.step(int(sim.RunActionType.REST_HEAL), 0) if rc.hp * 10 < rc.max_hp * 6 \
                        else rc.step(*legal[-1])
                elif rc.screen == SCREEN.MAP:
                    rc.step(int(sim.RunActionType.MOVE), 0)
                elif rc.screen == SCREEN.SHOP:
                    rc.step(int(sim.RunActionType.LEAVE_SHOP), 0)
                elif rc.screen == SCREEN.EVENT:
                    rc.step(int(sim.RunActionType.EVENT_CHOICE), 0)
                else:
                    rc.step(*legal[0])
        wins += rc.won
    dt = time.perf_counter() - start
    return {"runs_s": runs / dt, "combats_s": combats / dt, "winrate": wins / runs, "seconds": dt}


def bench_mcts(simulations: int = 64, decisions: int = 2000) -> dict:
    rc = new_run(1)
    rc.step(int(sim.RunActionType.MOVE), 0)
    bc = rc.battle
    start = time.perf_counter()
    for i in range(decisions):
        bc.search(simulations, 1.5, 0.05, i + 1)
    dt = time.perf_counter() - start
    return {"mcts_sims_s": simulations * decisions / dt, "decisions_s": decisions / dt}


def bench_selfplay(simulations: int = 16, runs: int = 20) -> dict:
    torch.set_num_threads(1)
    model = CombatNet()
    from agent.selfplay import play_episode
    start = time.perf_counter()
    records = 0
    wins = 0
    for seed in range(runs):
        ep = play_episode(seed + 1, model, simulations, sample=False)
        records += len(ep["records"])
        wins += ep["won"]
    dt = time.perf_counter() - start
    return {"selfplay_runs_s": runs / dt, "decisions_s": records / dt,
            "sims_s": records * simulations / dt, "winrate": wins / runs}


def bench_cpp_binary(path: pathlib.Path, runs: int) -> dict:
    if not path.exists():
        return {}
    out = subprocess.run([str(path), "run", str(runs)], capture_output=True, text=True)
    return {"cpp": out.stdout.strip()} if out.returncode == 0 else {}


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=2000)
    parser.add_argument("--simulations", type=int, default=16)
    parser.add_argument("--mcts-sims", type=int, default=64)
    args = parser.parse_args(argv)

    print("python-driven", bench_runs(args.runs), flush=True)
    print("c++ mcts", bench_mcts(args.mcts_sims), flush=True)
    print("selfplay net+search", bench_selfplay(args.simulations, min(args.runs, 50)), flush=True)
    exe = pathlib.Path(__file__).resolve().parents[1] / "simulator" / "bench.exe"
    cpp = bench_cpp_binary(exe, args.runs)
    if cpp:
        print("c++ bench", cpp, flush=True)


if __name__ == "__main__":
    main()
