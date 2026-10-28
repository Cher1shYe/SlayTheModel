"""Throughput benchmark for the native STS2 engine.

Reports real completions, not requests: a run counts only when it reaches
RUN_OVER, a combat only when an encounter was actually entered, and a
simulation only when the C++ search reports it completed. The old benchmark
issued MOVE at the Neow event screen (illegal), so it timed an empty search
while printing the requested simulation count.
"""
from __future__ import annotations

import argparse
import pathlib
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor

import torch

from agent.common import SCREEN, new_run, sim
from agent.heuristics import combat_policy, run_policy
from agent.nets import CombatNet
from agent.run_env import RunEnv


def _drive_runs(runs: int) -> dict:
    wins = 0
    completed = 0
    steps = 0
    combats = 0
    floors = 0
    start = time.perf_counter()
    for seed in range(1, runs + 1):
        env = RunEnv(seed)
        local = 0
        while not env.is_terminal() and local < 20000:
            local += 1
            action = (combat_policy(env) if env.screen == SCREEN.COMBAT
                      else run_policy(env))
            if not env.step(action):
                break
        steps += local
        if env.is_terminal():
            completed += 1
            combats += env.rc.combats_fought
            floors += env.rc.floor
            wins += int(env.rc.won)
    dt = time.perf_counter() - start
    return {
        "requested_runs": runs,
        "completed_runs": completed,
        "wins": wins,
        "win_rate": wins / runs,
        "mean_floor": floors / max(1, completed),
        "env_steps": steps,
        "env_steps_s": steps / dt,
        "completed_runs_s": completed / dt,
        "combats": combats,
        "combats_s": combats / dt,
        "seconds": dt,
    }


def _first_combat_battle(seed: int = 1):
    env = RunEnv(seed)
    guard = 0
    while not env.is_terminal() and guard < 20000:
        guard += 1
        if env.screen == SCREEN.COMBAT:
            return env
        action = run_policy(env)
        if not env.step(action):
            break
    raise RuntimeError("heuristic never entered a combat")


def _bench_search(simulations: int, decisions: int, resample: bool,
                  workers: int = 1) -> dict:
    env = _first_combat_battle()
    bc = env.battle
    assert len(bc.monsters) > 0, "search benchmark needs a real encounter"
    done = 0

    def work(chunk: int) -> int:
        total = 0
        for i in range(chunk):
            _a, _v, _val, actual = bc.search(
                simulations, 1.5, 0.05, i + 1, resample)
            total += int(actual)
        return total

    start = time.perf_counter()
    if workers > 1:
        chunks = [decisions // workers + (1 if i < decisions % workers else 0)
                  for i in range(workers)]
        with ThreadPoolExecutor(max_workers=workers) as pool:
            done = sum(pool.map(work, chunks))
    else:
        done = work(decisions)
    dt = time.perf_counter() - start
    return {
        "requested_simulations": simulations * decisions,
        "completed_simulations": done,
        "simulations_s": done / dt,
        "decisions_s": decisions / dt,
        "workers": workers,
        "resample": resample,
        "seconds": dt,
    }


def _bench_selfplay(simulations: int, runs: int) -> dict:
    torch.set_num_threads(1)
    model = CombatNet()
    from agent.selfplay import play_episode
    start = time.perf_counter()
    records = 0
    sims = 0
    wins = 0
    steps = 0
    floors = 0
    for seed in range(1, runs + 1):
        ep = play_episode(seed, model, simulations, sample=False)
        records += len(ep["records"])
        sims += ep["simulations"]
        wins += int(ep["won"])
        steps += ep["steps"]
        floors += ep["floor"]
    dt = time.perf_counter() - start
    return {"runs": runs, "completed_runs": runs, "win_rate": wins / runs,
            "mean_floor": floors / runs, "decisions": records,
            "valid_samples_s": records / dt, "completed_simulations": sims,
            "simulations_s": sims / dt, "env_steps_s": steps / dt,
            "seconds": dt}


def _bench_map_init(runs: int = 1000) -> dict:
    start = time.perf_counter()
    for seed in range(1, runs + 1):
        new_run(seed)
    dt = time.perf_counter() - start
    return {"map_inits": runs, "map_inits_s": runs / dt, "seconds": dt}


def _bench_cpp_binary(path: pathlib.Path, runs: int) -> dict:
    if not path.exists():
        return {}
    out = subprocess.run([str(path), "run", str(runs)], capture_output=True, text=True)
    return {"cpp": out.stdout.strip()} if out.returncode == 0 else {}


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=500)
    parser.add_argument("--simulations", type=int, default=16)
    parser.add_argument("--mcts-sims", type=int, default=64)
    parser.add_argument("--mcts-decisions", type=int, default=500)
    parser.add_argument("--workers", type=int, default=1,
                        help="threads for the GIL-released search benchmark")
    args = parser.parse_args(argv)

    print("python-driven", _drive_runs(args.runs), flush=True)
    print("map-init", _bench_map_init(args.runs), flush=True)
    print("source search", _bench_search(args.mcts_sims, args.mcts_decisions,
                                         False, args.workers), flush=True)
    print("resampled search", _bench_search(args.mcts_sims, args.mcts_decisions,
                                            True, args.workers), flush=True)
    print("selfplay net+search", _bench_selfplay(args.simulations,
                                                 min(args.runs, 50)), flush=True)
    exe = pathlib.Path(__file__).resolve().parents[1] / "simulator" / "bench.exe"
    cpp = _bench_cpp_binary(exe, args.runs)
    if cpp:
        print("c++ bench", cpp, flush=True)


if __name__ == "__main__":
    main()
