#!/usr/bin/env python3
"""Arm B 行为克隆训练:① 并行用 MCTS 神谕产数据 ② 监督模仿训练 ③ 周期 eval(楼层 + 模仿准确率)。
跑: ARM_B_ARCH=256,256 STS_SIM_COUNT=2000 python armB_train_parallel.py [n_data_seeds] [epochs] [workers]
模仿准确率 = 编码器够不够的体温计;eval 楼层 vs MCTS 标杆(sim2000≈39)= BC 追平了没。
"""
import os, sys, json, time, random, statistics, tempfile, shutil
import multiprocessing as mp
SB = os.environ.get("STS_BOT_DIR", "../sts-bot")
sys.path.insert(0, os.path.join(SB, "sim/sts_lightspeed/build312"))
sys.path.insert(0, SB)
import torch
import armB_train as B

ARCH = tuple(int(x) for x in os.environ.get("ARM_B_ARCH", "256,256").split(","))

def worker_gen(seed):
    return B.gen_demos(seed)

def worker_eval(args):
    seed, wpath = args
    net = B.Scorer(ARCH); net.load_state_dict(torch.load(wpath, weights_only=True)); net.eval()
    return B.play_with_model(seed, net)

if __name__ == "__main__":
    N_DATA = int(sys.argv[1]) if len(sys.argv) > 1 else 300
    EPOCHS = int(sys.argv[2]) if len(sys.argv) > 2 else 8
    W = int(sys.argv[3]) if len(sys.argv) > 3 else max(2, mp.cpu_count() - 2)
    BATCH = int(os.environ.get("BC_BATCH", "64"))
    TAG = os.environ.get("PROG_TAG", "B_" + "x".join(str(a) for a in ARCH))
    print(f"Arm B BC: {N_DATA}局产数据 {EPOCHS}epoch {W}workers sim{B.SIMCOUNT} arch{ARCH} input{B.INPUT_DIM}", flush=True)

    eval_seeds = B.read_seeds("eval_seeds_50.txt"); eset = set(eval_seeds)
    rng = random.Random(0); data_seeds = []
    while len(data_seeds) < N_DATA:
        s = rng.randint(1, 10**9)
        if s not in eset: data_seeds.append(s)

    ctx = mp.get_context("spawn")
    t0 = time.time()
    # ---------- ① 并行产数据 ----------
    with ctx.Pool(W) as pool:
        gens = pool.map(worker_gen, data_seeds)
    demos = [d for g in gens for d in g["demos"]]
    gen_floors = [g["floor"] for g in gens]
    print(f"产数据完: {len(demos)} 个战斗决策样本 | MCTS驱动平均楼层 {statistics.mean(gen_floors):.1f} | {time.time()-t0:.0f}s", flush=True)

    # ---------- ② 监督模仿训练 ----------
    net = B.Scorer(ARCH); opt = torch.optim.Adam(net.parameters(), lr=1e-3)
    TRACK = os.path.join(SB, f"armB_track_{TAG}.jsonl"); tf = open(TRACK, "w")
    from torch.utils.tensorboard import SummaryWriter
    tbdir = os.path.join(SB, "tb_armS", TAG); shutil.rmtree(tbdir, ignore_errors=True)
    tbw = SummaryWriter(log_dir=tbdir)
    ckdir = os.path.join(SB, "ckpts_" + TAG); shutil.rmtree(ckdir, ignore_errors=True); os.makedirs(ckdir)
    wpath = os.path.join(tempfile.gettempdir(), "armB_w.pt")
    best_ev = -1.0
    idxs = list(range(len(demos)))
    with ctx.Pool(W) as pool:
        def eval_floor():
            torch.save(net.state_dict(), wpath)
            ef = pool.map(worker_eval, [(s, wpath) for s in eval_seeds])
            return statistics.mean(r["floor"] for r in ef)
        for ep in range(EPOCHS):
            random.Random(ep).shuffle(idxs)
            opt.zero_grad(); losses = []; correct = 0; seen = 0; step_in_batch = 0
            for j in idxs:
                state, cands, gold = demos[j]
                scores = net.score(state, cands)
                losses.append(torch.nn.functional.cross_entropy(scores.unsqueeze(0), torch.tensor([gold])))
                correct += int(torch.argmax(scores).item() == gold); seen += 1; step_in_batch += 1
                if step_in_batch >= BATCH:
                    (torch.stack(losses).mean()).backward(); opt.step(); opt.zero_grad()
                    losses = []; step_in_batch = 0
            if losses:
                (torch.stack(losses).mean()).backward(); opt.step(); opt.zero_grad()
            acc = correct / max(1, seen)
            ev = eval_floor()
            tf.write(json.dumps({"epoch": ep + 1, "imit_acc": round(acc, 4), "eval_floor": round(ev, 2)}) + "\n"); tf.flush()
            tbw.add_scalar("bc/imit_acc", acc, ep + 1); tbw.add_scalar("bc/eval_floor", ev, ep + 1); tbw.flush()
            star = ""
            if ev > best_ev:
                best_ev = ev; torch.save(net.state_dict(), os.path.join(ckdir, f"ep{ep+1}_floor{ev:.1f}.pt")); star = " ★new-best"
            print(f"[epoch {ep+1}/{EPOCHS}] 模仿准确率 {acc:.3f} | eval楼层 {ev:.1f} | {time.time()-t0:.0f}s{star}", flush=True)
    torch.save(net.state_dict(), os.path.join(SB, f"armB_model_{TAG}.pt"))
    print(f"\nBC完. 末模仿准确率 {acc:.3f} | 末eval楼层 {ev:.1f} | best {best_ev:.1f} | {(time.time()-t0)/60:.0f}分", flush=True)
