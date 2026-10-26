#!/usr/bin/env python3
"""受控对照:Arm G 非战斗 + 盲目 MCTS 战斗(mcts_recommend 每步搜 sim 次)。
和我们的引导系统在【同样搜索预算】下比——引导@100=26,这里测盲@100/400/2000。
跑: python armB_blind.py 100,400,2000 [workers]
"""
import os, sys, statistics, time
import multiprocessing as mp
SB = os.environ.get("STS_BOT_DIR", "../sts-bot")
sys.path.insert(0, os.path.join(SB, "sim/sts_lightspeed/build312"))
sys.path.insert(0, SB)
import slaythespire as sts
import armB_selfplay as SP        # 复用 _load_armg / _armg_step / _set_all_pauses / NONCOMBAT

ASC = int(os.environ.get("ASC", "0"))     # Ascension 难度(0~20)

def play_blind(seed, sim):
    agnet = SP._load_armg()
    gc = sts.GameContext(sts.CharacterClass.IRONCLAD, seed, ASC)
    ag = sts.Agent(); ag.simulation_count_base = sim; SP._set_all_pauses(ag)
    steps = 0
    try:
        while gc.outcome == sts.GameOutcome.UNDECIDED and steps < 600:
            steps += 1; ag.playout(gc)
            if gc.outcome != sts.GameOutcome.UNDECIDED: break
            if gc.screen_state != sts.ScreenState.BATTLE:
                if gc.screen_state in SP.NONCOMBAT: SP._armg_step(gc, agnet)
                else: break
                continue
            bc = sts.BattleContext(); bc.init(gc); bs = 0
            while bc.outcome == sts.Outcome.UNDECIDED and bs < 800:
                bs += 1
                cands = sts.get_legal_actions(bc)
                if not cands: break
                if len(cands) == 1: cands[0].execute(bc); continue
                sts.mcts_recommend(bc, sim).execute(bc)        # 盲目 MCTS @sim
            bc.exit_battle(gc)
    except Exception: pass
    return {"seed": seed, "floor": gc.floor_num, "win": gc.outcome == sts.GameOutcome.PLAYER_VICTORY}

def worker(args):
    return play_blind(*args)

if __name__ == "__main__":
    sims = [int(x) for x in (sys.argv[1] if len(sys.argv) > 1 else "100,400,2000").split(",")]
    W = int(sys.argv[2]) if len(sys.argv) > 2 else max(2, mp.cpu_count() - 2)
    seeds = SP.MB.read_seeds("eval_seeds_50.txt")
    ctx = mp.get_context("spawn")
    print(f"受控对照 盲MCTS战斗(ArmG非战斗) sims={sims} {W}workers | 对照: 我们引导@100=26.7", flush=True)
    for sim in sims:
        t0 = time.time()
        with ctx.Pool(W) as pool:
            res = pool.map(worker, [(s, sim) for s in seeds])
        fl = [r["floor"] for r in res]; wr = statistics.mean(r["win"] for r in res)
        print(f"  盲MCTS @sim{sim}: eval楼层 {statistics.mean(fl):.1f} (范围{min(fl)}-{max(fl)}) | 通关{wr:.2f} | {(time.time()-t0)/60:.1f}分", flush=True)
