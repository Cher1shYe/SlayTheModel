"""Self-play training for the combat model against the native simulator.

Each decision runs C++ PUCT at the root (network priors, greedy rollouts), the
visit distribution is the policy target and the combat result is the value
target. Worked example: ``python -m deployment.train_local selfplay``.
"""
from __future__ import annotations

import argparse
import pathlib
import time

import numpy as np
import torch
import torch.nn.functional as F

from .common import (
    ACTION_FEAT_DIM,
    OUTCOME,
    PUBLIC_COMBAT_OBS_DIM,
    RACT,
    SCREEN,
    combat_action_arrays,
    new_run,
    public_combat_observation,
    screen_action,
    sim,
)
from .nets import CombatNet, load_checkpoint, save_checkpoint


class Episode:
    __slots__ = ("state", "acts", "mask", "target", "value")

    def __init__(self, state, acts, target):
        self.state = state
        self.acts = acts
        self.mask = np.ones(len(acts), dtype=np.float32)
        self.target = target
        self.value = 0.0


def play_episode(seed: int, model: CombatNet, simulations: int = 16,
                 sample: bool = True, epsilon: float = 0.05) -> dict:
    rc = new_run(seed)
    rng = np.random.default_rng(seed)
    records: list[Episode] = []
    combat_start = 0
    steps = 0
    status = "error"
    while rc.screen != SCREEN.RUN_OVER and steps < 5000:
        steps += 1
        if rc.screen == SCREEN.COMBAT:
            bc = rc.battle
            actions, feats = combat_action_arrays(bc)
            if len(actions) == 1:
                action = actions[0]
            else:
                state = public_combat_observation(bc)
                logits, _value = model.policy_value(
                    torch.from_numpy(state)[None], torch.from_numpy(feats)[None])
                probs = torch.softmax(logits[0], dim=-1).numpy().astype(np.float64)
                s_actions, visits, _values, sims_done = bc.search_priors(
                    simulations, probs.tolist(), 1.5, 0.05, seed & 0x7FFFFFFF)
                visits = np.asarray(visits, dtype=np.float32)
                if visits.sum() <= 0:
                    visits = probs.astype(np.float32)
                target = visits / max(1e-8, float(visits.sum()))
                records.append(Episode(state, feats, target))
                if sample and rng.random() < epsilon:
                    idx = int(rng.integers(0, len(visits)))
                elif sample:
                    idx = int(rng.choice(len(visits), p=target.astype(np.float64) / target.sum()))
                else:
                    idx = int(np.argmax(visits))
                action = s_actions[idx]
            if not rc.step_combat(*action):
                break
            if rc.screen != SCREEN.COMBAT:
                won = bc.outcome == OUTCOME.PLAYER_VICTORY
                hp_frac = bc.player_hp / max(1, bc.player_max_hp)
                value = (1.0 + hp_frac) if won else 0.0
                for rec in records[combat_start:]:
                    rec.value = value
                combat_start = len(records)
            continue

        action = screen_action(rc)
        if not rc.step(*action):
            break
    else:
        status = "terminated" if rc.screen == SCREEN.RUN_OVER else "truncated"
    return {"records": records if status == "terminated" else [],
            "won": bool(rc.won) and status == "terminated",
            "floor": int(rc.floor), "hp": int(rc.hp), "status": status}


def pad_batch(records: list[Episode]):
    b = len(records)
    k = max(len(r.acts) for r in records)
    states = np.zeros((b, PUBLIC_COMBAT_OBS_DIM), dtype=np.float32)
    acts = np.zeros((b, k, ACTION_FEAT_DIM), dtype=np.float32)
    mask = np.zeros((b, k), dtype=np.float32)
    target = np.zeros((b, k), dtype=np.float32)
    value = np.zeros((b,), dtype=np.float32)
    for i, r in enumerate(records):
        n = len(r.acts)
        states[i] = r.state
        acts[i, :n] = r.acts
        mask[i, :n] = 1.0
        target[i, :n] = r.target
        value[i] = r.value
    return (torch.from_numpy(states), torch.from_numpy(acts),
            torch.from_numpy(mask), torch.from_numpy(target), torch.from_numpy(value))


def train_batch(model: CombatNet, opt, records: list[Episode], epochs: int = 2,
                batch_size: int = 256, value_coef: float = 0.5) -> dict:
    losses = []
    for _ in range(epochs):
        order = np.random.permutation(len(records))
        for start in range(0, len(records), batch_size):
            idx = order[start:start + batch_size]
            states, acts, mask, target, value = pad_batch([records[i] for i in idx])
            logits, values = model(states, acts, mask)
            logp = torch.log_softmax(logits, dim=-1)
            policy_loss = -(target * logp).sum(dim=-1).mean()
            value_loss = F.mse_loss(values, value)
            loss = policy_loss + value_coef * value_loss
            opt.zero_grad()
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step()
            losses.append(float(loss.detach()))
    return {"loss": float(np.mean(losses)) if losses else 0.0}


def evaluate(model: CombatNet, simulations: int = 16, runs: int = 50, seed: int = 9999) -> dict:
    results = [play_episode(seed + i, model, simulations, sample=False)
               for i in range(runs)]
    statuses = [r["status"] for r in results]
    return {
        "winrate": float(np.mean([r["won"] for r in results])),
        "avg_floor": float(np.mean([r["floor"] for r in results])),
        "records": int(sum(len(r["records"]) for r in results)),
        "abnormal_rate": float(np.mean([s != "terminated" for s in statuses])),
        "truncated": statuses.count("truncated"),
        "errors": statuses.count("error"),
    }


def train(iterations: int = 20, episodes_per_iter: int = 16, simulations: int = 16,
          seed: int = 1, out_dir: str = "runs/selfplay", resume: str | None = None,
          lr: float = 3e-4, eval_every: int = 5, eval_runs: int = 30) -> CombatNet:
    torch.set_num_threads(1)
    model = CombatNet()
    if resume and pathlib.Path(resume).exists():
        load_checkpoint(resume, model)
        print(f"resumed {resume}", flush=True)
    opt = torch.optim.Adam(model.parameters(), lr=lr)
    out = pathlib.Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    for it in range(1, iterations + 1):
        start = time.time()
        episodes = [play_episode(seed * 100000 + it * 1000 + i, model, simulations, sample=True)
                    for i in range(episodes_per_iter)]
        valid = [e for e in episodes if e["status"] == "terminated"]
        abnormal = len(episodes) - len(valid)
        records = [rec for ep in valid for rec in ep["records"]]
        stats = train_batch(model, opt, records) if records else {"loss": 0.0}
        winrate = float(np.mean([e["won"] for e in valid])) if valid else 0.0
        avg_floor = float(np.mean([e["floor"] for e in episodes]))
        print(f"iter {it:3d} eps {len(episodes):3d} abnormal {abnormal:3d} records {len(records):6d} "
              f"win {winrate:.3f} floor {avg_floor:.1f} loss {stats['loss']:.4f} "
              f"{time.time() - start:.2f}s", flush=True)
        save_checkpoint(out / "combat.pt", model, {"iteration": it})
        if eval_every and it % eval_every == 0:
            print("eval", evaluate(model, simulations, eval_runs), flush=True)
    return model


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--iterations", type=int, default=20)
    parser.add_argument("--episodes-per-iter", type=int, default=16)
    parser.add_argument("--simulations", type=int, default=16)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--out-dir", default="runs/selfplay")
    parser.add_argument("--resume", default=None)
    parser.add_argument("--eval-runs", type=int, default=30)
    args = parser.parse_args(argv)
    model = train(args.iterations, args.episodes_per_iter, args.simulations,
                  args.seed, args.out_dir, args.resume, eval_runs=args.eval_runs)
    print("eval", evaluate(model, args.simulations, args.eval_runs), flush=True)


if __name__ == "__main__":
    main()
