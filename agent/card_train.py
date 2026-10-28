"""REINFORCE training for the run-level card-selection model.

Combats are played by the native greedy policy; the learned model only chooses
card rewards. Worked example: ``python -m deployment.train_local card``.
"""
from __future__ import annotations

import argparse
import pathlib
import time

import numpy as np
import torch

from .common import (
    RACT,
    SCREEN,
    card_feature_array,
    legal_run_actions,
    new_run,
    run_observation,
    sim,
)
from .nets import CardScorer, load_checkpoint, save_checkpoint


def _skip_features() -> np.ndarray:
    return np.asarray(sim.card_features(0, False, -1), dtype=np.float32)


def _run_return(rc) -> float:
    if rc.screen != SCREEN.RUN_OVER:
        return 0.0
    hp_frac = rc.hp / max(1, rc.max_hp)
    return (1.0 if rc.won else 0.0) + 0.3 * rc.floor / 15.0 + 0.2 * hp_frac


def collect_episode(seed: int, model: CardScorer, deterministic: bool = False) -> dict:
    rc = new_run(seed)
    records = []
    steps = 0
    while rc.screen != SCREEN.RUN_OVER and steps < 5000:
        steps += 1
        if rc.screen == SCREEN.COMBAT:
            if not rc.step_combat(*rc.battle.greedy_action(0.05, seed & 0x7FFFFFFF)):
                break
            continue
        if rc.screen == SCREEN.CARD_REWARD:
            offered = rc.offered
            cand = np.vstack([card_feature_array(offered), _skip_features()])
            obs = run_observation(rc)
            logits = model.scores(torch.from_numpy(obs)[None], torch.from_numpy(cand)[None])[0]
            probs = torch.softmax(logits, dim=-1)
            if deterministic:
                choice = int(torch.argmax(probs))
                logp = float(torch.log(probs[choice] + 1e-8))
            else:
                dist = torch.distributions.Categorical(probs=probs)
                choice = int(dist.sample())
                logp = float(dist.log_prob(torch.tensor(choice)))
            records.append({"obs": obs, "cand": cand, "choice": choice, "logp": logp})
            if choice >= len(offered):
                rc.step(int(RACT.SKIP_CARD), 0)
            else:
                rc.step(int(RACT.TAKE_CARD), choice)
            continue
        if rc.screen == SCREEN.REST:
            legal = legal_run_actions(rc)
            action = (int(RACT.REST_HEAL), 0) if rc.hp * 10 < rc.max_hp * 6 else legal[-1]
        elif rc.screen == SCREEN.SHOP:
            action = (int(RACT.LEAVE_SHOP), 0)
        elif rc.screen == SCREEN.EVENT:
            action = (int(RACT.EVENT_CHOICE), 0)
        elif rc.screen == SCREEN.TREASURE:
            action = (int(RACT.COLLECT), 0)
        elif rc.screen == SCREEN.MAP:
            action = (int(RACT.MOVE), rc.available_map_nodes()[0])
        else:
            break
        if not rc.step(*action):
            break
    return {"records": records, "return": _run_return(rc), "won": bool(rc.won),
            "floor": int(rc.floor), "hp": int(rc.hp)}


def train(iterations: int = 50, runs_per_iter: int = 32, seed: int = 1,
          out_dir: str = "runs/card", resume: str | None = None,
          lr: float = 3e-4) -> CardScorer:
    torch.set_num_threads(1)
    model = CardScorer()
    if resume and pathlib.Path(resume).exists():
        load_checkpoint(resume, model)
        print(f"resumed {resume}", flush=True)
    opt = torch.optim.Adam(model.parameters(), lr=lr)
    out = pathlib.Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    for it in range(1, iterations + 1):
        start = time.time()
        episodes = [collect_episode(seed * 100000 + it * 1000 + i, model)
                    for i in range(runs_per_iter)]
        returns = np.asarray([e["return"] for e in episodes], dtype=np.float32)
        if returns.std() < 1e-6:
            adv = returns - returns.mean()
        else:
            adv = (returns - returns.mean()) / (returns.std() + 1e-6)

        losses = []
        for ep, a in zip(episodes, adv):
            for rec in ep["records"]:
                obs = torch.from_numpy(rec["obs"])[None]
                cand = torch.from_numpy(rec["cand"])[None]
                logits = model(obs, cand)[0]
                logp = torch.log_softmax(logits, dim=-1)[rec["choice"]]
                loss = -(logp * float(a)) - 0.01 * torch.distributions.Categorical(logits=logits).entropy()
                losses.append(loss)
        if losses:
            opt.zero_grad()
            torch.stack(losses).mean().backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step()

        winrate = float(np.mean([e["won"] for e in episodes]))
        avg_floor = float(np.mean([e["floor"] for e in episodes]))
        print(f"iter {it:3d} runs {len(episodes):4d} win {winrate:.3f} floor {avg_floor:.1f} "
              f"return {returns.mean():.3f} loss {float(torch.stack(losses).mean().detach()) if losses else 0:.4f} "
              f"{time.time() - start:.2f}s", flush=True)
        save_checkpoint(out / "card.pt", model, {"iteration": it, "return": float(returns.mean())})
    return model


def evaluate(model: CardScorer, runs: int = 200, seed: int = 999) -> dict:
    results = [collect_episode(seed + i, model, deterministic=True) for i in range(runs)]
    return {
        "winrate": float(np.mean([r["won"] for r in results])),
        "avg_floor": float(np.mean([r["floor"] for r in results])),
    }


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--iterations", type=int, default=50)
    parser.add_argument("--runs-per-iter", type=int, default=32)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--out-dir", default="runs/card")
    parser.add_argument("--resume", default=None)
    parser.add_argument("--eval-runs", type=int, default=200)
    args = parser.parse_args(argv)
    model = train(args.iterations, args.runs_per_iter, args.seed, args.out_dir, args.resume)
    print("eval", evaluate(model, args.eval_runs), flush=True)


if __name__ == "__main__":
    main()
