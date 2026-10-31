"""Build the isolated fixture, retaining the existing native host runtime."""
from pathlib import Path
import hashlib
import json
import shutil
import subprocess

here = Path(__file__).resolve().parent
commands = []

def run(command):
    commands.append(command)
    result = subprocess.run(command, cwd=here, capture_output=True, text=True)
    with (here / "build.log").open("a") as output:
        output.write(result.stdout + result.stderr)
    result.check_returncode()

(here / "build.log").write_text("")
run(["dotnet", "build", "SimulatorAudit.csproj", "-c", "ExportRelease", "--no-restore", "-p:NuGetAudit=false"])
built = here / ".godot/mono/temp/bin/ExportRelease"
runtime = here / "SimulatorAudit.app/Contents/Resources/data_SimulatorAudit_macos_arm64"
for filename in ["SimulatorAudit.dll", "SimulatorAudit.pdb"]:
    shutil.copy2(built / filename, runtime / filename)
run(["codesign", "--force", "--deep", "--sign", "-", "--entitlements", str(here / "entitlements.plist"), str(here / "SimulatorAudit.app")])
(here / "build.json").write_text(json.dumps({
    "commands": commands,
    "host_runtime_source": "native-round3-relic-fixtures/SimulatorAudit.app",
    "harness_sha256": hashlib.sha256((here / "AuditWorker.cs").read_bytes()).hexdigest(),
    "assembly_sha256": hashlib.sha256((runtime / "SimulatorAudit.dll").read_bytes()).hexdigest(),
    "game_assembly_sha256": hashlib.sha256((runtime / "sts2.dll").read_bytes()).hexdigest(),
}, indent=2) + "\n")
print("Isolated native fixture built and signed.")
