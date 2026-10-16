"""Compare serial and persistent multiprocess sampling on identical jobs."""

import argparse
import gc
import json
from pathlib import Path
import sys
from time import perf_counter

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sts2_env.search.batch import SearchJob, SearchPool, run_job


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workers", type=int, nargs="+", default=[4])
    parser.add_argument("--sims", type=int, default=256)
    parser.add_argument("--depth", type=int, default=40)
    parser.add_argument("--seeds", type=int, default=6)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.seeds < 1 or args.sims < 1 or args.depth < 0 or any(w < 1 for w in args.workers):
        parser.error("workers, seeds, sims must be positive; depth must be nonnegative")
    jobs = [SearchJob(seed, advance, args.sims, args.depth, seed + 999)
            for seed in range(args.seeds) for advance in (0, 8)]
    rows = []
    # Include scenario setup, task/result serialization and GC in batch timing.
    gc.collect()
    start = perf_counter()
    reference = [run_job(job) for job in jobs]
    serial_seconds = perf_counter() - start
    total_sims = sum(result["simulations"] for result in reference)
    rows.append(dict(workers=1, seconds=serial_seconds,
                     sims_per_second=total_sims / serial_seconds, speedup=1.0))
    print(json.dumps(rows[-1]), flush=True)
    for workers in args.workers:
        with SearchPool(workers) as pool:
            start = perf_counter()
            results = pool.run(jobs)
            seconds = perf_counter() - start
            for a, b in zip(reference, results):
                for key in ("action", "simulations", "clones", "tree_digest"):
                    if a[key] != b[key]:
                        raise AssertionError(f"Serial/parallel mismatch: {key}")
            rows.append(dict(workers=workers, seconds=seconds,
                             sims_per_second=total_sims / seconds,
                             speedup=serial_seconds / seconds,
                             startup_seconds=pool.startup_seconds,
                             tree_equivalence=True))
            print(json.dumps(rows[-1]), flush=True)
    report = dict(jobs=len(jobs), simulations_per_job=args.sims,
                  rollout_depth=args.depth, total_simulations=total_sims, results=rows)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
