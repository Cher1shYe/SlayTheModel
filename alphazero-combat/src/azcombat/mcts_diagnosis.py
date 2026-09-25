"""Serial headless same-root pure-MCTS diagnosis; never use data for training."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time


ROOTS = (
    ("ordinary", "M4-FINAL-ORDINARY-045"),
    ("purity", "AZ-M4-CHAIN-A-501"),
    ("cascade-second", "M4-NESTED-030"),
)
ASSEMBLY = re.compile(
    r"^SLAY_WORKER_ASSEMBLY label=(NativeWorker|Search|CombatSolver) "
    r"path=(.+?) mvid=([A-Fa-f0-9-]{36}) sha256=([A-Fa-f0-9]{64})$",
    re.MULTILINE,
)
PUBLISH_MS = re.compile(r"^SLAY_NATIVE_WORKER_PUBLISH_MS=([0-9.]+)$", re.MULTILINE)
PROCESS_MS = re.compile(r"^SLAY_NATIVE_WORKER_PROCESS_MS=([0-9.]+)$", re.MULTILINE)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(output: Path, game_dir: Path, ritsu_root: Path) -> dict:
    if output.exists():
        raise FileExistsError(output)
    if not game_dir.is_dir() or not ritsu_root.is_dir():
        raise FileNotFoundError("game or RitsuLib root is missing")
    shell = shutil.which("pwsh.exe") or shutil.which("pwsh")
    if shell is None:
        raise FileNotFoundError("PowerShell 7 is required")
    repo = Path(__file__).resolve().parents[3]
    script = repo / "scripts" / "native-worker.ps1"
    output.mkdir(parents=True, exist_ok=False)
    manifest: dict = {"format": "azcombat.mcts-same-root-wave.v1", "status": "incomplete",
                      "order": [f"{root}-{mode}" for root, _ in ROOTS for mode in ("profiled", "control")],
                      "gameDir": str(game_dir.resolve()), "ritsuRoot": str(ritsu_root.resolve()),
                      "runs": []}
    manifest_path = output / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    identities: dict | None = None
    for root, seed in ROOTS:
        reference = None
        checkpoint = output / f"{root}.checkpoint.json"
        for mode in ("profiled", "control"):
            stem = f"{root}-{mode}"
            result_path = (output / f"{stem}.json").resolve()
            stage = (output / f"{stem}.stage").resolve()
            env = os.environ.copy()
            for name in tuple(env):
                if name.startswith("STS2_MCTS_EXPORT_") or name.startswith("STS2_ALPHAZERO_") \
                        or name.startswith("STS2_MCTS_DIAG_"):
                    env.pop(name)
            env.update({"STS2_MCTS_DIAG_OUT": str(result_path),
                        "STS2_MCTS_DIAG_ROOT": root, "STS2_MCTS_DIAG_SEED": seed,
                        "STS2_MCTS_DIAG_PROFILE": "1" if mode == "profiled" else "0"})
            env["STS2_MCTS_DIAG_CHECKPOINT_OUT" if mode == "profiled"
                else "STS2_MCTS_DIAG_CHECKPOINT_IN"] = str(checkpoint.resolve())
            command = [shell, "-NoProfile", "-File", str(script), "-GameDir", str(game_dir),
                       "-RitsuLibRoot", str(ritsu_root), "-Mode", "solver-mcts-diagnosis",
                       "-StageRoot", str(stage),
                       "-TimeoutSeconds", "700"]
            started = time.perf_counter()
            process = subprocess.run(command, cwd=repo, env=env, capture_output=True, text=True,
                                     encoding="utf-8", errors="replace", timeout=730, check=False)
            total_ms = (time.perf_counter() - started) * 1000
            launcher_out = output / f"{stem}.launcher.stdout.txt"
            launcher_err = output / f"{stem}.launcher.stderr.txt"
            launcher_out.write_text(process.stdout, encoding="utf-8")
            launcher_err.write_text(process.stderr, encoding="utf-8")
            worker_out = output / f"{stem}.worker.stdout.txt"
            worker_err = output / f"{stem}.worker.stderr.txt"
            for source, destination in ((stage / "stdout.txt", worker_out),
                                        (stage / "stderr.txt", worker_err)):
                if not source.is_file():
                    if process.returncode != 0:
                        continue
                    raise FileNotFoundError(f"worker log missing from isolated stage at {stem}: {source}")
                with source.open("rb") as reader, destination.open("xb") as writer:
                    shutil.copyfileobj(reader, writer)
            run_entry = {"root": root, "mode": mode, "seed": seed,
                         "stageRoot": str(stage),
                         "result": result_path.name, "launcherStdout": launcher_out.name,
                         "launcherStderr": launcher_err.name, "workerStdout": worker_out.name,
                         "workerStderr": worker_err.name, "exitCode": process.returncode,
                         "totalLaunchPublishProcessMs": total_ms,
                         "publishMs": [float(x) for x in PUBLISH_MS.findall(process.stdout)],
                         "workerProcessMs": [float(x) for x in PROCESS_MS.findall(process.stdout)],
                         "stdoutSha256": _sha(worker_out) if worker_out.is_file() else None,
                         "stderrSha256": _sha(worker_err) if worker_err.is_file() else None}
            manifest["runs"].append(run_entry)
            manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
            if process.returncode != 0 or not result_path.is_file():
                raise RuntimeError(f"Native diagnosis failed at {stem}; full logs preserved in {output}")
            stage_provenance_path = stage / "stage_provenance.json"
            stage_provenance = json.loads(stage_provenance_path.read_text(encoding="utf-8"))
            if Path(stage_provenance.get("stageRoot", "")).resolve() != stage:
                raise ValueError(f"Isolated stage provenance differs at {stem}")
            if not checkpoint.is_file():
                raise FileNotFoundError(f"Native entry checkpoint missing at {stem}")
            actual = json.loads(result_path.read_text(encoding="utf-8"))
            if actual.get("status") != "complete" or actual.get("rootKind") != root \
                    or actual.get("seed") != seed or actual.get("profileEnabled") is not (mode == "profiled"):
                raise ValueError(f"Native diagnosis identity/status mismatch at {stem}")
            matches = ASSEMBLY.findall(worker_out.read_text(encoding="utf-8"))
            if len(matches) != 3 or {match[0] for match in matches} != {"NativeWorker", "Search", "CombatSolver"}:
                raise ValueError(f"Actual assembly provenance is incomplete at {stem}")
            current_identities = {label: {"path": path, "mvid": mvid,
                                          "sha256": digest.upper()} for label, path, mvid, digest in matches}
            for item in current_identities.values():
                if _sha(Path(item["path"])).lower() != item["sha256"].lower():
                    raise ValueError(f"Loaded assembly hash differs from disk at {stem}")
            if {item["label"]: {key: item[key] for key in ("path", "mvid", "sha256")}
                    for item in stage_provenance["assemblies"]} != current_identities:
                raise ValueError(f"Loaded assembly identity differs from isolated stage at {stem}")
            if identities is None:
                identities = current_identities
            elif {label: (item["mvid"].lower(), item["sha256"].lower())
                    for label, item in identities.items()} != {
                        label: (item["mvid"].lower(), item["sha256"].lower())
                        for label, item in current_identities.items()}:
                raise ValueError(f"Runs did not load the same build at {stem}")
            root_identity = tuple(actual[key] for key in ("checkpointSha256", "rootKey",
                                                           "rootActionKeysSha256", "rootObservationSha256"))
            if root_identity[0].lower() != _sha(checkpoint).lower():
                raise ValueError(f"Run did not use the saved entry checkpoint at {stem}")
            if reference is None:
                reference = root_identity
            elif reference != root_identity:
                raise ValueError(f"Profiled/control runs differ at the frozen {root} root")
            arms = actual.get("arms", [])
            expected_labels = ["A-cold-1s", "warmup-discard-tree-1s",
                               "B-hot-new-tree-1s", "C-hot-new-tree-5s", "E-hot-fixed-16"]
            if mode == "profiled":
                expected_labels += ["D-hot-export-validation-1s"]
            if [arm.get("label") for arm in arms] != expected_labels \
                    or any(not arm.get("rootRestored") or arm.get("retainedVisits") != 0 for arm in arms):
                raise ValueError(f"Fresh tree/root restoration checks failed at {stem}")
            run_entry.update({"resultSha256": _sha(result_path), "assemblies": current_identities,
                              "stageProvenanceSha256": _sha(stage_provenance_path),
                              "checkpointSha256": reference[0], "rootKey": reference[1],
                              "completedSimulations": [arm["completedSimulations"] for arm in arms]})
            manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    manifest["status"] = "complete"
    manifest["assemblies"] = identities
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--game-dir", required=True, type=Path)
    parser.add_argument("--ritsu-root", required=True, type=Path)
    args = parser.parse_args()
    result = run(args.output, args.game_dir, args.ritsu_root)
    print(json.dumps({"status": result["status"], "runs": len(result["runs"])}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
