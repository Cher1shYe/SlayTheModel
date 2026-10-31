"""Run combat DAgger and write a compact, human-readable progress file.

The wrapper consumes the trainer's own per-batch JSON output; it does not
poll the process or modify the training loop. Launch it in a hidden process on
Windows and pass the trainer's original arguments after ``--``.
"""
from __future__ import annotations

import argparse
from collections import deque
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import time


_SHANGHAI = timezone(timedelta(hours=8))


def _stamp():
    return datetime.now(_SHANGHAI).strftime("%Y-%m-%d %H:%M:%S UTC+8")


class Progress:
    def __init__(self, path, log, *, start_round, target_round, games_per_round,
                 initial_games, simulations, workers):
        self.path, self.log = Path(path).resolve(), Path(log).resolve()
        self.start_round, self.target_round = start_round, target_round
        self.games_per_round, self.initial_games = games_per_round, initial_games
        self.simulations, self.workers = simulations, workers
        self.started = _stamp()
        self.state = "正在启动"
        self.detail = f"等待第 {start_round} 轮采样开始"
        self.trainer_pid = None
        self.last_batch = None
        self.last_validation = None
        self.result = None

    def consume(self, event):
        stage = event.get("stage")
        if stage in ("warmup", "dagger"):
            self.last_batch = event
            rnd = event.get("round", "?")
            n = event.get("stage_games", 0)
            if stage == "dagger" and isinstance(n, int) and n >= self.games_per_round:
                self.detail = f"第 {rnd} 轮采样完成，正在更新网络并验证"
            else:
                limit = self.games_per_round if stage == "dagger" else "初始化目标"
                self.detail = f"第 {rnd} 轮采样：{n} / {limit} 局"
        elif stage == "update":
            self.last_validation = event
            rnd = event.get("round", "?")
            if isinstance(rnd, int) and rnd < self.target_round:
                self.detail = f"第 {rnd} 轮更新及验证完成，准备第 {rnd + 1} 轮"
            else:
                self.detail = f"第 {rnd} 轮更新及验证完成，等待训练进程退出"
        self.write()

    def write(self):
        lines = ["# 战斗模型续训进度", "", f"- 状态：{self.state}",
                 f"- 当前阶段：{self.detail}",
                 f"- 续训轮次：第 {self.start_round}–{self.target_round} 轮，每轮 {self.games_per_round} 局",
                 f"- 教师 MCTS：每次 {self.simulations} 次模拟；采样 worker：{self.workers}",
                 f"- 起点：已完成 {self.initial_games} 局",
                 f"- 开始时间：{self.started}", f"- 最近更新：{_stamp()}",
                 f"- 进度进程 PID：{os.getpid()}",
                 f"- 训练进程 PID：{self.trainer_pid if self.trainer_pid is not None else '尚未启动'}",
                 f"- 完整日志：`{self.log}`"]
        if self.last_batch is not None:
            event = self.last_batch
            lines += [f"- 已完成训练局数（含起点）：{event.get('total_games', '未知')}",
                      f"- 正常结束：{event.get('completed', '未知')}；"
                      f"错误：{event.get('errors', '未知')}；截断：{event.get('truncated', '未知')}",
                      f"- 当前经验池样本：{event.get('replay_examples', '未知')}"]
        if self.last_validation is not None:
            event = self.last_validation
            val = event.get("validation", {})
            lines += [f"- 最近验证：第 {event.get('round', '?')} 轮；"
                      f"平均 {val.get('mean_floor', '未知')} 层；"
                      f"通关 {val.get('wins', '未知')} / {val.get('completed', '未知')} 局；"
                      f"错误 {val.get('errors', '未知')}、截断 {val.get('truncated', '未知')}"]
        if self.result is not None:
            lines.append(f"- 退出信息：{self.result}")
        lines += ["", "说明：进度按训练器完成的批次和验证结果更新；网络更新阶段可能数分钟不变。",
                  "检查点由训练器保存，正常结束或失败会更新本文件状态。", ""]
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        tmp.write_text("\n".join(lines), encoding="utf-8")
        os.replace(tmp, self.path)


def run(*, progress_path, log_path, start_round, target_round, games_per_round,
        initial_games, simulations, workers, trainer_args):
    if min(start_round, target_round, games_per_round, simulations, workers) < 1:
        raise ValueError("rounds, games, simulations and workers must be positive")
    if target_round < start_round or initial_games < 0:
        raise ValueError("invalid starting/target round or initial game count")
    if not trainer_args:
        raise ValueError("training arguments are required after --")
    progress = Progress(progress_path, log_path, start_round=start_round,
                        target_round=target_round, games_per_round=games_per_round,
                        initial_games=initial_games, simulations=simulations, workers=workers)
    progress.log.parent.mkdir(parents=True, exist_ok=True)
    if progress.path.exists() or progress.log.exists():
        raise FileExistsError("progress/log files already exist; use a new filename")
    progress.write()
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUNBUFFERED"] = "1"
    command = [sys.executable, "-u", "-m", "agent.combat_dagger", *trainer_args]
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
    recent = deque(maxlen=8)
    child = None
    try:
        with progress.log.open("x", encoding="utf-8", buffering=1) as log:
            child = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                     text=True, encoding="utf-8", errors="replace",
                                     env=env, creationflags=creationflags)
            progress.trainer_pid = child.pid
            progress.state = "运行中"
            progress.write()
            for line in child.stdout:
                log.write(line)
                recent.append(line.rstrip())
                try:
                    event = json.loads(line)
                except (ValueError, TypeError):
                    continue
                if isinstance(event, dict):
                    progress.consume(event)
            code = child.wait()
        confirmed = (code == 0 and progress.last_validation is not None and
                     progress.last_validation.get("round") == target_round)
        progress.state = "已完成" if confirmed else "失败" if code else "未确认完成"
        progress.result = f"训练进程退出码 {code}"
        if code == 0 and not confirmed:
            progress.detail = "训练正常退出，但未收到目标轮次的更新及验证记录"
        if code:
            progress.detail = "训练进程异常退出，请查看完整日志"
            progress.result += "; " + next((x for x in reversed(recent) if x), "无错误输出")
        progress.write()
        return code if code else 0 if confirmed else 1
    except BaseException as exc:
        if child is not None and child.poll() is None:
            child.terminate()
            child.wait(timeout=30)
        progress.state, progress.detail = "失败", "进度进程异常，请查看完整日志"
        progress.result = f"{type(exc).__name__}: {exc}"
        progress.write()
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--progress", required=True)
    parser.add_argument("--log", required=True)
    parser.add_argument("--start-round", type=int, required=True)
    parser.add_argument("--target-round", type=int, required=True)
    parser.add_argument("--games-per-round", type=int, default=600)
    parser.add_argument("--initial-games", type=int, required=True)
    parser.add_argument("--simulations", type=int, required=True)
    parser.add_argument("--workers", type=int, required=True)
    parser.add_argument("trainer_args", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    training = args.trainer_args
    if training and training[0] == "--":
        training = training[1:]
    return run(progress_path=args.progress, log_path=args.log,
               start_round=args.start_round, target_round=args.target_round,
               games_per_round=args.games_per_round, initial_games=args.initial_games,
               simulations=args.simulations, workers=args.workers, trainer_args=training)


if __name__ == "__main__":
    sys.exit(main())
