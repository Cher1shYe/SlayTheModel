import json
from pathlib import Path
import subprocess
import sys

import torch

from agent.armg import ArmGScorer
from agent.armg_train import _save
from deployment import evaluate_armg_fixed_mcts as evaluation


def test_fixed_budget_disables_only_boss_multiplier(monkeypatch):
    received = []
    monkeypatch.setattr(evaluation, "_original_plan",
                        lambda *args: received.append(args) or ([(1, 2, 3, 4), (2, 3, 4, 5)], 10000))
    result = evaluation._fixed_budget_plan("battle", 5, "mcts-oracle", 10000, 0.05, True)
    assert result[1] == 10000
    assert result[0] == [(1, 2, 3, 4)]
    assert received[0] == ("battle", 5, "mcts-oracle", 10000, 0.05, False)


def test_parallel_evaluation_saves_each_episode_and_provenance(tmp_path):
    model = ArmGScorer()
    checkpoint = tmp_path / "model.pt"
    _save(checkpoint, model, torch.optim.Adam(model.parameters()),
          {"games": 17}, {"combat": "mcts-oracle"})
    output = tmp_path / "result"
    root = Path(__file__).resolve().parents[1]
    command = [sys.executable, "-m", "deployment.evaluate_armg_fixed_mcts",
               "--checkpoint", str(checkpoint), "--out-dir", str(output),
               "--seeds", "2", "--simulations", "16", "--workers", "2", "--start", "100"]
    subprocess.run(command, cwd=root, check=True, capture_output=True, timeout=100)
    config = json.loads((output / "evaluation_config.json").read_text(encoding="utf-8"))
    episodes = [json.loads(line) for line in (output / "episodes.jsonl").read_text(encoding="utf-8").splitlines()]
    summary = json.loads((output / "summary.json").read_text(encoding="utf-8"))
    assert config["boss_multiplier"] == 1 and config["simulations_per_search"] == 16
    assert config["path_cache"].startswith("disabled")
    assert config["checkpoint_progress"]["games"] == 17 and len(config["sha256"]) == 64
    assert {r["seed"] for r in episodes} == {30000100, 30000101}
    assert summary["summary"]["episodes"] == 2
    assert all(r["status"] == "terminated" for r in episodes)
    assert all(r["mcts_simulations"] == r["mcts_searches"] * 16 for r in episodes)
