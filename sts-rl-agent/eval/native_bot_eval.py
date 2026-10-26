#!/usr/bin/env python3
"""在同样的 50 eval seed 上跑 gamerpuppy 原生 bot(ScumSearchAgent2:启发式非战斗 + MCTS战斗,
boss 翻倍默认开)——和我们的 ArmG+MCTS(42.5/14%@sim50000)直接对比,看差距在哪。
无任何 pause → ag.playout 一次跑完整局。
跑: python native_bot_eval.py 2000,50000 [workers]
"""
import os, sys, statistics, time
import multiprocessing as mp
SB = os.environ.get("STS_BOT_DIR", "../sts-bot")
sys.path.insert(0, os.path.join(SB, "sim/sts_lightspeed/build312"))
sys.path.insert(0, SB)
import slaythespire as sts

def play_native(args):
    seed, sim = args
    gc = sts.GameContext(sts.CharacterClass.IRONCLAD, seed, 0)
    ag = sts.Agent(); ag.simulation_count_base = sim     # boss_simulation_multiplier 默认=3(boss战×3)
    # 不设任何 pause → 原生 bot 全程自己打
    steps = 0
    while gc.outcome == sts.GameOutcome.UNDECIDED and steps < 2000:
        steps += 1; ag.playout(gc)
    return {"seed": seed, "floor": gc.floor_num, "win": gc.outcome == sts.GameOutcome.PLAYER_VICTORY}

def read_seeds(fn):
    return [int(x) for x in open(os.path.join(SB, fn)) if x.strip() and not x.startswith("#")]

if __name__ == "__main__":
    sims = [int(x) for x in (sys.argv[1] if len(sys.argv) > 1 else "2000,50000").split(",")]
    W = int(sys.argv[2]) if len(sys.argv) > 2 else max(2, mp.cpu_count() - 2)
    seeds = read_seeds("eval_seeds_50.txt")
    ctx = mp.get_context("spawn")
    print(f"原生 ScumSearch bot(启发式非战斗+MCTS战斗,boss×3) sims={sims} {W}workers | 对照 ArmG+MCTS@50000=42.5/14%", flush=True)
    for sim in sims:
        t0 = time.time()
        with ctx.Pool(W) as pool:
            res = pool.map(play_native, [(s, sim) for s in seeds])
        fl = [r["floor"] for r in res]; wr = statistics.mean(r["win"] for r in res)
        print(f"  原生bot @sim{sim}: 平均楼层 {statistics.mean(fl):.1f} (范围{min(fl)}-{max(fl)}) | 通关{wr:.2f} | {(time.time()-t0)/60:.1f}分", flush=True)
