"""End-to-end fixed-job AZ throughput with cold start and sampled process-tree RAM."""
import argparse
from collections import Counter
from dataclasses import replace
import os
from pathlib import Path
import platform
import sys
import threading
from time import perf_counter, sleep
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
import psutil
import torch
from sts2_env.az.config import atomic_json, content_hash
from sts2_env.az.network import PolicyValueNetwork, save_checkpoint
from sts2_env.az.replay_buffer import episode_digest
from sts2_env.az.scenarios import load_manifest
from sts2_env.az.self_play import CollectionJob, Collector, file_digest, initialize_worker


def ready_worker(delay):
    sleep(delay)
    return os.getpid()


class MemorySampler:
    def __enter__(self):
        self.peak = 0
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()
        return self

    def run(self):
        root = psutil.Process()
        while not self.stop.is_set():
            total = 0
            for process in [root] + root.children(recursive=True):
                try:
                    total += process.memory_info().rss
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            self.peak = max(self.peak, total)
            self.stop.wait(0.02)

    def __exit__(self, *args):
        self.stop.set()
        self.thread.join()


def digest(episode):
    return episode_digest({k: v for k, v in episode.items() if k not in ("debug", "worker_pid")})


def run(output, manifest, workers=(1, 4, 8), episodes=16, simulations=64, seed=42):
    output = Path(output).resolve()
    if output.exists() and any(output.iterdir()):
        raise ValueError("Benchmark requires an empty directory")
    recipes = [r for r in load_manifest(manifest) if r.split == "train"]
    if episodes < max(workers) or episodes > len(recipes):
        raise ValueError("Need at least one episode per worker and enough train recipes")
    initialize_worker()
    torch.manual_seed(seed)
    checkpoint = output / "initial.pt"
    save_checkpoint(checkpoint, PolicyValueNetwork("observable"), "benchmark", {}, {})
    jobs = [CollectionJob(str(i), 0, seed, recipe.to_dict(), str(checkpoint), file_digest(checkpoint),
            "benchmark", str(output / "errors"), simulations) for i, recipe in enumerate(recipes[:episodes])]
    reference, rows = None, []
    for count in workers:
        with MemorySampler() as memory:
            started = perf_counter()
            with Collector(count) as collector:
                # Spawn and initialize workers; each handshake deliberately yields to its peers.
                pids = set(collector.pool.map(ready_worker, [0.2] * count))
                startup = perf_counter() - started
                started = perf_counter()
                cold = collector.collect(jobs)
                cold_seconds = perf_counter() - started
                started = perf_counter()
                warm = collector.collect(jobs)
                seconds = perf_counter() - started
                labels = [digest(e) for e in warm]
                if labels != [digest(e) for e in cold] or (reference is not None and labels != reference):
                    raise AssertionError("Worker scheduling changed search labels")
                reference = labels
        decisions = sum(len(e["rows"]) for e in warm)
        sims = sum(r["search_simulations"] for e in warm for r in e["rows"])
        latencies = [r["search_seconds"] for e in warm for r in e["rows"]]
        row = dict(workers=count, startup_seconds=startup, cold_collection_seconds=cold_seconds,
                   warm_collection_seconds=seconds, decisions=decisions, simulations=sims,
                   simulations_per_second=sims / seconds, decisions_per_second=decisions / seconds,
                   episodes_per_second=episodes / seconds, decision_seconds_p50=float(np.percentile(latencies, 50)),
                   decision_seconds_p95=float(np.percentile(latencies, 95)), peak_process_tree_rss_bytes=memory.peak,
                   actual_worker_pids=sorted({e["worker_pid"] for e in warm}), labels_identical=True,
                   outcomes=dict(Counter(e["rows"][0]["termination_reason"] for e in warm)))
        rows.append(row)
        atomic_json(output / "report.json", dict(information_mode="observable", episodes=episodes,
                    simulations_per_decision=simulations, master_seed=seed, results=rows,
                    checkpoint_sha256=file_digest(checkpoint), manifest_sha256=file_digest(manifest),
                    job_hash=content_hash([j.scenario for j in jobs]), python=platform.python_version(),
                    torch=str(torch.__version__), cpu_count=os.cpu_count(),
                    memory_method="20ms sampled sum of parent and recursive child RSS; shared pages counted per process",
                    timing_scope="complete episodes incl setup, model load on cold pass, search, execution, IPC; pool startup separate"))
        print(row, flush=True)
    return rows


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="output/az_m5_benchmark")
    parser.add_argument("--manifest", default="data/az/m0_manifest.json")
    parser.add_argument("--workers", nargs="+", type=int, default=[1, 4, 8])
    parser.add_argument("--episodes", type=int, default=16)
    parser.add_argument("--simulations", type=int, default=64)
    parser.add_argument("--seed", type=int, default=42)
    run(**vars(parser.parse_args()))
