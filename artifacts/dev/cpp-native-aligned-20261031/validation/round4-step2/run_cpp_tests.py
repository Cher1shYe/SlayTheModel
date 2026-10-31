"""Run every compiled C++ regression and preserve each result for this round."""
from pathlib import Path
import concurrent.futures
import json
import subprocess
import time

output = Path(__file__).resolve().parent
root = output.parents[1]
logs = output / "cpp-logs"
logs.mkdir(exist_ok=True)


def run(source):
    name = source.stem
    started = time.monotonic()
    try:
        process = subprocess.run([str(root / "validation" / name)], cwd=root,
                                 capture_output=True, text=True, timeout=90)
        text = process.stdout + process.stderr
        code = process.returncode
    except subprocess.TimeoutExpired as exc:
        text, code = str(exc), "timeout"
    (logs / f"{name}.txt").write_text(text)
    row = {"name": name, "returncode": code, "seconds": time.monotonic() - started,
           "log": str((logs / f"{name}.txt").relative_to(root))}
    print(json.dumps(row), flush=True)
    return row


with concurrent.futures.ThreadPoolExecutor(max_workers=2) as workers:
    rows = list(workers.map(run, sorted((root / "simulator/tests").glob("*.cpp"))))
report = {"programs": len(rows), "failures": sum(row["returncode"] != 0 for row in rows),
          "assertions_enabled": True, "results": rows}
(output / "cpp-tests.json").write_text(json.dumps(report, indent=2) + "\n")
print(json.dumps({k: v for k, v in report.items() if k != "results"}))
raise SystemExit(bool(report["failures"]))
