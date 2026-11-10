"""Run existing simulator regressions without rewriting archived results."""
from pathlib import Path
import argparse
import json
import os
import subprocess
import sys
import time

port = Path(__file__).resolve().parents[2]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--out-dir", type=Path, default=port / "validation/local-check")
parser.add_argument("--legacy-adapters", action="store_true", help="Also check old ArmG adapters; requires PyTorch")
args = parser.parse_args()
out = args.out_dir.resolve()
out.mkdir(parents=True, exist_ok=True)
env = dict(os.environ)
env["PYTHONPATH"] = os.pathsep.join([str(port / "simulator"), str(port), env.get("PYTHONPATH", "")])
env["STS2_PORT_ROOT"] = str(port)
results = []


def run(name, command, timeout=180):
    started = time.monotonic()
    try:
        p = subprocess.run(command, cwd=port, env=env, capture_output=True, text=True, timeout=timeout)
        text = p.stdout + p.stderr
        code = p.returncode
    except (OSError, subprocess.TimeoutExpired) as exc:
        text, code = str(exc), -1
    (out / (name + ".txt")).write_text(text)
    results.append({"name": name, "command": command, "exit_code": code,
                    "wall_seconds": round(time.monotonic() - started, 3)})
    print(name, "PASS" if code == 0 else "FAIL", flush=True)


for source in sorted((port / "simulator/tests").glob("*.cpp")):
    run("cpp-" + source.stem, [str(port / "validation" / source.stem)])
python_tests = [
    "tests/test_content.py", "tests/test_binding_schema_contract.py",
    "tests/test_native_act_context.py", "tests/test_native_seed_identity.py",
    "tests/test_native_step1_state.py",
]
if args.legacy_adapters:
    python_tests += ["tests/test_engine_checkpoint_identity.py", "tests/test_armg_features.py"]
run("python-interface", [sys.executable, "-m", "pytest", "-q", *python_tests], timeout=300)
run("bench-1000", [str(port / "validation/bench"), "run", "1000"], timeout=180)
(out / "summary.json").write_text(json.dumps({
    "scope": "Existing C++ regressions, Python interface selection and greedy smoke; excludes strict NoSL audit and native DLL parity",
    "python": sys.executable,
    "passed": sum(r["exit_code"] == 0 for r in results),
    "failed": sum(r["exit_code"] != 0 for r in results),
    "results": results,
}, indent=2) + "\n")
sys.exit(1 if any(r["exit_code"] != 0 for r in results) else 0)
