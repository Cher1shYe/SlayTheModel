"""Full-run PPO from scratch (docs/plan.md 4, 6.2).

    python -m spire_rl.ppo --run runs/a100-1 --hours 8              # train (resumes if the run exists)
    python -m spire_rl.ppo --run runs/bench --bench                  # decisions/s and update speed

Synchronous PPO: ``workers`` x ``games`` simulator games step in lockstep; the trainer runs the
policy for all of them on the GPU, collects ``--samples`` decisions, computes GAE and updates
``--epochs`` times in minibatches (gradient accumulation over ``--micro``). The EMA copy of the
weights is kept for evaluation and saved next to the latest checkpoint; only those two files are
kept. ``--hours`` stops cleanly after the update that crosses the budget; SIGINT / SIGTERM stop
after the current update. Not yet: practice fights, hidden-information value input (switch
reserved: ``--value-hidden`` refuses), max-probability evaluation script.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import signal
import time
from pathlib import Path

import numpy as np
import torch

from . import net as N
from .rollout import Pool, unpack


def parse(argv=None):
    a = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    a.add_argument("--run", required=True, type=Path, help="run directory (checkpoints, log)")
    a.add_argument("--hours", type=float, default=0.0, help="stop after this much wall time (0 = no limit)")
    a.add_argument("--max-updates", type=int, default=0)
    a.add_argument("--ascension", type=int, default=10)
    a.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 4) - 2))
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
    a.add_argument("--lr", type=float, default=3e-5)
    a.add_argument("--warmup", type=int, default=20, help="updates of linear LR warm-up")
    a.add_argument("--clip", type=float, default=0.2)
    a.add_argument("--target-kl", type=float, default=0.03, help="stop the epoch loop past this KL")
    a.add_argument("--gamma", type=float, default=0.999)
    a.add_argument("--lam", type=float, default=0.95)
    a.add_argument("--vf-coef", type=float, default=0.5)
    a.add_argument("--ent-start", type=float, default=0.01)
    a.add_argument("--ent-end", type=float, default=0.001)
    a.add_argument("--ent-updates", type=int, default=3000, help="updates over which entropy decays")
    a.add_argument("--grad-clip", type=float, default=1.0)
    a.add_argument("--ema-hours", type=float, default=2.0, help="EMA averaging time constant")
    a.add_argument("--save-minutes", type=float, default=30.0)
    a.add_argument("--reward", type=json.loads, default={}, help='reward weight overrides, e.g. \'{"floor": 0.02}\'')
    a.add_argument("--value-hidden", action="store_true", help="value sees hidden info (not implemented yet)")
    a.add_argument("--device", default="cuda" if torch.cuda.is_available() else "cpu")
    a.add_argument("--bench", action="store_true", help="measure sampling and update speed, then exit")
    return a.parse_args(argv)


def _masked_logp(out, allowed):
    return torch.log_softmax(out["logp"].masked_fill(~allowed, float("-inf")), -1)


def _allowed_tensor(rows, width):
    t = torch.zeros(len(rows), width, dtype=torch.bool)
    for i, a in enumerate(rows):
        t[i, :len(a)] = torch.from_numpy(a)
    return t


class Trainer:
    def __init__(self, args):
        if args.value_hidden:
            raise SystemExit("--value-hidden: the hidden-information value input is not implemented yet")
        self.args = args
        self.dev = torch.device(args.device)
        self.amp = self.dev.type == "cuda"
        args.run.mkdir(parents=True, exist_ok=True)
        cfg = N.UnifiedNetConfig(dim=args.dim, ctx_layers=args.ctx_layers, combat_layers=args.combat_layers,
                                 heads=args.heads, observation_schema="spire.public/1")
        self.net = N.UnifiedNet(cfg).to(self.dev)
        self.opt = torch.optim.AdamW(self.net.parameters(), lr=args.lr, weight_decay=0.0, betas=(0.9, 0.999))
        self.ema = N.UnifiedNet(cfg).to(self.dev).eval()
        self.ema.load_state_dict(self.net.state_dict())
        for prm in self.ema.parameters():
            prm.requires_grad_(False)
        self.update = 0
        self.samples_total = 0
        self.wall = 0.0          # training wall time over all sessions
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
        if ck["config"] != N.asdict(self.net.cfg):
            raise SystemExit(f"{latest}: network config {ck['config']} differs from the arguments")
        self.net.load_state_dict(ck["state"])
        self.ema.load_state_dict(ck["ema"])
        self.opt.load_state_dict(ck["opt"])
        self.update, self.samples_total, self.wall = ck["update"], ck["samples_total"], ck["wall"]
        print(f"resumed {latest}: update {self.update}, {self.samples_total} samples, {self.wall / 3600:.2f} h")

    def save(self):
        from . import public_obs
        from .sim import sim
        latest, ema = self._paths()
        meta = {"format": "spire_rl.unified/1", "config": N.asdict(self.net.cfg),
                "public_catalog_sha256": public_obs.CATALOG_SHA256, "public_feature_version": public_obs.FEATURE_VERSION,
                "macro_obs_version": int(sim.MACRO_OBS_VERSION), "combat_obs_version": int(sim.COMBAT_OBS_VERSION),
                "ruleset": sim.ENGINE_RULESET_ID}
        full = dict(meta, state=self.net.state_dict(), ema=self.ema.state_dict(), opt=self.opt.state_dict(),
                    update=self.update, samples_total=self.samples_total, wall=self.wall, args=vars(self.args) | {"run": str(self.args.run)})
        for path, payload in ((latest, full), (ema, dict(meta, state=self.ema.state_dict(), extra={"update": self.update}))):
            tmp = path.with_suffix(".tmp")
            torch.save(payload, tmp)
            os.replace(tmp, path)          # never leave a half-written checkpoint

    # ---------------------------------------------------------------- policy
    @torch.no_grad()
    def policy(self, packed, allowed):
        """Sample actions; returns (actions, logp, values) for the given decisions."""
        self.net.eval()
        acts, logps, vals = [], [], []
        bs = self.args.infer_batch
        for i in range(0, len(packed), bs):
            obs = [unpack(x) for x in packed[i:i + bs]]
            b = N.collate(obs).to(self.dev, non_blocking=True)
            with torch.autocast("cuda", dtype=torch.bfloat16, enabled=self.amp):
                out = self.net(b)
            lp = _masked_logp({"logp": out["logp"].float()}, _allowed_tensor(allowed[i:i + bs], b.cmask.shape[1]).to(self.dev))
            a = torch.distributions.Categorical(logits=lp).sample()
            acts.append(a.cpu()); logps.append(lp.gather(1, a[:, None])[:, 0].cpu()); vals.append(out["value"].float().cpu())
        return torch.cat(acts).numpy(), torch.cat(logps).numpy(), torch.cat(vals).numpy()

    # ---------------------------------------------------------------- sampling
    def collect(self, pool, steps):
        """Lockstep sampling until ``--samples`` decisions; returns the batch and finished games."""
        n = len(steps)
        per_game = math.ceil(self.args.samples / n)
        buf = {k: [] for k in ("obs", "allowed", "act", "logp", "val", "rew", "done")}
        finished, t0 = [], time.time()
        for _ in range(per_game):
            packed = [s.obs for s in steps]; allowed = [s.allowed for s in steps]
            act, logp, val = self.policy(packed, allowed)
            steps = pool.act(act.tolist())
            buf["obs"].append(packed); buf["allowed"].append(allowed)
            buf["act"].append(act); buf["logp"].append(logp); buf["val"].append(val)
            buf["rew"].append(np.array([s.reward for s in steps], np.float32))
            buf["done"].append(np.array([s.done for s in steps], bool))
            finished += [s.info for s in steps if s.info]
        _, _, last_val = self.policy([s.obs for s in steps], [s.allowed for s in steps])
        T = per_game
        rew, done, val = np.stack(buf["rew"]), np.stack(buf["done"]), np.stack(buf["val"])
        adv = np.zeros((T, n), np.float32); gae = np.zeros(n, np.float32)
        g, lam = self.args.gamma, self.args.lam
        for t in reversed(range(T)):
            nxt = last_val if t == T - 1 else val[t + 1]
            nonterm = 1.0 - done[t]
            delta = rew[t] + g * nxt * nonterm - val[t]
            gae = delta + g * lam * nonterm * gae
            adv[t] = gae
        ret = adv + val
        flat = lambda x: [y for row in x for y in row]
        batch = {"obs": flat(buf["obs"]), "allowed": flat(buf["allowed"]), "act": np.concatenate(buf["act"]),
                 "logp": np.concatenate(buf["logp"]), "adv": adv.reshape(-1), "ret": ret.reshape(-1),
                 "val": val.reshape(-1)}
        return batch, finished, steps, time.time() - t0

    # ---------------------------------------------------------------- update
    def learn(self, batch):
        a = self.args
        frac = min(1.0, self.update / max(1, a.ent_updates))
        ent_coef = a.ent_start + (a.ent_end - a.ent_start) * frac
        lr = a.lr * min(1.0, (self.update + 1) / max(1, a.warmup))
        for gr in self.opt.param_groups:
            gr["lr"] = lr
        n = len(batch["act"])
        adv = batch["adv"]
        adv = (adv - adv.mean()) / (adv.std() + 1e-8)
        stats = {"policy_loss": [], "value_loss": [], "entropy": [], "kl": [], "clipfrac": []}
        self.net.train()
        stop = False
        for epoch in range(a.epochs):
            order = np.random.permutation(n)
            for m0 in range(0, n, a.minibatch):
                mb = order[m0:m0 + a.minibatch]
                self.opt.zero_grad(set_to_none=True)
                kls = []
                for u0 in range(0, len(mb), a.micro):
                    idx = mb[u0:u0 + a.micro]
                    b = N.collate([unpack(batch["obs"][i]) for i in idx]).to(self.dev, non_blocking=True)
                    allowed = _allowed_tensor([batch["allowed"][i] for i in idx], b.cmask.shape[1]).to(self.dev)
                    act = torch.from_numpy(batch["act"][idx]).to(self.dev)
                    old = torch.from_numpy(batch["logp"][idx]).to(self.dev)
                    A = torch.from_numpy(adv[idx]).to(self.dev)
                    R = torch.from_numpy(batch["ret"][idx]).to(self.dev)
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
                torch.nn.utils.clip_grad_norm_(self.net.parameters(), a.grad_clip)
                self.opt.step()
                if np.mean(kls) > a.target_kl:
                    stop = True
                    break
            if stop:
                break
        out = {k: float(np.mean(v)) if v else None for k, v in stats.items()}
        out.update(lr=lr, ent_coef=ent_coef, kl_stop=stop, epochs_done=epoch + 1)
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
        pool = Pool(a.workers, a.games, a.seed + 7919 * self.update, a.ascension, a.reward or None)
        print(f"net {N.count_params(self.net) / 1e6:.1f}M params on {self.dev}; {a.workers} workers x {a.games} games")
        session0, last_save = time.time(), time.time()
        log = open(a.run / "log.jsonl", "a")
        try:
            steps = pool.reset()
            while not stop["flag"]:
                t0 = time.time()
                batch, finished, steps, t_collect = self.collect(pool, steps)
                t1 = time.time()
                st = self.learn(batch)
                t2 = time.time()
                self.update += 1
                self.samples_total += len(batch["act"])
                self.wall += t2 - t0
                self.ema_step(t2 - t0)
                rec = {"update": self.update, "time": time.strftime("%Y-%m-%d %H:%M:%S"), "wall_h": self.wall / 3600,
                       "samples": self.samples_total, "decisions_per_s": len(batch["act"]) / t_collect,
                       "collect_s": t_collect, "learn_s": t2 - t1, **st, "games": len(finished)}
                if finished:
                    rec.update(return_mean=float(np.mean([f["return"] for f in finished])),
                               floor_mean=float(np.mean([f["floor"] for f in finished])),
                               win_rate=float(np.mean([f["won"] for f in finished])),
                               act_reached=[int(np.sum([f["act"] >= k for f in finished])) for k in (1, 2)],
                               reasons={r: sum(f["reason"] == r for f in finished) for r in {f["reason"] for f in finished}},
                               errors=[f["error"] for f in finished if "error" in f][:3])
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
        pool = Pool(a.workers, a.games, a.seed, a.ascension, a.reward or None)
        print(f"net {N.count_params(self.net) / 1e6:.1f}M params on {self.dev}; {a.workers} workers x {a.games} games")
        try:
            steps = pool.reset()
            n, t0 = 0, time.time()
            batch_obs, batch_allowed = [], []
            while time.time() - t0 < seconds:
                packed = [s.obs for s in steps]; allowed = [s.allowed for s in steps]
                act, _, _ = self.policy(packed, allowed)
                batch_obs += packed; batch_allowed += allowed
                steps = pool.act(act.tolist()); n += len(steps)
            dt = time.time() - t0
            print(f"sampling: {n / dt:.0f} decisions/s ({n} in {dt:.0f}s)")
            m = min(len(batch_obs), a.minibatch)
            fake = {"obs": batch_obs[:m], "allowed": batch_allowed[:m],
                    "act": np.zeros(m, np.int64), "logp": np.zeros(m, np.float32),
                    "adv": np.random.randn(m).astype(np.float32), "ret": np.zeros(m, np.float32), "val": np.zeros(m, np.float32)}
            # Always-allowed candidate 0 keeps the fake batch valid.
            for row in fake["allowed"]:
                row[0] = True
            saved = (a.epochs, a.target_kl)
            a.epochs, a.target_kl = 1, float("inf")
            t1 = time.time(); self.learn(fake); dt2 = time.time() - t1
            a.epochs, a.target_kl = saved
            print(f"update: {m / dt2:.0f} samples/s per epoch ({m} in {dt2:.1f}s)")
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
