#!/usr/bin/env python3
"""死因分析:用训好的 Arm G 模型,在 50 个 eval seed 上贪心跑一遍,
看它死在哪(楼层/幕)、过没过各幕 boss——判断 38–39 以上的空间还归不归非战斗决策管。
跑: ARM_G_ARCH=128,128 python death_analysis.py armG_model_G128x128_15k.pt
"""
import os, sys, statistics, collections
import multiprocessing as mp
SB = os.environ.get("STS_BOT_DIR", "../sts-bot")
sys.path.insert(0, os.path.join(SB, "sim/sts_lightspeed/build312"))
sys.path.insert(0, SB)
import armG_train_parallel as P   # 复用 worker_play(greedy) + ARCH

MODEL = sys.argv[1] if len(sys.argv) > 1 else os.path.join(SB, "armG_model_G128x128_15k.pt")
import armG_train as A
eval_seeds = A.read_seeds("eval_seeds_50.txt")

# act boss 楼层(IRONCLAD):act1≈16/17, act2≈33/34, act3≈50/51
ACT_BOSS_FLOOR = {1: 16, 2: 33, 3: 50}

if __name__ == "__main__":
    ctx = mp.get_context("spawn")
    with ctx.Pool(int(os.environ.get("WORKERS", "12"))) as pool:
        res = pool.map(P.worker_play, [(s, MODEL, True) for s in eval_seeds])

    floors = [r["floor"] for r in res]
    wins = sum(r["win"] for r in res)
    by_act = collections.Counter(r["act"] for r in res)          # 死时所在幕
    print(f"模型: {os.path.basename(MODEL)} | {len(res)} 个eval seed 贪心")
    print(f"平均楼层 {statistics.mean(floors):.1f} | 中位 {statistics.median(floors)} | 范围 {min(floors)}-{max(floors)} | 胜(通关)率 {wins}/{len(res)}")
    print(f"结束时所在幕分布: {dict(sorted(by_act.items()))}")

    # 过 boss 情况:floor 超过该幕 boss 楼层即视为过了那个 boss
    for act, bf in ACT_BOSS_FLOOR.items():
        passed = sum(1 for f in floors if f > bf)
        print(f"  过 act{act} boss(>f{bf}) 的局数: {passed}/{len(res)}")

    # 死亡楼层直方图(按 10 层一档)
    hist = collections.Counter((f // 5) * 5 for f in floors)
    print("死亡楼层直方图(5层一档):", dict(sorted(hist.items())))

    # 死在 boss 楼层附近(±1)的有多少 = 卡在战斗墙
    near_boss = sum(1 for f in floors for bf in ACT_BOSS_FLOOR.values() if abs(f - bf) <= 1)
    print(f"死在某幕 boss 楼层±1 的局数(疑似战斗墙): {near_boss}/{len(res)}")
