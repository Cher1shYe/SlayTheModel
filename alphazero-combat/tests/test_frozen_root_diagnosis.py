from __future__ import annotations

import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from azcombat.frozen_root_diagnosis import (
    ARMS, ROOTS, _choice_context_alignment, _metrics, audit_frozen_root,
    policy_distance,
)


class FrozenRootDiagnosisTests(unittest.TestCase):
    def test_choice_context_mismatch_is_explicit_not_silently_accepted(self):
        observation = {"SchemaVersion": 3, "Choice": None}
        frame = {"Observation": observation, "TriggerCardId": "PURITY",
                 "Effect": "Exhaust", "SourcePile": "Hand", "MinCount": 0,
                 "MaxCount": 1, "Ordered": False,
                 "Candidates": [{"CombatCardIndex": 4, "ModelId": "CARD.STRIKE_IRONCLAD",
                                 "UpgradeLevel": 0, "InternalStateKey": "diagnostic-only"}],
                 "CompletedSelections": []}
        root = {"rootKind": "purity", "observation": observation,
                "choiceFrame": frame, "choiceContextAligned": False}
        self.assertFalse(_choice_context_alignment(root))
        root["choiceContextAligned"] = True
        with self.assertRaisesRegex(ValueError, "reported choice-context alignment"):
            _choice_context_alignment(root)
        root["choiceContextAligned"] = False
        root["choiceFrame"]["Candidates"] = []
        with self.assertRaisesRegex(ValueError, "verifiable pre-selection frame"):
            _choice_context_alignment(root)

    def test_policy_distance_requires_full_support(self):
        result = policy_distance([3, 1, 0], [0.5, 0.25, 0.25])
        self.assertTrue(result["top1Agrees"])
        self.assertGreater(result["klPureToPrior"], 0)
        self.assertGreater(result["js"], 0)
        with self.assertRaisesRegex(ValueError, "full legal-action support"):
            policy_distance([1, 1], [1, 0])

    def test_value_metrics_keep_battles_distinct_from_decisions(self):
        rows = [{"seed": "a", "encounter": "one", "outcome": "win",
                 "target": 0.5, "value": 0.3},
                {"seed": "a", "encounter": "one", "outcome": "win",
                 "target": 0.5, "value": 0.4},
                {"seed": "b", "encounter": "one", "outcome": "loss",
                 "target": -0.8, "value": 0.2}]
        summary = _metrics(rows)
        self.assertEqual(summary["battles"], 2)
        self.assertEqual(summary["roots"], 3)
        self.assertEqual(summary["positiveValueFailureRoots"], 1)
        self.assertAlmostEqual(summary["valueMae"], (0.2 + 0.1 + 1.0) / 3)

    def test_frozen_artifact_rejects_fabricated_counts_and_missing_guidance(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            assembly = root / "worker.dll"
            assembly.write_bytes(b"test assembly")
            digest = hashlib.sha256(assembly.read_bytes()).hexdigest()
            observation = {"SchemaVersion": 3, "Choice": None}
            observation_json = json.dumps(observation, separators=(",", ":"))
            arms = []
            for mode in ARMS:
                pure = mode == "pure-mcts"
                guided_prior = mode.startswith("model-prior")
                guided_value = mode.endswith("model-value")
                evaluator = 0 if pure else 3
                inference = evaluator if guided_prior or guided_value else 0
                arms.append({"mode": mode, "completedSimulations": 32,
                             "selectedActionId": "a", "rootVisits": 32 if pure else 31,
                             "actions": [{"actionId": "a", "visits": 20,
                                          "meanQ": 0.1, "bestQ": 0.2},
                                         {"actionId": "b", "visits": 12 if pure else 11,
                                          "meanQ": -0.1, "bestQ": 0.0}],
                             "networkInferenceCalls": inference,
                             "modelPriorAppliedNodes": evaluator if guided_prior else 0,
                             "modelValueBackprops": evaluator if guided_value else 0,
                             "evaluatorCalls": evaluator, "fallbackCount": 0,
                             "outcome": None, "valueTarget": None})
            identity = {"path": str(assembly), "mvid": "x", "sha256": digest}
            artifact = {"format": "azcombat.frozen-root-policy-value-diagnosis.v1",
                        "status": "complete", "searchOnly": True,
                        "rootTerminal": False,
                        "trajectoryOutcome": None, "trajectoryValueTarget": None,
                        "rootKind": "ordinary", "seed": ROOTS["ordinary"],
                        "regressionOnly": True, "stateKey": "frozen-key",
                        "model": {"sha256": "f" * 64}, "maxDepth": 200,
                        "maxSimulations": 32, "legalActionIds": ["a", "b"],
                        "observation": observation,
                        "observationSha256": hashlib.sha256(observation_json.encode()).hexdigest(),
                        "rootModel": {"outsideSearch": True, "logits": [1, 0],
                                      "prior": [0.7, 0.3], "value": 0.2,
                                      "actionScores": [
                                          {"actionId": "a", "logit": 1, "prior": 0.7},
                                          {"actionId": "b", "logit": 0, "prior": 0.3}]},
                        "assemblies": {name: identity for name in
                                       ("nativeWorker", "search", "combatSolver")},
                        "arms": arms}
            path = root / "diagnostic.json"
            path.write_text(json.dumps(artifact), encoding="utf-8")
            self.assertEqual(audit_frozen_root(path, "f" * 64)["legalActions"], 2)
            artifact["arms"][1]["actions"][1]["visits"] = 12
            path.write_text(json.dumps(artifact), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "arm accounting"):
                audit_frozen_root(path, "f" * 64)
            artifact["arms"][1]["actions"][1]["visits"] = 11
            artifact["arms"][1]["modelValueBackprops"] = 0
            path.write_text(json.dumps(artifact), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "guidance counters"):
                audit_frozen_root(path, "f" * 64)


if __name__ == "__main__":
    unittest.main()
