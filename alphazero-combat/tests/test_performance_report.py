from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from azcombat.performance_report import summarize


class PerformanceReportTests(unittest.TestCase):
    def _write_input(self, base: Path, metrics: list[dict]) -> Path:
        path = base / "probe.jsonl"
        provenance = {"decisionMetrics": metrics}
        path.write_text("\n".join(json.dumps({"provenance": provenance})
                                  for _ in range(2)) + "\n", encoding="utf-8")
        path.with_suffix(".probe.json").write_text(json.dumps({
            "status": "complete", "maxSimulations": None,
            "requestedSearchMode": "policy-value-tree-v1",
        }), encoding="utf-8")
        return path

    def test_decision_network_counts_come_from_matching_raw_metric(self):
        with TemporaryDirectory() as directory:
            base = Path(directory)
            self._write_input(base, [
                {"networkPriorCalls": 2, "networkValueCalls": 3, "networkFallbacks": 0},
                {"networkPriorCalls": 5, "networkValueCalls": 7, "networkFallbacks": 1},
            ])
            audited = {
                "samples": 2, "choiceRows": [], "simulations": [100, 200],
                "elapsedMilliseconds": [1000, 1000],
                "priorCalls": 7, "valueCalls": 10, "fallbacks": 1,
            }
            with patch("azcombat.performance_report.audit_probe", return_value=audited) as audit:
                decisions = summarize(base)["decisions"]
            self.assertIs(audit.call_args.kwargs["verify_current_assembly"], False)

            self.assertEqual(
                [(row["priorCalls"], row["valueCalls"], row["fallbacks"])
                 for row in decisions],
                [(2, 3, 0), (5, 7, 1)],
            )

    def test_decision_metrics_must_align_with_audited_sample_count(self):
        with TemporaryDirectory() as directory:
            base = Path(directory)
            self._write_input(base, [
                {"networkPriorCalls": 2, "networkValueCalls": 3, "networkFallbacks": 0},
            ])
            audited = {
                "samples": 2, "choiceRows": [], "simulations": [100, 200],
                "elapsedMilliseconds": [1000, 1000],
                "priorCalls": 2, "valueCalls": 3, "fallbacks": 0,
            }
            with patch("azcombat.performance_report.audit_probe", return_value=audited), \
                    self.assertRaisesRegex(ValueError, "not aligned"):
                summarize(base)


if __name__ == "__main__":
    unittest.main()
