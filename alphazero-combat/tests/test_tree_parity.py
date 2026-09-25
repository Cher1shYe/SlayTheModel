from __future__ import annotations

import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import onnxruntime as ort

from azcombat.export import export_onnx
from azcombat.samples import write_jsonl
from azcombat.training import CombatDataset, TrainConfig, encode_actions, encode_observation, train
from azcombat.tree_parity import verify
from test_training import sample


class TreeParityTests(unittest.TestCase):
    def test_full_root_alignment_and_numeric_comparison(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            training_jsonl = root / "training.jsonl"
            checkpoint, onnx = root / "model.pt", root / "model.onnx"
            trajectory, native_path = root / "trajectory.jsonl", root / "native.parity.jsonl"
            records = [sample("train"), sample("validation")]
            write_jsonl(records, training_jsonl)
            train(CombatDataset([training_jsonl]), checkpoint, TrainConfig(epochs=1, hidden=16))
            manifest = export_onnx(checkpoint, onnx, records)
            decision = records[0]
            raw = decision.to_dict()
            raw["stateKey"] = "root-state-key"
            raw["provenance"] = {
                "modelLoadStatus": f"model-ready sha256={manifest['onnxSha256']}",
                "decisionMetrics": [{"parentDecision": 0, "choiceLayer": 0,
                                     "stateKey": raw["stateKey"], "searchMode": "policy-value-tree-v1",
                                     "networkPriorCalls": 2, "networkValueCalls": 2,
                                     "networkFallbacks": 0}],
            }
            trajectory.write_text(json.dumps(raw) + "\n", encoding="utf-8")
            ids, actions = encode_actions(decision)
            entities, globals_ = encode_observation(decision)
            logits, value = ort.InferenceSession(str(onnx), providers=["CPUExecutionProvider"]).run(None, {
                "entities": entities.numpy(), "globals": globals_.numpy(), "actions": actions.numpy(),
            })
            observation_json = json.dumps(raw["observation"], separators=(",", ":"))
            native = {"seed": decision.seed, "decision": 0, "choiceLayer": 0,
                      "stateKey": raw["stateKey"], "observationJson": observation_json,
                      "observationSha256": hashlib.sha256(observation_json.encode()).hexdigest(),
                      "orderedActionIds": ids, "logits": logits.tolist(), "value": float(value),
                      "outsideSearch": True}

            def save_native() -> None:
                native_path.write_text(json.dumps(native) + "\n", encoding="utf-8")

            save_native()
            self.assertEqual(verify(checkpoint, onnx, trajectory, native_path)["roots"], 1)

            native["orderedActionIds"] = ids[::-1]
            save_native()
            with self.assertRaisesRegex(ValueError, "ordered legal actions"):
                verify(checkpoint, onnx, trajectory, native_path)
            native["orderedActionIds"] = ids

            native["value"] = float(value) + 0.1
            save_native()
            with self.assertRaisesRegex(ValueError, "Native/ONNX value"):
                verify(checkpoint, onnx, trajectory, native_path)
            native["value"] = float(value)

            native["observationSha256"] = "0" * 64
            save_native()
            with self.assertRaisesRegex(ValueError, "observation hash/content"):
                verify(checkpoint, onnx, trajectory, native_path)
            native["observationSha256"] = hashlib.sha256(observation_json.encode()).hexdigest()

            raw["provenance"]["decisionMetrics"][0]["networkFallbacks"] = 1
            trajectory.write_text(json.dumps(raw) + "\n", encoding="utf-8")
            save_native()
            with self.assertRaisesRegex(ValueError, "tree guidance provenance"):
                verify(checkpoint, onnx, trajectory, native_path)


if __name__ == "__main__":
    unittest.main()
