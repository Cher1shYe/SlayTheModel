"""Parallel episode collection with batched policy inference.

Environments advance in worker threads (combat MCTS and observation building
release the GIL in C++); every pending decision is scored in one batched
forward on the device. A rollout stops starting new episodes once it holds
``min_transitions`` decisions (or the job list ends) and then finishes every
in-flight episode, so collected episodes are always complete.
"""
from __future__ import annotations

import concurrent.futures as cf
import time
from dataclasses import dataclass, field
from typing import Iterator

import numpy as np
import torch

from .config import RunConfig
from .data import Episode, collate
from .env import MacroEnv, Outcome
from .model import SpireNet
from .ppo import _autocast


@dataclass
class Job:
    episode_id: int
    game_seed: int
    search_seed: int


@dataclass
class RolloutResult:
    episodes: list[Episode]
    transitions: int
    started: int
    wall_seconds: float
    inference_seconds: float
    env_seconds: float
    forward_calls: int
    stats: dict = field(default_factory=dict)


class _Slot:
    def __init__(self, env: MacroEnv):
        self.env = env
        self.episode: Episode | None = None
        self.obs = None
        self.rng: np.random.Generator | None = None


def _episode_summary(ep: Episode) -> dict:
    log = ep.info["log"]
    return {
        "outcome": ep.outcome.name, "floor": ep.info["floor"], "act": ep.info["act"],
        "won": ep.outcome == Outcome.WIN, "decisions": len(ep), "forced": log.forced_steps,
        "combats": len(log.combats), "mcts_decisions": log.mcts_decisions,
        "mcts_simulations": log.mcts_simulations, "combat_seconds": log.combat_seconds,
        "reward_raw": ep.info["reward_raw"],
        "seed": ep.game_seed,
    }


class Collector:
    def __init__(self, cfg: RunConfig, model: SpireNet, device: torch.device, num_envs: int | None = None):
        self.cfg = cfg
        self.model = model
        self.device = device
        n = num_envs or cfg.ppo.num_envs
        self.slots = [_Slot(MacroEnv(cfg.combat, cfg.reward, cfg.ascension, cfg.max_macro_steps)) for _ in range(n)]
        self.pool = cf.ThreadPoolExecutor(max_workers=n, thread_name_prefix="macro-env")

    def close(self) -> None:
        self.pool.shutdown(wait=True)

    # -- one rollout ---------------------------------------------------------
    def collect(self, jobs: Iterator[Job], stage: int, alpha: float, min_transitions: int | None,
                sample_seed: int, greedy: bool = False) -> RolloutResult:
        """Run episodes until ``min_transitions`` (None = all jobs), then finish those in flight.

        Each episode samples from its own stream seeded by (sample_seed,
        episode_id), so results do not depend on thread completion order.
        """
        started_at = time.perf_counter()
        finished: list[Episode] = []
        futures: dict[cf.Future, _Slot] = {}
        ready: list[_Slot] = []
        transitions = started = forward_calls = 0
        infer_s = 0.0
        scale = self.cfg.reward.scale
        jobs = iter(jobs)
        exhausted = False

        def want_more() -> bool:
            return not exhausted and (min_transitions is None or transitions < min_transitions)

        def start(slot: _Slot) -> bool:
            nonlocal exhausted, started
            job = next(jobs, None)
            if job is None:
                exhausted = True
                return False
            slot.episode = Episode(job.episode_id, job.game_seed, stage)
            slot.episode.info["reward_raw"] = 0.0
            slot.rng = np.random.default_rng([sample_seed & 0xFFFFFFFF, job.episode_id])
            futures[self.pool.submit(slot.env.reset, job.game_seed, job.search_seed)] = slot
            started += 1
            return True

        for slot in self.slots:
            if want_more():
                start(slot)

        while futures or ready:
            if futures:
                done, _ = cf.wait(list(futures), timeout=None if not ready else 0,
                                  return_when=cf.FIRST_COMPLETED)
                for fut in done:
                    slot = futures.pop(fut)
                    res = fut.result()
                    ep = slot.episode
                    if len(ep.actions) > len(ep.reward):        # result of a step
                        ep.reward.append(np.array([res.reward_raw / scale, *res.components], np.float32))
                        ep.info["reward_raw"] += res.reward_raw
                        transitions += 1
                    if res.outcome == Outcome.RUNNING:
                        slot.obs = res.next_obs
                        ready.append(slot)
                        continue
                    ep.outcome = res.outcome
                    ep.failure_reason = res.failure_reason
                    ep.final_obs = res.final_obs
                    ep.info.update(log=slot.env.log, floor=int(slot.env.rc.floor), act=int(slot.env.rc.act))
                    finished.append(ep)
                    slot.episode = None
                    if want_more():
                        start(slot)
            if not ready:
                continue
            # Batch every pending decision into one forward.
            batch_slots, ready = ready, []
            targets = []
            for slot in batch_slots:
                slot.episode.obs.append(slot.obs)
                targets.append((slot.episode, len(slot.episode.obs) - 1))
            t0 = time.perf_counter()
            self.model.eval()
            with torch.no_grad(), _autocast(self.device, self.cfg.ppo.bf16):
                out = self.model(collate(targets, self.cfg.model.window).to(self.device))
            logp_all = torch.log_softmax(out.logits.float(), -1).cpu().numpy()
            values = out.value.float().cpu().numpy()
            infer_s += time.perf_counter() - t0
            forward_calls += 1
            for i, slot in enumerate(batch_slots):
                ep = slot.episode
                legal = slot.obs.num_candidates
                lp = logp_all[i, :legal]
                if greedy:
                    a = int(np.argmax(lp))
                else:
                    p = np.exp(lp - lp.max())
                    a = int(slot.rng.choice(legal, p=p / p.sum()))
                ep.actions.append(a)
                ep.logp.append(float(lp[a]))
                ep.value.append(float(values[i]))
                futures[self.pool.submit(slot.env.step, a, slot.obs, alpha)] = slot

        # Bootstrap values for truncated episodes (state after the last action).
        trunc = [ep for ep in finished if ep.outcome == Outcome.TRUNCATED and ep.final_obs is not None and len(ep)]
        if trunc:
            override = {(ep.episode_id, len(ep)): ep.final_obs for ep in trunc}
            with torch.no_grad(), _autocast(self.device, self.cfg.ppo.bf16):
                out = self.model(collate([(ep, len(ep)) for ep in trunc], self.cfg.model.window,
                                         obs_override=override).to(self.device))
            for ep, v in zip(trunc, out.value.float().cpu().numpy()):
                ep.bootstrap_value = float(v)
        wall = time.perf_counter() - started_at
        return RolloutResult(finished, transitions, started, wall, infer_s, wall - infer_s, forward_calls,
                             summarize(finished))


def summarize(episodes: list[Episode]) -> dict:
    if not episodes:
        return {"episodes": 0}
    rows = [_episode_summary(ep) for ep in episodes]
    n = len(rows)
    outcomes = {o.name: sum(r["outcome"] == o.name for r in rows) for o in Outcome if o != Outcome.RUNNING}
    normal = [r for r in rows if r["outcome"] in ("WIN", "DEATH")]
    return {
        "episodes": n,
        "wins": outcomes["WIN"],
        "win_rate": outcomes["WIN"] / n,
        "win_rate_normal_end": (outcomes["WIN"] / len(normal)) if normal else 0.0,
        "failures": outcomes["FAILURE"],
        "truncations": outcomes["TRUNCATED"],
        "deaths": outcomes["DEATH"],
        "floor_mean": float(np.mean([r["floor"] for r in rows])),
        "floor_max": int(max(r["floor"] for r in rows)),
        "reach_act2": sum(r["act"] >= 1 for r in rows) / n,
        "reach_act3": sum(r["act"] >= 2 for r in rows) / n,
        "decisions_mean": float(np.mean([r["decisions"] for r in rows])),
        "combats_mean": float(np.mean([r["combats"] for r in rows])),
        "combat_seconds": float(sum(r["combat_seconds"] for r in rows)),
        "mcts_simulations": int(sum(r["mcts_simulations"] for r in rows)),
        "reward_raw_mean": float(np.mean([r["reward_raw"] for r in rows])),
        "winning_seeds": sorted({r["seed"] for r in rows if r["won"]}),
        "failure_reasons": sorted({ep.failure_reason for ep in episodes if ep.outcome == Outcome.FAILURE}),
    }
