from __future__ import annotations

from pathlib import Path
import json
import subprocess
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from azcombat.mcts_diagnosis import run


class MctsDiagnosisStageTests(unittest.TestCase):
    def test_each_root_launch_requests_its_own_new_stage(self):
        with TemporaryDirectory() as directory:
            base = Path(directory)
            output = base / "diagnosis"
            with patch("azcombat.mcts_diagnosis.shutil.which", return_value="pwsh"), \
                    patch("azcombat.mcts_diagnosis.subprocess.run",
                          side_effect=RuntimeError("intercept")) as launch:
                with self.assertRaisesRegex(RuntimeError, "intercept"):
                    run(output, base, base)
            command = launch.call_args.args[0]
            self.assertEqual(command[command.index("-StageRoot") + 1],
                             str((output / "ordinary-profiled.stage").resolve()))
            self.assertNotIn("-SkipBuild", command)

    def test_failed_publish_keeps_run_record_without_worker_logs(self):
        with TemporaryDirectory() as directory:
            base = Path(directory)
            output = base / "diagnosis"
            failure = subprocess.CompletedProcess(["pwsh"], 1, "stage created\n", "copy failed\n")
            with patch("azcombat.mcts_diagnosis.shutil.which", return_value="pwsh"), \
                    patch("azcombat.mcts_diagnosis.subprocess.run", return_value=failure):
                with self.assertRaisesRegex(RuntimeError, "Native diagnosis failed"):
                    run(output, base, base)
            manifest = json.loads((output / "manifest.json").read_text())
            self.assertEqual(len(manifest["runs"]), 1)
            self.assertEqual(manifest["runs"][0]["exitCode"], 1)
            self.assertEqual((output / "ordinary-profiled.launcher.stderr.txt").read_text(),
                             "copy failed\n")
            self.assertFalse((output / "ordinary-profiled.worker.stdout.txt").exists())


if __name__ == "__main__":
    unittest.main()
