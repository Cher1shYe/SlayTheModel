from __future__ import annotations

import json

import pytest

from deployment import run_combat_dagger_background as background


def test_progress_distinguishes_sampling_update_and_validation(tmp_path):
    progress = background.Progress(tmp_path / "progress.md", tmp_path / "train.log",
                                   start_round=6, target_round=10, games_per_round=600,
                                   initial_games=2900, simulations=1024, workers=8)
    progress.state = "运行中"
    progress.consume({"stage": "dagger", "round": 6, "stage_games": 32,
                      "total_games": 2932, "completed": 2932, "errors": 0,
                      "truncated": 0, "replay_examples": 100000})
    text = progress.path.read_text(encoding="utf-8")
    assert "第 6 轮采样：32 / 600 局" in text
    assert "已完成训练局数（含起点）：2932" in text
    progress.consume({"stage": "dagger", "round": 6, "stage_games": 600})
    assert "采样完成，正在更新网络并验证" in progress.path.read_text(encoding="utf-8")
    progress.consume({"stage": "update", "round": 6,
                      "validation": {"mean_floor": 28.0, "wins": 1,
                                     "completed": 30, "errors": 0, "truncated": 0}})
    text = progress.path.read_text(encoding="utf-8")
    assert "第 6 轮更新及验证完成，准备第 7 轮" in text
    assert "平均 28.0 层" in text


@pytest.mark.parametrize("exit_code, expected", [(0, "已完成"), (1, "失败")])
def test_wrapper_preserves_output_and_records_real_exit(tmp_path, monkeypatch, exit_code, expected):
    events = [{"stage": "dagger", "round": 10, "stage_games": 600},
              {"stage": "update", "round": 10, "validation": {"mean_floor": 25}}]

    class FakeProcess:
        pid = 1234
        stdout = [json.dumps(event) + "\n" for event in events] + ["diagnostic\n"]

        def wait(self, timeout=None):
            return exit_code

        def poll(self):
            return exit_code

    seen = []

    def popen(command, **kwargs):
        seen.append(command)
        return FakeProcess()

    monkeypatch.setattr(background.subprocess, "Popen", popen)
    progress_path, log_path = tmp_path / "progress.md", tmp_path / "train.log"
    code = background.run(progress_path=progress_path, log_path=log_path,
                          start_round=6, target_round=10, games_per_round=600,
                          initial_games=2900, simulations=1024, workers=8,
                          trainer_args=["--out-dir", str(tmp_path)])
    assert code == exit_code
    text = progress_path.read_text(encoding="utf-8")
    assert f"状态：{expected}" in text and "训练进程 PID：1234" in text
    assert f"训练进程退出码 {exit_code}" in text
    assert "diagnostic" in log_path.read_text(encoding="utf-8")
    assert seen[0][1:4] == ["-u", "-m", "agent.combat_dagger"]


def test_zero_exit_without_final_round_is_not_reported_as_completed(tmp_path, monkeypatch):
    class EarlyExit:
        pid = 1234
        stdout = ["help output\n"]

        def wait(self, timeout=None):
            return 0

        def poll(self):
            return 0

    monkeypatch.setattr(background.subprocess, "Popen", lambda *args, **kwargs: EarlyExit())
    progress = tmp_path / "progress.md"
    code = background.run(progress_path=progress, log_path=tmp_path / "train.log",
                          start_round=6, target_round=10, games_per_round=600,
                          initial_games=2900, simulations=1024, workers=8,
                          trainer_args=["--help"])
    assert code == 1
    assert "状态：未确认完成" in progress.read_text(encoding="utf-8")
