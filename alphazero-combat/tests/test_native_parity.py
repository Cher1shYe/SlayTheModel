from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import torch

from azcombat.native_parity_cli import verify
from azcombat.samples import write_jsonl
from azcombat.training import CombatDataset, TrainConfig, encode_actions, encode_observation, load_checkpoint, train
from test_training import sample


class NativeParityTests(unittest.TestCase):
    def test_requires_same_visited_action_and_value(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            jsonl, checkpoint, stdout = (root / name for name in ("data.jsonl", "model.pt", "stdout.txt"))
            records = [sample("one"), sample("two")]
            write_jsonl(records, jsonl)
            train(CombatDataset([jsonl]), checkpoint, TrainConfig(epochs=1, hidden=16))
            model, _ = load_checkpoint(checkpoint)
            lines = []
            for index, record in enumerate(records):
                ids, actions = encode_actions(record)
                with torch.no_grad():
                    logits, value = model(*encode_observation(record), actions)
                selected = ids[max(range(len(ids)), key=lambda pos: float(logits[pos]))]
                lines.append(f"SLAY_WORKER_ALPHAZERO decision={index} shadow=True model-root:{selected} value={float(value):.6f}")
            stdout.write_text("\n".join(lines), encoding="utf-8")
            self.assertEqual(verify(checkpoint, jsonl, stdout)["samples"], 2)
            stdout.write_text("\n".join(lines).replace("model-root:play", "model-root:illegal"), encoding="utf-8")
            with self.assertRaises(ValueError):
                verify(checkpoint, jsonl, stdout)


if __name__ == "__main__":
    unittest.main()
