"""Synchronous, least-privilege Claude delegation; completion still needs Codex review."""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import uuid


ROOT = Path(__file__).resolve().parents[1]
SECTIONS = ("Goal", "Scope", "Acceptance criteria", "Forbidden")
WRITE_TOOLS = "Read,Edit,Write,Glob,Grep"
READ_TOOLS = "Read,Glob,Grep"


def parse_task(task):
    sections = {}
    for match in re.finditer(r"^## (.+?)\s*\n(.*?)(?=^## |\Z)", task, re.M | re.S):
        name, body = match.group(1).strip(), match.group(2).strip()
        if name in sections:
            raise ValueError(f"Duplicate section: {name}")
        sections[name] = body
    for name in SECTIONS:
        if not sections.get(name):
            raise ValueError(f"Task requires a nonempty '## {name}' section")
    lines = [line for line in sections["Acceptance criteria"].splitlines() if line.strip()]
    if any(not line.startswith("- ") or not line[2:].strip() for line in lines):
        raise ValueError("Every acceptance criterion must be a nonempty '- ' bullet point")
    criteria = [line[2:].strip() for line in lines]
    if not criteria:
        raise ValueError("Acceptance criteria must contain '- ' bullet points")
    return criteria


def claude_command():
    # Execute the native binary directly: never interpolate task text into a shell.
    native = shutil.which("claude.exe")
    if native:
        return [native]
    launcher = shutil.which("claude")
    if launcher:
        path = Path(launcher)
        if os.name == "nt" and path.suffix.lower() in (".cmd", ".bat", ".ps1"):
            npm_native = path.parent / "node_modules/@anthropic-ai/claude-code/bin/claude.exe"
            if npm_native.is_file():
                return [str(npm_native)]
            raise RuntimeError("Only a Windows shell shim was found; install/expose the native claude.exe")
        return [launcher]
    raise RuntimeError("Claude CLI not found on PATH")


def build_prompt(task, criteria, read_only, cwd):
    checklist = "\n".join(f"C{i}: {item}" for i, item in enumerate(criteria, 1))
    return f"""You are Claude Code, the executor of a task delegated by Codex.
Codex retains architecture, integration, acceptance and final delivery authority.
Working directory: {cwd}
Complete only the task below. Existing unrelated changes belong to the user.
Do not undo them. Do not commit, merge, push, delete data, change permissions,
access credentials, install dependencies, invoke other agents, or run shell/code.
Use only the explicitly available file tools. Stay within the stated scope.
Do not modify AGENTS.md, Claude settings, tool configuration, or .handoffs/.
If blocked, report the exact reason; never bypass restrictions or claim completion.
{"READ ONLY: do not modify any file." if read_only else "Edit only files explicitly allowed by Scope."}
Task:
<delegated_task>
{task}
</delegated_task>
Acceptance checklist:
{checklist}

Your final response MUST be a single JSON object (no Markdown fences):
{{"status":"completed|partial|blocked|failed", "summary":"nonempty description",
"changed_files":[], "checks":[{{"id":"C1","passed":true,"evidence":"specific evidence"}}],
"remaining_work":[]}}
Include one check for EVERY checklist ID. Use actual JSON booleans.
Use completed only if ALL criteria are fully met and remaining_work is empty.
If a required test cannot be run with available tools, report partial/blocked.
List every changed path. Codex will independently inspect the diff and test results.
"""


def validate_output(returncode, raw, criteria, read_only):
    if returncode != 0:
        raise ValueError(f"Claude exited with code {returncode}")
    outer = json.loads(raw)
    if not isinstance(outer, dict) or outer.get("is_error") is not False:
        raise ValueError("Claude JSON is_error must explicitly be false")
    if outer.get("type") != "result" or outer.get("subtype") != "success":
        raise ValueError("Claude did not emit a successful terminal result")
    if outer.get("permission_denials"):
        raise ValueError("Claude reported denied tool calls; review required")
    result = outer.get("result")
    if not isinstance(result, str) or not result.strip():
        raise ValueError("Claude result is empty or not a string")
    completion = json.loads(result)
    if not isinstance(completion, dict) or completion.get("status") != "completed":
        raise ValueError("Executor did not explicitly report completed")
    if not isinstance(completion.get("summary"), str) or not completion["summary"].strip():
        raise ValueError("Completion summary is empty")
    if completion.get("remaining_work") != []:
        raise ValueError("Executor has missing or outstanding work")
    changed = completion.get("changed_files")
    if not isinstance(changed, list) or any(not isinstance(p, str) or not p.strip() for p in changed):
        raise ValueError("changed_files must be an explicit list of paths")
    if read_only and changed:
        raise ValueError("Read-only executor reported file modifications")
    checks = completion.get("checks")
    expected = {f"C{i}" for i in range(1, len(criteria) + 1)}
    if not isinstance(checks, list) or len(checks) != len(expected):
        raise ValueError("Missing or duplicate acceptance checks")
    seen = set()
    for check in checks:
        if not isinstance(check, dict) or not isinstance(check.get("id"), str):
            raise ValueError("Malformed acceptance check")
        seen.add(check["id"])
        if check.get("passed") is not True or not isinstance(check.get("evidence"), str) or not check["evidence"].strip():
            raise ValueError("Acceptance criterion failed or lacks evidence")
    if seen != expected:
        raise ValueError("Acceptance check IDs do not match the task")
    return completion


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("task", type=Path, help="UTF-8 Markdown task with four required sections")
    parser.add_argument("--cwd", type=Path, default=ROOT, help="Executor working directory inside this workspace")
    parser.add_argument("--read-only", action="store_true", help="Expose only Read, Glob and Grep")
    parser.add_argument("--timeout", type=int, default=600, help="Synchronous call timeout in seconds")
    args = parser.parse_args(argv)
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    run = ROOT / ".handoffs" / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ") + "-" + uuid.uuid4().hex[:8])
    run.mkdir(parents=True)
    raw, errors, completion = b"", b"", None
    status, reason, returncode = "failed", "", None
    metadata = {"task_source": str(args.task.resolve()), "read_only": args.read_only}
    try:
        task_bytes = args.task.read_bytes()
        (run / "task.md").write_bytes(task_bytes)
        task = task_bytes.decode("utf-8-sig")
        criteria = parse_task(task)
        cwd = args.cwd.resolve(strict=True)
        if not cwd.is_dir() or not cwd.is_relative_to(ROOT):
            raise ValueError("--cwd must be a directory within the workspace")
        prompt = build_prompt(task, criteria, args.read_only, cwd)
        (run / "prompt.txt").write_text(prompt, encoding="utf-8")
        allowed = READ_TOOLS if args.read_only else WRITE_TOOLS
        command = claude_command() + [
            "-p", "--output-format", "json", "--tools", allowed,
            "--allowedTools", allowed, "--permission-mode", "dontAsk",
            "--safe-mode", "--disable-slash-commands", "--no-chrome",
            "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}',
            "--no-session-persistence",
        ]
        metadata.update(command=command, cwd=str(cwd), timeout_seconds=args.timeout)
        # stdin avoids shell injection and Windows command-line length limits.
        proc = subprocess.run(command, input=prompt.encode("utf-8"), cwd=cwd,
                              capture_output=True, timeout=args.timeout, shell=False)
        raw, errors, returncode = proc.stdout, proc.stderr, proc.returncode
        completion = validate_output(returncode, raw.decode("utf-8-sig"), criteria, args.read_only)
        status = "completed_pending_codex_review"
        reason = "Executor completion checks passed; Codex must inspect diff and run tests before acceptance."
    except subprocess.TimeoutExpired as exc:
        raw, errors = exc.stdout or b"", exc.stderr or b""
        reason = f"Claude timed out after {args.timeout} seconds; completion is unverified."
    except (OSError, ValueError, RuntimeError) as exc:
        reason = f"{type(exc).__name__}: {exc}"
    finally:
        (run / "claude.raw.json").write_bytes(raw)
        (run / "stderr.log").write_bytes(errors)
        (run / "error.log").write_text("" if completion else reason + "\n", encoding="utf-8")
        metadata.update(status=status, returncode=returncode, reason=reason)
        (run / "run.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
        report = f"# Claude delegation report\n\n- Status: `{status}`\n- Process exit code: `{returncode}`\n- Codex acceptance: **pending**\n\n{reason}\n\n"
        if completion:
            report += "## Executor report (untrusted; verify independently)\n\n```json\n" + json.dumps(completion, ensure_ascii=False, indent=2) + "\n```\n"
        report += "\n## Artifacts\n\nSee task.md, prompt.txt (if generated), claude.raw.json, stderr.log, error.log and run.json.\n"
        (run / "report.md").write_text(report, encoding="utf-8")
    print(f"status={status}\nreport={run / 'report.md'}")
    if not completion:
        print(reason, file=sys.stderr)
    return 0 if completion else 1


if __name__ == "__main__":
    sys.exit(main())
