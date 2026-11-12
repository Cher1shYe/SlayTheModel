"""Command line: python -m spire_rl {train,distill,pretrain-critic,eval,compare,check,params,config,dashboard,smoke}."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import torch


def _device(name: str) -> torch.device:
    if name == "auto":
        return torch.device("cuda" if torch.cuda.is_available() else "cpu")
    return torch.device(name)


def _config(args, log=print):
    from .config import PRESETS, make_config
    overrides = {}
    preset, saved, saved_progress = args.preset, None, {}
    if getattr(args, "init_checkpoint", None):
        # The network shapes (and the per-size training defaults) come from the checkpoint being continued.
        from . import checkpoint as ckpt
        from .config import RunConfig
        payload = ckpt.load(Path(args.init_checkpoint))
        saved, saved_progress = RunConfig.from_dict(payload["config"]), payload.get("progress") or {}
        if saved.preset in PRESETS:
            preset = saved.preset
    if args.episodes:
        overrides["total_episodes"] = args.episodes
    if getattr(args, "seed", None) is not None:
        overrides["seed"] = args.seed
    if getattr(args, "train_seed_base", None) is not None:
        overrides["train_seed_base"] = args.train_seed_base
    elif saved_progress.get("next_train_seed") is not None:
        # Never replay game seeds the continued weights (or their critic) were trained on.
        overrides["train_seed_base"] = int(saved_progress["next_train_seed"])
        log(f"training game seeds continue at {overrides['train_seed_base']} (from {args.init_checkpoint})")
    ppo = {}
    if getattr(args, "lr", None) is not None:
        ppo["lr"] = args.lr
    if args.num_envs:
        ppo["num_envs"] = args.num_envs
    if getattr(args, "microbatch", None):
        ppo["microbatch"] = args.microbatch
    if ppo:
        overrides["ppo"] = ppo
    reward = {}
    if getattr(args, "gate_policy", None):
        reward["gate_policy"] = args.gate_policy
    if getattr(args, "alpha", None) is not None:
        from .config import RewardStage
        reward["stages"] = (RewardStage(10 ** 9, float(args.alpha), float(args.entropy_coef)),)
    if reward:
        overrides["reward"] = reward
    fork = {k: getattr(args, "fork_" + k) for k in ("rest_prob", "map_prob", "card_prob", "seeds", "coef")
            if getattr(args, "fork_" + k, None) is not None}
    if fork:
        overrides["fork"] = fork
    if getattr(args, "critic_replay", None) is not None:
        ppo["critic_replay_rollouts"] = args.critic_replay
        overrides["ppo"] = ppo
    cfg = make_config(preset, **overrides)
    if saved is not None:
        import dataclasses
        cfg = dataclasses.replace(cfg, preset=saved.preset, model=saved.model, critic=saved.critic)
    return cfg


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="spire_rl", description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    t = sub.add_parser("train", help="train one run (a new run directory each time)")
    t.add_argument("--preset", default="main",
                   help="small (~0.02B, 8-step history), main (~0.2B), large-1b (~0.93B), large-0.7b, tiny; "
                        "ignored with --init-checkpoint (the checkpoint's preset is used)")
    t.add_argument("--run-dir", required=True)
    t.add_argument("--episodes", type=int, help="training starts budget (default 10000)")
    t.add_argument("--num-envs", type=int)
    t.add_argument("--microbatch", type=int)
    t.add_argument("--seed", type=int)
    t.add_argument("--gate-policy", choices=("stop", "hold"))
    t.add_argument("--device", default="auto")
    t.add_argument("--stop-after-updates", type=int, help="short profiling run (M3)")
    t.add_argument("--init-checkpoint", help="continue from these weights (best.pt/last.pt); new optimizer, new run")
    t.add_argument("--critic-prior", help="critic weights from `pretrain-critic` (overrides the checkpoint's critic)")
    t.add_argument("--alpha", type=float, help="one fixed progress weight for the whole run (no reward stages)")
    t.add_argument("--entropy-coef", type=float, default=0.01, help="entropy weight used with --alpha")
    t.add_argument("--fork-rest", dest="fork_rest_prob", type=float, help="paired-fork probability at campfires")
    t.add_argument("--fork-map", dest="fork_map_prob", type=float, help="paired-fork probability at map choices")
    t.add_argument("--fork-card", dest="fork_card_prob", type=float, help="paired-fork probability at card rewards")
    t.add_argument("--fork-seeds", dest="fork_seeds", type=int, help="paired seed sets per fork")
    t.add_argument("--fork-coef", dest="fork_coef", type=float, help="weight of the fork policy loss")
    t.add_argument("--critic-replay", type=int, help="earlier rollouts kept for critic training (0 = off)")
    t.add_argument("--train-seed-base", type=int,
                   help="first training game seed (default: continue after the checkpoint's seeds, else 1000000)")
    t.add_argument("--max-hours", type=float,
                   help="stop before the next rollout after this many hours and save last.pt (continue with "
                        "--init-checkpoint <run>/last.pt in a new run directory)")
    t.add_argument("--lr", type=float, help="policy learning rate (default per preset)")

    ds = sub.add_parser("distill", help="distill an archived policy (and a critic) into a preset, offline")
    ds.add_argument("--archive", nargs="+", required=True, help="archive directories (rollout_*.npz)")
    ds.add_argument("--out", required=True, help="output checkpoint, e.g. runs/distill-small.pt")
    ds.add_argument("--preset", default="small")
    ds.add_argument("--files", type=int, default=60, help="use the last N rollout files (the policy drifts)")
    ds.add_argument("--holdout-files", type=int, default=6)
    ds.add_argument("--epochs", type=int, default=4)
    ds.add_argument("--files-per-chunk", type=int, default=12)
    ds.add_argument("--lr", type=float, default=2e-4)
    ds.add_argument("--microbatch", type=int, default=32)
    ds.add_argument("--device", default="auto")

    pc = sub.add_parser("pretrain-critic", help="offline critic prior from trajectory archives")
    pc.add_argument("--archive", nargs="+", required=True, help="archive directories (rollout_*.npz)")
    pc.add_argument("--out", required=True, help="output file, e.g. runs/critic-prior.pt")
    pc.add_argument("--init-checkpoint", help="take the critic shape (and starting weights) from this checkpoint")
    pc.add_argument("--preset", default="main")
    pc.add_argument("--epochs", type=int, default=2)
    pc.add_argument("--holdout-files", type=int, default=8)
    pc.add_argument("--files-per-chunk", type=int, default=16)
    pc.add_argument("--microbatch", type=int, default=32)
    pc.add_argument("--device", default="auto")

    e = sub.add_parser("eval", help="evaluate a checkpoint on the validation or test seeds")
    e.add_argument("--checkpoint", required=True)
    e.add_argument("--split", choices=("val", "test"), default="val")
    e.add_argument("--limit", type=int)
    e.add_argument("--num-envs", type=int)
    e.add_argument("--device", default="auto")
    e.add_argument("--out", help="write the full result (incl. per-seed outcomes) to this JSON file")

    cmp_ = sub.add_parser("compare", help="paired comparison of two `eval --out` results on the same seeds")
    cmp_.add_argument("a")
    cmp_.add_argument("b")

    ck = sub.add_parser("check", help="environment check + GPU memory/time check for a preset (M3)")
    ck.add_argument("--preset", default="main")
    ck.add_argument("--device", default="auto")
    ck.add_argument("--microbatch", type=int)
    ck.add_argument("--episodes", type=int, default=2, help="random-policy episodes with the real MCTS budget")
    ck.add_argument("--skip-gpu", action="store_true")
    ck.add_argument("--out", help="write the report to this JSON file")

    cf = sub.add_parser("config", help="print the full configuration of a preset as JSON")
    cf.add_argument("--preset", default="main")

    pr = sub.add_parser("params", help="parameter count and training-state memory estimate")
    pr.add_argument("--preset", default="main")

    d = sub.add_parser("dashboard", help="re-render dashboard.html of a run directory")
    d.add_argument("--run-dir", required=True)

    s = sub.add_parser("smoke", help="tiny end-to-end check (CPU friendly, ~minutes)")
    s.add_argument("--run-dir", default="runs/smoke")
    s.add_argument("--device", default="auto")

    args = ap.parse_args(argv)
    if args.cmd == "params":
        from .config import make_config
        from .model import SpireNet, count_parameters
        from .train import env_spec
        cfg = make_config(args.preset)
        with torch.device("meta"):
            n = count_parameters(SpireNet(cfg.model, env_spec(cfg)))
            nc = count_parameters(SpireNet(cfg.critic, env_spec(cfg))) if cfg.critic is not None else 0
        print(json.dumps({"preset": args.preset, "parameters": n, "critic_parameters": nc,
                          "fp32_param_grad_adam_gb": round(16 * n / 1e9, 2)}, indent=2))
        return 0
    if args.cmd == "dashboard":
        from .metrics import MetricsLogger
        cfgj = json.loads((Path(args.run_dir) / "config.json").read_text())
        c = cfgj["config"]
        print(MetricsLogger(Path(args.run_dir), tuple(c["sweet_spot"]), c["total_episodes"],
                            f"SpireNet {c['preset']}").render())
        return 0
    if args.cmd == "eval":
        from . import checkpoint as ckpt
        from .config import RunConfig
        from .train import build_critic, build_model, evaluate
        device = _device(args.device)
        payload = ckpt.load(Path(args.checkpoint))
        cfg = RunConfig.from_dict(payload["config"])
        model = build_model(cfg, device)
        model.load_state_dict(payload["model"])
        critic = build_critic(cfg, device)
        if critic is not None and payload.get("critic") is not None:
            critic.load_state_dict(payload["critic"])
        res = evaluate(model, cfg, device, args.split, args.num_envs, args.limit, critic=critic)
        res["checkpoint"] = str(args.checkpoint)
        res["checkpoint_progress"] = payload.get("progress", {})
        if args.out:
            Path(args.out).write_text(json.dumps(res, indent=1, default=str))
        print(json.dumps({k: v for k, v in res.items() if k != "per_seed"}, indent=2, default=str))
        return 0
    if args.cmd == "pretrain-critic":
        import dataclasses
        from .config import RunConfig, make_config
        from .pretrain import pretrain_critic
        cfg = make_config(args.preset)
        if args.init_checkpoint:
            from . import checkpoint as ckpt
            saved = RunConfig.from_dict(ckpt.load(Path(args.init_checkpoint))["config"])
            cfg = dataclasses.replace(cfg, critic=saved.critic)
        rep = pretrain_critic(cfg, [Path(a) for a in args.archive], Path(args.out), _device(args.device),
                              init_checkpoint=args.init_checkpoint, epochs=args.epochs,
                              files_per_chunk=args.files_per_chunk, holdout_files=args.holdout_files,
                              microbatch=args.microbatch)
        print(json.dumps(rep, indent=2, default=str))
        return 0
    if args.cmd == "distill":
        from .config import make_config
        from .distill import distill
        rep = distill(make_config(args.preset), [Path(a) for a in args.archive], Path(args.out), _device(args.device),
                      files=args.files, holdout_files=args.holdout_files, epochs=args.epochs,
                      files_per_chunk=args.files_per_chunk, lr=args.lr, microbatch=args.microbatch)
        print(json.dumps(rep, indent=2, default=str))
        return 0
    if args.cmd == "compare":
        from .tools import paired_compare
        a, b = (json.loads(Path(x).read_text()) for x in (args.a, args.b))
        print(json.dumps(paired_compare(a, b), indent=2))
        return 0
    if args.cmd == "config":
        from .config import make_config
        cfg = make_config(args.preset)
        print(json.dumps({"config": cfg.to_dict(), "fingerprint": cfg.fingerprint()}, indent=2, default=str))
        return 0
    if args.cmd == "check":
        from .config import make_config
        from .tools import env_check, host_info, resource_check
        device = _device(args.device)
        cfg = make_config(args.preset, **({"ppo": {"microbatch": args.microbatch}} if args.microbatch else {}))
        report = {"host": host_info(Path(".")), **env_check(cfg, args.episodes, log=lambda r: print(r, file=sys.stderr))}
        if not args.skip_gpu:
            report["resources"] = resource_check(cfg, device, log=lambda r: print(r, file=sys.stderr))
        if args.out:
            Path(args.out).write_text(json.dumps(report, indent=1, default=str))
        print(json.dumps(report, indent=2, default=str))
        return 0
    if args.cmd == "smoke":
        from .config import make_config
        from .train import train
        cfg = make_config("tiny", total_episodes=12, eval_every=6, val_seeds=(9_000_000, 4),
                          combat={"normal_simulations": 8, "boss_simulations": 16})
        print(json.dumps(train(cfg, Path(args.run_dir), _device(args.device), stop_after_updates=3),
                         indent=2, default=str))
        return 0
    from .train import train
    cfg = _config(args)
    summary = train(cfg, Path(args.run_dir), _device(args.device), stop_after_updates=args.stop_after_updates,
                    init_checkpoint=args.init_checkpoint, critic_prior=args.critic_prior, max_hours=args.max_hours)
    print(json.dumps(summary, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
