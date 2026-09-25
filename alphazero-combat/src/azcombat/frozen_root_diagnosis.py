"""Independent frozen-root ablations and read-only held-out model diagnostics."""
from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess

import numpy as np
import onnxruntime as ort

from .experiments import checked_model
from .research_report import audit_wave
from .samples import read_jsonl
from .training import encode_actions, encode_observation


ROOTS = {
    "ordinary": "M4-FINAL-ORDINARY-045",
    "purity": "AZ-M4-CHAIN-A-501",
    "cascade-second": "M4-NESTED-030",
}
ARMS = ("pure-mcts", "model-prior_model-value", "model-prior_constant-zero-value",
        "uniform-prior_model-value", "uniform-prior_constant-zero-value")
ASSEMBLY = re.compile(
    r"^SLAY_WORKER_ASSEMBLY label=(NativeWorker|Search|CombatSolver) "
    r"path=(.+?) mvid=([A-Fa-f0-9-]{36}) sha256=([A-Fa-f0-9]{64})$",
    re.MULTILINE,
)
STAGE = re.compile(r"^SLAY_NATIVE_WORKER_STAGE=(.+)$", re.MULTILINE)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().lower()


def _write(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def _probabilities(values: list[float]) -> list[float]:
    if not values or any(not math.isfinite(value) or value < 0 for value in values):
        raise ValueError("distribution has invalid entries")
    total = sum(values)
    if total <= 0:
        raise ValueError("distribution has zero mass")
    return [value / total for value in values]


def policy_distance(reference: list[float], predicted: list[float]) -> dict:
    """KL(reference || predicted) and JS; zero reference entries contribute zero."""
    if len(reference) != len(predicted):
        raise ValueError("policy vectors have different legal action sets")
    p, q = _probabilities(reference), _probabilities(predicted)
    if any(value <= 0 for value in q):
        raise ValueError("model prior must have full legal-action support")
    mixture = [(left + right) / 2 for left, right in zip(p, q, strict=True)]
    kl = sum(left * math.log(left / right) for left, right in zip(p, q, strict=True)
             if left > 0)
    js = (sum(left * math.log(left / middle)
              for left, middle in zip(p, mixture, strict=True) if left > 0)
          + sum(right * math.log(right / middle)
                for right, middle in zip(q, mixture, strict=True) if right > 0)) / 2
    return {"klPureToPrior": kl, "js": js,
            "top1Agrees": int(np.argmax(p)) == int(np.argmax(q))}


def _choice_context_alignment(raw: dict) -> bool:
    observation = raw["observation"]
    frame = raw.get("choiceFrame")
    if raw["rootKind"] == "ordinary":
        if frame is not None or observation.get("Choice") is not None \
                or raw.get("choiceContextObservation") is not None:
            raise ValueError("ordinary frozen root unexpectedly has choice context")
        aligned = True
    else:
        if not isinstance(frame, dict) or frame.get("Observation") != observation \
                or not frame.get("Candidates") or frame.get("MinCount") is None \
                or frame.get("MaxCount") is None or type(frame.get("Ordered")) is not bool:
            raise ValueError("pending frozen root lacks a verifiable pre-selection frame")
        candidates = frame["Candidates"]
        if type(frame["MinCount"]) is not int or type(frame["MaxCount"]) is not int \
                or not 0 <= frame["MinCount"] <= frame["MaxCount"] <= len(candidates) \
                or len({candidate["CombatCardIndex"] for candidate in candidates}) != len(candidates) \
                or not isinstance(frame.get("CompletedSelections"), list):
            raise ValueError("pending frozen-root choice cardinality or candidate identity differs")
        expected_choice = {key: frame[key] for key in
                           ("TriggerCardId", "Effect", "SourcePile", "MinCount", "MaxCount",
                            "Ordered", "CompletedSelections")}
        expected_choice["Candidates"] = [
            {key: candidate[key] for key in
             ("CombatCardIndex", "ModelId", "UpgradeLevel")}
            for candidate in frame["Candidates"]]
        expected_observation = {**observation, "Choice": expected_choice}
        provided = raw.get("choiceContextObservation")
        if provided is not None and provided != expected_observation:
            raise ValueError("diagnostic choice context does not match captured frame")
        choice = observation.get("Choice")
        if choice is not None and choice != expected_choice:
            raise ValueError("model choice observation differs from captured choice frame")
        aligned = choice is not None
    if "choiceContextAligned" in raw and raw["choiceContextAligned"] is not aligned:
        raise ValueError("reported choice-context alignment differs from actual model input")
    return aligned


def audit_frozen_root(path: Path, expected_model_hash: str) -> dict:
    raw = json.loads(path.read_text(encoding="utf-8"))
    ids = raw.get("legalActionIds")
    if raw.get("format") != "azcombat.frozen-root-policy-value-diagnosis.v1" \
            or raw.get("status") != "complete" or raw.get("searchOnly") is not True \
            or raw.get("regressionOnly") is not True \
            or raw.get("trajectoryOutcome") is not None \
            or raw.get("trajectoryValueTarget") is not None \
            or raw.get("rootKind") not in ROOTS or raw.get("seed") != ROOTS[raw["rootKind"]] \
            or type(ids) is not list or not ids or len(ids) != len(set(ids)) \
            or raw.get("model", {}).get("sha256", "").lower() != expected_model_hash.lower() \
            or raw.get("maxDepth") != 200 or raw.get("maxSimulations") != 32:
        raise ValueError("frozen-root artifact contract or model identity differs")
    if raw.get("observation", {}).get("SchemaVersion") != 3 \
            or hashlib.sha256(json.dumps(raw["observation"], separators=(",", ":")).encode()).hexdigest().lower() \
            != raw.get("observationSha256", "").lower():
        raise ValueError("frozen-root observation/hash differs")
    choice_context_aligned = _choice_context_alignment(raw)
    root_model = raw.get("rootModel", {})
    if root_model.get("outsideSearch") is not True or raw.get("rootTerminal") is not False \
            or len(root_model.get("logits", [])) != len(ids) \
            or len(root_model.get("prior", [])) != len(ids) \
            or any(not math.isfinite(x) for x in root_model["logits"]) \
            or root_model.get("actionScores") != [
                {"actionId": action_id, "logit": root_model["logits"][index],
                 "prior": root_model["prior"][index]}
                for index, action_id in enumerate(ids)] \
            or not math.isfinite(root_model.get("value", float("nan"))) \
            or not -1 <= root_model["value"] <= 1 \
            or abs(sum(root_model["prior"]) - 1) > 1e-6 \
            or any(not math.isfinite(x) or x <= 0 for x in root_model["prior"]):
        raise ValueError("frozen-root model output is invalid")
    arms = raw.get("arms", [])
    if [arm.get("mode") for arm in arms] != list(ARMS):
        raise ValueError("frozen-root arm set/order differs")
    for arm in arms:
        actions = arm.get("actions", [])
        counts = [action.get("visits") for action in actions]
        if [action.get("actionId") for action in actions] != ids \
                or any(type(count) is not int or count < 0 for count in counts) \
                or arm.get("selectedActionId") not in ids \
                or arm.get("selectedActionId") not in [a["actionId"] for a in actions if a["visits"] > 0] \
                or arm.get("completedSimulations") != 32 \
                or arm.get("rootVisits") != sum(counts) \
                or sum(counts) != 32 - (arm["mode"] != "pure-mcts") \
                or arm.get("fallbackCount") != 0 \
                or arm.get("outcome") is not None or arm.get("valueTarget") is not None \
                or arm.get("terminal") is not None or arm.get("unresolved") is not None:
            raise ValueError(f"frozen-root arm accounting differs: {arm.get('mode')}")
        if arm["mode"] == "pure-mcts":
            expected = (0, 0, 0)
        elif arm["mode"] == "uniform-prior_constant-zero-value":
            expected = (0, 0, 0)
        elif arm["mode"] == "model-prior_constant-zero-value":
            expected = (arm["networkInferenceCalls"], arm["evaluatorCalls"], 0)
        elif arm["mode"] == "uniform-prior_model-value":
            expected = (arm["networkInferenceCalls"], 0, arm["evaluatorCalls"])
        else:
            expected = (arm["networkInferenceCalls"], arm["evaluatorCalls"],
                        arm["evaluatorCalls"])
        if tuple(arm.get(key) for key in ("networkInferenceCalls", "modelPriorAppliedNodes",
                                          "modelValueBackprops")) != expected \
                or (arm["mode"] != "pure-mcts" and arm["evaluatorCalls"] < 1) \
                or ((arm["mode"].startswith("model-prior")
                     or arm["mode"] == "uniform-prior_model-value")
                    and arm["networkInferenceCalls"] != arm["evaluatorCalls"]):
            raise ValueError(f"frozen-root guidance counters differ: {arm['mode']}")
        for action in actions:
            if action["visits"] == 0 and (action.get("meanQ") is not None or action.get("bestQ") is not None):
                raise ValueError("unvisited frozen-root action has a fabricated Q")
            if action["visits"] > 0 and (not math.isfinite(action.get("meanQ", float("nan")))
                                          or not -1 <= action["meanQ"] <= 1):
                raise ValueError("visited frozen-root action lacks finite Q")
    for name, identity in raw.get("assemblies", {}).items():
        path_on_disk = Path(identity["path"])
        if name not in {"nativeWorker", "search", "combatSolver"} \
                or _sha(path_on_disk) != identity["sha256"].lower():
            raise ValueError("frozen-root assembly provenance differs from disk")
    if set(raw.get("assemblies", {})) != {"nativeWorker", "search", "combatSolver"}:
        raise ValueError("frozen-root assembly provenance is incomplete")
    pure, full = arms[0], arms[1]
    distance = policy_distance([item["visits"] for item in pure["actions"]],
                               root_model["prior"])
    return {"rootKind": raw["rootKind"], "seed": raw["seed"],
            "stateKey": raw["stateKey"], "legalActions": len(ids),
            "modelValue": root_model["value"], **distance,
            "choiceContextAligned": choice_context_aligned,
            "choiceAwareComparisonValid": choice_context_aligned,
            "pureSelectedActionId": pure["selectedActionId"],
            "fullTreeSelectedActionId": full["selectedActionId"],
            "fullTreeDisagreesWithPure": full["selectedActionId"] != pure["selectedActionId"],
            "armSimulations": {arm["mode"]: arm["completedSimulations"] for arm in arms},
            "modelPriorNodes": full["modelPriorAppliedNodes"],
            "modelValueBackprops": full["modelValueBackprops"],
            "fallbacks": sum(arm["fallbackCount"] for arm in arms)}


def _metrics(rows: list[dict]) -> dict:
    if not rows:
        return {"battles": 0, "roots": 0, "valueMae": None, "valueMse": None,
                "outcomeBrier": None, "positiveValueRoots": 0,
                "positiveValueFailureRoots": 0, "positiveValueFailureRate": None}
    terminal = [row for row in rows if row["outcome"] in {"win", "loss"}]
    positive = [row for row in rows if row["value"] > 0]
    return {"battles": len({(row["seed"], row["encounter"]) for row in rows}),
            "roots": len(rows),
            "valueMae": sum(abs(row["value"] - row["target"]) for row in rows) / len(rows),
            "valueMse": sum((row["value"] - row["target"]) ** 2 for row in rows) / len(rows),
            # A diagnostic proxy: the reward value is not trained as a win probability.
            "outcomeBrier": (sum(((row["value"] + 1) / 2 - (row["outcome"] == "win")) ** 2
                                 for row in terminal) / len(terminal)) if terminal else None,
            "positiveValueRoots": len(positive),
            "positiveValueFailureRoots": sum(row["outcome"] != "win" for row in positive),
            "positiveValueFailureRate": (sum(row["outcome"] != "win" for row in positive)
                                         / len(positive)) if positive else None}


def _opening_metrics(rows: list[dict]) -> dict:
    if not rows:
        return {"pairs": 0, "meanKlPureToPrior": None, "meanJs": None,
                "top1AgreementRate": None, "treePureDisagreementRate": None}
    return {"pairs": len(rows),
            "meanKlPureToPrior": sum(row["klPureToPrior"] for row in rows) / len(rows),
            "meanJs": sum(row["js"] for row in rows) / len(rows),
            "top1AgreementRate": sum(row["top1Agrees"] for row in rows) / len(rows),
            "treePureDisagreementRate": sum(row["treeDisagreesWithPure"] for row in rows) / len(rows)}


def calibrate_held_out(model: Path, manifest_path: Path) -> dict:
    """Read-only E00-E09 diagnosis; never select a checkpoint or mutate the frozen wave."""
    model_hash = checked_model(model)
    audited = audit_wave(manifest_path)
    if audited["phase"] != "evaluation" or any(row["status"] != "complete" for row in audited["runs"]):
        raise ValueError("held-out evaluation wave must pass full strict reread")
    if audited["request"]["newOnnxSha256"].lower() != model_hash.lower():
        raise ValueError("diagnosed model differs from frozen held-out candidate")
    by_cell = {(row["seed"], row["encounter"], row["policy"]): row for row in audited["runs"]}
    session = ort.InferenceSession(str(model), providers=["CPUExecutionProvider"])
    values = []
    mismatched_choices = []
    openings = []
    for cell, row in by_cell.items():
        seed, encounter, policy = cell
        if policy != "new-tree":
            continue
        pure = by_cell[(seed, encounter, "pure-mcts")]
        samples = read_jsonl(Path(row["jsonl"]))
        pure_samples = read_jsonl(Path(pure["jsonl"]))
        if not samples or not pure_samples:
            raise ValueError("held-out trajectory is empty")
        raw_lines = Path(row["jsonl"]).read_text(encoding="utf-8").splitlines()
        if len(raw_lines) != len(samples):
            raise ValueError("strict held-out sample count differs from source lines")
        for decision_index, (sample, line) in enumerate(zip(samples, raw_lines, strict=True)):
            raw_sample = json.loads(line)
            if sample.observation["choice"] is not None:
                mismatched_choices.append({"seed": seed, "encounter": encounter,
                                           "deckTemplate": row["deckTemplate"],
                                           "outcome": sample.outcome,
                                           "sourceJsonl": row["jsonl"],
                                           "decisionIndex": decision_index,
                                           "stateKey": raw_sample["stateKey"]})
                continue
            entities, globals_ = encode_observation(sample)
            _, actions = encode_actions(sample)
            _, value = session.run(None, {
                "entities": entities.numpy(), "globals": globals_.numpy(),
                "actions": actions.numpy(),
            })
            prediction = float(np.asarray(value).reshape(-1)[0])
            if not math.isfinite(prediction) or not -1 <= prediction <= 1:
                raise ValueError("held-out model value is invalid")
            values.append({"seed": seed, "encounter": encounter,
                           "deckTemplate": row["deckTemplate"], "outcome": sample.outcome,
                           "target": sample.value_target, "value": prediction,
                           "choice": sample.observation["choice"] is not None,
                           "sourceJsonl": row["jsonl"], "decisionIndex": decision_index,
                           "stateKey": raw_sample["stateKey"]})
        first, pure_first = samples[0], pure_samples[0]
        ids, _ = encode_actions(first)
        pure_ids, _ = encode_actions(pure_first)
        with Path(row["jsonl"]).open(encoding="utf-8") as source:
            first_raw = json.loads(source.readline())
        with Path(pure["jsonl"]).open(encoding="utf-8") as source:
            pure_raw = json.loads(source.readline())
        if ids != pure_ids or first.observation != pure_first.observation \
                or first_raw["stateKey"] != pure_raw["stateKey"]:
            raise ValueError("held-out pure/tree opening roots do not match")
        entities, globals_ = encode_observation(first)
        _, actions = encode_actions(first)
        logits, _ = session.run(None, {"entities": entities.numpy(),
                                       "globals": globals_.numpy(), "actions": actions.numpy()})
        scores = np.asarray(logits).reshape(-1)
        exp = np.exp(scores - scores.max())
        prior = (exp / exp.sum()).tolist()
        pure_visits = [pure_first.visit_policy.get(action_id, 0) for action_id in ids]
        distance = policy_distance(pure_visits, prior)
        tree_selected = first_raw["provenance"]["decisionMetrics"][0]["selectedActionId"]
        pure_selected = pure_raw["provenance"]["decisionMetrics"][0]["selectedActionId"]
        openings.append({"seed": seed, "encounter": encounter,
                         "deckTemplate": row["deckTemplate"], "outcome": first.outcome,
                         "stateKey": first_raw["stateKey"], **distance,
                         "legalActionIds": ids, "prior": prior,
                         "pureVisits": pure_visits,
                         "treeVisits": [first.visit_policy.get(action_id, 0) for action_id in ids],
                         "modelTop1ActionId": ids[int(np.argmax(prior))],
                         "pureTop1ActionId": ids[int(np.argmax(pure_visits))],
                         "treeSelectedActionId": tree_selected,
                         "pureSelectedActionId": pure_selected,
                         "treeDisagreesWithPure": tree_selected != pure_selected})
    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in values:
        grouped["all"].append(row)
        grouped[f"outcome:{row['outcome']}"].append(row)
        grouped[f"encounter:{row['encounter']}"].append(row)
        grouped[f"deck:{row['deckTemplate']}"].append(row)
        grouped[f"encounter:{row['encounter']}/outcome:{row['outcome']}"].append(row)
        grouped[f"deck:{row['deckTemplate']}/outcome:{row['outcome']}"].append(row)
    positive = [row for row in values if row["value"] > 0]
    positive_battles = {(row["seed"], row["encounter"]) for row in positive}
    positive_failure_battles = {(row["seed"], row["encounter"]) for row in positive
                                if row["outcome"] != "win"}
    return {"source": str(manifest_path.resolve()), "sourceSha256": _sha(manifest_path),
            "modelSha256": model_hash, "readOnlyHeldOutSeeds": sorted({row["seed"] for row in values}),
            "selectionOrTuningPerformed": False,
            "valueCalibrationScope": "ordinary roots only: saved observation equals tree policy input",
            "choiceRowsExcluded": len(mismatched_choices),
            "choiceRowsExclusionReason": "tree policy input omits captured Choice context; saved JSONL does not",
            "choiceRows": mismatched_choices,
            "valueMetrics": {key: _metrics(group) for key, group in sorted(grouped.items())},
            "positiveValueThreshold": 0,
            "positiveValueFailureRate": (sum(row["outcome"] != "win" for row in positive)
                                         / len(positive)) if positive else None,
            "positiveValueBattles": len(positive_battles),
            "positiveValueFailureBattles": len(positive_failure_battles),
            "rootPredictions": values,
            "openingPrior": {**_opening_metrics(openings),
                             "byEncounter": {
                                 encounter: _opening_metrics([row for row in openings
                                                              if row["encounter"] == encounter])
                                 for encounter in sorted({row["encounter"] for row in openings})},
                             "byDeckTemplate": {
                                 deck: _opening_metrics([row for row in openings
                                                         if row["deckTemplate"] == deck])
                                 for deck in sorted({row["deckTemplate"] for row in openings})},
                             "rows": openings}}


def run(output: Path, model: Path, game_dir: Path, ritsu_root: Path,
        evaluation_manifest: Path, roots: tuple[str, ...] = tuple(ROOTS)) -> dict:
    if not roots or len(roots) != len(set(roots)) or any(root not in ROOTS for root in roots):
        raise ValueError("frozen-root selection must be nonempty, unique and registered")
    model = model.resolve(strict=True)
    model_hash = checked_model(model)
    if output.exists():
        raise FileExistsError(output)
    if not game_dir.is_dir() or not ritsu_root.is_dir():
        raise FileNotFoundError("game or RitsuLib directory is missing")
    shell = shutil.which("pwsh.exe") or shutil.which("pwsh")
    if shell is None:
        raise FileNotFoundError("PowerShell 7 is required")
    repo = Path(__file__).resolve().parents[3]
    output.mkdir(parents=True, exist_ok=False)
    manifest = {"format": "azcombat.frozen-root-diagnosis-wave.v1", "status": "incomplete",
                "modelPath": str(model), "modelSha256": model_hash,
                "requestedRoots": list(roots), "runs": []}
    manifest_path = output / "manifest.json"
    _write(manifest_path, manifest)
    try:
        for root in roots:
            seed = ROOTS[root]
            result_path = (output / f"{root}.json").resolve()
            stage = (output / f"{root}.stage").resolve()
            checkpoint = (output / f"{root}.checkpoint.json").resolve()
            env = os.environ.copy()
            for name in tuple(env):
                if name.startswith(("STS2_MCTS_EXPORT_", "STS2_ALPHAZERO_", "STS2_MCTS_DIAG_")):
                    env.pop(name)
            env.update({"STS2_MCTS_DIAG_POLICY_VALUE": "1", "STS2_MCTS_DIAG_MODEL": str(model),
                        "STS2_MCTS_DIAG_OUT": str(result_path), "STS2_MCTS_DIAG_ROOT": root,
                        "STS2_MCTS_DIAG_SEED": seed,
                        "STS2_MCTS_DIAG_CHECKPOINT_OUT": str(checkpoint)})
            command = [shell, "-NoProfile", "-File", str(repo / "scripts" / "native-worker.ps1"),
                       "-GameDir", str(game_dir.resolve()), "-RitsuLibRoot", str(ritsu_root.resolve()),
                       "-Mode", "solver-mcts-diagnosis", "-StageRoot", str(stage),
                       "-TimeoutSeconds", "700"]
            record = {"rootKind": root, "seed": seed, "stage": str(stage),
                      "result": str(result_path), "checkpoint": str(checkpoint), "status": "started"}
            manifest["runs"].append(record)
            _write(manifest_path, manifest)
            process = subprocess.run(command, cwd=repo, env=env, capture_output=True, text=True,
                                     encoding="utf-8", errors="replace", timeout=730, check=False)
            launcher_out = output / f"{root}.launcher.stdout.txt"
            launcher_err = output / f"{root}.launcher.stderr.txt"
            launcher_out.write_text(process.stdout, encoding="utf-8")
            launcher_err.write_text(process.stderr, encoding="utf-8")
            record.update({"exitCode": process.returncode,
                           "launcherStdout": str(launcher_out),
                           "launcherStderr": str(launcher_err)})
            _write(manifest_path, manifest)
            if process.returncode != 0 or not result_path.is_file() or not checkpoint.is_file():
                raise RuntimeError(f"frozen-root Native run failed at {root}; evidence in {stage}")
            match = STAGE.findall(process.stdout)
            if match != [str(stage)]:
                raise ValueError(f"launcher did not confirm the expected isolated stage for {root}")
            stdout = stage / "stdout.txt"
            matches = ASSEMBLY.findall(stdout.read_text(encoding="utf-8"))
            if len(matches) != 3 or {item[0] for item in matches} != \
                    {"NativeWorker", "Search", "CombatSolver"}:
                raise ValueError(f"worker assembly provenance is incomplete at {root}")
            actual = json.loads(result_path.read_text(encoding="utf-8"))
            for label, path, mvid, digest in matches:
                field = {"NativeWorker": "nativeWorker", "Search": "search",
                         "CombatSolver": "combatSolver"}[label]
                artifact = actual["assemblies"][field]
                if artifact["path"] != path or artifact["mvid"].lower() != mvid.lower() \
                        or artifact["sha256"].lower() != digest.lower() \
                        or _sha(Path(path)) != digest.lower():
                    raise ValueError(f"worker/artifact/disk assembly identity mismatch at {root}")
            if _sha(checkpoint) != actual["checkpointSha256"].lower():
                raise ValueError(f"frozen-root checkpoint hash mismatch at {root}")
            summary = audit_frozen_root(result_path, model_hash)
            record.update({"status": "complete", "resultSha256": _sha(result_path),
                           "checkpointSha256": _sha(checkpoint),
                           "stdoutSha256": _sha(stdout),
                           "stderrSha256": _sha(stage / "stderr.txt"), "summary": summary})
            _write(manifest_path, manifest)
        calibration = calibrate_held_out(model, evaluation_manifest)
        calibration_path = output / "held-out-read-only-calibration.json"
        _write(calibration_path, calibration)
        manifest["calibration"] = str(calibration_path)
        manifest["calibrationSha256"] = _sha(calibration_path)
        manifest["status"] = "complete"
        return manifest
    except Exception as error:
        manifest["status"] = "failed"
        manifest["error"] = str(error)
        raise
    finally:
        _write(manifest_path, manifest)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--model", required=True, type=Path)
    parser.add_argument("--game-dir", required=True, type=Path)
    parser.add_argument("--ritsu-root", required=True, type=Path)
    parser.add_argument("--evaluation-manifest", required=True, type=Path)
    parser.add_argument("--root", action="append", choices=tuple(ROOTS),
                        help="Run only this frozen root; repeat to select several")
    args = parser.parse_args()
    result = run(args.output, args.model, args.game_dir, args.ritsu_root,
                 args.evaluation_manifest, tuple(args.root) if args.root else tuple(ROOTS))
    print(json.dumps({"status": result["status"], "roots": len(result["runs"]),
                      "calibration": result.get("calibration")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
