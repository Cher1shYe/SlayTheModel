"""Offline distillation of an archived policy into a (smaller) network.

The archive stores, for every decision, the public observation and the action
the behaviour policy sampled. Maximum likelihood on those sampled actions
converges to the behaviour policy's probabilities, so no teacher weights are
needed. Only the last ``files`` rollout files are used (the policy changes
during a run); the last ``holdout_files`` of them are never trained on.

Held-out report per epoch:
  ``nll``           student cross-entropy on the sampled actions
  ``teacher_nll``   the behaviour policy's own cross-entropy (its entropy)
  ``kl_estimate``   nll - teacher_nll, an estimate of KL(teacher || student)
  ``top1``          how often the student's most likely action is the sampled one

The critic is trained in the same pass on the actually observed future events
(as in ``pretrain``), from random initialization, and scored on the same
held-out files. The result is a normal ``spire_rl/3`` checkpoint: evaluate it
with ``eval`` and continue with ``train --init-checkpoint``.
"""
from __future__ import annotations

import json
import random
import time
from pathlib import Path

import numpy as np
import torch

from . import checkpoint as ckpt
from .config import RunConfig
from .data import collate
from .ppo import _autocast, _value_loss
from .pretrain import archive_files, evaluate_critic, load_targets


def _policy_eval(model, eps, device, bf16: bool, chunk: int = 128) -> dict:
    model.eval()
    tg = [(ep, t) for ep in eps for t in range(len(ep))]
    nll, hits = 0.0, 0
    with torch.no_grad(), _autocast(device, bf16):
        for i in range(0, len(tg), chunk):
            part = tg[i:i + chunk]
            logp = model(collate(part, model.cfg.window).to(device)).logits.float()
            actions = torch.tensor([ep.actions[t] for ep, t in part], device=device)
            nll -= float(logp.gather(1, actions[:, None]).sum())
            hits += int((logp.argmax(-1) == actions).sum())
    model.train()
    teacher = -float(np.mean([ep.logp[t] for ep, t in tg]))
    n = max(1, len(tg))
    return {"nll": nll / n, "teacher_nll": teacher, "kl_estimate": nll / n - teacher, "top1": hits / n,
            "decisions": len(tg)}


def distill(cfg: RunConfig, archive_dirs: list[Path], out: Path, device: torch.device, files: int = 60,
            holdout_files: int = 6, epochs: int = 4, files_per_chunk: int = 12, lr: float = 2e-4,
            batch_targets: int = 128, microbatch: int = 32, seed: int = 0, next_train_seed: int | None = None,
            log=print) -> dict:
    from .train import build_critic, build_model, env_spec   # local import: avoid a cycle
    torch.manual_seed(seed)
    rng = random.Random(seed)
    model = build_model(cfg, device)
    critic = build_critic(cfg, device)
    p = cfg.ppo
    opt = torch.optim.AdamW(model.parameters(), lr=lr, betas=p.betas, eps=p.eps)
    copt = torch.optim.AdamW(critic.parameters(), lr=p.critic_lr, betas=p.betas, eps=p.eps) if critic is not None else None
    use = archive_files(archive_dirs)[-files:]
    if len(use) <= holdout_files:
        raise ValueError("not enough archive files for the holdout")
    train_files, hold_files = use[:-holdout_files], use[-holdout_files:]
    cand_num = env_spec(cfg).cand_num
    holdout = load_targets(hold_files, cand_num)
    # Continue the game seeds after the highest one in ALL given archives, not only the files used.
    if next_train_seed is None:
        top = 0
        for f in archive_files(archive_dirs):
            with np.load(f) as z:
                top = max(top, int(z["ep_seed"].max()) if len(z["ep_seed"]) else 0)
        next_train_seed = (top // 1_000_000 + 1) * 1_000_000
    log(f"distill: {len(train_files)} training files ({train_files[0].name}..{train_files[-1].name}), "
        f"{len(hold_files)} held out ({sum(map(len, holdout))} decisions)")
    report = {"files": [f.name for f in use], "holdout_files": [f.name for f in hold_files], "epochs": [],
              "before": {"policy": _policy_eval(model, holdout, device, p.bf16)}}
    log(f"held-out before: {report['before']}")
    out = Path(out)
    best = float("inf")
    started = time.perf_counter()
    total_steps = None
    step = 0
    for epoch in range(epochs):
        order = list(train_files)
        rng.shuffle(order)
        losses, vlosses = [], []
        for c0 in range(0, len(order), files_per_chunk):
            eps = load_targets(order[c0:c0 + files_per_chunk], cand_num)
            targets = [(ep, t) for ep in eps for t in range(len(ep))]
            rng.shuffle(targets)
            if total_steps is None:   # linear decay to 10% of lr, from the size of the first chunk
                total_steps = max(1, epochs * len(train_files) * len(targets)
                                  // (len(order[c0:c0 + files_per_chunk]) * batch_targets))
            model.train()
            if critic is not None:
                critic.train()
            for b0 in range(0, len(targets), batch_targets):
                batch = targets[b0:b0 + batch_targets]
                n = len(batch)
                for group in opt.param_groups:
                    group["lr"] = lr * (1.0 - 0.9 * min(1.0, step / total_steps))
                opt.zero_grad(set_to_none=True)
                if copt is not None:
                    copt.zero_grad(set_to_none=True)
                total = vtotal = 0.0
                for m0 in range(0, n, microbatch):
                    micro = batch[m0:m0 + microbatch]
                    actions = torch.tensor([ep.actions[t] for ep, t in micro], device=device)
                    with _autocast(device, p.bf16):
                        logp = model(collate(micro, cfg.model.window).to(device)).logits
                    loss = -logp.float().gather(1, actions[:, None]).sum()
                    (loss / n).backward()
                    total += float(loss.detach())
                    if critic is not None:
                        with _autocast(device, p.bf16):
                            value = critic(collate(micro, critic.cfg.window).to(device)).value
                        vloss = _value_loss(value, micro, p, device).sum()
                        (vloss / n).backward()
                        vtotal += float(vloss.detach())
                torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
                opt.step()
                if copt is not None:
                    torch.nn.utils.clip_grad_norm_(critic.parameters(), p.max_grad_norm)
                    copt.step()
                step += 1
                losses.append(total / n)
                vlosses.append(vtotal / n)
            del eps, targets
        row = {"epoch": epoch + 1, "train_nll": float(np.mean(losses)) if losses else None,
               "train_value_loss": float(np.mean(vlosses)) if vlosses else None,
               "policy": _policy_eval(model, holdout, device, p.bf16),
               "critic_ev": evaluate_critic(critic, holdout, device, p.bf16) if critic is not None else None,
               "minutes": (time.perf_counter() - started) / 60}
        report["epochs"].append(row)
        log(f"epoch {epoch + 1}: {row}")
        if row["policy"]["nll"] < best:     # keep the epoch with the lowest held-out cross-entropy
            best = row["policy"]["nll"]
            report.update(best_epoch=epoch + 1, heldout=row["policy"], heldout_critic_ev=row["critic_ev"])
            ckpt.save(out, cfg, model,
                      {"distilled_from": [str(d) for d in archive_dirs], "files": report["files"],
                       "epoch": epoch + 1, "heldout": row["policy"], "heldout_critic_ev": row["critic_ev"],
                       "next_train_seed": next_train_seed}, critic)
    report["saved"] = str(out)
    report["next_train_seed"] = next_train_seed
    Path(str(out) + ".json").write_text(json.dumps(report, indent=1, default=str))
    return report
