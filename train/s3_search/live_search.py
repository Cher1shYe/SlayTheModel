"""Run single-entrant, shared-seed comparisons from a completed calibration."""
import argparse
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
import json
import multiprocessing as mp
from pathlib import Path
import shutil
import sqlite3
import time

import numpy as np
from scipy.special import expit
import torch

import search as s
from live_batches import reveal_block
from rasch import fit


def sampled_strength(z, q, seed):
    rng = np.random.default_rng(seed)
    draws = z.mean + rng.standard_normal((4096, len(z.mean))) @ np.linalg.cholesky(z.cov).T
    theta = np.column_stack((np.zeros(len(draws)), draws[:, q:]))
    return theta, draws[:, :q]


def compare(ids, recall, y, parents, z, records, seeds, db, pool, rng, save, pending):
    """Freeze saturation at entry, re-rank unused seeds after every shared block."""
    pred = z.pred[ids]
    eligible = np.ones(len(seeds), dtype=bool) if recall else ~(
        (pred < .15).all(axis=0) | (pred > .85).all(axis=0))
    remaining = list(rng.permutation(np.flatnonzero(eligible)).astype(int))
    totals = np.zeros(len(ids), dtype=int)
    steps = []
    reason = "exhausted"
    while remaining:
        p = z.pred[ids]
        disagreement = 1 - p.prod(axis=0) - (1-p).prod(axis=0)
        # Evaluate a small prospective window in parallel. Only the selected
        # block below becomes evidence; scheduling cannot change any decision.
        window = sorted(remaining, key=disagreement.__getitem__, reverse=True)[:8]
        for index in window:
            for i in ids:
                key=(i,index)
                if key in pending or np.isfinite(y[i,index]):
                    continue
                pending[key]=pool.submit(s.trial,(i,records[i]["hash"],seeds[index]))
        j = int(window[0])
        for i in ids:
            future=pending.pop((i,j),None)
            if future is not None:
                future.result()
        remaining.remove(j)
        entrants = [records[i] for i in ids]

        results = s.outcomes(db, entrants, [seeds[j]])[:, 0].astype(int)
        z = reveal_block(y, parents, ids, j, results, z, save)
        if results.min() != results.max():
            totals += results
        steps.append([seeds[j], results.tolist(), totals.tolist()])
        weak = min(range(len(ids)), key=lambda n:(totals[n], z.pred[ids[n]].mean(), ids[n]))
        gaps = np.delete(totals - totals[weak], weak)
        if recall:
            if gaps[0] >= 3:
                reason = "recall_gap"
                break
        elif np.sum(1.5 ** -gaps.astype(float)) <= .25:
            reason = "strict"
            break
        elif len(steps) % 10 == 0 or not remaining:
            theta, b = sampled_strength(z,len(seeds),int(rng.integers(2**31)))
            scores = np.column_stack([expit(theta[:,i,None] - b).mean(axis=1) for i in ids])
            if np.mean(scores[:,weak] - np.delete(scores,weak,axis=1).min(axis=1) > .01) <= .2:
                reason = "tolerance"
                break
    ranked = sorted(range(len(ids)), key=lambda n:(-totals[n], -z.pred[ids[n]].mean(), ids[n]))
    kept = [ids[n] for n in ranked[:-1]]
    return kept, z, dict(ids=ids, reason=reason, eligible=int(eligible.sum()), steps=steps)


def report(y, z, records, kept):
    mean = z.pred.mean(axis=1)
    extra = sorted(set(range(len(records)))-set(kept),key=lambda i:(-mean[i],i))[:2]
    return dict(retained=kept, next_parent_pool=kept+extra, candidates=[
        dict(id=i,parent=c["parent"],wins=int(np.nansum(y[i])),games=int(np.isfinite(y[i]).sum()),
             estimate=float(mean[i])) for i,c in enumerate(records)])


def feedback(parent, records, rep, y, seeds, db):
    children=[]
    for child in records:
        if child["parent"]!=parent:
            continue
        i=child["id"]
        shared=np.isfinite(y[parent]) & np.isfinite(y[i])
        item=dict(id=i,direction=child["direction"],result=rep["candidates"][i],shared=int(shared.sum()))
        if rep["candidates"][i]["estimate"] < rep["candidates"][parent]["estimate"]-1e-12:
            lost=[seeds[j] for j in np.flatnonzero(shared & (y[parent]>y[i]))]
            gained=[seeds[j] for j in np.flatnonzero(shared & (y[parent]<y[i]))]
            reasons=Counter()
            for seed in lost:
                row=json.loads(db.execute("SELECT result FROM trials WHERE model=? AND seed=?",(child["hash"],seed)).fetchone()[0])
                reasons[row["reason"]+"/"+row["screen"]]+=1
            item.update(parent_only_wins=lost,child_only_wins=gained,
                        problem_summary=f"父胜子未胜 {len(lost)}，反向 {len(gained)}，父胜子未胜的结局 {dict(reasons)}。")
        children.append(item)
    return dict(parent_result=rep["candidates"][parent],children=children)


def run(args):
    old, work = args.calibration, args.run_dir
    protocol = s.read(old/"protocol.json")
    seeds = protocol["seeds"]
    assert len(seeds)==100 and set(seeds).isdisjoint(range(s.game.FIRST_SEED,s.game.FIRST_SEED+500))
    s.game.setup(str(args.weight))
    base=torch.load(args.weight,map_location="cpu",weights_only=True)
    records=[]
    with sqlite3.connect(work/"trials.sqlite") as db, ProcessPoolExecutor(
            args.workers,mp_context=mp.get_context("spawn"),initializer=s.worker_init,
            initargs=(str(args.weight),work)) as pool:
        db.execute("PRAGMA journal_mode=WAL")
        db.execute(s.TRIALS)
        db.execute("ATTACH DATABASE ? AS previous",(str(old/"trials.sqlite"),))
        for i in range(6):
            rec=s.read(old/f"c{i:04}.json")
            if s.tensor_id(torch.load(s.ck_path(old,i),weights_only=True)["model"],base["model"])!=rec["hash"]:
                raise ValueError("calibration weight changed")
            shutil.copyfile(s.ck_path(old,i),s.ck_path(work,i))
            s.write_json(work/f"c{i:04}.json",rec)
            db.executemany("INSERT OR IGNORE INTO trials SELECT * FROM previous.trials WHERE model=? AND seed=?",
                           [(rec["hash"],seed) for seed in seeds])
            records.append(rec)
        db.commit()
        y=s.outcomes(db,records,seeds)
        parents=[c["parent"] for c in records]
        z=fit(y,parents)
        kept=sorted(range(6),key=lambda i:(-z.pred[i].mean(),i))[:2]
        rep=report(y,z,records,kept)
        s.write_json(work/"round-000.json",rep)
        s.write_json(work/"protocol.json",dict(calibration=protocol,rounds=args.rounds,children=1,
            parent_pool=4,bounds=[.15,.85],repeat=1,strict=.25,eta=.01,alpha=.2,recall_gap=3,
            rule="full mechanism; one observation per fit; saturation frozen per main comparison"))
        with (work/"updates.jsonl").open("w",encoding="utf-8") as trace:
            pending={}
            for rnd in range(1,args.rounds+1):
                rng=np.random.default_rng(np.random.SeedSequence([17,rnd]))
                parent=int(rng.choice(rep["next_parent_pool"]))
                cid=len(records)
                req=dict(id=cid,round=rnd,parent=parent,parent_pool=rep["next_parent_pool"],
                         parent_checkpoint=s.ck_path(work,parent).name,submit=f"submit-{cid:04}.pt",
                         parent_direction=records[parent]["direction"],
                         parent_feedback=feedback(parent,records,rep,y,seeds,db))
                s.write_json(work/f"request-{rnd:03}.json",req)
                while not (rec:=s.admit(work,req,base["model"],records,base)):
                    time.sleep(.25)
                records.append(rec)
                parents.append(parent)
                y=np.vstack((y,np.full(len(seeds),np.nan)))
                z=fit(y,parents)
                def save(i,j,posterior):
                    trace.write(json.dumps(dict(round=rnd,id=i,seed=seeds[j],outcome=int(y[i,j]),
                        estimate=float(posterior.pred[i].mean()),observations=int(np.isfinite(y).sum())))+"\n")
                    trace.flush()
                kept,z,main=compare(kept+[cid],False,y,parents,z,records,seeds,db,pool,rng,save,pending)
                common=np.isfinite(y[kept]).all(axis=0)
                if common.any():
                    kept.sort(key=lambda i:(-y[i,common].mean(),i))
                challenges=[]
                tried=set()
                while True:
                    theta,_=sampled_strength(z,len(seeds),int(rng.integers(2**31)))
                    top=np.argsort(-theta,axis=1)[:,:2]
                    prob=np.bincount(top.ravel(),minlength=len(records))/len(theta)
                    eligible=[i for i in range(len(records)) if i not in kept and i not in tried and prob[i]>.2 and prob[i]>prob[kept[1]]]
                    if not eligible:
                        break
                    challenger=max(eligible,key=lambda i:(prob[i],-i))
                    tried.add(challenger)
                    winner,z,duel=compare([challenger,kept[1]],True,y,parents,z,records,seeds,db,pool,rng,save,pending)
                    kept[1]=winner[0]
                    challenges.append(duel)
                rep=report(y,z,records,kept)
                rep.update(round=rnd,main=main,recalls=challenges)
                s.write_json(work/f"round-{rnd:03}.json",rep)
                print(rnd,rep["next_parent_pool"],flush=True)
        for future in pending.values():
            future.result()
        chosen=[records[i] for i in rep["next_parent_pool"]]
        s.write_json(work/"test-selection.json",[dict(id=c["id"],hash=c["hash"]) for c in chosen])
        test=range(s.game.FIRST_SEED,s.game.FIRST_SEED+500)
        s.observe(pool,db,chosen,test)
        results=[]
        for c in chosen:
            rows=[json.loads(r) for r, in db.execute("SELECT result FROM trials WHERE model=? AND seed BETWEEN ? AND ? ORDER BY seed",(c["hash"],test.start,test.stop-1))]
            assert [r["seed"] for r in rows]==list(test)
            results.append(dict(id=c["id"],wins=sum(r["won"] for r in rows),count=len(rows),
                                reasons=dict(Counter(r["reason"] for r in rows))))
        s.write_json(work/"test-results.json",results)


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    for key in ("weight","run-dir","calibration"):
        p.add_argument("--"+key,required=True,type=Path)
    p.add_argument("--rounds",type=int,default=50)
    p.add_argument("--workers",type=int,default=8)
    a=p.parse_args()
    a.run_dir.mkdir(parents=True,exist_ok=True)
    with s.FileLock(str(a.run_dir/".search.lock"),timeout=0):
        run(a)

