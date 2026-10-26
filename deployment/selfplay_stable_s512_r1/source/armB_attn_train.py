#!/usr/bin/env python3
"""注意力版战斗 BC 训练:并行用 MCTS 产结构化数据 → 监督模仿 → eval。
对照 MLP 版:看 ① 模仿训练准确率能否突破 MLP 的 ~0.44(=表示是否是瓶颈);② eval 楼层能否突破 ~12。
跑: STS_SIM_COUNT=2000 python armB_attn_train.py [n_data] [epochs] [workers]
"""
import os, sys, json, time, random, statistics, tempfile, shutil
import multiprocessing as mp
SB = os.environ.get("STS_BOT_DIR", "../sts-bot")
sys.path.insert(0, os.path.join(SB, "sim/sts_lightspeed/build312"))
sys.path.insert(0, SB)
import torch
import armB_attn as A

D_MODEL = int(os.environ.get("D_MODEL", "64"))
LAYERS = int(os.environ.get("LAYERS", "2"))

def worker_gen(seed):
    return A.gen_attn_demos(seed)

def worker_eval(args):
    seed, wpath = args
    net = A.AttnScorer(d=D_MODEL, layers=LAYERS); net.load_state_dict(torch.load(wpath, weights_only=True)); net.eval()
    return A.play_with_attn(seed, net)

if __name__ == "__main__":
    N_DATA = int(sys.argv[1]) if len(sys.argv) > 1 else 300
    EPOCHS = int(sys.argv[2]) if len(sys.argv) > 2 else 12
    W = int(sys.argv[3]) if len(sys.argv) > 3 else max(2, mp.cpu_count() - 2)
    BATCH = int(os.environ.get("BC_BATCH", "64"))
    TAG = os.environ.get("PROG_TAG", f"ATTN_d{D_MODEL}L{LAYERS}")
    print(f"注意力BC: {N_DATA}局产数据 {EPOCHS}epoch {W}workers sim{A.MB.SIMCOUNT} d_model{D_MODEL} layers{LAYERS}", flush=True)

    eval_seeds = A.MB.read_seeds("eval_seeds_50.txt"); eset = set(eval_seeds)
    rng = random.Random(0); data_seeds = []
    while len(data_seeds) < N_DATA:
        s = rng.randint(1, 10**9)
        if s not in eset: data_seeds.append(s)

    ctx = mp.get_context("spawn"); t0 = time.time()
    with ctx.Pool(W) as pool:
        gens = pool.map(worker_gen, data_seeds)
    demos = [d for g in gens for d in g["demos"]]
    print(f"产数据完: {len(demos)} 样本 | MCTS驱动平均楼层 {statistics.mean(g['floor'] for g in gens):.1f} | {time.time()-t0:.0f}s", flush=True)

    net = A.AttnScorer(d=D_MODEL, layers=LAYERS); opt = torch.optim.Adam(net.parameters(), lr=1e-3)
    TRACK = os.path.join(SB, f"armB_track_{TAG}.jsonl"); tf = open(TRACK, "w")
    from torch.utils.tensorboard import SummaryWriter
    tbdir = os.path.join(SB, "tb_armS", TAG); shutil.rmtree(tbdir, ignore_errors=True); tbw = SummaryWriter(log_dir=tbdir)
    ckdir = os.path.join(SB, "ckpts_" + TAG); shutil.rmtree(ckdir, ignore_errors=True); os.makedirs(ckdir)
    wpath = os.path.join(tempfile.gettempdir(), "armB_attn_w.pt"); best_ev = -1.0
    idxs = list(range(len(demos)))
    with ctx.Pool(W) as pool:
        def eval_floor():
            torch.save(net.state_dict(), wpath)
            ef = pool.map(worker_eval, [(s, wpath) for s in eval_seeds])
            return statistics.mean(r["floor"] for r in ef)
        for ep in range(EPOCHS):
            random.Random(ep).shuffle(idxs)
            opt.zero_grad(); losses = []; correct = 0; n = 0
            for j in idxs:
                tokens, cands, gold = demos[j]
                scores = net.score(tokens, cands)
                losses.append(torch.nn.functional.cross_entropy(scores.unsqueeze(0), torch.tensor([gold])))
                correct += int(torch.argmax(scores).item() == gold); n += 1
                if len(losses) >= BATCH:
                    (torch.stack(losses).mean()).backward(); opt.step(); opt.zero_grad(); losses = []
            if losses:
                (torch.stack(losses).mean()).backward(); opt.step(); opt.zero_grad()
            acc = correct / max(1, n); ev = eval_floor()
            tf.write(json.dumps({"epoch": ep+1, "imit_acc": round(acc,4), "eval_floor": round(ev,2)}) + "\n"); tf.flush()
            tbw.add_scalar("attn/imit_acc", acc, ep+1); tbw.add_scalar("attn/eval_floor", ev, ep+1); tbw.flush()
            star = ""
            if ev > best_ev: best_ev = ev; torch.save(net.state_dict(), os.path.join(ckdir, f"ep{ep+1}_floor{ev:.1f}.pt")); star = " ★"
            print(f"[epoch {ep+1}/{EPOCHS}] 模仿准确率 {acc:.3f} | eval楼层 {ev:.1f} | {time.time()-t0:.0f}s{star}", flush=True)
    torch.save(net.state_dict(), os.path.join(SB, f"armB_model_{TAG}.pt"))
    print(f"\n注意力BC完. 末模仿acc {acc:.3f} | 末eval {ev:.1f} | best {best_ev:.1f} | {(time.time()-t0)/60:.0f}分", flush=True)
