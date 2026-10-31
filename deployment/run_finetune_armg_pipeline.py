"""Fine-tune a backed-up ArmG and then evaluate it on paired new games.

This is a local background wrapper, not reinforcement learning.  It never
changes the input checkpoint or sampled data, and cannot start evaluation
unless fine-tuning finishes and its checkpoint provenance matches the backup.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _read(path):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def _write(path, data):
    tmp = path.with_name(path.name + ".tmp")
    try:
        tmp.write_text(data, encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass


def run(*, checkpoint, sources, root_dir, epochs=3, lr=1e-5, kl_weight=1.0,
        games=100, workers=8, simulations=2000, boss_simulations=10000,
        max_steps=5000, seed=20261030):
    if min(epochs, games, workers, simulations, boss_simulations, max_steps) < 1 or lr <= 0 or kl_weight < 0:
        raise ValueError("invalid pipeline settings")
    checkpoint = Path(checkpoint).resolve(strict=True)
    sources = [Path(x).resolve(strict=True) for x in sources]
    if not sources:
        raise ValueError("at least one source dataset is required")
    extension = os.environ.get("STS2_PRIOR_PYD")
    if not extension or not Path(extension).resolve(strict=True).is_file():
        raise ValueError("STS2_PRIOR_PYD must name the isolated simulator extension")
    extension = Path(extension).resolve()
    root = Path(root_dir).resolve()
    root.mkdir(parents=True, exist_ok=False)
    original_sha, extension_sha = _sha(checkpoint), _sha(extension)
    finetune, evaluation = root / "finetune", root / "evaluation"
    config = {"baseline": str(checkpoint), "baseline_sha256": original_sha,
              "sources": [str(x) for x in sources], "simulator": str(extension),
              "simulator_sha256": extension_sha, "epochs": epochs, "lr": lr,
              "kl_weight": kl_weight, "evaluation_games_per_arm": games,
              "workers": workers, "simulations_per_decision": simulations,
              "boss_simulations_per_decision": boss_simulations, "max_steps": max_steps,
              "seed": seed, "created_utc": datetime.now(timezone.utc).isoformat()}
    (root / "config.json").write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    state = {"state": "running", "stage": "starting", "wrapper_pid": os.getpid(),
             "child_pid": None, "child_progress": None, "baseline": str(checkpoint),
             "baseline_sha256": original_sha, "config_path": str(root / "config.json"),
             "started_utc": datetime.now(timezone.utc).isoformat()}

    def save():
        state["updated_utc"] = datetime.now(timezone.utc).isoformat()
        _write(root / "progress.json", json.dumps(state, ensure_ascii=False, indent=2, allow_nan=False))
        child = state.get("child_progress") or {}
        lines = ["# 原 ArmG 后训练和对比进度", "", f"- 状态：{state['state']}",
                 f"- 阶段：{state['stage']}", f"- 模型备份：`{checkpoint}`",
                 f"- 更新时间（UTC）：{state['updated_utc']}"]
        if state["stage"] == "finetune":
            lines.append(f"- 后训练 epoch：{child.get('epoch', 0)} / {epochs}")
            if child.get("validation_loss_before") is not None:
                lines.append(f"- 后训练前验证先验交叉熵：{child['validation_loss_before']:.4f}")
            validation = child.get("validation") or {}
            if validation.get("site_cross_entropy") is not None:
                lines.append(f"- 最近验证先验交叉熵：{validation['site_cross_entropy']:.4f}")
        if state["stage"] == "evaluation":
            lines.append(f"- 评测已完成：{child.get('completed_jobs', 0)} / {2*games} 局")
            for arm, name in (("baseline", "原 ArmG"), ("candidate", "后训练 ArmG")):
                summary = (child.get("arms") or {}).get(arm) or {}
                if summary.get("mean_floor_completed") is not None:
                    lines.append(f"- {name}中途平均：{summary['mean_floor_completed']:.2f} 层（{summary['completed']} 局）")
            lines.append("- 中途平均可能受完成顺序影响，请以全部种子配对的结果为准。")
        if state["state"] == "completed":
            for arm, name in (("baseline", "原 ArmG"), ("candidate", "后训练 ArmG")):
                summary = (state.get("final_arms") or {}).get(arm) or {}
                if summary.get("mean_floor_completed") is not None:
                    lines.append(f"- {name}平均：{summary['mean_floor_completed']:.2f} 层（{summary['completed']} 局；通关 {summary['wins']} 局）")
            paired = state.get("final_paired") or {}
            if paired.get("mean_floor_difference") is not None:
                lines.append(f"- 配对平均层数差：{paired['mean_floor_difference']:+.2f} 层（{paired['complete_pairs']} 对）")
            if state.get("evaluation_summary"):
                lines.append(f"- 完整评测：`{state['evaluation_summary']}`")
        if state.get("stage_log"):
            lines.append(f"- 阶段日志：`{state['stage_log']}`")
        if state.get("candidate"):
            lines.append(f"- 后训练模型：`{state['candidate']}`")
        if state.get("error"):
            lines.append(f"- 错误：{state['error']}")
        lines.extend(["", f"评测使用 oracle 纯 MCTS：普通 {simulations} 次、Boss {boss_simulations} 次；不复用后续路径。", ""])
        _write(root / "progress.md", "\n".join(lines))

    env = os.environ.copy()
    env.update(PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1")
    no_window = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
    child = None

    def execute(stage, cmd, directory):
        nonlocal child
        log_path = root / (stage + ".log")
        state.update(stage=stage, child_progress=None, stage_dir=str(directory), stage_log=str(log_path))
        save()
        with log_path.open("x", encoding="utf-8", buffering=1) as log:
            child = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT, env=env, creationflags=no_window)
            state["child_pid"] = child.pid
            while child.poll() is None:
                state["child_progress"] = _read(directory / "progress.json")
                save()
                time.sleep(10)
            code = child.wait()
        result = _read(directory / "progress.json")
        state.update(child_progress=result, child_pid=None)
        save()
        if code or not result or result.get("state") != "completed":
            raise RuntimeError(f"{stage} did not complete successfully (exit={code}); see {log_path}")
        return result

    try:
        save()
        prior_cmd = [sys.executable, "-u", "-m", "deployment.finetune_armg_prior",
                     "--checkpoint", str(checkpoint), "--sources", *(str(x) for x in sources),
                     "--out-dir", str(finetune), "--epochs", str(epochs), "--lr", str(lr),
                     "--kl-weight", str(kl_weight), "--seed", str(seed)]
        result = execute("finetune", prior_cmd, finetune)
        candidate = finetune / "finetuned.pt"
        provenance = _read(finetune / "config.json") or {}
        if (_sha(checkpoint) != original_sha or _sha(extension) != extension_sha or
                provenance.get("checkpoint_sha256") != original_sha or
                result.get("stage") != "completed" or not candidate.is_file() or candidate.stat().st_size == 0):
            raise RuntimeError("fine-tuning output/provenance does not match the backup; evaluation not started")
        state["candidate"], state["candidate_sha256"] = str(candidate), _sha(candidate)
        eval_cmd = [sys.executable, "-u", "-m", "deployment.evaluate_armg_checkpoints",
                    "--baseline", str(checkpoint), "--candidate", str(candidate),
                    "--out-dir", str(evaluation), "--count", str(games), "--workers", str(workers),
                    "--simulations", str(simulations), "--boss-simulations", str(boss_simulations),
                    "--max-steps", str(max_steps), "--search-seed", str(seed)]
        execute("evaluation", eval_cmd, evaluation)
        report = _read(evaluation / "summary.json") or {}
        report_config = report.get("config") or {}
        if (report.get("state") != "completed" or (report.get("paired") or {}).get("complete_pairs") != games or
                (report_config.get("sha256") or {}).get("baseline") != original_sha or
                (report_config.get("sha256") or {}).get("candidate") != state["candidate_sha256"] or
                report_config.get("simulator_sha256") != extension_sha or _sha(checkpoint) != original_sha):
            raise RuntimeError("evaluation output, simulator or checkpoint provenance does not match")
        state.update(state="completed", stage="completed", evaluation_summary=str(evaluation / "summary.json"),
                     final_arms=report.get("arms"), final_paired=report.get("paired"))
        save()
        return state
    except BaseException as exc:
        if child is not None and child.poll() is None:
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(child.pid), "/T", "/F"], stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, creationflags=no_window, check=False)
            else:
                child.terminate()
            child.wait()
        state.update(state="failed", error=f"{type(exc).__name__}: {exc}", child_pid=None)
        save()
        raise


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--checkpoint", required=True)
    p.add_argument("--sources", nargs="+", required=True)
    p.add_argument("--root-dir", required=True)
    p.add_argument("--epochs", type=int, default=3)
    p.add_argument("--lr", type=float, default=1e-5)
    p.add_argument("--kl-weight", type=float, default=1.0)
    p.add_argument("--games", type=int, default=100)
    p.add_argument("--workers", type=int, default=8)
    p.add_argument("--simulations", type=int, default=2000)
    p.add_argument("--boss-simulations", type=int, default=10000)
    p.add_argument("--max-steps", type=int, default=5000)
    p.add_argument("--seed", type=int, default=20261030)
    return run(**vars(p.parse_args(argv)))


if __name__ == "__main__":
    main()
