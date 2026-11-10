"""Training metrics by step: JSONL (always), TensorBoard (if installed), HTML dashboard.

x axis everywhere = training episodes started (the budget unit of the plan);
`updates` and `transitions` are logged alongside for alternative views.
"""
from __future__ import annotations

import csv
import json
import math
import time
from pathlib import Path

from .dashboard import render_dashboard

try:  # optional
    from torch.utils.tensorboard import SummaryWriter  # type: ignore
except Exception:  # pragma: no cover - tensorboard not installed
    SummaryWriter = None


class MetricsLogger:
    def __init__(self, run_dir: Path, sweet_spot: tuple[int, int], total_episodes: int, title: str):
        self.dir = Path(run_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.train_path = self.dir / "metrics.jsonl"
        self.eval_path = self.dir / "eval.jsonl"
        self.sweet_spot = sweet_spot
        self.total = total_episodes
        self.title = title
        self.tb = SummaryWriter(str(self.dir / "tensorboard")) if SummaryWriter else None

    def _append(self, path: Path, row: dict) -> None:
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, default=_jsonable) + "\n")

    def log_update(self, row: dict) -> None:
        row = {"time": time.time(), **row}
        self._append(self.train_path, row)
        if self.tb:
            step = int(row["episodes"])
            for k, v in row.items():
                if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v):
                    self.tb.add_scalar(f"train/{k}", v, step)
            self.tb.flush()
        self.render()

    def log_eval(self, row: dict) -> None:
        row = {"time": time.time(), **row}
        self._append(self.eval_path, row)
        if self.tb:
            step = int(row["episodes"])
            for k in ("win_rate", "win_rate_ci_low", "win_rate_ci_high", "floor_mean", "reach_act2", "reach_act3"):
                if k in row:
                    self.tb.add_scalar(f"{row.get('split', 'val')}/{k}", row[k], step)
            self.tb.flush()
        self.render()

    @staticmethod
    def read(path: Path) -> list[dict]:
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def export_tables(self) -> list[Path]:
        """Writes metrics.csv (one row per update) and eval.csv, then re-renders the dashboard."""
        out = []
        for src in (self.train_path, self.eval_path):
            rows = self.read(src)
            if not rows:
                continue
            keys: list[str] = []
            for r in rows:
                keys.extend(k for k in r if k not in keys)
            dst = src.with_suffix(".csv")
            with dst.open("w", encoding="utf-8", newline="") as f:
                w = csv.DictWriter(f, fieldnames=keys)
                w.writeheader()
                for r in rows:
                    w.writerow({k: ("" if r.get(k) is None else r.get(k)) for k in keys})
            out.append(dst)
        out.append(self.render())
        return out

    def render(self) -> Path:
        out = self.dir / "dashboard.html"
        payload = {
            "title": self.title, "total": self.total, "sweet": list(self.sweet_spot),
            "train": self.read(self.train_path), "eval": self.read(self.eval_path),
            "generated": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        html = render_dashboard(payload)
        tmp = out.with_suffix(".tmp")
        tmp.write_text(html, encoding="utf-8")
        tmp.replace(out)
        return out


def _jsonable(v):
    if isinstance(v, float) and not math.isfinite(v):
        return None
    if hasattr(v, "item"):
        return v.item()
    return str(v)


def wilson(wins: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return 0.0, 0.0
    p = wins / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return max(0.0, centre - half), min(1.0, centre + half)


