"""Synchronous PPO loop: rollout -> GAE -> update -> log -> (validate) -> checkpoint."""
from __future__ import annotations

import json
import random
import time
from pathlib import Path

import torch

from . import checkpoint as ckpt
from .archive import write_rollout
from .config import RunConfig
from .metrics import MetricsLogger, wilson
from .model import EnvSpec, SpireNet, count_parameters
from .ppo import critic_quality, ppo_update, prepare, recompute_check
from .rollout import Collector, Job, summarize
from .sim import identity
from .tools import check_disk, sim_binary


def env_spec(cfg: RunConfig) -> EnvSpec:
    i = identity()
    return EnvSpec(i["macro_entity_num"], i["macro_cand_num"], i["macro_phases"], i["macro_vocab"],
                   i["run_action_types"])


# What the network sees is identical in training, validation and deployment:
# no reward-stage id, no alpha-weighted reward (G2 of the 2026-11-10 review).
POLICY_INPUTS = "stage-free; history rewards = event counts (floors, act entries, win)"


def build_model(cfg: RunConfig, device: torch.device) -> SpireNet:
    model = SpireNet(cfg.model, env_spec(cfg)).to(device)
    model.set_checkpointing(cfg.ppo.activation_checkpointing and device.type == "cuda")
    return model


def build_critic(cfg: RunConfig, device: torch.device) -> SpireNet | None:
    """Separate value network (only its 3-component value head is used), or None."""
    if cfg.critic is None:
        return None
    return SpireNet(cfg.critic, env_spec(cfg)).to(device)


def _mix(*values: int) -> int:
    """SplitMix64-style hash for independent derived seeds."""
    x = 0x9E3779B97F4A7C15
    for v in values:
        x ^= (v + 0x9E3779B97F4A7C15 + (x << 6) + (x >> 2)) & 0xFFFFFFFFFFFFFFFF
        x = (x * 0xBF58476D1CE4E5B9) & 0xFFFFFFFFFFFFFFFF
        x ^= x >> 31
    return x & 0xFFFFFFFF


def scheduled_stage(cfg: RunConfig, episodes_started: int) -> int:
    for i, st in enumerate(cfg.reward.stages):
        if episodes_started < st.until_episode:
            return i
    return len(cfg.reward.stages) - 1


def evaluate(model: SpireNet, cfg: RunConfig, device: torch.device, split: str, num_envs: int | None = None,
             limit: int | None = None, critic: SpireNet | None = None) -> dict:
    first, count = cfg.val_seeds if split == "val" else cfg.test_seeds
    if limit:
        count = min(count, limit)
    jobs = (Job(i, first + i, _mix(0xE7A1, first + i)) for i in range(count))
    collector = Collector(cfg, model, device, num_envs, critic=critic)
    try:
        # alpha=0 only scores true wins and weights the critic; it is not a network input.
        res = collector.collect(jobs, stage=-1, alpha=0.0, min_transitions=None,
                                sample_seed=0xE7A1)   # fixed evaluation sampling streams
    finally:
        collector.close()
    s = res.stats
    lo, hi = wilson(s["wins"], count)
    per_seed = sorted(({"seed": ep.game_seed, "won": ep.outcome.name == "WIN", "outcome": ep.outcome.name,
                        "floor": ep.info.get("floor"), "act": ep.info.get("act"), "decisions": len(ep),
                        "reward_raw": ep.info.get("reward_raw")} for ep in res.episodes), key=lambda r: r["seed"])
    return {"split": split, "episodes_evaluated": count, "win_rate": s["wins"] / count,
            "win_rate_ci_low": lo, "win_rate_ci_high": hi, "win_rate_normal_end": s["win_rate_normal_end"],
            "wins": s["wins"], "failures": s["failures"], "truncations": s["truncations"],
            "floor_mean": s["floor_mean"], "reach_act2": s["reach_act2"], "reach_act3": s["reach_act3"],
            "decisions_mean": s.get("decisions_mean"), "menu_loops": s.get("menu_loops", 0),
            "truncation_reasons": s.get("truncation_reasons", {}), "eval_seconds": res.wall_seconds,
            "conditions": {"policy_inputs": POLICY_INPUTS, "sampling": "stochastic, fixed streams",
                           "combat": cfg.combat.__dict__, "model": {"type_factorized": cfg.model.type_factorized}},
            "per_seed": per_seed}


def train(cfg: RunConfig, run_dir: Path, device: torch.device,
          stop_after_updates: int | None = None, log=print) -> dict:
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    torch.manual_seed(cfg.seed)
    rng_py = random.Random(cfg.seed + 1)
    model = build_model(cfg, device)
    critic = build_critic(cfg, device)
    p = cfg.ppo
    optimizer = torch.optim.AdamW(model.parameters(), lr=p.lr, betas=p.betas, eps=p.eps,
                                  weight_decay=p.weight_decay)
    critic_optimizer = (torch.optim.AdamW(critic.parameters(), lr=p.critic_lr, betas=p.betas, eps=p.eps,
                                          weight_decay=p.weight_decay) if critic is not None else None)
    progress = {"episodes_started": 0, "updates": 0, "transitions": 0, "stage": 0,
                "act2_episodes": 0, "winning_seeds": [], "alpha0_episodes": 0, "best_val": None,
                "stage_boundaries": [], "failures": 0, "stopped": None}
    if (run_dir / "metrics.jsonl").exists():
        raise FileExistsError(f"{run_dir} already holds a run; use a new run directory")
    disk = check_disk(run_dir, count_parameters(model) + (count_parameters(critic) if critic is not None else 0))
    log(f"checkpoint disk plan: {disk}")
    (run_dir / "config.json").write_text(json.dumps(
        {"config": cfg.to_dict(), "fingerprint": cfg.fingerprint(), "identity": identity(),
         "sim_binary": sim_binary(), "parameters": count_parameters(model),
         "critic_parameters": count_parameters(critic) if critic is not None else 0, "device": str(device)},
        indent=2, default=str))
    logger = MetricsLogger(run_dir, cfg.sweet_spot, cfg.total_episodes,
                           f"SpireNet {cfg.preset} ({count_parameters(model) / 1e9:.3f}B params)")
    collector = Collector(cfg, model, device, critic=critic)

    def run_eval(at: int) -> None:
        res = evaluate(model, cfg, device, "val", critic=critic)
        details = run_dir / "eval" / f"val_ep{at:06d}.json"
        details.parent.mkdir(exist_ok=True)
        details.write_text(json.dumps({"episodes": at, "updates": progress["updates"], **res}, indent=1))
        res = {k: v for k, v in res.items() if k not in ("per_seed", "conditions", "truncation_reasons")}
        logger.log_eval({"episodes": at, "updates": progress["updates"], **res})
        best = progress["best_val"]
        if best is None or res["win_rate"] > best["win_rate"]:   # ties keep the earlier checkpoint
            progress["best_val"] = {"episodes": at, "win_rate": res["win_rate"]}
            ckpt.save(run_dir / "best.pt", cfg, model, progress, critic)
        ckpt.save(run_dir / "last.pt", cfg, model, {**progress, "last_eval_episodes": at}, critic)
        log(f"[val @{at}] win {res['win_rate']:.3f} ({res['wins']}/{res['episodes_evaluated']}) "
            f"floor {res['floor_mean']:.1f} act2 {res['reach_act2']:.2f}")

    loop_start = time.perf_counter()   # wall clock for the ETA: includes validation and saving
    run_eval(0)
    try:
        while progress["episodes_started"] < cfg.total_episodes:
            started = progress["episodes_started"]
            stage = scheduled_stage(cfg, started)
            if stage > progress["stage"]:
                gate_ok, why = _gate(cfg, progress, stage)
                if not gate_ok:
                    if cfg.reward.gate_policy == "stop":
                        progress["stopped"] = f"gate before stage {stage} not met at {started} episodes: {why}"
                        log("STOP: " + progress["stopped"])
                        break
                    stage = progress["stage"]
                    log(f"hold stage {stage}: {why}")
                else:
                    progress["stage_boundaries"].append({"stage": stage, "episodes": started})
            progress["stage"] = stage
            st = cfg.reward.stages[stage]
            budget = cfg.total_episodes - started
            jobs = (Job(started + k, cfg.train_seed_base + started + k, _mix(cfg.seed, started + k))
                    for k in range(budget))
            cycle_start = time.perf_counter()
            if device.type == "cuda":
                torch.cuda.reset_peak_memory_stats(device)
            res = collector.collect(jobs, stage, st.alpha, p.min_transitions, sample_seed=cfg.seed)
            progress["episodes_started"] += res.started
            archive_bytes = 0
            if cfg.archive_trajectories and res.episodes:
                archive_bytes = write_rollout(
                    run_dir / "archive" / f"rollout_{progress['updates'] + 1:05d}.npz", res.episodes,
                    {"behaviour_updates": progress["updates"], "stage": stage, "alpha": st.alpha,
                     "fingerprint": cfg.fingerprint(), "identity": identity(), "sample_seed": cfg.seed})
            targets = prepare(res.episodes, p)
            quality = critic_quality(targets)
            failures = res.stats.get("failures", 0)
            progress["failures"] += failures
            if failures > max(2, 0.02 * len(res.episodes)):
                raise RuntimeError(f"too many engineering failures this rollout: {failures} "
                                   f"({res.stats.get('failure_reasons')}); fix before continuing")
            recompute = recompute_check(model, targets, cfg.model.window, device, p.bf16) if targets else 0.0
            if recompute > p.recompute_tolerance:
                raise RuntimeError(f"log-probability recompute mismatch {recompute:.4g} > {p.recompute_tolerance}")
            upd = ppo_update(model, optimizer, targets, p, st.entropy_coef, cfg.model.window, device, rng_py,
                             critic, critic_optimizer).values if targets else {}
            progress["updates"] += 1
            progress["transitions"] += res.transitions
            for ep in res.episodes:
                if ep.info.get("act", 0) >= 1:
                    progress["act2_episodes"] += 1
                if st.alpha == 0.0 and ep.outcome.name in ("WIN", "DEATH"):
                    progress["alpha0_episodes"] += 1
            progress["winning_seeds"] = sorted(set(progress["winning_seeds"]) | set(res.stats.get("winning_seeds", [])))
            if started // cfg.eval_every < progress["episodes_started"] // cfg.eval_every:
                run_eval(progress["episodes_started"])
            now = time.perf_counter()
            cycle = now - cycle_start                                   # this cycle incl. validation/saving
            spe = (now - loop_start) / max(1, progress["episodes_started"])   # all wall time so far / episode
            row = {"episodes": progress["episodes_started"], "episodes_at_rollout_start": started,
                   "updates": progress["updates"], "transitions": progress["transitions"],
                   "stage": stage, "alpha": st.alpha, "entropy_coef": st.entropy_coef,
                   # The rollout's own episode count must not overwrite the cumulative x axis.
                   **{("rollout_episodes" if k == "episodes" else k): v for k, v in res.stats.items()
                      if k not in ("winning_seeds", "failure_reasons", "truncation_reasons")},
                   **upd, **quality, "recompute_max_abs": recompute,
                   "rollout_transitions": res.transitions, "archive_mb": archive_bytes / 1e6, "env_seconds": res.env_seconds,
                   "inference_seconds": res.inference_seconds, "forward_calls": res.forward_calls,
                   "cycle_seconds": cycle, "seconds_per_episode": spe, "episodes_per_hour": 3600 / spe,
                   "eta_hours": spe * (cfg.total_episodes - progress["episodes_started"]) / 3600,
                   "winning_seed_families": len(progress["winning_seeds"]),
                   "alpha0_episodes": progress["alpha0_episodes"],
                   "gpu_peak_gib": (torch.cuda.max_memory_allocated(device) / 2 ** 30) if device.type == "cuda" else None}
            logger.log_update(row)
            log(f"[upd {progress['updates']}] episodes {progress['episodes_started']} stage {stage} "
                f"win {res.stats.get('win_rate', 0):.3f} floor {res.stats.get('floor_mean', 0):.1f} "
                f"kl {upd.get('approx_kl', float('nan')):.4f} ent {upd.get('entropy', float('nan')):.3f} "
                f"vEV {quality.get('value_ev', float('nan')):.2f} "
                f"{spe:.2f}s/ep")
            if stop_after_updates and progress["updates"] >= stop_after_updates:
                progress["stopped"] = f"stop_after_updates={stop_after_updates}"
                break
    finally:
        collector.close()
    ckpt.save(run_dir / "last.pt", cfg, model, {**progress, "final": True}, critic)
    summary = {**progress, "alpha0_requirement_met": progress["alpha0_episodes"] >= 2000,
               "parameters": count_parameters(model)}
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2, default=str))
    logger.export_tables()
    return summary


def _gate(cfg: RunConfig, progress: dict, stage: int) -> tuple[bool, str]:
    r = cfg.reward
    if stage >= 1 and progress["act2_episodes"] < r.gate_act2_episodes:
        return False, f"{progress['act2_episodes']} training episodes reached act 2 (< {r.gate_act2_episodes})"
    if r.stages[stage].alpha == 0.0 and len(progress["winning_seeds"]) < r.gate_win_seed_families:
        return False, (f"wins on {len(progress['winning_seeds'])} distinct training seed families "
                       f"(< {r.gate_win_seed_families})")
    return True, ""


__all__ = ["train", "evaluate", "build_model", "build_critic", "env_spec", "summarize"]
