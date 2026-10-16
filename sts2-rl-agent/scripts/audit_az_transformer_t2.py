"""Bounded T2 fixture audit: four decisions, two simulations/decision, one update.

No training experiment, curriculum, smoke rounds or final test set is started.
"""
from dataclasses import asdict
from pathlib import Path
import sys
import tempfile
import time
import json
import platform
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
import psutil
import torch
from sts2_env.az.config import EpisodeLimits, atomic_json, canonical_json
from sts2_env.az.model_factory import create_transformer, save_transformer_checkpoint
from sts2_env.az.self_play import CollectionJob, collect_episode, initialize_worker, file_digest
from sts2_env.az.scenarios import starter_scenario
from sts2_env.az.dynamic_search import VERSION
from sts2_env.az.entity_replay import EntityReplayBuffer, REPLAY_VERSION
from sts2_env.az.entity_encoder import SCHEMA, SCHEMA_HASH
from sts2_env.az.coordinator import Learner, save_training, restore_training
from sts2_env.az.network import code_digest


def main():
    initialize_worker()
    torch.manual_seed(17)
    process = psutil.Process()
    with tempfile.TemporaryDirectory(prefix='sts2-t2-contract-') as directory:
        root = Path(directory)
        model = create_transformer()
        checkpoint = root/'initial.pt'
        save_transformer_checkpoint(checkpoint, model, 'initial')
        job = CollectionJob('0', 0, 17, starter_scenario(2).to_dict(), str(checkpoint), file_digest(checkpoint),
                            'initial', str(root/'errors'), 2, EpisodeLimits(4, 100), search_version=VERSION)
        started = time.perf_counter()
        episode = collect_episode(job)
        collection_seconds = time.perf_counter()-started
        replay = EntityReplayBuffer(root/'replay')
        replay.commit(episode)
        resident_rss = process.memory_info().rss
        started = time.perf_counter()
        replay.release_memory()
        released_rss = process.memory_info().rss
        replay = EntityReplayBuffer(root/'replay')
        load_seconds = time.perf_counter()-started
        rng = np.random.default_rng(7)
        started = time.perf_counter()
        samples, _ = replay.sample(4, rng)
        sample_seconds = time.perf_counter()-started
        learner = Learner(model)
        started = time.perf_counter()
        history = [learner.update(samples, microbatch_size=2)]
        update_seconds = time.perf_counter()-started
        save_training(root/'training.pt', learner, rng, replay, 'candidate', {}, history, 0)
        resumed, rng2, history2 = restore_training(root/'training.pt', replay)
        assert all(torch.equal(v, resumed.model.state_dict()[k]) for k,v in learner.model.state_dict().items())
        assert rng.bit_generator.state == rng2.bit_generator.state and history == history2
        file = root/'replay/episodes'/f"{episode['episode_id']}.json.gz"
        report = dict(scope='fixed four-decision contract fixture, not a training experiment',
            schema=SCHEMA, schema_hash=SCHEMA_HASH, replay_version=REPLAY_VERSION, search_version=VERSION,
            code_digest=code_digest(), torch=str(torch.__version__), python=platform.python_version(),
            device='cpu', threads=1, tier='XS', decisions=len(episode['rows']), simulations_per_decision=2,
            episode_bytes=file.stat().st_size, bytes_per_decision=file.stat().st_size/len(episode['rows']),
            audit_and_features_json_bytes=len(canonical_json(episode).encode()),
            resident_rss=resident_rss, released_rss=released_rss,
            process_peak_working_set_bytes=getattr(process.memory_info(), 'peak_wset', None),
            collection_seconds=collection_seconds, load_seconds=load_seconds,
            load_decisions_per_second=len(episode['rows'])/load_seconds, sample_four_seconds=sample_seconds,
            update_four_microbatch_two_seconds=update_seconds,
            checkpoint_weights_optimizer_rng_reloaded=True,
            entity_lengths=[len(r['observation']['entities']) for r in episode['rows']],
            action_lengths=[len(r['policy_target']) for r in episode['rows']],
            outcome=episode['outcome'],
            caveat='Single tiny fixture. RSS includes Torch/model/allocator; release drops Replay objects but '
                   'does not promise OS memory reclamation. No production throughput or policy-quality claim.')
        target = Path(__file__).resolve().parents[1]/'docs/transformer_t2_audit.json'
        atomic_json(target, report)
        print(json.dumps({k:report[k] for k in ('decisions','episode_bytes','bytes_per_decision','load_seconds','sample_four_seconds','update_four_microbatch_two_seconds')}))


if __name__ == '__main__':
    main()
