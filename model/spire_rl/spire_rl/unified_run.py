"""Data generation and evaluation for the unified network, for the GPU machine
(docs/claude-unified-net-design-20261116.md, steps 3-5). Training: ``unified_pretrain``,
``unified_train``.

gen   whole runs; out-of-combat choices by a macro checkpoint (sampled, as in training; only to
      produce realistic decks and encounters; the unified macro policy is a later step);
      combats either by the rollout MCTS (teacher, no --net) or by the unified network +
      search (self-play, --net; all running combats share one network batch per round).
      Every searched combat decision is recorded with its run context and the run's per-act
      outcome (``unified_data``), a part file every --episodes-per-part finished runs.
      Resumable: <out>/progress.json keeps the runs done and the next seed; --episodes is the
      total for the directory, so the same command continues; --max-hours stops cleanly.
eval  the fixed combat-start snapshots (evalset.pkl.gz): players mcts128, mcts256 (rollout
      MCTS, CPU) and net, norm<B>, rate<B> (unified network alone / with search in the two
      value-scale modes; B = 256 means normal 256 / elite 512 / boss 1024, B = 64 means
      64/128/256). Results cached per player in <out>/<player>.pkl; paired differences printed.

Usage (from model/spire_rl):
  python -m spire_rl.unified_run gen --macro-ckpt <ckpt> --out <dir> --episodes N --envs E
      [--net <unified.pt> --mode norm|rate --device cuda --cpp-threads T --dirichlet 0.25]
      [--budgets 256,512,1024] [--first-seed S] [--max-hours H]
  python -m spire_rl.unified_run eval --evalset <evalset.pkl.gz> --out <dir>
      --players mcts128,mcts256,net,norm256,rate256 --net <unified.pt> [--device cuda] [--cpp-threads T]
"""
from __future__ import annotations

import argparse
import gzip
import json
import os
import pickle
import threading
import time
from pathlib import Path

import numpy as np
import torch

from . import unified_data as ud
from .unified_net import ValueWeights, load
from .unified_pretrain import setup_device


def _budgets(text: str) -> dict:
    n, e, b = (int(x) for x in text.split(","))
    return {"normal": n, "elite": e, "boss": b}


def gen(args) -> None:
    from . import checkpoint as ckpt
    from .config import RunConfig
    from .rollout import Collector, Job
    from .train import build_model
    from . import unified_play as up

    dev = setup_device(args.device)
    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)
    prog_path = out / "progress.json"
    prog = json.loads(prog_path.read_text()) if prog_path.exists() else {}
    first = args.first_seed if args.first_seed is not None else int(prog.get("next_seed", args.first_seed_default))
    part = int(prog.get("next_part", 0))
    total = int(prog.get("done", 0))          # runs already in this directory (--episodes is the total target)
    if total >= args.episodes:
        print(f"gen: {out} already has {total} runs (target {args.episodes})", flush=True)
        return
    budgets = _budgets(args.budgets)
    p = ckpt.load(args.macro_ckpt)
    cfg = RunConfig.from_dict(p["config"])
    model = build_model(cfg, dev); model.load_state_dict(p["model"]); model.eval()
    collector = Collector(cfg, model, dev, num_envs=args.envs)
    sink: list = []
    lock = threading.Lock()
    server = None
    if args.net:
        net = load(args.net, dev)
        batch = up.CombatBatch(net, budgets, args.mode, ValueWeights(), c_puct=args.c_puct,
                               dirichlet_frac=args.dirichlet, record=True, cpp_threads=args.cpp_threads)
        server = up.CombatServer(batch, sink)
        server.lock = lock
        hook = server.hook
        player = f"net+search {args.mode} ({args.net})"
    else:
        from . import combat_play as cp

        def hook(env, seed):                     # teacher: as unified_data.make_recording_hook, thread-safe sink
            m = env.rc.macro_observation()
            res = cp.play_rollout_mcts(env.rc, budgets, seed, record=True)
            res.meta.update(game_seed=int(env.game_seed), ctx=m)
            with lock:
                sink.append(res)
            return res.decisions, res.forced, res.simulations, res.ok
        player = "rollout MCTS"
    for slot in collector.slots:
        slot.env.combat_hook = hook
    print(f"gen: {player}, budgets {budgets}, envs {args.envs}, device {dev}, first seed {first}, "
          f"part {part}", flush=True)
    meta = {"macro_ckpt": args.macro_ckpt, "net": args.net or "", "mode": args.mode if args.net else "mcts",
            "budgets": budgets, "dirichlet": args.dirichlet if args.net else 0.0}
    t0 = time.time()
    deadline = t0 + 3600 * args.max_hours if args.max_hours else None
    pending: dict[int, tuple[int, bool]] = {}
    stats = {"episodes": 0, "decisions": 0, "floors": []}

    def flush(force: bool = False):
        nonlocal part
        if not pending or (len(pending) < args.episodes_per_part and not force):
            return
        with lock:
            recs = [r for r in sink if r.meta.get("game_seed") in pending]
            sink[:] = [r for r in sink if r.meta.get("game_seed") not in pending]
        d = ud.pack(recs, dict(pending))
        if d is not None:
            np.savez_compressed(out / f"part_{part:05d}.npz", **d)
            stats["decisions"] += int(len(d["action"]))
        part += 1
        pending.clear()

    def on_episode(ep):
        if int(ep.outcome) in (1, 2):             # WIN, DEATH (truncated / failed runs are dropped)
            pending[int(ep.game_seed)] = (int(ep.info.get("floor", 0)), int(ep.outcome) == 1)
            stats["floors"].append(int(ep.info.get("floor", 0)))
        else:
            with lock:
                sink[:] = [r for r in sink if r.meta.get("game_seed") != int(ep.game_seed)]
        stats["episodes"] += 1
        flush()

    done = 0
    chunk = max(args.envs * 3, args.episodes_per_part)
    try:
        while total + done < args.episodes and not (deadline and time.time() > deadline):
            n = min(chunk, args.episodes - total - done)
            seeds = [first + done + i for i in range(n)]
            jobs = [Job(done + i, s, (s * 2654435761) & 0xFFFFFFFF) for i, s in enumerate(seeds)]
            collector.collect(iter(jobs), stage=0, alpha=0.5, min_transitions=None, sample_seed=first,
                              on_episode=on_episode)
            done += n
            flush(force=True)
            prog_path.write_text(json.dumps({"next_seed": first + done, "next_part": part, "done": total + done, **meta},
                                            indent=1))
            el = time.time() - t0
            extra = ""
            if server is not None:
                b = server.batch
                extra = (f" | leaves {b.leaves} rounds {b.rounds} mean batch {b.leaves / max(1, b.rounds):.1f} "
                         f"network {b.infer_seconds:.0f}s")
            print(f"[{el:.0f}s] episodes {total + done}/{args.episodes} ({el / max(1, done):.1f}s each) "
                  f"floors {np.mean(stats['floors'][-n:] or [0]):.1f} decisions {stats['decisions']}{extra}", flush=True)
    finally:
        if server is not None:
            server.close()
        collector.close()
    print(f"stopped: {total + done}/{args.episodes} runs in {out}, next seed {first + done}", flush=True)
    if total + done < args.episodes:
        raise SystemExit(3)                        # not finished (--max-hours): the caller must not go on


BUDGETS = {"128": {"normal": 128, "elite": 128, "boss": 512}, "256": {"normal": 256, "elite": 512, "boss": 1024},
           "64": {"normal": 64, "elite": 128, "boss": 256}, "16": {"normal": 16, "elite": 32, "boss": 64}}


def evaluate(args) -> None:
    from . import combat_play as cp
    from . import unified_play as up

    dev = setup_device(args.device)
    with gzip.open(args.evalset, "rb") as f:
        items = pickle.load(f)
    kinds = args.kinds.split(",")
    items = [s for s in items if s["kind"] in kinds][:args.limit]
    snaps = [s["snapshot"] for s in items]
    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)
    net = load(args.net, dev) if args.net else None
    results = {}
    for name in args.players.split(","):
        path = out / (f"{name}.pkl" if name.startswith("mcts") else f"{name}{args.tag}.pkl")   # MCTS: shared
        if path.exists():
            results[name] = pickle.load(open(path, "rb"))
            continue
        t0 = time.time()
        if name.startswith("mcts"):
            res = cp.play_batch(snaps, ("mcts", BUDGETS[name[4:]]), seed=args.seed, threads=args.cpp_threads, log=print)
        else:
            if net is None:
                raise SystemExit(f"player {name} needs --net")
            mode = "net" if name == "net" else name[:4]
            bud = None if mode == "net" else BUDGETS[name[4:]]
            res = up.play_batch(snaps, net, bud, mode=mode, seed=args.seed, c_puct=args.c_puct, log=print,
                                cpp_threads=args.cpp_threads)
        for r in res:
            r.obs = []; r.visits = []; r.actions = []; r.meta = {}
        pickle.dump(res, open(path, "wb"))
        results[name] = res
        print(f"{name}: {time.time() - t0:.0f}s", json.dumps(cp.summarize(res)), flush=True)
    names = list(results)
    summary = {"players": {n: cp.summarize(results[n]) for n in names}, "paired": {}}
    print("\n== summary (death rate, value, HP loss of wins as share of max HP)")
    for n in names:
        print(f"{n:9s} " + "  ".join(f"{k}: n={v['n']} death {v['death']:.3f} value {v['value']:.3f} "
                                     f"hp_loss {v['hp_loss']:.3f} pot {v['potions_used']:.2f}"
                                     for k, v in summary["players"][n].items()))
    print("\n== paired differences (row minus column), value and death, +- standard error")
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            pr = cp.paired(results[a], results[b])
            summary["paired"][f"{a} - {b}"] = pr
            print(f"{a} - {b}: " + "  ".join(f"{k}: dV {v['value_diff']:+.3f}±{v['value_se']:.3f} "
                                             f"dDeath {v['death_diff']:+.3f}±{v['death_se']:.3f}" for k, v in pr.items()))
    (out / f"summary{args.tag}.json").write_text(json.dumps(summary, indent=1))


def main(argv=None):
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("gen")
    g.add_argument("--macro-ckpt", required=True); g.add_argument("--out", required=True)
    g.add_argument("--episodes", type=int, required=True); g.add_argument("--envs", type=int, default=os.cpu_count() or 4)
    g.add_argument("--budgets", default="256,512,1024"); g.add_argument("--first-seed", type=int)
    g.add_argument("--first-seed-default", type=int, default=7_200_000, help="first seed when <out> has no progress yet")
    g.add_argument("--episodes-per-part", type=int, default=8); g.add_argument("--max-hours", type=float)
    g.add_argument("--net"); g.add_argument("--mode", default="norm", choices=("norm", "rate"))
    g.add_argument("--device", default="cpu"); g.add_argument("--cpp-threads", type=int, default=1)
    g.add_argument("--dirichlet", type=float, default=0.25); g.add_argument("--c-puct", type=float, default=1.5)
    e = sub.add_parser("eval")
    e.add_argument("--evalset", required=True); e.add_argument("--out", required=True)
    e.add_argument("--players", required=True); e.add_argument("--net")
    e.add_argument("--device", default="cpu"); e.add_argument("--cpp-threads", type=int, default=1)
    e.add_argument("--kinds", default="normal,elite,boss"); e.add_argument("--limit", type=int)
    e.add_argument("--seed", type=int, default=12345); e.add_argument("--c-puct", type=float, default=1.5)
    e.add_argument("--tag", default="")
    args = ap.parse_args(argv)
    if args.cmd == "gen":
        gen(args)
    else:
        evaluate(args)


if __name__ == "__main__":
    main()
