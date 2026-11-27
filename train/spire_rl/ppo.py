"""Full-run PPO from scratch (docs/plan.md 4, 6.2).

    python -m spire_rl.ppo --run runs/a100-1 --hours 8              # train (resumes if the run exists)
    python -m spire_rl.ppo --run runs/bench --bench                  # decisions/s and update speed

Synchronous PPO: ``workers`` x ``games`` simulator games step in lockstep; the trainer runs the
policy for all of them on the GPU, collects ``--samples`` decisions, computes GAE and updates
``--epochs`` times in minibatches (gradient accumulation over ``--micro``). The EMA copy of the
weights is kept for evaluation and saved next to the latest checkpoint; only those two files are
kept. ``--hours`` stops cleanly after the update that crosses the budget; SIGINT / SIGTERM stop
after the current update. ``--practice`` is the share of games playing single practice fights;
``--value-hidden`` lets the value (never the policy) see the draw order. Evaluate with
``python -m spire_rl.evaluate``.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import signal
import time
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
import torch

from . import net as N
from .rollout import HIDDEN_CARDS, Pool, unpack


def _cpus() -> int:
    """CPUs this process may use (affinity, not the host count where available)."""
    try:
        return len(os.sched_getaffinity(0))
    except AttributeError:
        return os.cpu_count() or 4


# Presets (docs/runbook.md). ``--size`` fixes the network and its learning rate (scaled as
# 3e-5 x 768 / width); ``--machine`` sets only speed / memory knobs, which never change the
# gradient of an update. Any flag given explicitly overrides the preset.
SIZES = {
    "large":  dict(dim=768, ctx_layers=12, combat_layers=12, heads=12, lr=3e-5),    # 218M (runs 1-3)
    "medium": dict(dim=512, ctx_layers=8, combat_layers=8, heads=8, lr=4.5e-5),     # 69M
    "small":  dict(dim=384, ctx_layers=6, combat_layers=6, heads=6, lr=6e-5),       # 32M
    "tiny":   dict(dim=256, ctx_layers=4, combat_layers=4, heads=4, lr=9e-5),       # 11M
}
MACHINES = {
    # laptop RTX 5090, 24 GB, 8 CPU threads (DEVLOG 57): micro 256 spilled to system memory
    "5090": dict(workers=6, games=16, micro=128, micro_tokens=16000, infer_batch=512),
    # A100 40 or 80 GB: same rows per chunk as run 1, a token cap that fits 40 GB
    "a100": dict(workers=max(1, _cpus() - 2), games=32, micro=256, micro_tokens=32000, infer_batch=512),
}


def parse(argv=None):
    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument("--size", choices=sorted(SIZES))
    pre.add_argument("--machine", choices=sorted(MACHINES))
    known, _ = pre.parse_known_args(argv)
    a = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    a.add_argument("--size", choices=sorted(SIZES), help="network preset: " + ", ".join(
        f"{k} (width {v['dim']}, {v['ctx_layers']}+{v['combat_layers']} layers, lr {v['lr']:g})" for k, v in SIZES.items()))
    a.add_argument("--machine", choices=sorted(MACHINES), help="speed/memory preset for the GPU machine")
    a.add_argument("--run", required=True, type=Path, help="run directory (checkpoints, log)")
    a.add_argument("--hours", type=float, default=0.0, help="stop after this much wall time (0 = no limit)")
    a.add_argument("--max-updates", type=int, default=0)
    a.add_argument("--ascension", type=int, default=10)
    a.add_argument("--workers", type=int, default=max(1, _cpus() - 2))
    a.add_argument("--games", type=int, default=32, help="games per worker")
    a.add_argument("--seed", type=int, default=1)
    # network (plan 6.2: 768 wide, 12 + 12 layers, 217M)
    a.add_argument("--dim", type=int, default=768)
    a.add_argument("--ctx-layers", type=int, default=12)
    a.add_argument("--combat-layers", type=int, default=12)
    a.add_argument("--heads", type=int, default=12)
    # PPO (plan 6.2)
    a.add_argument("--samples", type=int, default=65536, help="decisions per update")
    a.add_argument("--epochs", type=int, default=2)
    a.add_argument("--minibatch", type=int, default=4096)
    a.add_argument("--micro", type=int, default=256, help="rows per forward/backward (gradient accumulation)")
    a.add_argument("--infer-batch", type=int, default=512, help="rows per inference forward while sampling")
    a.add_argument("--no-sort-micro", dest="sort_micro", action="store_false",
                   help="do not group rows of similar size into micro-batches (same gradient either way)")
    a.add_argument("--micro-tokens", type=int, default=0,
                   help="also cap rows x padded entities per micro-batch (0 = rows only); bounds GPU memory")
    a.add_argument("--bench-micro", default="", help="--bench: comma-separated --micro sizes to time, e.g. 32,64,128,256")
    a.add_argument("--lr", type=float, default=3e-5)
    a.add_argument("--warmup-steps", type=int, default=100,
                   help="optimizer steps of linear LR warm-up (DEVLOG 49; was 20 updates, a whole slow run)")
    a.add_argument("--clip", type=float, default=0.2)
    a.add_argument("--target-kl", type=float, default=0.03, help="stop the epoch loop past this KL")
    a.add_argument("--credit", choices=("two-level", "flat"), default="two-level",
                   help="two-level: combat GAE within each fight + macro GAE between out-of-combat decisions, "
                        "discount per floor (DEVLOG 52); flat: one GAE per decision with --gamma / --lam (runs 1-2)")
    a.add_argument("--gamma-floor", type=float, default=0.99, help="two-level: discount per floor climbed")
    a.add_argument("--lam-combat", type=float, default=0.95, help="two-level: GAE lambda per decision inside a fight")
    a.add_argument("--lam-macro", type=float, default=0.9, help="two-level: GAE lambda per floor between macro decisions")
    a.add_argument("--gamma", type=float, default=0.999, help="flat: discount per decision")
    a.add_argument("--lam", type=float, default=0.95, help="flat: GAE lambda per decision")
    a.add_argument("--vf-coef", type=float, default=0.5)
    a.add_argument("--no-value-norm", dest="value_norm", action="store_false",
                   help="train the value on raw returns (before DEVLOG 51) instead of normalized ones")
    a.add_argument("--ent-start", type=float, default=0.01)
    a.add_argument("--ent-end", type=float, default=0.001)
    a.add_argument("--ent-updates", type=int, default=3000, help="updates over which entropy decays")
    a.add_argument("--grad-clip", type=float, default=1.0)
    a.add_argument("--ema-hours", type=float, default=2.0, help="EMA averaging time constant")
    a.add_argument("--save-minutes", type=float, default=30.0)
    a.add_argument("--reward", type=json.loads, default={}, help='reward weight overrides, e.g. \'{"floor": 0.02}\'')
    a.add_argument("--practice", type=float, default=0.4, help="share of games playing practice fights")
    a.add_argument("--value-hidden", action="store_true", help="value also sees the draw order (training only)")
    a.add_argument("--device", default="cuda" if torch.cuda.is_available() else "cpu")
    a.add_argument("--bench", action="store_true", help="measure sampling and update speed, then exit")
    if known.size:
        a.set_defaults(**SIZES[known.size])
    if known.machine:
        a.set_defaults(**MACHINES[known.machine])
    return a.parse_args(argv)


def _masked_logp(out, allowed):
    return torch.log_softmax(out["logp"].masked_fill(~allowed, float("-inf")), -1)


def _allowed_tensor(rows, width):
    t = torch.zeros(len(rows), width, dtype=torch.bool)
    for i, a in enumerate(rows):
        t[i, :len(a)] = torch.from_numpy(a)
    return t


def minibatches(order, size):
    """Equal minibatches of at least ``size`` rows (when there are that many). A leftover sliver
    must not become its own optimizer step: run 1 had a 32-row minibatch whose noisy KL ended
    updates early (DEVLOG 39)."""
    return np.array_split(order, max(1, len(order) // size))


def microbatches(minibatch, size, lengths=None, tokens=0):
    """Near-equal forward/backward chunks of at most ``size`` rows. With ``lengths`` (entities per
    row: run context, combat) the rows are sorted first, so a chunk is padded to rows of similar
    size instead of to the longest of a random 256 (about 40% wasted work, DEVLOG 47). ``tokens``
    > 0 also caps rows x padded entities per chunk, so activation memory stays bounded as decks
    grow (long rows get smaller chunks). The loss of each chunk is weighted by its share of the
    minibatch, so the summed gradient is unchanged either way."""
    if lengths is None:
        return np.array_split(minibatch, math.ceil(len(minibatch) / size))
    minibatch = minibatch[np.lexsort((lengths[minibatch, 1], lengths[minibatch, 0]))]
    if tokens <= 0:
        return np.array_split(minibatch, math.ceil(len(minibatch) / size))
    chunks, start, ctx_max, cmb_max = [], 0, 0, 0
    for i, row in enumerate(minibatch):
        c, k = max(ctx_max, int(lengths[row, 0])), max(cmb_max, int(lengths[row, 1]))
        if i > start and ((i - start + 1) * (c + k + 1) > tokens or i - start >= size):
            chunks.append(minibatch[start:i])
            start, c, k = i, int(lengths[row, 0]), int(lengths[row, 1])
        ctx_max, cmb_max = c, k
    chunks.append(minibatch[start:])
    return chunks


def entity_lengths(packed) -> np.ndarray:
    """[N, 2] run-context and combat entity counts of packed inputs (the collate padding sizes)."""
    return np.array([(d["n_ctx"], len(d["kind"]) - d["n_ctx"]) for d in packed], np.int64).reshape(-1, 2)


class ValueNorm:
    """Running mean / std of the value targets (DEVLOG 51). The network's value output is in these
    normalized units; everything outside the loss (GAE, practice settlement, logs) sees real reward
    units through ``denormalize``. Rewards are tiny (return std ~0.03), so without this the value
    loss gave the shared trunk about 1/50 of the policy's gradient. Debiased EMA over updates;
    before the first update it is the identity."""

    def __init__(self, beta: float = 0.9, min_std: float = 1e-4):
        self.beta, self.min_std = beta, min_std
        self.m1 = self.m2 = self.weight = 0.0

    @property
    def mean(self) -> float:
        return self.m1 / self.weight if self.weight else 0.0

    @property
    def std(self) -> float:
        if not self.weight:
            return 1.0
        return max(self.min_std, math.sqrt(max(0.0, self.m2 / self.weight - self.mean ** 2)))

    def update(self, x) -> None:
        x = np.asarray(x, np.float64)
        b = self.beta
        self.m1 = b * self.m1 + (1 - b) * float(x.mean())
        self.m2 = b * self.m2 + (1 - b) * float((x * x).mean())
        self.weight = b * self.weight + (1 - b)

    def normalize(self, x):
        return (x - self.mean) / self.std

    def denormalize(self, x):
        return x * self.std + self.mean

    def state_dict(self) -> dict:
        return {"beta": self.beta, "m1": self.m1, "m2": self.m2, "weight": self.weight}

    def load_state_dict(self, d: dict) -> None:
        self.beta, self.m1, self.m2, self.weight = d["beta"], d["m1"], d["m2"], d["weight"]


def two_level_gae(rew, done, val, combat, floor, fight, last_val, last_combat, last_floor, last_fight,
                  gamma_floor=0.99, lam_combat=0.95, lam_macro=0.9):
    """Advantages with two time scales (DEVLOG 52). Arrays are [T, n] (time x game slot); ``rew[t]``
    is the reward after decision t, ``done[t]`` that the game ended after it; ``last_*`` describe
    the decision after the last row (truncation, bootstrapped with ``last_val``).

    Time is game progress: a step from floor f to floor f' is discounted by gamma_floor ** (f' - f);
    clicks on the same floor are not discounted (a per-decision discount made value depend on how
    many decisions a turn took).

    * Combat decisions: GAE with ``lam_combat`` per decision, only inside the same fight; the last
      decision of a fight bootstraps with the value of the state after it (as practice wins do).
    * Out-of-combat (macro) decisions: semi-MDP GAE over macro decisions only. Everything between
      two macro decisions (whole fights included) is one transition: its rewards go to the earlier
      macro decision; lambda decays ``lam_macro`` per floor, not per click.

    Returns (advantage, value target, Monte-Carlo return with the same discount)."""
    T, n = rew.shape
    adv = np.zeros((T, n), np.float32)
    mc = np.zeros((T, n), np.float32)
    gae_c = np.zeros(n)
    y_next = np.zeros(n); z_next = np.zeros(n); am_next = np.zeros(n)
    g_mc = np.asarray(last_val, np.float64).copy()
    for t in reversed(range(T)):
        last = t == T - 1
        nv = np.asarray(last_val if last else val[t + 1], np.float64)
        nc = np.asarray(last_combat if last else combat[t + 1], bool)
        nf = np.asarray(last_floor if last else floor[t + 1])
        nfi = np.asarray(last_fight if last else fight[t + 1])
        nonterm = ~np.asarray(done[t], bool)
        steps = np.where(nonterm, np.maximum(nf - floor[t], 0), 0)
        disc = gamma_floor ** steps
        r, v = rew[t].astype(np.float64), val[t].astype(np.float64)
        # combat chain: continues only to the next decision of the same fight
        same_fight = nonterm & combat[t] & nc & (fight[t] == nfi) & (not last)
        delta_c = r + nonterm * disc * nv - v
        gae_c = delta_c + same_fight * lam_combat * disc * gae_c
        # macro chain: Y = rewards up to the next macro decision + its discounted value,
        # Z = its discounted, lambda-weighted advantage
        if last:
            y_t = r + nonterm * disc * nv
            z_t = np.zeros(n)
        else:
            macro_next = ~nc
            y_t = r + nonterm * disc * np.where(macro_next, nv, y_next)
            z_t = nonterm * disc * lam_macro ** steps * np.where(macro_next, am_next, z_next)
        am_t = y_t + z_t - v
        adv[t] = np.where(combat[t], gae_c, am_t)
        y_next, z_next, am_next = y_t, z_t, am_t
        g_mc = r + nonterm * disc * g_mc
        mc[t] = g_mc
    return adv, adv + val, mc


def normalize_by_group(adv, groups):
    """Standardize advantages separately per decision level, so out-of-combat decisions (about a
    third of the samples, a different scale) are not drowned by combat ones."""
    out = np.empty_like(adv, dtype=np.float32)
    for g in np.unique(groups):
        m = groups == g
        x = adv[m]
        out[m] = (x - x.mean()) / (x.std() + 1e-8) if m.sum() > 1 else 0.0
    return out


def explained_variance(target, prediction) -> float:
    """1 = the value predicts the target exactly, 0 = no better than its mean, < 0 = worse."""
    variance = float(np.var(target))
    return float(1 - np.var(target - prediction) / variance) if variance > 0 else 0.0


def encounter_name(encounter) -> str:
    from .sim import sim
    try:
        return sim.Encounter(int(encounter)).name
    except Exception:
        return str(encounter)


def run_metrics(finished) -> dict:
    """Where full games ended: death floors and rooms, elite / boss entries and wins."""
    lost = [f for f in finished if not f["won"]]
    fights = {k: {"entered": sum(f["fought"][k] for f in finished)} for k in ("normal", "elite", "boss")}
    fights["elite"]["won"] = sum(f["elites"] for f in finished)
    fights["boss"]["won"] = sum(f["bosses"] for f in finished)
    in_fight = [f for f in lost if f["death_room"] != "noncombat" and f["encounter"] is not None]
    return {"death_floors": {str(k): v for k, v in sorted(Counter(f["floor"] for f in lost).items())},
            "deaths_by_room": dict(Counter(f["death_room"] for f in lost)), "fights": fights,
            "deaths_by_encounter": {encounter_name(k): v for k, v in
                                    Counter(f["encounter"] for f in in_fight).most_common(8)}}


def error_line(f) -> str:
    return (f'{f["error"]} [seed={f["seed"]} floor={f["floor"]} encounter={encounter_name(f["encounter"])} '
            f'room={f["death_room"]} decisions={f["decisions"]}]')


class Trainer:
    def __init__(self, args):
        self.args = args
        self.dev = torch.device(args.device)
        self.amp = self.dev.type == "cuda"
        args.run.mkdir(parents=True, exist_ok=True)
        cfg = N.UnifiedNetConfig(dim=args.dim, ctx_layers=args.ctx_layers, combat_layers=args.combat_layers,
                                 heads=args.heads, observation_schema="spire.public/1",
                                 value_hidden=args.value_hidden)
        self.net = N.UnifiedNet(cfg).to(self.dev)
        self.opt = torch.optim.AdamW(self.net.parameters(), lr=args.lr, weight_decay=0.0, betas=(0.9, 0.999))
        self.ema = N.UnifiedNet(cfg).to(self.dev).eval()
        self.ema.load_state_dict(self.net.state_dict())
        for prm in self.ema.parameters():
            prm.requires_grad_(False)
        self.update = 0
        self.opt_steps = 0      # optimizer steps over all sessions (LR warm-up)
        self.vnorm = ValueNorm()
        self.samples_total = 0
        self.wall = 0.0          # training wall time over all sessions
        self.timing = defaultdict(float)    # seconds per phase in the current update
        self.resume()

    # ---------------------------------------------------------------- checkpoints
    def _paths(self):
        return self.args.run / "latest.pt", self.args.run / "ema.pt"

    def resume(self):
        latest, _ = self._paths()
        if not latest.exists():
            return
        ck = torch.load(latest, map_location="cpu", weights_only=False)
        from . import public_obs
        if ck["public_feature_version"] != public_obs.FEATURE_VERSION or ck["public_catalog_sha256"] != public_obs.CATALOG_SHA256:
            raise SystemExit(f"{latest}: observation version differs from the code; start a new --run")
        if {"value_hidden": False, **ck["config"]} != N.asdict(self.net.cfg):   # older runs lack the key
            raise SystemExit(f"{latest}: network config {ck['config']} differs from the arguments "
                             f"(was --size different from the first start? see sessions.jsonl in the run directory)")
        self.net.load_state_dict(ck["state"])
        self.ema.load_state_dict(ck["ema"])
        self.opt.load_state_dict(ck["opt"])
        self.update, self.samples_total, self.wall = ck["update"], ck["samples_total"], ck["wall"]
        self.opt_steps = ck.get("optimizer_steps_total", self._adam_steps())   # older runs: Adam's own count
        if "value_norm" in ck:
            self.vnorm.load_state_dict(ck["value_norm"])
        print(f"resumed {latest}: update {self.update}, {self.samples_total} samples, {self.wall / 3600:.2f} h")

    def _adam_steps(self) -> int:
        """Optimizer steps already taken, from AdamW's per-parameter state (0 before the first)."""
        for st in self.opt.state.values():
            if "step" in st:
                return int(st["step"])
        return 0

    def lr_at(self, step: int) -> float:
        """Linear warm-up over the first ``--warmup-steps`` optimizer steps, then constant."""
        return self.args.lr * min(1.0, (step + 1) / max(1, self.args.warmup_steps))

    def save(self):
        from . import public_obs
        from .sim import sim
        latest, ema = self._paths()
        meta = {"format": "spire_rl.unified/1", "config": N.asdict(self.net.cfg),
                "public_catalog_sha256": public_obs.CATALOG_SHA256, "public_feature_version": public_obs.FEATURE_VERSION,
                "macro_obs_version": int(sim.MACRO_OBS_VERSION), "combat_obs_version": int(sim.COMBAT_OBS_VERSION),
                "ruleset": sim.ENGINE_RULESET_ID}
        full = dict(meta, state=self.net.state_dict(), ema=self.ema.state_dict(), opt=self.opt.state_dict(),
                    update=self.update, optimizer_steps_total=self.opt_steps, value_norm=self.vnorm.state_dict(), samples_total=self.samples_total, wall=self.wall, args=vars(self.args) | {"run": str(self.args.run)})
        for path, payload in ((latest, full), (ema, dict(meta, state=self.ema.state_dict(), value_norm=self.vnorm.state_dict(),
                                                          extra={"update": self.update}))):
            tmp = path.with_suffix(".tmp")
            torch.save(payload, tmp)
            os.replace(tmp, path)          # never leave a half-written checkpoint

    # ---------------------------------------------------------------- policy
    @torch.no_grad()
    def policy(self, packed, allowed, hidden=None):
        """Sample actions; returns (actions, logp, values) for the given decisions."""
        self.net.eval()
        acts, logps, vals = [], [], []
        bs = self.args.infer_batch
        for i in range(0, len(packed), bs):
            t0 = time.perf_counter()
            obs = [unpack(x) for x in packed[i:i + bs]]
            b = N.collate(obs)
            if hidden is not None:
                b.hidden = torch.from_numpy(np.stack(hidden[i:i + bs])).long()
            b = b.to(self.dev, non_blocking=True)
            t1 = time.perf_counter()
            with torch.autocast("cuda", dtype=torch.bfloat16, enabled=self.amp):
                out = self.net(b)
            lp = _masked_logp({"logp": out["logp"].float()}, _allowed_tensor(allowed[i:i + bs], b.cmask.shape[1]).to(self.dev))
            a = torch.distributions.Categorical(logits=lp).sample()
            acts.append(a.cpu()); logps.append(lp.gather(1, a[:, None])[:, 0].cpu()); vals.append(self._value_out(out["value"].float()).cpu())
            t2 = time.perf_counter()        # .cpu() waits for the GPU
            self.timing["collect_prepare"] += t1 - t0
            self.timing["collect_network"] += t2 - t1
        return torch.cat(acts).numpy(), torch.cat(logps).numpy(), torch.cat(vals).numpy()

    def _value_out(self, v):
        """Network value output -> real reward units."""
        return self.vnorm.denormalize(v) if self.args.value_norm else v

    # ---------------------------------------------------------------- sampling
    def collect(self, pool, steps):
        """Lockstep sampling until ``--samples`` decisions; returns the batch and finished games."""
        n = len(steps)
        per_game = math.ceil(self.args.samples / n)
        buf = {k: [] for k in ("obs", "allowed", "hidden", "act", "logp", "val", "rew", "done", "combat", "floor", "fight")}
        two_level = self.args.credit == "two-level"
        use_hidden = self.args.value_hidden
        finished, t0 = [], time.time()
        for _ in range(per_game):
            packed = [s.obs for s in steps]; allowed = [s.allowed for s in steps]
            hidden = [s.hidden for s in steps] if use_hidden else None
            prev = steps
            act, logp, val = self.policy(packed, allowed, hidden)
            t_env = time.perf_counter()
            steps = pool.act(act.tolist())
            self.timing["collect_simulator"] += time.perf_counter() - t_env
            buf["obs"].append(packed); buf["allowed"].append(allowed)
            if use_hidden:
                buf["hidden"].append(hidden)
            buf["act"].append(act); buf["logp"].append(logp); buf["val"].append(val)
            buf["combat"].append(np.array([bool(x["in_combat"]) for x in packed]))
            buf["floor"].append(np.array([s.floor for s in prev], np.int64))
            buf["fight"].append(np.array([s.fight for s in prev], np.int64))
            rew_t = np.array([s.reward for s in steps], np.float32)
            boots = [(i, s.boot) for i, s in enumerate(steps) if s.boot is not None]
            if boots:       # practice win: settle with the value of the post-combat state
                obs_b = [x for _, x in boots]
                _, _, v_b = self.policy(obs_b, [np.ones(len(x["cand_type"]), bool) for x in obs_b],
                                        [np.zeros(HIDDEN_CARDS, np.int32) for _ in obs_b] if use_hidden else None)
                # post-combat state is on the same floor: no discount in two-level time
                rew_t[[i for i, _ in boots]] += (1.0 if two_level else self.args.gamma) * v_b
            buf["rew"].append(rew_t)
            buf["done"].append(np.array([s.done for s in steps], bool))
            finished += [s.info for s in steps if s.info]
        _, _, last_val = self.policy([s.obs for s in steps], [s.allowed for s in steps],
                                     [s.hidden for s in steps] if use_hidden else None)
        T = per_game
        rew, done, val = np.stack(buf["rew"]), np.stack(buf["done"]), np.stack(buf["val"])
        combat = np.stack(buf["combat"])
        if two_level:
            a = self.args
            adv, ret, full_return = two_level_gae(
                rew, done, val, combat, np.stack(buf["floor"]), np.stack(buf["fight"]), last_val,
                np.array([bool(s.obs["in_combat"]) for s in steps]), np.array([s.floor for s in steps]),
                np.array([s.fight for s in steps]), a.gamma_floor, a.lam_combat, a.lam_macro)
        else:
            adv = np.zeros((T, n), np.float32); gae = np.zeros(n, np.float32)
            g, lam = self.args.gamma, self.args.lam
            for t in reversed(range(T)):
                nxt = last_val if t == T - 1 else val[t + 1]
                nonterm = 1.0 - done[t]
                delta = rew[t] + g * nxt * nonterm - val[t]
                gae = delta + g * lam * nonterm * gae
                adv[t] = gae
            ret = adv + val
            full_return = np.zeros((T, n), np.float32); following = last_val.copy()   # lambda = 1: no value in the target
            for t in reversed(range(T)):
                following = rew[t] + g * (1.0 - done[t]) * following
                full_return[t] = following
        c, m = combat.reshape(-1), ~combat.reshape(-1)
        rf, vf = ret.reshape(-1), val.reshape(-1)
        diag = {"value_ev": explained_variance(rf, vf),
                "value_ev_full_return": explained_variance(full_return.reshape(-1), vf),
                "value_ev_combat": explained_variance(rf[c], vf[c]) if c.any() else None,
                "value_ev_macro": explained_variance(rf[m], vf[m]) if m.any() else None,
                "macro_share": float(m.mean()),
                "advantage_std_combat": float(adv.reshape(-1)[c].std()) if c.any() else None,
                "advantage_std_macro": float(adv.reshape(-1)[m].std()) if m.any() else None,
                "value_mean": float(val.mean()), "value_std": float(val.std()),
                "return_std": float(full_return.std()), "advantage_std": float(adv.std())}
        flat = lambda x: [y for row in x for y in row]
        batch = {"obs": flat(buf["obs"]), "allowed": flat(buf["allowed"]), "act": np.concatenate(buf["act"]),
                 "logp": np.concatenate(buf["logp"]), "adv": adv.reshape(-1), "ret": ret.reshape(-1),
                 "val": val.reshape(-1), "combat": combat.reshape(-1), "diag": diag}
        if use_hidden:
            batch["hidden"] = np.stack(flat(buf["hidden"]))
        return batch, finished, steps, time.time() - t0

    # ---------------------------------------------------------------- update
    def learn(self, batch):
        a = self.args
        frac = min(1.0, self.update / max(1, a.ent_updates))
        ent_coef = a.ent_start + (a.ent_end - a.ent_start) * frac
        n = len(batch["act"])
        adv = batch["adv"]
        if a.credit == "two-level" and "combat" in batch:
            adv = normalize_by_group(adv, batch["combat"])
        else:
            adv = (adv - adv.mean()) / (adv.std() + 1e-8)
        if a.value_norm:            # stats include this batch, then the loss is in normalized units
            self.vnorm.update(batch["ret"])
            ret_target = self.vnorm.normalize(batch["ret"]).astype(np.float32)
        else:
            ret_target = batch["ret"]
        stats = {"policy_loss": [], "value_loss": [], "entropy": [], "kl": [], "clipfrac": []}
        self.net.train()
        stop = False
        optimizer_steps, kl_max, kl_stop_at = 0, float("-inf"), None
        lengths = entity_lengths(batch["obs"]) if a.sort_micro else None
        real_tokens = padded_tokens = max_tokens = rows_done = 0
        if self.dev.type == "cuda":
            torch.cuda.reset_peak_memory_stats(self.dev)
        for epoch in range(a.epochs):
            order = np.random.permutation(n)
            for mb_index, mb in enumerate(minibatches(order, a.minibatch)):
                self.opt.zero_grad(set_to_none=True)
                kls = []
                for idx in microbatches(mb, a.micro, lengths, a.micro_tokens if a.sort_micro else 0):
                    t0 = time.perf_counter()
                    b = N.collate([unpack(batch["obs"][i]) for i in idx])
                    rows = b.mask.shape[0]; rows_done += rows
                    real_tokens += int(b.mask.sum()) + int(b.c_mask.sum())
                    padded_tokens += rows * (b.mask.shape[1] + b.c_mask.shape[1])
                    max_tokens = max(max_tokens, b.mask.shape[1] + b.c_mask.shape[1])
                    if "hidden" in batch:
                        b.hidden = torch.from_numpy(batch["hidden"][idx]).long()
                    b = b.to(self.dev, non_blocking=True)
                    allowed = _allowed_tensor([batch["allowed"][i] for i in idx], b.cmask.shape[1]).to(self.dev)
                    act = torch.from_numpy(batch["act"][idx]).to(self.dev)
                    old = torch.from_numpy(batch["logp"][idx]).to(self.dev)
                    A = torch.from_numpy(adv[idx]).to(self.dev)
                    R = torch.from_numpy(ret_target[idx]).to(self.dev)
                    t1 = time.perf_counter()
                    with torch.autocast("cuda", dtype=torch.bfloat16, enabled=self.amp):
                        out = self.net(b)
                    lp_all = _masked_logp({"logp": out["logp"].float()}, allowed)
                    lp = lp_all.gather(1, act[:, None])[:, 0]
                    ratio = torch.exp(lp - old)
                    pl = -torch.min(ratio * A, ratio.clamp(1 - a.clip, 1 + a.clip) * A).mean()
                    vl = (out["value"].float() - R).pow(2).mean()
                    p_all = lp_all.exp()
                    ent = -(p_all * lp_all.masked_fill(~allowed, 0.0)).sum(-1).mean()
                    loss = (pl + a.vf_coef * vl - ent_coef * ent) * (len(idx) / len(mb))
                    loss.backward()
                    with torch.no_grad():
                        kl = (old - lp).mean().item()
                        kls.append(kl)
                        stats["policy_loss"].append(pl.item()); stats["value_loss"].append(vl.item())
                        stats["entropy"].append(ent.item()); stats["kl"].append(kl)
                        stats["clipfrac"].append(((ratio - 1).abs() > a.clip).float().mean().item())
                    t2 = time.perf_counter()        # .item() waits for the GPU
                    self.timing["learn_prepare"] += t1 - t0
                    self.timing["learn_network"] += t2 - t1
                t3 = time.perf_counter()
                torch.nn.utils.clip_grad_norm_(self.net.parameters(), a.grad_clip)
                lr = self.lr_at(self.opt_steps)
                for gr in self.opt.param_groups:
                    gr["lr"] = lr
                self.opt.step()
                self.opt_steps += 1
                self.timing["learn_optimizer"] += time.perf_counter() - t3
                optimizer_steps += 1
                mb_kl = float(np.mean(kls))
                kl_max = max(kl_max, mb_kl)
                if mb_kl > a.target_kl:
                    stop = True
                    kl_stop_at = {"epoch": epoch + 1, "minibatch": mb_index + 1, "rows": len(mb), "kl": mb_kl}
                    break
            if stop:
                break
        out = {k: float(np.mean(v)) if v else None for k, v in stats.items()}
        out.update(lr=lr, ent_coef=ent_coef, kl_stop=stop, epochs_done=epoch + 1, optimizer_steps=optimizer_steps,
                   value_norm={"mean": self.vnorm.mean, "std": self.vnorm.std, "on": bool(a.value_norm)},
                   optimizer_steps_total=self.opt_steps,
                   kl_max=kl_max, kl_stop_at=kl_stop_at,
                   learn_tokens={"padded_over_real": padded_tokens / max(1, real_tokens),
                                 "real_per_row": real_tokens / max(1, rows_done), "max_per_row": max_tokens})
        if self.dev.type == "cuda":
            free, total = torch.cuda.mem_get_info(self.dev)
            out["gpu_memory_gib"] = {"peak_allocated": torch.cuda.max_memory_allocated(self.dev) / 2**30,
                                     "peak_reserved": torch.cuda.max_memory_reserved(self.dev) / 2**30,
                                     "free_after": free / 2**30, "total": total / 2**30}
        return out

    @torch.no_grad()
    def ema_step(self, dt):
        decay = math.exp(-dt / (self.args.ema_hours * 3600))
        for e, p_ in zip(self.ema.parameters(), self.net.parameters()):
            e.mul_(decay).add_(p_.detach(), alpha=1 - decay)
        for e, b in zip(self.ema.buffers(), self.net.buffers()):
            e.copy_(b)

    # ---------------------------------------------------------------- main loop
    def run(self):
        a = self.args
        stop = {"flag": False}
        for sig in (signal.SIGINT, signal.SIGTERM):
            signal.signal(sig, lambda *_: stop.__setitem__("flag", True))
        pool = Pool(a.workers, a.games, a.seed + 7919 * self.update, a.ascension, a.reward or None,
                    a.practice, a.value_hidden)
        print(f"net {N.count_params(self.net) / 1e6:.1f}M params on {self.dev}; {a.workers} workers x {a.games} games")
        from .sim import sim
        with open(a.run / "sessions.jsonl", "a") as f:     # one line per start: what was run, from which update
            f.write(json.dumps({"start": time.strftime("%Y-%m-%d %H:%M:%S"), "update": self.update,
                                "ruleset": sim.ENGINE_RULESET_ID, "params_m": round(N.count_params(self.net) / 1e6, 1),
                                "args": {k: (str(v) if isinstance(v, Path) else v) for k, v in vars(a).items()}}) + "\n")
        session0, last_save = time.time(), time.time()
        log = open(a.run / "log.jsonl", "a")
        try:
            steps = pool.reset()
            while not stop["flag"]:
                t0 = time.time()
                self.timing.clear()
                batch, all_finished, steps, t_collect = self.collect(pool, steps)
                finished = [f for f in all_finished if f["mode"] == "full"]     # run metrics: full games only
                practice = [f for f in all_finished if f["mode"] == "practice"]
                t1 = time.time()
                st = self.learn(batch)
                t2 = time.time()
                self.update += 1
                self.samples_total += len(batch["act"])
                self.wall += t2 - t0
                self.ema_step(t2 - t0)
                rec = {"update": self.update, "time": time.strftime("%Y-%m-%d %H:%M:%S"), "wall_h": self.wall / 3600,
                       "samples": self.samples_total, "decisions_per_s": len(batch["act"]) / t_collect,
                       "collect_s": t_collect, "learn_s": t2 - t1, **st, **batch["diag"], "games": len(finished),
                       "timing_s": {k: round(v, 2) for k, v in sorted(self.timing.items())}}
                if finished:
                    rec.update(return_mean=float(np.mean([f["return"] for f in finished])),
                               floor_mean=float(np.mean([f["floor"] for f in finished])),
                               win_rate=float(np.mean([f["won"] for f in finished])),
                               act_reached=[int(np.sum([f["act"] >= k for f in finished])) for k in (1, 2)],
                               reasons={r: sum(f["reason"] == r for f in finished) for r in {f["reason"] for f in finished}},
                               errors=[error_line(f) for f in finished if "error" in f][:3],
                               **run_metrics(finished))
                if practice:
                    rec["practice"] = {k: {"fights": len(x), "win_rate": float(np.mean([f["reason"] != "died" and f["reason"] in ("practice_win", "won") for f in x]))}
                                       for k in ("normal", "elite", "boss") if (x := [f for f in practice if f["fight"] == k])}
                    rec["practice_errors"] = [error_line(f) for f in practice if "error" in f][:3]
                log.write(json.dumps(rec) + "\n"); log.flush()
                print(f"u{self.update} {rec['decisions_per_s']:.0f} dec/s collect {t_collect:.0f}s learn {t2 - t1:.0f}s "
                      f"games {len(finished)} floor {rec.get('floor_mean', float('nan')):.1f} "
                      f"win {rec.get('win_rate', float('nan')):.3f} kl {st['kl']:.4f} ent {st['entropy']:.3f}", flush=True)
                if time.time() - last_save > a.save_minutes * 60:
                    self.save(); last_save = time.time()
                if a.hours and time.time() - session0 > a.hours * 3600:
                    break
                if a.max_updates and self.update >= a.max_updates:
                    break
        finally:
            self.save()
            log.close()
            pool.close()
            print(f"saved {a.run} at update {self.update}")

    def bench(self, seconds=60):
        """Sampling decisions/s (policy forward included) and update throughput."""
        a = self.args
        pool = Pool(a.workers, a.games, a.seed, a.ascension, a.reward or None, a.practice, a.value_hidden)
        print(f"net {N.count_params(self.net) / 1e6:.1f}M params on {self.dev}; {a.workers} workers x {a.games} games")
        try:
            steps = pool.reset()
            n, t0 = 0, time.time()
            batch_obs, batch_allowed = [], []
            while time.time() - t0 < seconds:
                packed = [s.obs for s in steps]; allowed = [s.allowed for s in steps]
                act, _, _ = self.policy(packed, allowed, [s.hidden for s in steps] if a.value_hidden else None)
                batch_obs += packed; batch_allowed += allowed
                steps = pool.act(act.tolist()); n += len(steps)
            dt = time.time() - t0
            print(f"sampling: {n / dt:.0f} decisions/s ({n} in {dt:.0f}s)")
            m = min(len(batch_obs), a.minibatch)
            fake = {"obs": batch_obs[:m], "allowed": batch_allowed[:m],
                    "act": np.zeros(m, np.int64), "logp": np.zeros(m, np.float32),
                    "adv": np.random.randn(m).astype(np.float32), "ret": np.zeros(m, np.float32), "val": np.zeros(m, np.float32)}
            if a.value_hidden:
                fake["hidden"] = np.zeros((m, HIDDEN_CARDS), np.int32)
            # Always-allowed candidate 0 keeps the fake batch valid.
            for row in fake["allowed"]:
                row[0] = True
            saved = (a.epochs, a.target_kl, a.micro, a.sort_micro)
            a.epochs, a.target_kl = 1, float("inf")
            lengths = entity_lengths(fake["obs"])
            print(f"entities per row: run context mean {lengths[:, 0].mean():.0f} max {lengths[:, 0].max()}, "
                  f"combat mean {lengths[:, 1].mean():.0f} max {lengths[:, 1].max()}")
            sweep = [int(x) for x in a.bench_micro.split(",") if x] or [a.micro]
            # The first pass also warms up CUDA kernels and the allocator; time each setting after it.
            self.learn({**fake, "obs": fake["obs"][:min(m, 512)], "allowed": fake["allowed"][:min(m, 512)],
                        **{k: fake[k][:min(m, 512)] for k in ("act", "logp", "adv", "ret", "val")}})
            for micro in sweep:
                for sort in (False, True):
                    a.micro, a.sort_micro = micro, sort
                    self.timing.clear()
                    t1 = time.time(); st = self.learn(fake); dt2 = time.time() - t1
                    mem = st.get("gpu_memory_gib", {})
                    print(f"update micro {micro} {'sorted' if sort else 'random'}: {m / dt2:.0f} samples/s per epoch "
                          f"({m} in {dt2:.1f}s; padded/real tokens {st['learn_tokens']['padded_over_real']:.2f}; "
                          f"peak reserved {mem.get('peak_reserved', float('nan')):.1f} GiB, "
                          f"free after {mem.get('free_after', float('nan')):.1f} of {mem.get('total', float('nan')):.1f} GiB)")
            a.epochs, a.target_kl, a.micro, a.sort_micro = saved
            per_update = a.samples / (n / dt) + a.epochs * a.samples / (m / dt2)
            print(f"estimate per update of {a.samples} samples x {a.epochs} epochs: {per_update / 60:.1f} min; "
                  f"{3600 * a.samples / per_update / 1e6:.2f}M decisions/hour")
            if self.dev.type == "cuda":
                print(f"peak GPU memory {torch.cuda.max_memory_allocated() / 2**30:.1f} GiB")
        finally:
            pool.close()


def main(argv=None):
    args = parse(argv)
    torch.manual_seed(args.seed)
    np.random.seed(args.seed)
    t = Trainer(args)
    if args.bench:
        t.bench()
    else:
        t.run()


if __name__ == "__main__":
    main()
