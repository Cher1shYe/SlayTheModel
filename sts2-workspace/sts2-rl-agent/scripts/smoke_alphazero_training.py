"""M3 two-round collection/training smoke; no evaluation or champion promotion."""
import argparse
from collections import Counter
from pathlib import Path
import sys
from time import perf_counter
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
import torch
from sts2_env.az.config import atomic_json, derive_seed
from sts2_env.az.learner import Learner
from sts2_env.az.network import PolicyValueNetwork, save_checkpoint
from sts2_env.az.replay_buffer import ReplayBuffer
from sts2_env.az.scenarios import load_manifest
from sts2_env.az.self_play import CollectionJob, Collector, file_digest, initialize_worker


def run(output, manifest, workers=2, episodes=4, simulations=64, updates=20, seed=42):
    root = Path(output).resolve() / "observable"
    if root.exists() and any(root.iterdir()):
        raise ValueError("Choose an empty output directory")
    recipes = [r for r in load_manifest(manifest) if r.split == "train"]
    if not 0 < episodes * 2 <= len(recipes):
        raise ValueError("Insufficient train recipes")
    initialize_worker()
    torch.manual_seed(seed)
    champion = PolicyValueNetwork("observable").eval()
    version = f"initial-{seed}"
    config = dict(workers=workers, episodes=episodes, simulations=simulations, updates=updates,
                  seed=seed, iterations=2, deterministic_algorithms=True, cpu_threads=1)
    checkpoint = root / "initial.pt"
    save_checkpoint(checkpoint, champion, version, config, {})
    replay = ReplayBuffer(root / "replay")
    rounds = []
    with Collector(workers) as collector:
        for iteration in range(2):
            jobs = [CollectionJob(str(j), iteration, seed, recipes[iteration * episodes + j].to_dict(),
                                  str(checkpoint), file_digest(checkpoint), version,
                                  str(root / "errors"), simulations) for j in range(episodes)]
            started = perf_counter()
            completed = collector.collect(jobs)
            collection_seconds = perf_counter() - started
            for episode in completed:
                replay.commit(episode)
            learner = Learner(champion)
            started = perf_counter()
            history = learner.train(replay, np.random.default_rng(derive_seed(seed, iteration, "learner", "batches")),
                                    updates=updates, batch_size=256)
            training_seconds = perf_counter() - started
            statistics = dict(iteration=iteration, replay_samples=replay.size, history=history,
                              collection_seconds=collection_seconds, training_seconds=training_seconds,
                              outcomes=dict(Counter(e["rows"][0]["termination_reason"] for e in completed)),
                              worker_pids=sorted({e["worker_pid"] for e in completed}),
                              simulations=sum(r["search_simulations"] for e in completed for r in e["rows"]),
                              decisions=sum(len(e["rows"]) for e in completed))
            save_checkpoint(root / f"candidate-{iteration}.pt", learner.model, f"candidate-{seed}-{iteration}",
                            config, statistics, iteration)
            rounds.append(statistics)
            print(f"round {iteration}: {statistics['outcomes']}, replay={replay.size}, loss={history[-1]['loss']:.4f}", flush=True)
    report = dict(stage="M3", config=config, rounds=rounds, learning_acceptance="not_evaluated",
                  promotion="not_implemented_champion_unchanged", resume_scope="replay_only",
                  torch_version=str(torch.__version__), numpy_version=np.__version__)
    atomic_json(root / "report.json", report)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="output/az_m3_smoke")
    parser.add_argument("--manifest", default="data/az/m0_manifest.json")
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--episodes", type=int, default=4)
    parser.add_argument("--simulations", type=int, default=64)
    parser.add_argument("--updates", type=int, default=20)
    parser.add_argument("--seed", type=int, default=42)
    run(**vars(parser.parse_args()))
