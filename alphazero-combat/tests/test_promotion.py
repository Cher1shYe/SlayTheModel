from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from azcombat.experiments import run_wave
from azcombat.promotion import write_gate


class PromotionSafetyTests(unittest.TestCase):
    def test_selfplay_requires_champion_before_any_output(self):
        with TemporaryDirectory() as directory:
            output = Path(directory) / "new-wave"
            with self.assertRaises(ValueError):
                run_wave(mode="selfplay", output=output, game_dir=Path(directory),
                         ritsu_root=Path(directory), model=Path(directory) / "missing.onnx",
                         seeds=["a", "b"], encounters=["CULTISTS_NORMAL"])
            self.assertFalse(output.exists())

    def test_unregistered_encounter_rejected_before_any_output(self):
        with TemporaryDirectory() as directory:
            output = Path(directory) / "new-wave"
            with self.assertRaises(ValueError):
                run_wave(mode="evaluate", output=output, game_dir=Path(directory),
                         ritsu_root=Path(directory), model=Path(directory) / "missing.onnx",
                         seeds=["a", "b"], encounters=["UNKNOWN_ENCOUNTER"])
            self.assertFalse(output.exists())

    def test_denied_gate_does_not_replace_champion(self):
        with TemporaryDirectory() as directory:
            base = Path(directory)
            champion = base / "champion.json"
            report = base / "gate.json"
            champion.write_text('{"previous":"unchanged"}', encoding="utf-8")
            write_gate({"approved": False, "reasons": ["missing death evidence"]}, report, champion)
            self.assertEqual(json.loads(champion.read_text(encoding="utf-8")), {"previous": "unchanged"})
            self.assertTrue(report.is_file())
            with self.assertRaises(FileExistsError):
                write_gate({"approved": False}, report, champion)


if __name__ == "__main__":
    unittest.main()
