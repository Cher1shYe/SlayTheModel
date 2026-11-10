"""Command line: python -m spire_rl {train,eval,compare,check,params,config,dashboard,smoke}."""
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


def _config(args):
    from .config import make_config
    overrides = {}
    if args.episodes:
        overrides["total_episodes"] = args.episodes
    if getattr(args, "seed", None) is not None:
        overrides["seed"] = args.seed
    ppo = {}
    if args.num_envs:
        ppo["num_envs"] = args.num_envs
    if getattr(args, "microbatch", None):
        ppo["microbatch"] = args.microbatch
    if ppo:
        overrides["ppo"] = ppo
    if getattr(args, "gate_policy", None):
        overrides["reward"] = {"gate_policy": args.gate_policy}
    return make_config(args.preset, **overrides)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="spire_rl", description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    t = sub.add_parser("train", help="train one run (a new run directory each time)")
    t.add_argument("--preset", default="main", help="main (~0.2B), large-1b (~0.93B), large-0.7b, tiny")
    t.add_argument("--run-dir", required=True)
    t.add_argument("--episodes", type=int, help="training starts budget (default 10000)")
    t.add_argument("--num-envs", type=int)
    t.add_argument("--microbatch", type=int)
    t.add_argument("--seed", type=int)
    t.add_argument("--gate-policy", choices=("stop", "hold"))
    t.add_argument("--device", default="auto")
    t.add_argument("--stop-after-updates", type=int, help="short profiling run (M3)")

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
        print(json.dumps({"preset": args.preset, "parameters": n,
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
        from .train import build_model, evaluate
        device = _device(args.device)
        payload = ckpt.load(Path(args.checkpoint))
        cfg = RunConfig.from_dict(payload["config"])
        model = build_model(cfg, device)
        model.load_state_dict(payload["model"])
        res = evaluate(model, cfg, device, args.split, args.num_envs, args.limit)
        res["checkpoint"] = str(args.checkpoint)
        res["checkpoint_progress"] = payload.get("progress", {})
        if args.out:
            Path(args.out).write_text(json.dumps(res, indent=1, default=str))
        print(json.dumps({k: v for k, v in res.items() if k != "per_seed"}, indent=2, default=str))
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
    summary = train(cfg, Path(args.run_dir), _device(args.device), stop_after_updates=args.stop_after_updates)
    print(json.dumps(summary, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
