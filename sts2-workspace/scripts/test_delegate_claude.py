"""Exercise delegation failure boundaries without contacting Claude."""

import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import delegate_claude as delegate


TASK = "## Goal\nRead README.\n## Scope\nREADME.md only.\n## Acceptance criteria\n- Summarize README.\n## Forbidden\nNo modifications.\n"


def payload(**changes):
    completion = {"status": "completed", "summary": "Read README", "changed_files": [],
                  "checks": [{"id": "C1", "passed": True, "evidence": "README project title"}],
                  "remaining_work": []}
    completion.update(changes)
    return {"type": "result", "subtype": "success", "is_error": False,
            "result": json.dumps(completion), "permission_denials": []}


class DelegationTests(unittest.TestCase):
    def test_valid_completion_is_only_pending_review(self):
        self.assertEqual(delegate.validate_output(0, json.dumps(payload()), ["one"], True)["status"], "completed")

    def test_failures_cannot_pass(self):
        cases = [(1, payload()), (0, {**payload(), "is_error": True}),
                 (0, {**payload(), "result": ""}), (0, {**payload(), "subtype": "error_max_turns"}),
                 (0, {**payload(), "permission_denials": [{"tool": "Read"}]}),
                 (0, payload(status="partial")), (0, payload(status="blocked")),
                 (0, payload(remaining_work=["unfinished"])), (0, payload(checks=[])),
                 (0, payload(checks=[{"id": "C1", "passed": "true", "evidence": "x"}])),
                 (0, payload(changed_files=["README.md"])), (0, {"result": "x"})]
        for code, body in cases:
            with self.subTest(body=body), self.assertRaises(ValueError):
                delegate.validate_output(code, json.dumps(body), ["one"], True)
        for raw in ("", "not json", "[]", json.dumps({**payload(), "result": "not json"})):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                delegate.validate_output(0, raw, ["one"], True)

    def test_duplicate_check_is_rejected(self):
        item = {"id": "C1", "passed": True, "evidence": "x"}
        with self.assertRaises(ValueError):
            delegate.validate_output(0, json.dumps(payload(checks=[item, item])), ["one", "two"], False)

    def test_task_requires_explicit_sections_and_criteria(self):
        self.assertEqual(delegate.parse_task(TASK), ["Summarize README."])
        with self.assertRaises(ValueError):
            delegate.parse_task(TASK.replace("## Forbidden", "## Other"))
        with self.assertRaises(ValueError):
            delegate.parse_task(TASK.replace("- Summarize", "Summarize"))
        with self.assertRaises(ValueError):
            delegate.parse_task(TASK.replace("- Summarize README.", "- Summarize README.\nAlso run tests."))

    def run_mock(self, root, outcome, read_only=True):
        task = root / "task.md"
        task.write_text(TASK, encoding="utf-8")
        with patch.object(delegate, "ROOT", root), patch.object(delegate, "claude_command", return_value=["claude.exe"]), patch.object(delegate.subprocess, "run") as call:
            if isinstance(outcome, Exception):
                call.side_effect = outcome
            else:
                call.return_value = subprocess.CompletedProcess([], *outcome)
            code = delegate.main([str(task), "--cwd", str(root)] + (["--read-only"] if read_only else []))
            if not isinstance(outcome, Exception):
                args, kwargs = call.call_args
                command = args[0]
                self.assertFalse(kwargs["shell"])
                self.assertEqual(command[command.index("--tools") + 1], delegate.READ_TOOLS if read_only else delegate.WRITE_TOOLS)
                self.assertEqual(command[command.index("--permission-mode") + 1], "dontAsk")
                self.assertNotIn("--dangerously-skip-permissions", command)
                self.assertNotIn("--allow-dangerously-skip-permissions", command)
        return code

    def test_artifacts_and_unique_runs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertEqual(self.run_mock(root, (0, json.dumps(payload()).encode(), b"")), 0)
            self.assertEqual(self.run_mock(root, (0, json.dumps(payload()).encode(), b""), False), 0)
            runs = list((root / ".handoffs").iterdir())
            self.assertEqual(len(runs), 2)
            for run in runs:
                for name in ("task.md", "prompt.txt", "claude.raw.json", "stderr.log", "error.log", "run.json", "report.md"):
                    self.assertTrue((run / name).is_file(), name)
                metadata = json.loads((run / "run.json").read_text(encoding="utf-8"))
                self.assertEqual(metadata["status"], "completed_pending_codex_review")
                self.assertIn("**pending**", (run / "report.md").read_text(encoding="utf-8"))

    def test_timeout_and_launch_failure_generate_failed_reports(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for exception in (subprocess.TimeoutExpired("claude", 1, output=b"partial", stderr=b"timeout"), OSError("missing executable")):
                self.assertEqual(self.run_mock(root, exception), 1)
            for run in (root / ".handoffs").iterdir():
                self.assertEqual(json.loads((run / "run.json").read_text(encoding="utf-8"))["status"], "failed")
                self.assertTrue((run / "error.log").read_text(encoding="utf-8").strip())
                self.assertTrue((run / "report.md").is_file())


if __name__ == "__main__":
    unittest.main()
