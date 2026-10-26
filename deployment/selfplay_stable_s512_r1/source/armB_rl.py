#!/usr/bin/env python3
"""Arm B 战斗 RL:per-battle REINFORCE(奖励=赢+留血),BC 权重热启动。
不再模仿 MCTS,直接用模型能看到的信息把仗打好。看 eval 楼层能否从 BC 的~12 往上走、逼近/超过 MCTS。
跑: ARM_B_ARCH=256,256 STS_SIM_COUNT=2000 INIT=armB_model_B256x256.pt python armB_rl.py [n_games] [workers] [batch]
"""
import os, sys, json, time, random, statistics, tempfile, shutil
import multiprocessing as mp
SB = os.environ.get("STS_BOT_DIR", "../sts-bot")
sys.path.insert(0, os.path.join(SB, "sim/sts_lightspeed/build312"))
sys.path.insert(0, SB)
import torch
import armB_train as B

ARCH = tuple(int(x) for x in os.environ.get("ARM_B_ARCH", "256,256").split(","))
INIT = os.environ.get("INIT", "")     # 热启动权重(BC 模型);空=从零

def worker_rollout(args):
    seed, wpath = args
    net = B.Scorer(ARCH); net.load_state_dict(torch.load(wpath, weights_only=True)); net.eval()
    return B.gen_rl_rollout(seed, net)

def worker_eval(args):
    seed, wpath = args
    net = B.Scorer(ARCH); net.load_state_dict(torch.load(wpath, weights_only=True)); net.eval()
    return B.play_with_model(seed, net)

def battle_loss(net, traj, adv):                 # 重算 logprob(带梯度)
    lps = []
    for state, descs, a in traj:
        lps.append(torch.log_softmax(net.score(state, descs), dim=0)[a])
    if not lps: return None
    return -(torch.stack(lps).sum()) * adv

if __name__ == "__main__":
    N = int(sys.argv[1]) if len(sys.argv) > 1 else 6000
    W = int(sys.argv[2]) if len(sys.argv) > 2 else max(2, mp.cpu_count() - 2)
    BATCH = int(sys.argv[3]) if len(sys.argv) > 3 else 32
    EVAL_EVERY = int(os.environ.get("EVAL_EVERY", "400"))
    TAG = os.environ.get("PROG_TAG", "RL_" + "x".join(str(a) for a in ARCH))
    print(f"Arm B RL: {N}局 {W}workers batch{BATCH} sim{B.SIMCOUNT} arch{ARCH} init={INIT or '从零'} | 每{EVAL_EVERY}局eval", flush=True)

    net = B.Scorer(ARCH)
    if INIT and os.path.exists(os.path.join(SB, INIT)):
        net.load_state_dict(torch.load(os.path.join(SB, INIT), weights_only=True))
        print(f"热启动: 载入 {INIT}", flush=True)
    opt = torch.optim.Adam(net.parameters(), lr=3e-4)        # 微调用小 lr

    eval_seeds = B.read_seeds("eval_seeds_50.txt"); eset = set(eval_seeds)
    rng = random.Random(0); games = []
    while len(games) < N:
        s = rng.randint(1, 10**9)
        if s not in eset: games.append(s)

    baseline = None; floors = []; t0 = time.time()
    TRACK = os.path.join(SB, f"armB_track_{TAG}.jsonl"); tf = open(TRACK, "w")
    from torch.utils.tensorboard import SummaryWriter
    tbdir = os.path.join(SB, "tb_armS", TAG); shutil.rmtree(tbdir, ignore_errors=True); tbw = SummaryWriter(log_dir=tbdir)
    ckdir = os.path.join(SB, "ckpts_" + TAG); shutil.rmtree(ckdir, ignore_errors=True); os.makedirs(ckdir)
    best_ev = -1.0; best_ck = None
    wpath = os.path.join(tempfile.gettempdir(), "armB_rl_w.pt")
    ctx = mp.get_context("spawn")
    with ctx.Pool(W) as pool:
        def eval_floor():
            torch.save(net.state_dict(), wpath)
            ef = pool.map(worker_eval, [(s, wpath) for s in eval_seeds])
            return statistics.mean(r["floor"] for r in ef)
        done = 0; next_eval = EVAL_EVERY
        for b in range(0, len(games), BATCH):
            batch = games[b:b + BATCH]
            torch.save(net.state_dict(), wpath)
            results = pool.map(worker_rollout, [(s, wpath) for s in batch])
            opt.zero_grad(); losses = []
            for r in results:
                for traj, R in r["battles"]:
                    baseline = R if baseline is None else 0.99 * baseline + 0.01 * R
                    l = battle_loss(net, traj, R - baseline)
                    if l is not None: losses.append(l)
                floors.append(r["floor"]); done += 1
            if losses:
                (torch.stack(losses).mean()).backward(); opt.step()
            if done >= next_eval:
                tr = statistics.mean(floors[-EVAL_EVERY:]); ev = eval_floor()
                tf.write(json.dumps({"game": done, "train_floor": round(tr,2), "eval_floor": round(ev,2)}) + "\n"); tf.flush()
                tbw.add_scalar("rl/train_floor", tr, done); tbw.add_scalar("rl/eval_floor", ev, done); tbw.flush()
                ckpath = os.path.join(ckdir, f"g{done}_floor{ev:.1f}.pt"); torch.save(net.state_dict(), ckpath)
                star = ""
                if ev > best_ev: best_ev = ev; best_ck = ckpath; star = " ★"
                print(f"[{done}/{N}] train楼层 {tr:.1f} | eval楼层 {ev:.1f} | {time.time()-t0:.0f}s{star}", flush=True)
                next_eval += EVAL_EVERY
        final_ev = eval_floor()
    torch.save(net.state_dict(), os.path.join(SB, f"armB_model_{TAG}.pt"))
    print(f"\nRL完 {done}局. 末eval楼层 {final_ev:.1f} | best {best_ev:.1f} ({os.path.basename(best_ck) if best_ck else '-'}) | {(time.time()-t0)/60:.0f}分", flush=True)
