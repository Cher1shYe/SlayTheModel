"""Check the outside-combat worker's actual schema/identity startup; no training."""
from pathlib import Path
import json
import subprocess
import sys
import tempfile

out = Path(__file__).resolve().parent
root = out.parents[1]
sys.path.insert(0, str(root))

import torch
from agent import armg
from agent.common import sim
from agent.nets import checkpoint_config

torch.set_num_threads(1)
model = armg.ArmGScorer()
config = checkpoint_config(model) | {
    "armg_feature_version": armg.ARMG_FEATURE_VERSION,
    "armg_obs_dim": armg.ARMG_OBS_DIM,
    "armg_action_dim": armg.ARMG_ACTION_DIM,
}
with tempfile.TemporaryDirectory(prefix="sts2-step1-worker-") as temp:
    path = Path(temp) / "startup-only.pt"
    torch.save({"state_dict": model.state_dict(), "config": config,
                "settings": {"simulator_sha256": config["engine_contract"]["simulator_sha256"]}}, path)
    command = [sys.executable, str(root / "scripts/armg_live_worker.py"),
               "--checkpoint", str(path), "--sts2-root", str(root), "--simulator", sim.__file__]
    result = subprocess.run(command, cwd=root, input="", text=True,
                            capture_output=True, timeout=45)
    report = {"returncode": result.returncode, "stdout": result.stdout, "stderr": result.stderr,
              "schemas": [int(sim.PUBLIC_OBS_VERSION), int(sim.ACTION_SCHEMA_VERSION), armg.ARMG_FEATURE_VERSION],
              "scope": "Worker startup using a temporary untrained current-format checkpoint, then EOF. No game/UI actions or training.",
              "user_checkpoint_read_or_modified": False}
    (out / "bridge-startup.json").write_text(json.dumps(report, indent=2)+"\n")
    print(json.dumps(report))
    raise SystemExit(result.returncode)
