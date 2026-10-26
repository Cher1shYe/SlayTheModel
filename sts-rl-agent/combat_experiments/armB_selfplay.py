#!/usr/bin/env python3
"""Arm B AlphaZero 自对弈循环:用"当前网络引导的MCTS"自对弈,
把 MCTS访问分布当策略老师、实际胜负当价值老师,在搜索自己走到的局面上重训 policy+value,迭代滚上去。
热启动 BC策略 + MC价值网。看 eval楼层能否一轮轮爬向/超过 MCTS 的 23。
跑: N_SIMS=100 python armB_selfplay.py [iters] [games_per_iter] [train_epochs] [workers]
"""
import os, sys, json, time, random, statistics, tempfile, shutil
import multiprocessing as mp
SB = os.environ.get("STS_BOT_DIR", "../sts-bot")
sys.path.insert(0, os.path.join(SB, "sim/sts_lightspeed/build312"))
sys.path.insert(0, SB)
import slaythespire as sts
import torch
import armB_train as MB
import armB_value as VV
import armB_mcts as MC

N_SIMS = int(os.environ.get("N_SIMS", "100"))
MC.C_PUCT = float(os.environ.get("C_PUCT", "2.0"))
P_ARCH = tuple(int(x) for x in os.environ.get("ARM_B_ARCH", "256,256").split(","))
V_ARCH = tuple(int(x) for x in os.environ.get("VAL_ARCH", "256,256").split(","))
INIT_P = os.environ.get("INIT_P", "armB_model_B256x256.pt")
INIT_V = os.environ.get("INIT_V", "armB_model_VAL256x256.pt")

# 接成熟的 Arm G 非战斗模型(变量一致 + 给战斗好build,标杆=ArmG+MCTS≈39)
import armG_train as AG
AG_ARCH = tuple(int(x) for x in os.environ.get("ARM_G_ARCH", "128,128").split(","))
AG_PATH = os.environ.get("ARMG", "armG_model_G128x128_15k.pt")
NONCOMBAT = (sts.ScreenState.REWARDS, sts.ScreenState.MAP_SCREEN, sts.ScreenState.REST_ROOM,
             sts.ScreenState.SHOP_ROOM, sts.ScreenState.EVENT_SCREEN)

def _load(wp, wv):
    p = MB.Scorer(P_ARCH); p.load_state_dict(torch.load(wp, weights_only=True)); p.eval()
    v = VV.ValueNet(V_ARCH); v.load_state_dict(torch.load(wv, weights_only=True)); v.eval()
    return p, v

def _load_armg():
    g = AG.Scorer(AG_ARCH); g.load_state_dict(torch.load(os.path.join(SB, AG_PATH), weights_only=True)); g.eval()
    return g

def _armg_step(gc, agnet):                          # 用 Arm G 做一个非战斗决策
    kind, descs, execs = AG.build_choices(gc)
    if not descs:
        if gc.screen_state == sts.ScreenState.REWARDS: gc.skip_reward_cards()
        return
    if len(descs) == 1: execs[0](gc); return
    with torch.no_grad():
        a = int(torch.argmax(agnet.score(torch.tensor(AG.obs_vec(gc), dtype=torch.float32), descs)).item())
    execs[a](gc)

def _set_all_pauses(ag):
    ag.pause_on_card_reward = ag.pause_on_map = ag.pause_on_rest = ag.pause_on_shop = ag.pause_on_event = ag.pause_on_battle = True

def worker_selfplay(args):
    seed, wp, wv = args
    policy, value = _load(wp, wv); agnet = _load_armg()
    rng = random.Random(seed)
    gc = sts.GameContext(sts.CharacterClass.IRONCLAD, seed, 0)
    ag = sts.Agent(); ag.simulation_count_base = MB.SIMCOUNT; _set_all_pauses(ag)
    samples = []; steps = 0
    try:
        while gc.outcome == sts.GameOutcome.UNDECIDED and steps < 600:
            steps += 1; ag.playout(gc)
            if gc.outcome != sts.GameOutcome.UNDECIDED: break
            if gc.screen_state != sts.ScreenState.BATTLE:           # 非战斗:交 Arm G
                if gc.screen_state in NONCOMBAT: _armg_step(gc, agnet)
                else: break
                continue
            bc = sts.BattleContext(); bc.init(gc); bs = 0; bsamp = []
            while bc.outcome == sts.Outcome.UNDECIDED and bs < 800:
                bs += 1
                cands = sts.get_legal_actions(bc)
                if not cands: break
                if len(cands) == 1: cands[0].execute(bc); continue
                state = MB.encode_battle(bc); hand = list(bc.hand)
                cds = [MB.cand_desc(bc, a, hand) for a in cands]
                root = MC.Node(bc.clone())                          # 引导MCTS
                for _ in range(N_SIMS): MC.simulate(root, policy, value)
                tot = sum(root.N) if root.N else 0
                if tot == 0:
                    visit = [1.0/len(cands)]*len(cands); idx = 0
                else:
                    visit = [n/tot for n in root.N]
                    idx = rng.choices(range(len(cands)), weights=visit)[0]   # 按访问分布采样=探索
                bsamp.append([state, cds, visit])
                cands[idx].execute(bc)
            V = VV._battle_value(bc)                                 # 本场终局价值→所有局面
            for s in bsamp: samples.append((s[0], s[1], s[2], V))
            bc.exit_battle(gc)
    except Exception: pass
    return {"seed": seed, "floor": gc.floor_num, "samples": samples}

def worker_eval(args):                              # 集成 eval:Arm G 非战斗 + 贪心引导MCTS 战斗
    seed, wp, wv = args
    policy, value = _load(wp, wv); agnet = _load_armg()
    gc = sts.GameContext(sts.CharacterClass.IRONCLAD, seed, 0)
    ag = sts.Agent(); ag.simulation_count_base = MB.SIMCOUNT; _set_all_pauses(ag)
    steps = 0
    try:
        while gc.outcome == sts.GameOutcome.UNDECIDED and steps < 600:
            steps += 1; ag.playout(gc)
            if gc.outcome != sts.GameOutcome.UNDECIDED: break
            if gc.screen_state != sts.ScreenState.BATTLE:
                if gc.screen_state in NONCOMBAT: _armg_step(gc, agnet)
                else: break
                continue
            bc = sts.BattleContext(); bc.init(gc); bs = 0
            while bc.outcome == sts.Outcome.UNDECIDED and bs < 800:
                bs += 1
                cands = sts.get_legal_actions(bc)
                if not cands: break
                if len(cands) == 1: cands[0].execute(bc); continue
                a = MC.mcts_search(bc, policy, value, N_SIMS)
                (a if a is not None else cands[0]).execute(bc)
            bc.exit_battle(gc)
    except Exception: pass
    return {"seed": seed, "floor": gc.floor_num, "win": gc.outcome == sts.GameOutcome.PLAYER_VICTORY}

def train(policy, value, opt_p, opt_v, buf, epochs, batch=64):
    idxs = list(range(len(buf)))
    for ep in range(epochs):
        random.Random(ep).shuffle(idxs)
        lp, lv = [], []
        for j in idxs:
            state, cds, visit, V = buf[j]
            scores = policy.score(state, cds)
            lp.append(-(torch.tensor(visit) * torch.log_softmax(scores, dim=0)).sum())   # 策略:拟合访问分布
            lv.append((value.value(state) - V) ** 2)                                     # 价值:拟合胜负
            if len(lp) >= batch:
                opt_p.zero_grad(); torch.stack(lp).mean().backward(); opt_p.step()
                opt_v.zero_grad(); torch.stack(lv).mean().backward(); opt_v.step()
                lp, lv = [], []
        if lp:
            opt_p.zero_grad(); torch.stack(lp).mean().backward(); opt_p.step()
            opt_v.zero_grad(); torch.stack(lv).mean().backward(); opt_v.step()

if __name__ == "__main__":
    ITERS = int(sys.argv[1]) if len(sys.argv) > 1 else 12
    GPI = int(sys.argv[2]) if len(sys.argv) > 2 else 120
    TEPOCHS = int(sys.argv[3]) if len(sys.argv) > 3 else 4
    W = int(sys.argv[4]) if len(sys.argv) > 4 else max(2, mp.cpu_count() - 2)
    BUF_CAP = int(os.environ.get("BUF_CAP", "40000"))
    TAG = os.environ.get("PROG_TAG", "SP")
    print(f"自对弈: {ITERS}轮 每轮{GPI}局 {TEPOCHS}训练epoch {W}workers N_SIMS{N_SIMS} c_puct{MC.C_PUCT}", flush=True)

    policy = MB.Scorer(P_ARCH); policy.load_state_dict(torch.load(os.path.join(SB, INIT_P), weights_only=True))
    value = VV.ValueNet(V_ARCH); value.load_state_dict(torch.load(os.path.join(SB, INIT_V), weights_only=True))
    opt_p = torch.optim.Adam(policy.parameters(), lr=3e-4)
    opt_v = torch.optim.Adam(value.parameters(), lr=3e-4)

    eval_seeds = MB.read_seeds("eval_seeds_50.txt"); eset = set(eval_seeds)
    rng = random.Random(0)
    TRACK = os.path.join(SB, f"armB_track_{TAG}.jsonl"); tf = open(TRACK, "w")
    from torch.utils.tensorboard import SummaryWriter
    tbdir = os.path.join(SB, "tb_armS", TAG); shutil.rmtree(tbdir, ignore_errors=True); tbw = SummaryWriter(log_dir=tbdir)
    ckdir = os.path.join(SB, "ckpts_" + TAG); shutil.rmtree(ckdir, ignore_errors=True); os.makedirs(ckdir)
    wp = os.path.join(tempfile.gettempdir(), "sp_p.pt"); wv = os.path.join(tempfile.gettempdir(), "sp_v.pt")
    buf = []; best_ev = -1.0; t0 = time.time()
    ctx = mp.get_context("spawn")
    with ctx.Pool(W) as pool:
        # 基线 eval(迭代前)
        torch.save(policy.state_dict(), wp); torch.save(value.state_dict(), wv)
        ev0 = statistics.mean(r["floor"] for r in pool.map(worker_eval, [(s, wp, wv) for s in eval_seeds]))
        print(f"[iter 0 基线] eval楼层 {ev0:.1f} | {time.time()-t0:.0f}s", flush=True)
        tbw.add_scalar("sp/eval_floor", ev0, 0); best_ev = ev0
        for it in range(1, ITERS + 1):
            torch.save(policy.state_dict(), wp); torch.save(value.state_dict(), wv)
            sp_seeds = []
            while len(sp_seeds) < GPI:
                s = rng.randint(1, 10**9)
                if s not in eset: sp_seeds.append(s)
            gens = pool.map(worker_selfplay, [(s, wp, wv) for s in sp_seeds])
            new = [d for g in gens for d in g["samples"]]
            buf += new; buf = buf[-BUF_CAP:]                       # 滑动缓冲
            sp_floor = statistics.mean(g["floor"] for g in gens)
            train(policy, value, opt_p, opt_v, buf, TEPOCHS)
            torch.save(policy.state_dict(), wp); torch.save(value.state_dict(), wv)
            ev = statistics.mean(r["floor"] for r in pool.map(worker_eval, [(s, wp, wv) for s in eval_seeds]))
            tf.write(json.dumps({"iter": it, "buf": len(buf), "sp_floor": round(sp_floor,2), "eval_floor": round(ev,2)}) + "\n"); tf.flush()
            tbw.add_scalar("sp/eval_floor", ev, it); tbw.add_scalar("sp/selfplay_floor", sp_floor, it); tbw.flush()
            star = ""
            if ev > best_ev:
                best_ev = ev; torch.save(policy.state_dict(), os.path.join(ckdir, f"it{it}_p_floor{ev:.1f}.pt"))
                torch.save(value.state_dict(), os.path.join(ckdir, f"it{it}_v_floor{ev:.1f}.pt")); star = " ★"
            print(f"[iter {it}/{ITERS}] buf{len(buf)} 自对弈楼层{sp_floor:.1f} | eval楼层 {ev:.1f} | {time.time()-t0:.0f}s{star}", flush=True)
    print(f"\n自对弈完. 基线{ev0:.1f} → best {best_ev:.1f} | {(time.time()-t0)/60:.0f}分", flush=True)
