"""Separate cProfile component audit; inclusive timings are not additive."""
import argparse
import cProfile
import pickle
from pathlib import Path
import pstats
import sys
from time import perf_counter
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
from sts2_env.az.config import atomic_json
from sts2_env.az.learner import Learner
from sts2_env.az.network import load_checkpoint
from sts2_env.az.replay_buffer import ReplayBuffer
from sts2_env.az.scenarios import load_manifest
from sts2_env.az.self_play import CollectionJob, collect_episode, file_digest, initialize_worker


def run(checkpoint, manifest, output, simulations=64):
    output = Path(output)
    if output.exists() and any(output.iterdir()):
        raise ValueError("Profile requires an empty output directory")
    initialize_worker()
    model, metadata = load_checkpoint(checkpoint, "observable")
    recipe = next(r for r in load_manifest(manifest) if r.split == "train")
    job = CollectionJob("profile", 0, 42, recipe.to_dict(), str(Path(checkpoint).resolve()), file_digest(checkpoint),
                        metadata["model_version"], str(output / "errors"), simulations)
    profiler = cProfile.Profile()
    episode = profiler.runcall(collect_episode, job)
    output.mkdir(parents=True, exist_ok=True)
    profiler.dump_stats(str(output / "collection.prof"))
    components = {"cloning": ("clone.py", "clone_state"), "legal_mask": ("action_space.py", "get_action_mask"),
                  "particle_sampling": ("information.py", "sample"), "network_inference": ("network.py", "predict"),
                  "particle_transition": ("information.py", "step"), "real_environment_step": ("adapter.py", "step")}
    timings = {}
    for label, (file, name) in components.items():
        rows = [value for (path, _, func), value in pstats.Stats(profiler).stats.items()
                if path.replace("\\", "/").endswith(file) and func == name]
        timings[label] = dict(calls=sum(r[1] for r in rows), self_seconds=sum(r[2] for r in rows),
                             cumulative_seconds=sum(r[3] for r in rows))
    started = perf_counter()
    encoded = pickle.dumps((job, episode))
    pickle.loads(encoded)
    serialization = perf_counter() - started
    replay = ReplayBuffer(output / "replay")
    replay.commit(episode)
    learner = Learner(model)
    started = perf_counter()
    history = learner.train(replay, np.random.default_rng(42), updates=20)
    report = dict(components=timings, ipc_payload_bytes=len(encoded),
                  ipc_serialization_roundtrip_seconds=serialization,
                  ipc_note="pickle only; pipe transport and scheduler overhead included in end-to-end benchmark",
                  training_updates=20, training_seconds=perf_counter() - started, training_history=history,
                  timing_note="cProfile adds overhead; inclusive components overlap and cannot be summed",
                  cloning_note="belief reconstruction builds fresh worlds; zero clone_state calls are expected")
    atomic_json(output / "report.json", report)
    print(report["components"], flush=True)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--checkpoint", default="output/az_m5_benchmark/initial.pt")
    p.add_argument("--manifest", default="data/az/m0_manifest.json")
    p.add_argument("--output", default="output/az_m5_profile")
    p.add_argument("--simulations", type=int, default=64)
    run(**vars(p.parse_args()))
