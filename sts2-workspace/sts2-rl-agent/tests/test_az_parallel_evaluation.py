from pathlib import Path
import numpy as np
import pytest
import torch
from sts2_env.az.config import EpisodeLimits
from sts2_env.az.evaluation import evaluate, evaluate_parallel
from sts2_env.az.network import PolicyValueNetwork, save_checkpoint
from sts2_env.az.scenarios import starter_scenario
from sts2_env.az.self_play import Collector, initialize_worker


def test_parallel_evaluation_preserves_seed_identity_and_cache(tmp_path):
    initialize_worker()
    torch.manual_seed(42)
    model = PolicyValueNetwork("observable")
    checkpoint = tmp_path / "model.pt"
    save_checkpoint(checkpoint, model, "test", {}, {})
    recipes = [starter_scenario(i + 100, split="validation") for i in range(4)]
    limits = EpisodeLimits(4, 100)
    cache = tmp_path / "cache"
    def labels(rows):
        return [{k: v for k, v in r.items() if k != "decision_seconds"} for r in rows]
    with Collector(2) as collector:
        for budget in (0, 4):
            serial = evaluate(model, "test", recipes, budget, seed=7, limits=limits)
            parallel = evaluate_parallel(collector.pool, checkpoint, recipes, budget, 7, limits, cache)
            assert labels(serial) == labels(parallel)
            assert parallel == evaluate_parallel(collector.pool, checkpoint, recipes, budget, 7, limits, cache)
    assert len(list(cache.glob("*.json"))) == 8
    list(cache.glob("*.json"))[0].write_text('{"sha256":"wrong","result":{}}')
    with Collector(1) as collector:
        with pytest.raises(ValueError, match="Corrupted"):
            for budget in (0, 4):
                evaluate_parallel(collector.pool, checkpoint, recipes, budget, 7, limits, cache)
