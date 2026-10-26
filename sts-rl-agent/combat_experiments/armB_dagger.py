#!/usr/bin/env python3
"""Arm B DAgger:迭代聚合数据治 BC 的误差累积。
Round0: MCTS 驱动产数据(=BC 起点)→ 训 → eval。
Round1..K: 模型自己驾驶踩坑、MCTS 在坑里给答案 → 追加进数据集 → 重训 → eval。
看 eval 楼层能否一轮轮被拉起来,逼近 MCTS。
跑: ARM_B_ARCH=256,256 STS_SIM_COUNT=2000 python armB_dagger.py [rounds] [seeds_per_round] [epochs] [workers]
"""
import os, sys, json, time, random, statistics, tempfile, shutil
import multiprocessing as mp
SB = os.environ.get("STS_BOT_DIR", "../sts-bot")
sys.path.insert(0, os.path.join(SB, "sim/sts_lightspeed/build312"))
sys.path.insert(0, SB)
import torch
import armB_train as B

ARCH = tuple(int(x) for x in os.environ.get("ARM_B_ARCH", "256,256").split(","))

def worker_mcts(seed):                          # round0:MCTS 驱动产数据
    return B.gen_demos(seed)

def worker_dagger(args):                         # 后续轮:模型驾驶 + MCTS 标注
    seed, wpath = args
    net = B.Scorer(ARCH); net.load_state_dict(torch.load(wpath, weights_only=True)); net.eval()
    return B.gen_dagger_demos(seed, net)

def worker_eval(args):
    seed, wpath = args
    net = B.Scorer(ARCH); net.load_state_dict(torch.load(wpath, weights_only=True)); net.eval()
    return B.play_with_model(seed, net)

def train_on(D, epochs, batch=64):
    net = B.Scorer(ARCH); opt = torch.optim.Adam(net.parameters(), lr=1e-3)
    idxs = list(range(len(D)))
    acc = 0.0
    for ep in range(epochs):
        random.Random(ep).shuffle(idxs)
        opt.zero_grad(); losses = []; correct = 0; n = 0
        for k, j in enumerate(idxs):
            state, cands, gold = D[j]
            scores = net.score(state, cands)
            losses.append(torch.nn.functional.cross_entropy(scores.unsqueeze(0), torch.tensor([gold])))
            correct += int(torch.argmax(scores).item() == gold); n += 1
            if len(losses) >= batch:
                (torch.stack(losses).mean()).backward(); opt.step(); opt.zero_grad(); losses = []
        if losses:
            (torch.stack(losses).mean()).backward(); opt.step(); opt.zero_grad()
        acc = correct / max(1, n)
    return net, acc

if __name__ == "__main__":
    ROUNDS = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    SPR = int(sys.argv[2]) if len(sys.argv) > 2 else 150
    EPOCHS = int(sys.argv[3]) if len(sys.argv) > 3 else 8
    W = int(sys.argv[4]) if len(sys.argv) > 4 else max(2, mp.cpu_count() - 2)
    TAG = os.environ.get("PROG_TAG", "DAG_" + "x".join(str(a) for a in ARCH))
    print(f"DAgger: {ROUNDS}轮 每轮{SPR}局 {EPOCHS}epoch {W}workers sim{B.SIMCOUNT} arch{ARCH}", flush=True)

    eval_seeds = B.read_seeds("eval_seeds_50.txt"); eset = set(eval_seeds)
    rng = random.Random(0)
    def fresh_seeds(n):
        out = []
        while len(out) < n:
            s = rng.randint(1, 10**9)
            if s not in eset: out.append(s)
        return out

    TRACK = os.path.join(SB, f"armB_track_{TAG}.jsonl"); tf = open(TRACK, "w")
    from torch.utils.tensorboard import SummaryWriter
    tbdir = os.path.join(SB, "tb_armS", TAG); shutil.rmtree(tbdir, ignore_errors=True); tbw = SummaryWriter(log_dir=tbdir)
    ckdir = os.path.join(SB, "ckpts_" + TAG); shutil.rmtree(ckdir, ignore_errors=True); os.makedirs(ckdir)
    wpath = os.path.join(tempfile.gettempdir(), "armB_dag_w.pt")
    D = []; net = None; best_ev = -1.0; t0 = time.time()
    ctx = mp.get_context("spawn")
    with ctx.Pool(W) as pool:
        def eval_floor():
            torch.save(net.state_dict(), wpath)
            ef = pool.map(worker_eval, [(s, wpath) for s in eval_seeds])
            return statistics.mean(r["floor"] for r in ef)
        for rd in range(ROUNDS + 1):
            if rd == 0:                                    # round0:MCTS 驱动(BC 起点)
                gens = pool.map(worker_mcts, fresh_seeds(SPR))
            else:                                          # 后续:模型驾驶踩坑 + MCTS 标注
                torch.save(net.state_dict(), wpath)
                gens = pool.map(worker_dagger, [(s, wpath) for s in fresh_seeds(SPR)])
            new = [d for g in gens for d in g["demos"]]; D += new
            gen_fl = statistics.mean(g["floor"] for g in gens)
            net, acc = train_on(D, EPOCHS)                 # 在聚合后的全量 D 上重训
            ev = eval_floor()
            tf.write(json.dumps({"round": rd, "D_size": len(D), "gen_floor": round(gen_fl,2),
                                 "imit_acc": round(acc,4), "eval_floor": round(ev,2)}) + "\n"); tf.flush()
            tbw.add_scalar("dag/eval_floor", ev, rd); tbw.add_scalar("dag/imit_acc", acc, rd)
            tbw.add_scalar("dag/D_size", len(D), rd); tbw.flush()
            star = ""
            if ev > best_ev:
                best_ev = ev; torch.save(net.state_dict(), os.path.join(ckdir, f"r{rd}_floor{ev:.1f}.pt")); star = " ★"
            tag = "round0(BC)" if rd == 0 else f"DAgger{rd}"
            print(f"[{tag}] D={len(D)} 产数据驾驶者楼层{gen_fl:.1f} | 模仿acc {acc:.3f} | eval楼层 {ev:.1f} | {time.time()-t0:.0f}s{star}", flush=True)
    torch.save(net.state_dict(), os.path.join(SB, f"armB_model_{TAG}.pt"))
    print(f"\nDAgger完. best eval楼层 {best_ev:.1f} | {(time.time()-t0)/60:.0f}分", flush=True)
