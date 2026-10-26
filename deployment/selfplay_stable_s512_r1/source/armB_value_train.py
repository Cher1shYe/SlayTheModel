#!/usr/bin/env python3
"""价值网训练 + 1步前瞻 eval。看 eval 楼层能否破前馈的 ~12-14、逼近 MCTS 的 23。
跑: STS_SIM_COUNT=2000 python armB_value_train.py [n_data] [epochs] [workers]
"""
import os, sys, json, time, random, statistics, tempfile, shutil
import multiprocessing as mp
SB = os.environ.get("STS_BOT_DIR", "../sts-bot")
sys.path.insert(0, os.path.join(SB, "sim/sts_lightspeed/build312"))
sys.path.insert(0, SB)
import torch
import armB_value as V

ARCH = tuple(int(x) for x in os.environ.get("VAL_ARCH", "256,256").split(","))

def worker_gen(seed):
    return V.gen_value_data(seed)

def worker_eval(args):
    seed, wpath = args
    vnet = V.ValueNet(ARCH); vnet.load_state_dict(torch.load(wpath, weights_only=True)); vnet.eval()
    return V.play_with_value(seed, vnet)

if __name__ == "__main__":
    N_DATA = int(sys.argv[1]) if len(sys.argv) > 1 else 300
    EPOCHS = int(sys.argv[2]) if len(sys.argv) > 2 else 15
    W = int(sys.argv[3]) if len(sys.argv) > 3 else max(2, mp.cpu_count() - 2)
    BATCH = int(os.environ.get("VAL_BATCH", "128"))
    TAG = os.environ.get("PROG_TAG", "VAL_" + "x".join(str(a) for a in ARCH))
    print(f"价值网: {N_DATA}局产数据 {EPOCHS}epoch {W}workers sim{V.MB.SIMCOUNT} arch{ARCH}", flush=True)

    eval_seeds = V.MB.read_seeds("eval_seeds_50.txt"); eset = set(eval_seeds)
    rng = random.Random(0); data_seeds = []
    while len(data_seeds) < N_DATA:
        s = rng.randint(1, 10**9)
        if s not in eset: data_seeds.append(s)

    ctx = mp.get_context("spawn"); t0 = time.time()
    with ctx.Pool(W) as pool:
        gens = pool.map(worker_gen, data_seeds)
    data = [d for g in gens for d in g["data"]]
    vals = [v for _, v in data]
    print(f"产数据完: {len(data)} 局面 | 价值均值 {statistics.mean(vals):.2f} | MCTS楼层 {statistics.mean(g['floor'] for g in gens):.1f} | {time.time()-t0:.0f}s", flush=True)

    vnet = V.ValueNet(ARCH); opt = torch.optim.Adam(vnet.parameters(), lr=1e-3)
    TRACK = os.path.join(SB, f"armB_track_{TAG}.jsonl"); tf = open(TRACK, "w")
    from torch.utils.tensorboard import SummaryWriter
    tbdir = os.path.join(SB, "tb_armS", TAG); shutil.rmtree(tbdir, ignore_errors=True); tbw = SummaryWriter(log_dir=tbdir)
    ckdir = os.path.join(SB, "ckpts_" + TAG); shutil.rmtree(ckdir, ignore_errors=True); os.makedirs(ckdir)
    wpath = os.path.join(tempfile.gettempdir(), "armB_val_w.pt"); best_ev = -1.0
    X = torch.tensor([s for s, _ in data], dtype=torch.float32)
    Y = torch.tensor([v for _, v in data], dtype=torch.float32)
    idxs = list(range(len(data)))
    with ctx.Pool(W) as pool:
        def eval_floor():
            torch.save(vnet.state_dict(), wpath)
            ef = pool.map(worker_eval, [(s, wpath) for s in eval_seeds])
            return statistics.mean(r["floor"] for r in ef), statistics.mean(r["win"] for r in ef)
        for ep in range(EPOCHS):
            random.Random(ep).shuffle(idxs); mse_sum = 0.0; nb = 0
            for b in range(0, len(idxs), BATCH):
                bi = idxs[b:b+BATCH]
                pred = vnet.net(X[bi]).squeeze(-1)
                loss = torch.nn.functional.mse_loss(pred, Y[bi])
                opt.zero_grad(); loss.backward(); opt.step()
                mse_sum += loss.item(); nb += 1
            ev, wr = eval_floor()
            tf.write(json.dumps({"epoch": ep+1, "val_mse": round(mse_sum/nb,4), "eval_floor": round(ev,2), "win_rate": round(wr,3)}) + "\n"); tf.flush()
            tbw.add_scalar("val/mse", mse_sum/nb, ep+1); tbw.add_scalar("val/eval_floor", ev, ep+1); tbw.add_scalar("val/win_rate", wr, ep+1); tbw.flush()
            star = ""
            if ev > best_ev: best_ev = ev; torch.save(vnet.state_dict(), os.path.join(ckdir, f"ep{ep+1}_floor{ev:.1f}.pt")); star = " ★"
            print(f"[epoch {ep+1}/{EPOCHS}] valMSE {mse_sum/nb:.3f} | eval楼层 {ev:.1f} | 通关率 {wr:.2f} | {time.time()-t0:.0f}s{star}", flush=True)
    torch.save(vnet.state_dict(), os.path.join(SB, f"armB_model_{TAG}.pt"))
    print(f"\n价值网+1步前瞻完. 末eval {ev:.1f} | best {best_ev:.1f} | {(time.time()-t0)/60:.0f}分", flush=True)
