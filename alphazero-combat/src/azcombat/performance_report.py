"""Read-only wall-clock simulations/s report for uncapped Native probe decisions."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import statistics

from .native_probe import audit_probe


def _decision_metrics(path: Path, expected_count: int) -> list[dict]:
    first_line = path.read_text(encoding="utf-8").splitlines()[0]
    provenance = json.loads(first_line).get("provenance", {})
    metrics = provenance.get("decisionMetrics")
    if not isinstance(metrics, list) or len(metrics) != expected_count:
        raise ValueError("decision metrics are not aligned with performance decisions")
    return metrics


def summarize(directory: Path) -> dict:
    rows = []
    for path in sorted(directory.glob("*.jsonl")):
        saved = json.loads(path.with_suffix(".probe.json").read_text(encoding="utf-8"))
        if saved.get("status") != "complete" or saved.get("maxSimulations") is not None:
            raise ValueError(f"performance input is incomplete or capped: {path}")
        # A later ExportRelease can replace the shared stage DLLs. The archived
        # worker log and every sample still must agree; current disk is not the
        # binary that an earlier run loaded.
        actual = audit_probe(path, expected=saved, verify_current_assembly=False)
        choice_layers = {item["index"]: item["choiceLayer"] for item in actual["choiceRows"]}
        if len(actual["simulations"]) != actual["samples"]:
            raise ValueError("per-decision performance counts are missing")
        metrics = _decision_metrics(path, actual["samples"])
        for index, (simulations, elapsed, metric) in enumerate(zip(
                actual["simulations"], actual["elapsedMilliseconds"], metrics, strict=True)):
            rows.append({"run": path.name, "mode": saved["requestedSearchMode"],
                         "kind": "choice" if index in choice_layers else "ordinary",
                         "choiceLayer": choice_layers.get(index, 0),
                         "simulations": simulations, "elapsedMilliseconds": elapsed,
                         "simulationsPerSecond": simulations / (elapsed / 1000),
                         "priorCalls": metric["networkPriorCalls"],
                         "valueCalls": metric["networkValueCalls"],
                         "fallbacks": metric["networkFallbacks"]})
    if not rows:
        raise ValueError("no uncapped performance decisions")
    groups = []
    for mode, kind in sorted({(row["mode"], row["kind"]) for row in rows}):
        rates = sorted(row["simulationsPerSecond"] for row in rows
                       if row["mode"] == mode and row["kind"] == kind)
        groups.append({"mode": mode, "kind": kind, "count": len(rates),
                       "minimum": rates[0], "median": statistics.median(rates),
                       "maximum": rates[-1], "everyDecisionAtLeast100": rates[0] >= 100})
    return {"format": "azcombat.native-performance.v1", "source": str(directory.resolve()),
            "budgetBasis": "simulations / full decision elapsedMilliseconds",
            "assemblyEvidence": "archived worker log and JSONL provenance; current stage DLLs may be newer",
            "thresholdSimulationsPerSecond": 100, "decisions": rows, "groups": groups}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()
    if args.report.exists():
        raise FileExistsError(args.report)
    report = summarize(args.directory)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    with args.report.open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report["groups"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
