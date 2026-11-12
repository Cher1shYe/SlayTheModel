"""Parallel episode collection with batched policy inference.

Environments advance in worker threads (combat MCTS and observation building
release the GIL in C++); every pending decision is scored in one batched
forward on the device. A rollout stops starting new episodes once it holds
``min_transitions`` decisions (or the job list ends) and then finishes every
in-flight episode, so collected episodes are always complete.

Paired forks (``RunConfig.fork``): at some decisions of a training episode the
environment is copied once per (option, seed set). Branches of one seed set
share the combat-search seed and the policy sampling stream, so the difference
between options is not drowned in luck. A branch runs with the current policy
until its horizon. Campfire and map forks: act change, ``max_combats`` fights,
``max_decisions`` decisions or the end of the run, the remainder estimated by
the critic (without its win output unless ``bootstrap_win``). Card-reward forks
compare every offered card and skip and run to the end of the act, counting
only real events (``card_to_act_end`` / ``card_bootstrap``).
Branch steps are never added to the PPO data; only the per-option returns are
attached to the forked decision (``Episode.info["forks"]``).
"""
from __future__ import annotations

import collections
import concurrent.futures as cf
import os
import time
from dataclasses import dataclass, field
from typing import Iterator

import numpy as np
import torch

from .config import RunConfig
from .data import Episode, candidate_groups, collate
from .env import MacroEnv, Outcome
from .model import VALUE_SCALE, SpireNet, combine_value, value_weights
from .ppo import _autocast

REST_HEAL, REST_UPGRADE, MOVE = 3, 4, 0        # sim.RunActionType values
TAKE_CARD, SKIP_CARD = 1, 2
SCREEN_MAP, SCREEN_CARD_REWARD, SCREEN_REST = 0, 2, 3


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


@dataclass
class Fork:
    """One paired fork of decision ``t`` of ``episode``."""
    fork_id: int
    episode: Episode
    t: int
    options: list[int]           # candidate indices executed in the branches
    groups: list[int]            # action group of each option
    group_level: bool            # options represent whole action groups (else single candidates)
    screen: int
    returns: dict = field(default_factory=dict)    # (option, seed) -> r_train-unit return
    failed: bool = False
    details: dict = field(default_factory=dict)    # (option, seed) -> compact audit record
    max_combats: int = 0         # branch horizon: fights (0 = no limit)
    max_decisions: int = 40      # branch horizon: decisions
    bootstrap_act_end: bool = True   # critic estimate at an act change (else real events only)


class _Slot:
    def __init__(self, env: MacroEnv):
        self.env = env
        self.episode: Episode | None = None
        self.obs = None
        self.rng: np.random.Generator | None = None
        # branch state (fork slots only)
        self.fork: Fork | None = None
        self.option = self.seed = 0
        self.start_act = 0
        self.events = np.zeros(3, np.float64)
        self.branch_decisions = 0


def _episode_summary(ep: Episode) -> dict:
    log = ep.info["log"]
    return {
        "outcome": ep.outcome.name, "floor": ep.info["floor"], "act": ep.info["act"],
        "won": ep.outcome == Outcome.WIN, "decisions": len(ep), "forced": log.forced_steps,
        "combats": len(log.combats), "mcts_decisions": log.mcts_decisions,
        "mcts_simulations": log.mcts_simulations, "combat_seconds": log.combat_seconds,
        "reward_raw": ep.info["reward_raw"],
        "seed": ep.game_seed, "menu_loops": log.menu_loops,
        "truncation_reason": ep.failure_reason if ep.outcome == Outcome.TRUNCATED else "",
    }


class Collector:
    def __init__(self, cfg: RunConfig, model: SpireNet, device: torch.device, num_envs: int | None = None,
                 critic: SpireNet | None = None):
        self.cfg = cfg
        self.model = model
        self.critic = critic          # separate value network; None = the policy's value head
        self.device = device
        n = num_envs or cfg.ppo.num_envs
        self.slots = [_Slot(MacroEnv(cfg.combat, cfg.reward, cfg.ascension, cfg.max_macro_steps,
                                     cfg.max_grid_steps)) for _ in range(n)]
        # Fork branches are extra simulator work next to the n episodes: give them the
        # spare cores (at most twice n). Results do not depend on the number of workers.
        self.workers = max(n, min(os.cpu_count() or n, 2 * n)) if cfg.fork.enabled else n
        self.pool = cf.ThreadPoolExecutor(max_workers=self.workers, thread_name_prefix="macro-env")

    def close(self) -> None:
        self.pool.shutdown(wait=True)

    def _critic_values(self, targets, policy_out) -> np.ndarray:
        """[B, 3] value components for the batch (separate critic if configured)."""
        if self.critic is None:
            return policy_out.value.float().cpu().numpy()
        self.critic.eval()
        return self.critic(collate(targets, self.critic.cfg.window).to(self.device)).value.float().cpu().numpy()

    def _bootstrap(self, items) -> np.ndarray:
        """Critic components at the state after the last action of each (episode, final_obs)."""
        override = {(ep.episode_id, len(ep)): obs for ep, obs in items}
        tg = [(ep, len(ep)) for ep, _ in items]
        out = []
        with torch.no_grad(), _autocast(self.device, self.cfg.ppo.bf16):
            for i in range(0, len(tg), 64):
                part = tg[i:i + 64]
                if self.critic is None:
                    o = self.model(collate(part, self.cfg.model.window, obs_override=override).to(self.device))
                else:
                    self.critic.eval()
                    o = self.critic(collate(part, self.critic.cfg.window, obs_override=override).to(self.device))
                out.append(o.value.float().cpu().numpy())
        return np.concatenate(out) if out else np.zeros((0, 3), np.float32)

    # -- forks ---------------------------------------------------------------
    def _fork_options(self, obs, taken: int, lp: np.ndarray, rng: np.random.Generator):
        """(screen, options, groups, group_level) if this decision is fork-eligible, else None."""
        fc = self.cfg.fork
        screen = obs.phase // 2 if obs.phase % 2 == 0 else -1
        groups = candidate_groups(obs)
        if screen == SCREEN_MAP and fc.map_prob > 0:
            moves = [i for i in range(obs.num_candidates) if obs.cand_type[i] == MOVE]
            # A potion used on the map screen is not a route choice: option 0 must be the taken move.
            if len(moves) < 2 or taken not in moves or rng.random() >= fc.map_prob:
                return None
            others = [m for m in moves if m != taken]
            rng.shuffle(others)
            opts = ([taken] + others)[:fc.max_options]
            return screen, opts, [int(groups[o]) for o in opts], False
        if screen == SCREEN_CARD_REWARD and fc.card_prob > 0:
            # Every offered card and skip, as single candidates (which card, not only whether).
            picks = [i for i in range(obs.num_candidates) if obs.cand_type[i] in (TAKE_CARD, SKIP_CARD)]
            if len(picks) < 2 or taken not in picks or rng.random() >= fc.card_prob:
                return None
            others = [c for c in picks if c != taken]
            rng.shuffle(others)
            opts = ([taken] + others)[:fc.max_options]
            return screen, opts, [int(groups[o]) for o in opts], False
        prob = fc.rest_prob if screen == SCREEN_REST else 0.0
        present = sorted(set(int(g) for g in groups))
        if prob <= 0 or len(present) < 2 or rng.random() >= prob:
            return None
        opts, ogroups = [], []
        taken_group = int(groups[taken])
        for g in [taken_group] + [g for g in present if g != taken_group]:
            if g == taken_group:
                o = taken
            else:   # representative: sampled from the policy within the group
                members = np.flatnonzero(groups == g)
                p = np.exp(lp[members] - lp[members].max())
                o = int(rng.choice(members, p=p / p.sum()))
            opts.append(o); ogroups.append(g)
        return screen, opts[:fc.max_options], ogroups[:fc.max_options], True

    # -- one rollout ---------------------------------------------------------
    def collect(self, jobs: Iterator[Job], stage: int, alpha: float, min_transitions: int | None,
                sample_seed: int, greedy: bool = False, forks: bool = False) -> RolloutResult:
        """Run episodes until ``min_transitions`` (None = all jobs), then finish those in flight.

        ``stage`` only labels the episodes; it is not a network input. ``alpha``
        sets the reward and the critic combination weights. ``forks`` enables the
        paired forks of ``cfg.fork`` (training only).

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
        weights = value_weights(alpha, self.cfg.reward)
        wvec = np.asarray(weights, np.float64)
        fc = self.cfg.fork
        use_forks = forks and fc.enabled and not greedy
        all_forks: list[Fork] = []
        branch_boot: list[tuple[_Slot, Episode, object]] = []
        active_branches = 0
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
            slot.episode.info.update(reward_raw=0.0, alpha=alpha, value_weights=weights)
            slot.rng = np.random.default_rng([sample_seed & 0xFFFFFFFF, job.episode_id])
            futures[self.pool.submit(slot.env.reset, job.game_seed, job.search_seed)] = slot
            started += 1
            return True

        def finish_branch(slot: _Slot, res, reason: str, bootstrap_obs=None) -> None:
            nonlocal active_branches
            active_branches -= 1
            slot.fork.details[(slot.option, slot.seed)].update(
                events=slot.events.tolist(), bootstrap_comps=[0.0, 0.0, 0.0],
                bootstrapped=bootstrap_obs is not None, stop_reason=reason,
                outcome=res.outcome.name, failure_reason=res.failure_reason,
                decisions=slot.branch_decisions, combats=len(slot.env.log.combats))
            if bootstrap_obs is not None:
                branch_boot.append((slot, slot.episode, bootstrap_obs))
            else:
                slot.fork.returns[(slot.option, slot.seed)] = float(slot.events @ wvec)

        def spawn_forks(slot: _Slot, t: int, taken: int, lp: np.ndarray) -> None:
            nonlocal active_branches
            ep = slot.episode
            frng = np.random.default_rng([sample_seed & 0xFFFFFFFF, ep.episode_id, t, 0xF0])
            found = self._fork_options(slot.obs, taken, lp, frng)
            if found is None:
                return
            screen, opts, groups, group_level = found
            n_branches = len(opts) * fc.seeds
            if active_branches + n_branches > fc.max_active_branches:
                return
            fork = Fork(len(all_forks), ep, t, opts, groups, group_level, screen)
            if screen == SCREEN_CARD_REWARD:
                fork.max_combats = 0 if fc.card_to_act_end else fc.max_combats
                fork.max_decisions = fc.card_max_decisions if fc.card_to_act_end else fc.max_decisions
                fork.bootstrap_act_end = fc.card_bootstrap or not fc.card_to_act_end
            else:
                fork.max_combats, fork.max_decisions = fc.max_combats, fc.max_decisions
            all_forks.append(fork)
            ep.info.setdefault("forks", []).append(fork)
            for s in range(fc.seeds):
                search_seed = int(frng.integers(0, 2 ** 32))
                sample = int(frng.integers(0, 2 ** 32))
                for k, opt in enumerate(opts):
                    b = _Slot(slot.env.fork(search_seed))
                    b.fork, b.option, b.seed = fork, k, s
                    fork.details[(k, s)] = {"search_seed": search_seed, "sample_seed": [sample, 0xB4]}
                    b.start_act = int(slot.env.rc.act)
                    b.rng = np.random.default_rng([sample, 0xB4])          # same stream for every option
                    bid = -(1 + (fork.fork_id * 64 + k * 8 + s))           # unique key for collate
                    be = Episode(bid, ep.game_seed, stage)
                    be.obs = ep.obs[:t + 1]
                    be.actions = ep.actions[:t] + [opt]
                    be.reward = ep.reward[:t]
                    b.episode = be
                    active_branches += 1
                    futures[self.pool.submit(b.env.step, opt, slot.obs, alpha)] = b

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
                    if slot.fork is not None:                   # --- branch result
                        ep.reward.append(np.array([res.reward_raw / scale, *res.components], np.float32))
                        slot.events += res.components
                        slot.branch_decisions += 1
                        if res.outcome == Outcome.FAILURE:
                            slot.fork.failed = True
                            finish_branch(slot, res, "failure")
                        elif res.outcome in (Outcome.WIN, Outcome.DEATH):
                            finish_branch(slot, res, res.outcome.name.lower())
                        elif res.outcome == Outcome.TRUNCATED:
                            finish_branch(slot, res, "truncated", res.final_obs)
                        elif int(slot.env.rc.act) != slot.start_act or res.components[1] > 0:
                            finish_branch(slot, res, "act_change",
                                          res.next_obs if slot.fork.bootstrap_act_end else None)
                        elif slot.fork.max_combats and len(slot.env.log.combats) >= slot.fork.max_combats:
                            finish_branch(slot, res, "max_combats", res.next_obs)
                        elif slot.branch_decisions >= slot.fork.max_decisions:
                            finish_branch(slot, res, "max_decisions", res.next_obs)
                        else:
                            slot.obs = res.next_obs
                            ready.append(slot)
                        continue
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
            # Batch every pending decision (episodes and branches) into one forward.
            batch_slots, ready = ready, []
            targets = []
            for slot in batch_slots:
                slot.episode.obs.append(slot.obs)
                targets.append((slot.episode, len(slot.episode.obs) - 1))
            t0 = time.perf_counter()
            self.model.eval()
            with torch.no_grad(), _autocast(self.device, self.cfg.ppo.bf16):
                out = self.model(collate(targets, self.cfg.model.window).to(self.device))
                main_rows = [i for i, s in enumerate(batch_slots) if s.fork is None]
                comps = np.zeros((len(batch_slots), 3), np.float32)
                if main_rows:
                    comps[main_rows] = self._critic_values([targets[i] for i in main_rows], None) \
                        if self.critic is not None else out.value.float().cpu().numpy()[main_rows]
            logp_all = torch.log_softmax(out.logits.float(), -1).cpu().numpy()
            values = combine_value(comps, alpha, self.cfg.reward)
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
                if slot.fork is None:
                    ep.logp.append(float(lp[a]))
                    ep.value.append(float(values[i]))
                    ep.value_comps.append(comps[i].copy())
                    if use_forks:
                        spawn_forks(slot, len(ep.obs) - 1, a, lp)
                futures[self.pool.submit(slot.env.step, a, slot.obs, alpha)] = slot

        # Bootstrap values: truncated episodes and branches stopped at the horizon.
        trunc = [ep for ep in finished if ep.outcome == Outcome.TRUNCATED and ep.final_obs is not None and len(ep)]
        items = [(ep, ep.final_obs) for ep in trunc] + [(be, obs) for _, be, obs in branch_boot]
        comps = self._bootstrap(items) if items else np.zeros((0, 3), np.float32)
        for ep, c in zip(trunc, comps[:len(trunc)]):
            ep.bootstrap_comps = c.copy()
            ep.bootstrap_value = float(combine_value(c, alpha, self.cfg.reward))
        scale_vec = np.asarray(VALUE_SCALE, np.float64)
        for (slot, _, _), c in zip(branch_boot, comps[len(trunc):]):
            c = c.astype(np.float64)
            if not fc.bootstrap_win:
                c[2] = 0.0          # real wins are in slot.events; the critic's guess is not used
            slot.fork.details[(slot.option, slot.seed)]["bootstrap_comps"] = c.tolist()   # as used in the return
            slot.fork.returns[(slot.option, slot.seed)] = float((slot.events + c * scale_vec) @ wvec)
        wall = time.perf_counter() - started_at
        stats = summarize(finished)
        stats.update(fork_stats(all_forks, fc.seeds))
        return RolloutResult(finished, transitions, started, wall, infer_s, wall - infer_s, forward_calls, stats)


def fork_option_returns(fork: Fork, seeds: int) -> np.ndarray | None:
    """Mean return of each option over seed sets, or None if incomplete/failed."""
    if fork.failed:
        return None
    vals = np.full((len(fork.options), seeds), np.nan)
    for (k, s), v in fork.returns.items():
        vals[k, s] = v
    if np.isnan(vals).any():
        return None
    return vals.mean(1)


def fork_stats(forks: list[Fork], seeds: int) -> dict:
    if not forks:
        return {"forks": 0}
    ok = [(f, fork_option_returns(f, seeds)) for f in forks]
    ok = [(f, r) for f, r in ok if r is not None]
    spread = [float(r.max() - r.min()) for _, r in ok]
    # Only unique best options provide evidence of choosing better; report ties separately.
    best = [np.isclose(r, r.max(), rtol=1e-6, atol=1e-8) for _, r in ok]
    taken_best = [float(mask[0]) for mask in best if mask.sum() == 1]
    by_screen = collections.Counter(f.screen for f, _ in ok)

    def taken_best_on(screen: int) -> float:   # same rule as fork_taken_was_best, one screen
        vals = [float(mask[0]) for (f, _), mask in zip(ok, best) if f.screen == screen and mask.sum() == 1]
        return float(np.mean(vals)) if vals else float("nan")

    rest = [(f, r) for f, r in ok if f.screen == SCREEN_REST and REST_HEAL in f.groups and REST_UPGRADE in f.groups]
    heal_better = [float(r[f.groups.index(REST_HEAL)] > r[f.groups.index(REST_UPGRADE)]) for f, r in rest]
    return {"forks": len(forks), "forks_complete": len(ok),
            "fork_branches": sum(len(f.options) * seeds for f in forks),
            # simulator and inference work spent in branches (cost of the forks)
            "fork_branch_decisions": sum(d.get("decisions", 0) for f in forks for d in f.details.values()),
            "fork_branch_combats": sum(d.get("combats", 0) for f in forks for d in f.details.values()),
            "fork_rest": by_screen.get(SCREEN_REST, 0), "fork_map": by_screen.get(SCREEN_MAP, 0),
            "fork_card": by_screen.get(SCREEN_CARD_REWARD, 0),
            "fork_return_spread": float(np.mean(spread)) if spread else float("nan"),
            "fork_taken_was_best": float(np.mean(taken_best)) if taken_best else float("nan"),
            "fork_decisive": len(taken_best),
            "fork_rest_taken_was_best": taken_best_on(SCREEN_REST),
            "fork_map_taken_was_best": taken_best_on(SCREEN_MAP),
            "fork_card_taken_was_best": taken_best_on(SCREEN_CARD_REWARD),
            "fork_tie_rate": float(np.mean([mask.sum() > 1 for mask in best])) if best else float("nan"),
            "fork_rest_heal_better": float(np.mean(heal_better)) if heal_better else float("nan")}


def rest_behaviour(episodes: list[Episode]) -> dict:
    """Campfire choice when both heal and upgrade are legal, split by HP (behaviour check)."""
    low, full = [], []
    for ep in episodes:
        for o, a in zip(ep.obs, ep.actions):
            if o.phase // 2 != SCREEN_REST or o.phase % 2:
                continue
            types = o.cand_type
            if not ((types == REST_HEAL).any() and (types == REST_UPGRADE).any()):
                continue
            hp = float(o.num[0][0]); heal = float(types[a] == REST_HEAL)
            if hp < 0.5:
                low.append(heal)
            elif hp > 0.999:
                full.append(heal)
    return {"rest_heal_rate_hp_below_50": float(np.mean(low)) if low else float("nan"),
            "rest_heal_rate_full_hp": float(np.mean(full)) if full else float("nan"),
            "rest_choices_hp_below_50": len(low), "rest_choices_full_hp": len(full)}


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
        "menu_loops": sum(r["menu_loops"] for r in rows),
        "truncation_reasons": dict(sorted(collections.Counter(
            r["truncation_reason"] for r in rows if r["outcome"] == "TRUNCATED").items())),
        "failure_reasons": sorted({ep.failure_reason for ep in episodes if ep.outcome == Outcome.FAILURE}),
        **rest_behaviour(episodes),
    }
