"""Offline critic prior from trajectory archives (value prior for a warm-started run).

Targets are the actually observed future events of each decision (floors
completed, acts entered, win), normalized like the critic outputs; only runs
that ended normally (win or death) are used. Files are streamed in chunks so
host memory stays bounded. The last ``holdout_files`` archive files are never
trained on; explained variance on them selects the saved epoch, including the
initial critic (epoch 0) so offline training cannot replace it with a worse score.

Run 2 evidence (2026-11-11): the online critic reached EV ~0.05 on future
floors, the same network family trained offline on 12 rollouts ~0.29.
"""
from __future__ import annotations

import dataclasses
import json
import random
import time
from pathlib import Path

import numpy as np
import torch

from .archive import read_rollout
from .config import RunConfig
from .data import collate
from .model import VALUE_SCALE, SpireNet
from .ppo import _autocast, critic_update
from .sim import identity

FORMAT = "spire_rl.critic/1"
SCALE = np.asarray(VALUE_SCALE, np.float32)


def archive_files(dirs: list[Path]) -> list[Path]:
    files = []
    for d in dirs:
        files.extend(sorted(Path(d).glob("rollout_*.npz")))
    if not files:
        raise FileNotFoundError(f"no rollout_*.npz in {dirs}")
    return files


def load_targets(files: list[Path], cand_num: int) -> list:
    """Episodes with ``comp_returns`` = future events / scale; normal endings only.

    Episode ids are renumbered within the returned list (the original is kept in
    ``info["archive_episode_id"]``): ``collate`` keys states by episode id, and
    archives of different runs reuse the same ids.
    """
    eps = []
    for f in files:
        _, episodes = read_rollout(f)
        for ep in episodes:
            if ep.outcome.name not in ("WIN", "DEATH") or len(ep) == 0:
                continue
            ep.info["archive_episode_id"], ep.episode_id = ep.episode_id, len(eps)
            events = np.stack([r[1:4] for r in ep.reward]).astype(np.float64)
            ep.comp_returns = (np.cumsum(events[::-1], 0)[::-1] / SCALE).astype(np.float32)
            for o in ep.obs:
                if o.cand_num.shape[1] < cand_num:          # older macro observation (v1): no deselect flag
                    o.cand_num = np.pad(o.cand_num, ((0, 0), (0, cand_num - o.cand_num.shape[1])))
                o.num = o.num.astype(np.float16)
            ep.info["source"] = f.name
            eps.append(ep)
    return eps


def evaluate_critic(critic: SpireNet, eps, device, bf16: bool, chunk: int = 128) -> dict:
    critic.eval()
    tg = [(ep, t) for ep in eps for t in range(len(ep))]
    pred = []
    with torch.no_grad(), _autocast(device, bf16):
        for i in range(0, len(tg), chunk):
            pred.append(critic(collate(tg[i:i + chunk], critic.cfg.window).to(device)).value.float().cpu().numpy())
    critic.train()
    p = np.concatenate(pred) * SCALE
    y = np.concatenate([ep.comp_returns for ep in eps]) * SCALE
    out = {}
    for k, name in enumerate(("floors", "acts", "win")):
        var = float(np.var(y[:, k]))
        out[name] = (1.0 - float(np.var(y[:, k] - p[:, k])) / var) if var > 0 else None
    out["decisions"] = int(len(y))
    return out


def pretrain_critic(cfg: RunConfig, archive_dirs: list[Path], out: Path, device: torch.device,
                    init_checkpoint: Path | None = None, epochs: int = 2, files_per_chunk: int = 16,
                    holdout_files: int = 8, microbatch: int = 32, seed: int = 0, log=print) -> dict:
    if cfg.critic is None:
        raise ValueError("config has no separate critic")
    from .train import build_critic, env_spec   # local import: avoid a cycle
    torch.manual_seed(seed)
    rng = random.Random(seed)
    critic = build_critic(cfg, device)
    if init_checkpoint:
        from . import checkpoint as ckpt
        payload = ckpt.load(Path(init_checkpoint))
        if payload.get("critic") is not None:
            critic.load_state_dict(payload["critic"])
            log(f"critic initialised from {init_checkpoint}")
    p = dataclasses.replace(cfg.ppo, value_epochs=1, microbatch=microbatch)
    optimizer = torch.optim.AdamW(critic.parameters(), lr=p.critic_lr, betas=p.betas, eps=p.eps)
    files = archive_files(archive_dirs)
    if len(files) <= holdout_files:
        raise ValueError("not enough archive files for the holdout")
    train_files, hold = files[:-holdout_files], files[-holdout_files:]
    cand_num = env_spec(cfg).cand_num
    holdout = load_targets(hold, cand_num)
    log(f"archives: {len(train_files)} training files, {len(hold)} holdout files ({sum(map(len, holdout))} decisions)")
    report = {"before": evaluate_critic(critic, holdout, device, p.bf16), "epochs": []}
    log(f"held-out EV before: {report['before']}")

    def score(ev):
        values = [ev[k] for k in ("floors", "acts") if ev[k] is not None]
        return sum(values) if values and all(np.isfinite(v) for v in values) else -float("inf")

    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)

    def save_best(epoch, ev):
        payload = {"format": FORMAT, "critic": critic.state_dict(), "critic_config": dataclasses.asdict(cfg.critic),
                   "identity": identity(), "heldout_ev": ev, "epoch": epoch,
                   "archives": [str(d) for d in archive_dirs], "init_checkpoint": str(init_checkpoint or "")}
        tmp = out.with_suffix(".tmp")
        torch.save(payload, tmp)
        tmp.replace(out)
        report.update(best_epoch=epoch, best_heldout_ev=ev, improved=epoch > 0)

    best_score = score(report["before"])
    if not np.isfinite(best_score):
        raise ValueError("held-out floors/acts EV is not finite; cannot select a critic prior")
    report["selection_metric"] = "floors_ev + acts_ev (zero-variance components omitted)"
    save_best(0, report["before"])
    started = time.perf_counter()
    for epoch in range(epochs):
        order = list(train_files)
        rng.shuffle(order)
        losses = []
        for c0 in range(0, len(order), files_per_chunk):
            eps = load_targets(order[c0:c0 + files_per_chunk], cand_num)
            targets = [(ep, t) for ep in eps for t in range(len(ep))]
            if targets:
                losses.append(critic_update(critic, optimizer, targets, p, critic.cfg.window, device, rng)["value_loss"])
            del eps, targets
        ev = evaluate_critic(critic, holdout, device, p.bf16)
        row = {"epoch": epoch + 1, "train_loss": float(np.mean(losses)) if losses else None, "heldout_ev": ev,
               "minutes": (time.perf_counter() - started) / 60}
        report["epochs"].append(row)
        log(f"epoch {epoch + 1}: {row}")
        candidate_score = score(ev)
        if candidate_score > best_score:
            best_score = candidate_score
            save_best(epoch + 1, ev)
    log(f"selected critic epoch {report['best_epoch']}; improved over initial: {report['improved']}")
    report["saved"] = str(out)
    Path(str(out) + ".json").write_text(json.dumps(report, indent=1, default=str))
    return report
