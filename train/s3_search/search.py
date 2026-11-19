"""Resumable S3 candidate search on SF2 v14, A9 final boss only."""
import argparse
from concurrent.futures import ProcessPoolExecutor
from hashlib import sha256
from collections import Counter
import json
import multiprocessing as mp
from pathlib import Path
import sqlite3
import sys

import numpy as np
import torch
from filelock import FileLock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from a9 import evaluate_a9 as game
from a9.adapter import WEIGHT_SHA256
from rasch import fit, screen, select

TRIALS = "CREATE TABLE IF NOT EXISTS trials (model TEXT, seed INTEGER, won INTEGER, result TEXT, PRIMARY KEY(model,seed))"


def write_json(path, value):
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    tmp.replace(path)


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def tensor_id(state, reference):
    if state.keys() != reference.keys():
        raise ValueError("candidate parameter names differ from sh02v17")
    h = sha256()
    for key in sorted(reference):
        t = state[key]
        if t.shape != reference[key].shape or t.dtype != reference[key].dtype:
            raise ValueError(f"incompatible tensor {key}")
        if not torch.isfinite(t).all():
            raise ValueError(f"nonfinite tensor {key}")
        h.update(key.encode() + b"\0")
        h.update(t.detach().contiguous().numpy().tobytes())
    return h.hexdigest()


def worker_init(weight, work):
    global db, folder, current
    game.setup(weight)
    db = sqlite3.connect(work / "trials.sqlite", timeout=90)
    folder, current = work, None


def trial(job):
    global current
    cid, digest, seed = job
    if db.execute("SELECT 1 FROM trials WHERE model=? AND seed=?", (digest, seed)).fetchone():
        return
    if current != digest:
        ck = torch.load(folder / f"c{cid:04}.pt", map_location="cpu", weights_only=True)
        if tensor_id(ck["model"], game.model.state_dict()) != digest:
            raise ValueError(f"candidate {cid} differs from its recorded parameters")
        game.model.load_state_dict(ck["model"], strict=True)
        current = digest
    row = game.evaluate(seed)
    with db:
        db.execute("INSERT INTO trials VALUES (?,?,?,?)",
                   (digest, seed, int(row["won"]), json.dumps(row)))


def observe(pool, db, candidates, seeds):
    jobs = []
    for candidate in candidates:
        done = {s for s, in db.execute("SELECT seed FROM trials WHERE model=?", (candidate["hash"],))}
        jobs.extend((candidate["id"], candidate["hash"], s) for s in seeds if s not in done)
    for _ in pool.map(trial, jobs):
        pass


def outcomes(db, candidates, seeds):
    lookup = {s: j for j, s in enumerate(seeds)}
    y = np.full((len(candidates), len(seeds)), np.nan)
    for i, c in enumerate(candidates):
        for seed, won in db.execute("SELECT seed, won FROM trials WHERE model=?", (c["hash"],)):
            if seed in lookup:
                y[i, lookup[seed]] = won
    if not np.isfinite(y).all():
        raise RuntimeError("incomplete candidate comparison")
    return y


def ck_path(work, i):
    return work / f"c{i:04}.pt"


def parent_feedback(parent, candidates, report, db, panel):
    """Only direct children of this parent, including submitted siblings."""
    scores = {c["id"]: c for c in report.get("candidates", [])}
    parent_score = scores.get(parent)
    children = []
    feedback = dict(parent_result=parent_score, panel_size=len(panel), children=children)
    seeds = set(panel)

    def trials(cid):
        rows = db.execute("SELECT seed, result FROM trials WHERE model=?", (candidates[cid]["hash"],))
        return {s: json.loads(result) for s, result in rows if s in seeds}

    parent_trials = None
    for c in candidates:
        if c["parent"] != parent:
            continue
        cid = c["id"]
        result = scores.get(cid)
        item = dict(id=cid, direction=c["direction"], result=result)
        children.append(item)
        if result is None or result["estimate"] >= parent_score["estimate"] - 1e-12:
            continue
        if parent_trials is None:
            parent_trials = trials(parent)
        child_trials = trials(cid)
        lost = sorted(s for s in seeds if parent_trials[s]["won"] and not child_trials[s]["won"])
        gained = sorted(s for s in seeds if not parent_trials[s]["won"] and child_trials[s]["won"])
        endings = Counter((child_trials[s]["reason"], child_trials[s]["screen"]) for s in lost)
        evidence = "、".join(f"{reason}/{screen} {n} 局" for (reason, screen), n in sorted(endings.items()))
        gap = 100 * (parent_score["estimate"] - result["estimate"])
        summary = (f"后验估计低于父代 {gap:.2f} 个百分点。同种子对照中，"
                   f"父胜子未胜 {len(lost)} 局，子胜父未胜 {len(gained)} 局。")
        if evidence:
            summary += f"父胜子未胜的结束原因及界面为 {evidence}。"
        item["problem_summary"] = summary
        item["parent_only_wins"] = lost
        item["child_only_wins"] = gained
    return feedback


def admit(work, req, reference, candidates, base):
    i = req["id"]
    path, meta = ck_path(work, i), work / f"c{i:04}.json"
    if meta.exists():
        record = read(meta)
        if record["request"] != req or not path.exists():
            raise ValueError(f"candidate {i} lineage or checkpoint missing/changed")
        if tensor_id(torch.load(path, weights_only=True)["model"], reference) != record["hash"]:
            raise ValueError(f"candidate {i} checkpoint changed")
        return record
    if i == 0:
        ck, note = base, "sh02v17"
    else:
        incoming = work / req["submit"]
        if not incoming.exists():
            return None
        ck = torch.load(incoming, map_location="cpu", weights_only=True)
        note = ck.get("direction")
        if not isinstance(note, str) or not note.strip():
            raise ValueError(f"candidate {i} must describe its modification in direction")
        note = note.strip()
    if ck.get("model_config") != base["model_config"]:
        raise ValueError(f"candidate {i} model_config mismatch")
    digest = tensor_id(ck["model"], reference)
    if any(c["hash"] == digest for c in candidates):
        raise ValueError(f"candidate {i} duplicates an admitted checkpoint")
    record = dict(id=i, parent=req["parent"], hash=digest, direction=note, request=req)
    tmp = path.with_suffix(".tmp")
    torch.save(dict(model=ck["model"], model_config=base["model_config"]), tmp)
    tmp.replace(path)
    write_json(meta, record)
    return record


def search(args, work):
    if sha256(args.weight.read_bytes()).hexdigest() != WEIGHT_SHA256:
        raise ValueError("expected original sh02v17 weight")
    seeds = list(range(args.seed_start, args.seed_start + args.seeds))
    if seeds[0] < 0 or seeds[-1] >= 2**48 or set(seeds).intersection(range(7540000, 7540500)):
        raise ValueError("use a separate valid development seed panel")
    game.setup(str(args.weight))
    paths = [Path(__file__), HERE / "rasch.py", Path(game.__file__),
             *(HERE.parent / "a9" / n for n in ("adapter.py", "layout.py", "loop_penalty.py")),
             Path(game.sim.__file__)]
    protocol = dict(seeds=seeds, random_seed=args.rng, initial=args.initial,
                    children=args.children, weight=WEIGHT_SHA256,
                    proposer="codex",
                    runtime={p.name: sha256(p.read_bytes()).hexdigest() for p in paths})
    manifest = work / "protocol.json"
    if manifest.exists() and read(manifest) != protocol:
        raise ValueError("run configuration, evaluator or proposer changed; choose a new run directory")
    write_json(manifest, protocol)
    base = torch.load(args.weight, weights_only=True, map_location="cpu")
    candidates, retained, extra = [], [], []
    report, panel = {}, []
    with sqlite3.connect(work / "trials.sqlite", timeout=90) as db, ProcessPoolExecutor(
            args.workers, mp_context=mp.get_context("spawn"), initializer=worker_init,
            initargs=(str(args.weight), work)) as pool:
        db.execute("PRAGMA journal_mode=WAL")
        db.execute(TRIALS)
        for rnd in range(args.rounds + 1):
            rng = np.random.default_rng(np.random.SeedSequence([args.rng, rnd]))
            parent_pool = retained + extra if rnd else [0]
            count = args.children if rnd else args.initial
            first = len(candidates)
            new = list(range(first, first + count))
            requests = []
            for slot, cid in enumerate(new):
                parent = int(rng.choice(parent_pool)) if cid else -1
                req = dict(id=cid, round=rnd, slot=slot, parent=parent,
                           parent_checkpoint=ck_path(work, parent).name if cid else None,
                           parent_pool=parent_pool if cid else [], submit=f"submit-{cid:04}.pt",
                           proposal_seed=int(rng.integers(2**31)),
                           previous_report=f"round-{rnd-1:03}.json" if rnd else None)
                if cid:
                    req["parent_feedback"] = parent_feedback(parent, candidates, report, db, panel)
                    req["instruction"] = ("请结合父权重及其已有子代的反馈，自行决定修改方向。"
                                          "在提交权重的 direction 字段记录实际改了什么，以及想验证什么。")
                requests.append(req)
                write_json(work / f"requests-{rnd:03}.json", requests)
                record = admit(work, req, base["model"], candidates, base)
                if record is None:
                    print(f"Waiting for Codex weight proposals in {work / f'requests-{rnd:03}.json'}")
                    return
                candidates.append(record)
            parents = [c["parent"] for c in candidates]
            if rnd == 0:
                observe(pool, db, candidates, seeds)
                pilot = fit(outcomes(db, candidates, seeds), parents)
                keep, prior = screen(pilot)
                panel = [seeds[i] for i in keep]
                scores = pilot.pred[:, keep].mean(axis=1)
                write_json(work / "calibration.json", dict(
                    probabilities=dict(zip(seeds, map(float, pilot.pred.mean(axis=0)))),
                    kept=panel, interval=[.15, .85]))
                np.savez(work / "calibration-prior.npz", mean=prior[0], covariance=prior[1])
            else:
                observe(pool, db, candidates[first:], panel)
                y = outcomes(db, candidates, panel)
                y[:args.initial] = np.nan  # initial observations are already in the joint prior
                scores = fit(y, parents, prior).pred.mean(axis=1)
            active = retained + new
            retained, extra = select(scores, active)
            wins = outcomes(db, candidates, panel).sum(axis=1)
            report = dict(round=rnd, active=active, retained=retained,
                          posterior_outside=extra, next_parent_pool=retained + extra,
                          seeds=len(panel), candidates=[dict(id=c["id"], parent=c["parent"],
                          wins=int(wins[i]), estimate=float(scores[i]), checkpoint=ck_path(work,i).name)
                          for i,c in enumerate(candidates)])
            write_json(work / f"round-{rnd:03}.json", report)
            print(f"round {rnd}: seeds={len(panel)} retained={retained} other={extra}", flush=True)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--weight", required=True, type=Path)
    p.add_argument("--run-dir", required=True, type=Path)
    p.add_argument("--rounds", type=int, default=2, help="total generations after calibration")
    p.add_argument("--initial", type=int, default=6, help="includes unmodified baseline")
    p.add_argument("--children", type=int, default=2)
    p.add_argument("--seed-start", type=int, default=8541000)
    p.add_argument("--seeds", type=int, default=100)
    p.add_argument("--rng", type=int, default=17)
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--manual", action="store_true", help="use Codex proposals (default)")
    a = p.parse_args()
    if a.initial < 4 or min(a.seeds, a.children, a.workers) < 1 or min(a.rounds,a.rng) < 0:
        p.error("initial >= 4; seeds, children, workers >= 1; rounds and rng >= 0")
    work = a.run_dir.resolve()
    work.mkdir(parents=True, exist_ok=True)
    with FileLock(str(work / ".search.lock"), timeout=0):
        search(a, work)


if __name__ == "__main__":
    main()

