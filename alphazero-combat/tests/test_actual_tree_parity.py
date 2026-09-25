from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import onnxruntime as ort

from azcombat.actual_tree_parity import verify_frozen_root
from azcombat.export import export_onnx
from azcombat.samples import read_jsonl, write_jsonl
from azcombat.training import (CombatDataset, TrainConfig, encode_actions,
                               encode_observation, train)
from test_training import sample


class ActualTreeParityTests(unittest.TestCase):
    def test_tree_evaluator_uses_exact_choice_and_model_outputs(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            training = root / "training.jsonl"
            checkpoint, onnx = root / "model.pt", root / "model.onnx"
            base = sample("choice")
            choice = {
                "triggerCardId": "PURITY", "effect": "Exhaust", "sourcePile": "Hand",
                "minCount": 1, "maxCount": 1, "ordered": False,
                "candidates": [{"combatCardIndex": 3, "modelId": "STRIKE_IRONCLAD",
                                "upgradeLevel": 0}], "completedSelections": [],
            }
            raw_sample = base.to_dict()
            raw_sample["observation"]["choice"] = choice
            raw_sample["legalActions"] = [{"kind": "NestedChoice", "actionId": "choice:3",
                                           "payload": {"CardId": "PURITY", "CardOccurrence": 0,
                                                       "TargetCombatId": None,
                                                       "SelectedCards": [{"CardId": "STRIKE_IRONCLAD"}]}}]
            raw_sample["visitPolicy"] = {"choice:3": 1}
            raw_sample["provenance"] = {"regressionOnly": True, "forcedFixtureCard": "PURITY"}
            regression = root / "regression.jsonl"
            regression.write_text(json.dumps(raw_sample) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "regression-only"):
                read_jsonl(regression)
            validated = read_jsonl(regression, allow_regression=True)[0]
            write_jsonl([base, sample("other")], training)
            train(CombatDataset([training]), checkpoint, TrainConfig(epochs=1, hidden=16))
            export_onnx(checkpoint, onnx, [base, validated])
            ids, actions = encode_actions(validated)
            entities, globals_ = encode_observation(validated)
            logits, value = ort.InferenceSession(str(onnx), providers=["CPUExecutionProvider"]).run(None, {
                "entities": entities.numpy(), "globals": globals_.numpy(),
                "actions": actions.numpy(),
            })
            observation = raw_sample["observation"]
            observation_json = json.dumps(observation, separators=(",", ":"))
            native_action = {
                "Key": ids[0], "Kind": "PlayCard", "CardId": "PURITY",
                "CardOccurrence": 0, "TargetCombatId": None, "ChoiceKey": "selection",
                "SelectedCards": [{"CardId": "STRIKE_IRONCLAD"}],
            }
            trace = {
                "arm": "model-prior_model-value", "invocation": 1, "stateKey": "root:key",
                "observation": observation, "observationJson": observation_json,
                "observationSha256": hashlib.sha256(observation_json.encode()).hexdigest(),
                "orderedActionIds": ids, "legalActions": [native_action],
                "logits": logits.tolist(), "value": float(value),
                "actualTreeEvaluator": True,
            }
            frame = {
                "Observation": {**observation, "choice": None},
                "TriggerCardId": "PURITY", "Effect": "Exhaust", "SourcePile": "Hand",
                "MinCount": 1, "MaxCount": 1, "Ordered": False,
                "Candidates": [{"CombatCardIndex": 3, "ModelId": "STRIKE_IRONCLAD",
                                "UpgradeLevel": 0, "InternalStateKey": "not-public"}],
                "CompletedSelections": [],
            }
            report = {"regressionOnly": True, "searchOnly": True, "rootKind": "purity",
                      "stateKey": "root:key", "observation": observation,
                      "choiceFrame": frame, "legalActionIds": ids,
                      "liveBaseObservation": frame["Observation"],
                      "liveChoiceEvidence": {"MinCount": 1, "MaxCount": 1,
                          "Candidates": [{"CombatCardIndex": 3,
                                          "ModelId": "STRIKE_IRONCLAD", "UpgradeLevel": 0}]},
                      "liveCompletedSelections": [], "exportObservation": observation,
                      "actualTreeEvaluatorInputs": [trace, {
                          **trace, "arm": "expanded-choice-probe", "stateKey": "internal:choice"}]}
            report_path = root / "report.json"
            report_path.write_text(json.dumps(report), encoding="utf-8")
            raw_sample["stateKey"] = "root:key"
            raw_sample["legalActions"][0]["payload"] = native_action
            regression.write_text(json.dumps(raw_sample) + "\n", encoding="utf-8")
            checked = verify_frozen_root(checkpoint, onnx, report_path,
                                         export_jsonl=regression)
            self.assertEqual(checked["treeNodes"], 2)
            self.assertEqual(checked["expandedChoiceNodes"], 1)
            self.assertEqual(checked["choiceNodes"], 2)
            self.assertLessEqual(checked["maxNativeOnnxError"], 1e-5)

            bad = deepcopy(report)
            bad["actualTreeEvaluatorInputs"][0]["observation"]["choice"] = None
            report_path.write_text(json.dumps(bad), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "observation"):
                verify_frozen_root(checkpoint, onnx, report_path)
            bad = deepcopy(report)
            bad["actualTreeEvaluatorInputs"][0]["actualTreeEvaluator"] = False
            report_path.write_text(json.dumps(bad), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "tree evaluator"):
                verify_frozen_root(checkpoint, onnx, report_path)
            bad = deepcopy(report)
            bad["liveChoiceEvidence"]["Candidates"][0]["CombatCardIndex"] = 9
            report_path.write_text(json.dumps(bad), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "independent live choice"):
                verify_frozen_root(checkpoint, onnx, report_path)
            report_path.write_text(json.dumps(report), encoding="utf-8")
            raw_sample["legalActions"][0]["payload"]["SelectedCards"] = []
            regression.write_text(json.dumps(raw_sample) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "export legal action"):
                verify_frozen_root(checkpoint, onnx, report_path, export_jsonl=regression)


if __name__ == "__main__":
    unittest.main()
