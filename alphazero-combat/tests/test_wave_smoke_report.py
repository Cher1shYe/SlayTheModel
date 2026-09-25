from __future__ import annotations

import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from azcombat.samples import TrainingSample
from azcombat.schema import ActionNode
from azcombat.wave_smoke_report import audit_wave
from test_schema_reward import observation


_MVID = "7ff424b8-8fde-4d97-8b53-f86c544bd74e"
_HASH = "A" * 64
_MODEL_BYTES = b"test-candidate"
_MODEL_SHA = hashlib.sha256(_MODEL_BYTES).hexdigest().upper()
_ASSEMBLIES = {
    "nativeWorker": {"path": r"C:\stage\NativeWorker.dll", "mvid": _MVID, "sha256": _HASH},
    "search": {"path": r"C:\stage\Search.dll", "mvid": _MVID, "sha256": _HASH},
    "combatSolver": {"path": r"C:\stage\CombatSolver.dll", "mvid": _MVID, "sha256": _HASH},
}


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _run(base: Path, policy: str, *, actual_mode: str | None = None, simulations: int = 42,
         fallback: int = 0, regression: bool = False, invalid_policy: bool = False,
         choice: bool = False) -> dict:
    stem = policy
    jsonl = base / f"{stem}.jsonl"
    stdout = base / f"{stem}.worker.stdout.txt"
    stderr = base / f"{stem}.worker.stderr.txt"
    mode = actual_mode or ("pure-mcts" if policy == "baseline" else "policy-value-tree-v1")
    prior = 0 if policy == "baseline" or fallback else 7
    value = 0 if policy == "baseline" or fallback else 7
    provenance = {
        "seed": "seed-new", "encounter": "CULTISTS_NORMAL", "searchMode": mode,
        "requestedSearchMode": "pure-mcts" if policy == "baseline" else "policy-value-tree-v1",
        "budgetMilliseconds": 1000, "maxSimulations": 50, "modelFallbacks": fallback,
        "modelScored": prior, "modelUsed": value, "modelShadow": False,
        "modelLoadStatus": ("pure-mcts:no-model-configured" if policy == "baseline"
                            else f"model-ready path=C:\\candidate.onnx sha256={_MODEL_SHA}"),
        "regressionOnly": regression, "forcedFixtureCard": "PURITY" if regression else None,
        "decisionMetrics": [{"networkPriorCalls": prior, "networkValueCalls": value,
                             "networkFallbacks": fallback, "simulations": simulations,
                             "elapsedMilliseconds": 1005, "stateKey": "root",
                             "searchMode": mode,
                             "networkFallbackReason": "test inference failed" if fallback else None,
                             "maxSimulations": 50, "budgetMilliseconds": 1000}],
        "assemblies": _ASSEMBLIES,
    }
    raw = TrainingSample(
        "seed-new", "full_combat", observation(),
        (ActionNode("PlayCard", "play", {"CardId": "STRIKE_IRONCLAD"}),
         ActionNode("EndTurn", "end", terminal=True)),
        {"play": 42}, -0.5, "unresolved",
    ).to_dict()
    if choice:
        raw["observation"]["choice"] = {
            "triggerCardId": "BURNING_PACT", "effect": "exhaust", "sourcePile": "Hand",
            "minCount": 1, "maxCount": 1, "ordered": False,
            "candidates": [{"combatCardIndex": 3, "modelId": "STRIKE_IRONCLAD", "upgradeLevel": 0}],
            "completedSelections": [],
        }
        raw["legalActions"] = [{"kind": "NestedChoice", "actionId": "choice:0", "terminal": False}]
        raw["visitPolicy"] = {"choice:0": 42}
    raw.update({"stateKey": "root", "simulations": simulations, "provenance": provenance})
    if invalid_policy:
        raw["visitPolicy"] = {"unknown": 1}
    jsonl.write_text(json.dumps(raw) + "\n", encoding="utf-8")
    stdout.write_text("\n".join(
        f"SLAY_WORKER_ASSEMBLY label={label} path={identity['path']} mvid={_MVID} sha256={_HASH}"
        for label, identity in (("NativeWorker", _ASSEMBLIES["nativeWorker"]),
                                ("Search", _ASSEMBLIES["search"]),
                                ("CombatSolver", _ASSEMBLIES["combatSolver"]))
    ) + f"\nSLAY_WORKER_EXPORT_OUT={jsonl.resolve()}\n", encoding="utf-8")
    stderr.write_text("pure-mcts-fallback reason=test inference failed\n" if fallback else "", encoding="utf-8")
    return {
        "seed": "seed-new", "encounter": "CULTISTS_NORMAL", "scenario": "ordinary",
        "startType": "full_combat", "policy": policy, "jsonl": jsonl.name,
        "sha256": _hash(jsonl), "workerStdout": stdout.name,
        "workerStdoutSha256": _hash(stdout), "workerStderr": stderr.name,
        "exitCode": 0, "searchMode": mode, "maxSimulations": 50,
        "budgetMilliseconds": 1000,
    }


def _manifest(base: Path, entries: list[dict], **changes) -> None:
    model = base / "candidate.onnx"
    model.write_bytes(_MODEL_BYTES)
    data = {
        "format": "azcombat.wave.v2", "mode": "evaluate", "status": "complete",
        "baselineSearchMode": "pure-mcts", "candidateSearchMode": "policy-value-tree-v1",
        "maxSimulations": 50, "budgetMilliseconds": 1000,
        "decisionBudgetMilliseconds": 1000, "candidateSha256": _MODEL_SHA,
        "candidateOnnx": str(model),
        "runs": entries,
    }
    data.update(changes)
    (base / "manifest.json").write_text(json.dumps(data), encoding="utf-8")


class WaveSmokeReportTests(unittest.TestCase):
    def test_strictly_reports_pure_baseline_and_actual_tree_calls(self):
        with TemporaryDirectory() as directory:
            base = Path(directory)
            _manifest(base, [_run(base, "baseline"), _run(base, "candidate")])
            report = audit_wave(base, expected_runs=2)
            self.assertTrue(report["valid"], report["errors"])
            baseline, candidate = report["runs"]
            self.assertEqual(baseline["searchModes"], ["pure-mcts"])
            self.assertEqual(baseline["networkPriorCalls"], 0)
            self.assertEqual(candidate["networkPriorCalls"], 7)
            self.assertEqual(candidate["networkValueCalls"], 7)
            self.assertEqual(candidate["simulations"]["maximum"], 42)
            self.assertEqual(candidate["sampleCount"], 1)
            self.assertEqual(set(candidate["assemblies"]), {"NativeWorker", "Search", "CombatSolver"})

    def test_choice_observation_is_strictly_read_and_counted(self):
        with TemporaryDirectory() as directory:
            base = Path(directory)
            _manifest(base, [_run(base, "candidate", choice=True)])
            report = audit_wave(base, expected_runs=1)
            self.assertTrue(report["valid"], report["errors"])
            self.assertEqual(report["runs"][0]["choiceSamples"], 1)

    def test_mode_budget_and_fallback_are_not_successful_tree_guidance(self):
        with TemporaryDirectory() as directory:
            base = Path(directory)
            _manifest(base, [_run(base, "candidate", actual_mode="pure-mcts-fallback",
                                  simulations=51, fallback=1)], decisionBudgetMilliseconds=1100)
            report = audit_wave(base, expected_runs=1)
            self.assertFalse(report["valid"])
            failures = "\n".join(report["errors"])
            self.assertIn("fallback occurred", failures)
            self.assertIn("differs from requested", failures)
            self.assertIn("exceeds requested max", failures)
            self.assertIn("below requested budget", failures)
            self.assertEqual(report["runs"][0]["fallbackReasons"], ["test inference failed"])

    def test_per_decision_mode_and_choice_cap_cannot_hide_behind_trajectory_mode(self):
        with TemporaryDirectory() as directory:
            base = Path(directory)
            entry = _run(base, "candidate", choice=True)
            path = base / entry["jsonl"]
            raw = json.loads(path.read_text(encoding="utf-8"))
            metric = raw["provenance"]["decisionMetrics"][0]
            metric["searchMode"] = "pure-mcts-fallback"
            metric["networkFallbacks"] = 1
            metric["networkFallbackReason"] = "forced test failure"
            metric["maxSimulations"] = 49
            raw["provenance"]["modelFallbacks"] = 1
            path.write_text(json.dumps(raw) + "\n", encoding="utf-8")
            entry["sha256"] = _hash(path)
            _manifest(base, [entry])
            report = audit_wave(base, expected_runs=1)
            self.assertFalse(report["valid"])
            failures = "\n".join(report["errors"])
            self.assertIn("trajectory searchMode differs", failures)
            self.assertIn("actual per-decision searchMode differs", failures)
            self.assertIn("per-decision maxSimulations differs", failures)
            self.assertEqual(report["runs"][0]["choiceSamples"], 1)

    def test_invalid_policy_and_regression_only_are_rejected_without_filtering(self):
        for regression, invalid_policy in ((True, False), (False, True)):
            with self.subTest(regression=regression, invalid_policy=invalid_policy):
                with TemporaryDirectory() as directory:
                    base = Path(directory)
                    _manifest(base, [_run(base, "candidate", regression=regression,
                                          invalid_policy=invalid_policy)])
                    report = audit_wave(base, expected_runs=1)
                    self.assertFalse(report["valid"])
                    self.assertEqual(report["runs"][0]["rawLineCount"], 1)
                    self.assertEqual(report["runs"][0]["sampleCount"], 0)
                    self.assertIn("strict audit failed", "\n".join(report["errors"]))

    def test_manifest_hash_and_loaded_provenance_are_required(self):
        with TemporaryDirectory() as directory:
            base = Path(directory)
            entry = _run(base, "candidate")
            entry["sha256"] = "0" * 64
            _manifest(base, [entry])
            report = audit_wave(base)
            self.assertFalse(report["valid"])
            self.assertIn("JSONL SHA256 differs", "\n".join(report["errors"]))
            entry["sha256"] = _hash(base / entry["jsonl"])
            (base / entry["workerStdout"]).write_text("", encoding="utf-8")
            entry["workerStdoutSha256"] = _hash(base / entry["workerStdout"])
            _manifest(base, [entry])
            report = audit_wave(base)
            self.assertFalse(report["valid"])
            self.assertIn("loaded assembly identities", "\n".join(report["errors"]))


if __name__ == "__main__":
    unittest.main()
