"""Run isolated native rule fixtures against the existing native probe assembly."""
from pathlib import Path
import hashlib
import json
import os
import subprocess
import time

here = Path(__file__).resolve().parent
workspace = Path("/Users/yebohou/SlayTheModel")
dev = workspace / "artifacts/dev/rtg-probe-20261027"
binary = here / "SimulatorAudit.app/Contents/MacOS/SimulatorAudit"
pack = Path.home() / "Library/Application Support/Steam/steamapps/common/Slay the Spire 2/SlayTheSpire2.app/Contents/Resources/Slay the Spire 2.pck"
env = {k: v for k, v in os.environ.items() if not k.startswith("STS2_")}
env.update(STS2_GAME_PACK=str(pack), STS2_AUDIT_OUT=str(here / "results.json"))
command = [str(binary), "--headless", "--path", str(here), "--log-file", str(here / "godot.log")]
start = time.perf_counter()
with (here / "stdout.log").open("w") as stdout, (here / "stderr.log").open("w") as stderr:
    try:
        result = subprocess.run(command, env=env, stdout=stdout, stderr=stderr, timeout=110)
        status = {"exit_code": result.returncode, "timed_out": False}
    except subprocess.TimeoutExpired:
        status = {"exit_code": None, "timed_out": True}
status.update(command=command, seconds=time.perf_counter()-start,
              environment={k:v for k,v in env.items() if k.startswith("STS2_")},
              harness_sha256=hashlib.sha256((here/"AuditWorker.cs").read_bytes()).hexdigest())
(here / "invocation.json").write_text(json.dumps(status, indent=2) + "\n")
print(json.dumps(status, indent=2), flush=True)
if (here / "results.json").exists():
    result = json.loads((here / "results.json").read_text())
    print(json.dumps({"status": result.get("status"), "fixtures": len(result.get("results", [])),
                      "error": result.get("error"), "results": str(here / "results.json")}), flush=True)
else:
    print((here / "stdout.log").read_text()[-2500:], flush=True)
    print((here / "stderr.log").read_text()[-2500:], flush=True)
