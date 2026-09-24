from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from azcombat.export import export_onnx
from azcombat.samples import write_jsonl
from azcombat.training import CombatDataset, TrainConfig, train
from test_training import sample


class ExportTests(unittest.TestCase):
    def test_onnx_dynamic_parity_and_refuse_overwrite(self):
        with TemporaryDirectory() as directory:
            base = Path(directory)
            data = base / "data.jsonl"
            checkpoint = base / "candidate.pt"
            output = base / "candidate.onnx"
            records = [sample("one"), sample("two")]
            write_jsonl(records, data)
            train(CombatDataset([data]), checkpoint, TrainConfig(epochs=1, hidden=16))
            manifest = export_onnx(checkpoint, output, records)
            self.assertEqual(manifest["paritySamples"], 2)
            self.assertLess(manifest["maxAbsError"], 1e-4)
            self.assertTrue(output.with_suffix(".manifest.json").is_file())
            with self.assertRaises(FileExistsError):
                export_onnx(checkpoint, output, records)


if __name__ == "__main__":
    unittest.main()
