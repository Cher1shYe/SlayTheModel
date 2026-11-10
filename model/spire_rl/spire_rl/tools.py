"""Environment / GPU memory check, disk planning and paired model comparison."""
from __future__ import annotations

import dataclasses
import hashlib
import math
import os
import platform
import random
import resource
import shutil
import sys
import tempfile
import time
from pathlib import Path

import numpy as np
import torch

from . import checkpoint as ckpt
from .config import RunConfig
from .data import Episode
from .env import MacroEnv, Observation, Outcome
from .model import count_parameters
from .ppo import _autocast, ppo_update
from .sim import identity, sim


def sim_binary() -> dict:
    path = Path(sim.__file__)
    return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def host_info(run_dir: Path | None = None) -> dict:
    info = {
        "python": sys.version.split()[0], "torch": torch.__version__, "platform": platform.platform(),
        "cpu_count": os.cpu_count(),
        "ram_gb": round(os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 1e9, 1)
        if hasattr(os, "sysconf") and "SC_PHYS_PAGES" in os.sysconf_names else None,
        "cuda": torch.version.cuda if torch.cuda.is_available() else None,
    }
    if torch.cuda.is_available():
        p = torch.cuda.get_device_properties(0)
        info.update(gpu=p.name, gpu_total_gib=round(p.total_memory / 2 ** 30, 2),
                    bf16_supported=torch.cuda.is_bf16_supported())
    if run_dir is not None:
        d = Path(run_dir)
        while not d.exists():
            d = d.parent
        info["disk_free_gb"] = round(shutil.disk_usage(d).free / 1e9, 1)
    return info


def check_disk(run_dir: Path, n_params: int) -> dict:
    """Only best.pt (FP32 weights) is kept; while it is replaced a temporary copy exists."""
    weights = 4 * n_params
    need = 2 * weights
    d = Path(run_dir)
    while not d.exists():
        d = d.parent
    free = shutil.disk_usage(d).free
    plan = {"best_checkpoint_gb": round(weights / 1e9, 2), "needed_gb": round(need / 1e9, 1),
            "free_gb": round(free / 1e9, 1)}
    if free < need:
        raise RuntimeError(f"not enough disk space for best.pt in {run_dir}: {plan} "
                           "(trajectory archive not included)")
    return plan


# ---------------------------------------------------------------------------
def _stress_episode(cfg: RunConfig, entities: int, candidates: int, length: int) -> Episode:
    """A long episode of large real-shaped states (worst-case memory, not real play)."""
    env = MacroEnv(dataclasses.replace(cfg.combat, normal_simulations=4, boss_simulations=8), cfg.reward)
    obs = env.reset(31337, 1).next_obs
    rng = random.Random(0)
    best = obs
    while obs is not None:
        if obs.kind.shape[0] > best.kind.shape[0]:
            best = obs
        obs = env.step(rng.randrange(obs.num_candidates), obs, 1.0).next_obs
    o = best
    n, c = o.kind.shape[0], o.num_candidates
    rows = np.resize(np.arange(n), entities)          # repeat real entities up to the target size
    crow = np.resize(np.arange(c), candidates)
    big = Observation(o.kind[rows], o.id[rows], o.num[rows], o.edges, o.cand_type[crow], o.cand_index[crow],
                      o.cand_target[crow], o.cand_target2[crow], o.cand_num[crow], o.phase)
    ep = Episode(0, 0, 0)
    ep.obs = [big] * length
    ep.actions = [0] * length
    ep.logp = [float(-math.log(candidates))] * length
    ep.value = [0.0] * length
    ep.reward = [np.zeros(4, np.float32)] * length
    ep.outcome = Outcome.DEATH
    ep.aux = np.zeros((length, 6), np.float32)
    ep.aux[:, 3:] = 1.0
    gen = np.random.default_rng(0)
    ep.advantages = gen.standard_normal(length).astype(np.float32)
    ep.returns = gen.standard_normal(length).astype(np.float32)
    ep.info["log"] = env.log
    return ep


def resource_check(cfg: RunConfig, device: torch.device, entities: int = 160, candidates: int = 24,
                   log=print) -> dict:
    """Peak memory at init / forward+backward / first optimizer step / save, and step time (M3)."""
    from .train import build_model
    cuda = device.type == "cuda"

    def mem() -> dict:
        if not cuda:
            return {"host_peak_rss_gb": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
                                              / (1e9 if sys.platform == "darwin" else 1e6), 2)}
        free, total = torch.cuda.mem_get_info(device)
        return {"allocated_gib": round(torch.cuda.memory_allocated(device) / 2 ** 30, 2),
                "peak_allocated_gib": round(torch.cuda.max_memory_allocated(device) / 2 ** 30, 2),
                "peak_reserved_gib": round(torch.cuda.max_memory_reserved(device) / 2 ** 30, 2),
                "device_used_gib": round((total - free) / 2 ** 30, 2),
                "host_peak_rss_gb": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1e6, 2)}

    def reset() -> None:
        if cuda:
            torch.cuda.synchronize(device)
            torch.cuda.reset_peak_memory_stats(device)

    p = cfg.ppo
    W = cfg.model.window
    report = {"preset": cfg.preset, "device": str(device), "host": host_info(), "bf16": p.bf16 and cuda,
              "microbatch": p.microbatch, "batch_targets": p.batch_targets, "window": W,
              "stress_shape": {"entities": entities, "candidates": candidates}}
    base = _stress_episode(cfg, entities, candidates, length=W)
    # One episode per target, as after PPO shuffling: no state is shared inside a microbatch.
    targets = []
    for i in range(p.batch_targets):
        ep = dataclasses.replace(base, episode_id=i, info=dict(base.info))
        targets.append((ep, W - 1))                                # full window
    reset()
    model = build_model(cfg, device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=p.lr, betas=p.betas, eps=p.eps, weight_decay=p.weight_decay)
    report["parameters"] = count_parameters(model)
    report["init"] = mem()
    log(f"init {report['init']}")

    reset()
    from .data import collate
    model.eval()
    t0 = time.perf_counter()
    with torch.no_grad(), _autocast(device, p.bf16):
        model(collate(targets[:p.num_envs], W).to(device))
    if cuda:
        torch.cuda.synchronize(device)
    report["rollout_forward"] = {**mem(), "seconds": round(time.perf_counter() - t0, 3), "batch": p.num_envs}

    one = dataclasses.replace(p, epochs=1, target_kl=1e9)
    reset()
    t0 = time.perf_counter()
    ppo_update(model, optimizer, targets, one, 0.01, W, device, random.Random(0))   # creates Adam state
    if cuda:
        torch.cuda.synchronize(device)
    report["first_optimizer_step"] = {**mem(), "seconds": round(time.perf_counter() - t0, 3)}
    log(f"first optimizer step {report['first_optimizer_step']}")
    reset()
    t0 = time.perf_counter()
    ppo_update(model, optimizer, targets, one, 0.01, W, device, random.Random(1))
    if cuda:
        torch.cuda.synchronize(device)
    step_s = time.perf_counter() - t0
    report["steady_optimizer_step"] = {**mem(), "seconds": round(step_s, 3)}
    log(f"steady optimizer step {report['steady_optimizer_step']}")

    reset()
    with tempfile.TemporaryDirectory() as tmp:
        t0 = time.perf_counter()
        path = Path(tmp) / "best.pt"
        ckpt.save(path, cfg, model, {})
        report["save"] = {**mem(), "seconds": round(time.perf_counter() - t0, 2),
                          "file_gb": round(path.stat().st_size / 1e9, 2)}
    log(f"save {report['save']}")
    steps = p.epochs * math.ceil(p.min_transitions / p.batch_targets)
    report["estimate"] = {
        "optimizer_steps_per_update_max": steps,
        "update_seconds_per_rollout_max": round(steps * step_s, 1),
        "note": "worst-case shapes; real rollouts are smaller and KL early stop shortens updates",
    }
    if cuda:
        total = torch.cuda.get_device_properties(device).total_memory / 2 ** 30
        peak = max(report[k]["peak_reserved_gib"] for k in ("first_optimizer_step", "steady_optimizer_step", "save"))
        report["headroom_gib"] = round(total - peak, 2)
        report["fits_with_3gib_headroom"] = total - peak >= 3.0
    return report


def env_check(cfg: RunConfig, episodes: int = 2, log=print) -> dict:
    """Plays random macro choices with the real combat budget; reports timing and invariants."""
    env = MacroEnv(cfg.combat, cfg.reward, cfg.ascension, cfg.max_macro_steps)
    rows = []
    for k in range(episodes):
        t0 = time.perf_counter()
        obs = env.reset(7_000_000 + k, k).next_obs
        rng = random.Random(k)
        decisions, max_ent, max_cand = 0, 0, 0
        r = None
        while obs is not None:
            max_ent, max_cand = max(max_ent, obs.kind.shape[0]), max(max_cand, obs.num_candidates)
            r = env.step(rng.randrange(obs.num_candidates), obs, 1.0)
            obs = r.next_obs
            decisions += 1
        rows.append({"seed": 7_000_000 + k, "outcome": r.outcome.name if r else "NO_DECISION",
                     "floor": int(env.rc.floor), "decisions": decisions, "forced": env.log.forced_steps,
                     "combats": len(env.log.combats), "combat_seconds": round(env.log.combat_seconds, 2),
                     "seconds": round(time.perf_counter() - t0, 2), "max_entities": max_ent,
                     "max_candidates": max_cand})
        log(rows[-1])
    return {"identity": identity(), "sim_binary": sim_binary(), "random_policy_episodes": rows}


# ---------------------------------------------------------------------------
def paired_compare(a: dict, b: dict) -> dict:
    """Paired comparison of two evaluations on the same seeds (exact McNemar test)."""
    wa = {r["seed"]: r["won"] for r in a["per_seed"]}
    wb = {r["seed"]: r["won"] for r in b["per_seed"]}
    if set(wa) != set(wb):
        raise ValueError("the evaluations used different seeds; a paired comparison needs the same seed set")
    both = sum(wa[s] and wb[s] for s in wa)
    only_a = sum(wa[s] and not wb[s] for s in wa)
    only_b = sum(wb[s] and not wa[s] for s in wa)
    n = len(wa)
    k, m = min(only_a, only_b), only_a + only_b
    p = min(1.0, 2 * sum(math.comb(m, i) for i in range(k + 1)) / 2 ** m) if m else 1.0
    return {"seeds": n, "a_wins": both + only_a, "b_wins": both + only_b, "both": both,
            "only_a": only_a, "only_b": only_b, "neither": n - both - only_a - only_b,
            "win_rate_diff_a_minus_b": (only_a - only_b) / n, "mcnemar_exact_p": p}
