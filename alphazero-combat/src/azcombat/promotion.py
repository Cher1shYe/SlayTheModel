"""Fail-closed, artifact-derived candidate gate and atomic champion alias."""
from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import re
import shutil
import uuid

import torch

from .experiments import REGISTERED_ENCOUNTERS, STARTS, checked_model, sha256
from .reward import Outcome, TerminalResult, score_result
from .samples import read_jsonl

ASSEMBLY = re.compile(r"SLAY_WORKER_ASSEMBLY label=(NativeWorker|Search|CombatSolver) .*?sha256=([A-Fa-f0-9]{64})")


def _inside(base: Path, name: str) -> Path:
    target = (base / name).resolve()
    if not target.is_relative_to(base.resolve()) or not target.is_file():
        raise ValueError(f"missing/out-of-run artifact: {name}")
    return target


def _audit_run(base: Path, entry: dict, model_sha: str, minimum_rate: float = 100.0) -> dict:
    if entry.get("exitCode") != 0 or entry.get("encounter") not in REGISTERED_ENCOUNTERS \
            or entry.get("startType") not in STARTS:
        raise ValueError("run failed or has an unregistered encounter/start")
    path = _inside(base, entry["jsonl"])
    if sha256(path).lower() != entry.get("sha256", "").lower():
        raise ValueError("JSONL SHA256 differs from the wave manifest")
    raw_lines = path.read_text(encoding="utf-8").splitlines()
    if not raw_lines or any(not line.strip() for line in raw_lines):
        raise ValueError("run has zero or blank JSONL samples")
    raw = [json.loads(line) for line in raw_lines]
    samples = read_jsonl(path)
    if len(raw) != len(samples):
        raise ValueError("JSONL raw/strict sample counts differ")
    stdout = _inside(base, entry["stdout"]).read_text(encoding="utf-8")
    loaded = {label: digest.upper() for label, digest in ASSEMBLY.findall(stdout)}
    if set(loaded) != {"NativeWorker", "Search", "CombatSolver"}:
        raise ValueError("missing actual loaded assembly provenance")
    provenance = raw[0].get("provenance")
    if not isinstance(provenance, dict) or any(line.get("provenance") != provenance for line in raw):
        raise ValueError("trajectory provenance changed across decisions")
    expected = {"NativeWorker": "nativeWorker", "Search": "search", "CombatSolver": "combatSolver"}
    if any(provenance.get("assemblies", {}).get(key, {}).get("sha256", "").upper() != digest
           for label, digest in loaded.items() for key in [expected[label]]):
        raise ValueError("loaded assembly and sample provenance differ")
    if provenance.get("seed") != entry["seed"] or provenance.get("encounter") != entry["encounter"] \
            or any(s.seed != entry["seed"] or s.start_type != entry["startType"] for s in samples):
        raise ValueError("seed, encounter or start type differs")
    start = provenance.get("startProvenance")
    if entry["startType"] == "mid_combat_verified":
        if not isinstance(start, dict) or start.get("replayVerified") is not True \
                or start.get("midTurns", 0) < 1 or len(start.get("prefix", [])) != start["midTurns"]:
            raise ValueError("mid-combat checkpoint/prefix evidence missing")
        if start.get("entryHp") != provenance.get("entryHp") \
                or start.get("initialEnemyEffectiveHp") != provenance.get("initialEnemyEffectiveHp"):
            raise ValueError("mid-combat reward start differs")
    elif start is not None:
        raise ValueError("full-combat run has mid-combat provenance")
    outcome = Outcome(samples[0].outcome)
    if any(sample.outcome != outcome.value or sample.value_target != samples[0].value_target for sample in samples):
        raise ValueError("trajectory value/outcome was not uniformly backfilled")
    if type(provenance.get("terminal")) is not bool \
            or provenance["terminal"] != (outcome is not Outcome.UNRESOLVED):
        raise ValueError("native settlement and outcome disagree")
    value = score_result(TerminalResult(outcome, provenance["entryHp"], provenance["playerHp"],
                                        provenance["enemyDamageLost"], provenance["initialEnemyEffectiveHp"]))
    if abs(value - samples[0].value_target) > 1e-6:
        raise ValueError("trajectory reward does not match native HP evidence")
    metrics = provenance.get("decisionMetrics")
    if not isinstance(metrics, list) or len(metrics) != len(samples):
        raise ValueError("per-decision search metrics missing")
    rates = []
    for sample, line, metric in zip(samples, raw, metrics, strict=True):
        simulations, elapsed = metric.get("simulations"), metric.get("elapsedMilliseconds")
        if type(simulations) is not int or simulations <= 0 or type(elapsed) not in (int, float) \
                or not math.isfinite(elapsed) or elapsed < 1000 \
                or line.get("stateKey") != metric.get("stateKey") or line.get("simulations") != simulations:
            raise ValueError("invalid/misaligned effective simulation or live wall-clock evidence")
        rate = simulations / (elapsed / 1000)
        if rate < minimum_rate:
            raise ValueError(f"effective simulation rate {rate:.3f} < {minimum_rate}")
        rates.append(rate)
    policy = entry["policy"]
    status = provenance.get("modelLoadStatus", "")
    if policy == "baseline":
        if status != "pure-mcts:no-model-configured" or provenance.get("modelUsed") != 0:
            raise ValueError("baseline was not pure MCTS")
    elif policy in {"candidate", "champion"}:
        if model_sha.upper() not in status.upper() or not status.startswith("model-ready") \
                or provenance.get("modelShadow") is not False or provenance.get("modelFallbacks") != 0 \
                or provenance.get("modelUsed") != len(samples) or provenance.get("modelScored") != len(samples):
            raise ValueError("candidate model was not used for every real decision")
    else:
        raise ValueError("unknown evaluation policy")
    if any((base / (entry["jsonl"] + suffix)).is_file()
           for suffix in (".diagnostic.json", ".live-action-diagnostic.json")):
        raise ValueError("run has failure diagnostics")
    choice_flags = [bool(sample.legal_actions and sample.legal_actions[0].kind == "NestedChoice") for sample in samples]
    nested = any(a and b for a, b in zip(choice_flags, choice_flags[1:]))
    death = outcome is Outcome.LOSS and provenance["playerHp"] == 0
    return {"seed": entry["seed"], "encounter": entry["encounter"], "startType": entry["startType"],
            "policy": policy, "outcome": outcome.value, "value": value, "samples": len(samples),
            "minSimulationsPerSecond": min(rates), "nestedChoice": nested, "settledDeath": death}


def audit_wave(manifest_path: Path, checkpoint: Path) -> dict:
    """A report is evidence, never a user-supplied 'passed' flag."""
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    base = manifest_path.resolve().parent
    model = Path(manifest["candidateOnnx"]).resolve(strict=True)
    model_sha = checked_model(model)
    catalog = Path(__file__).resolve().parents[3] / "combat" / "coverage" / "combat-hooks.json"
    payload = torch.load(checkpoint, map_location="cpu", weights_only=True)
    if payload.get("format") != "azcombat.checkpoint.v1":
        raise ValueError("unsupported checkpoint")
    model_manifest = json.loads(model.with_suffix(".manifest.json").read_text(encoding="utf-8"))
    if model_manifest.get("checkpointSha256", "").lower() != sha256(checkpoint).lower() \
            or manifest.get("candidateSha256", "").lower() != model_sha.lower():
        raise ValueError("evaluation model/checkpoint identity mismatch")
    seeds = manifest.get("seeds", [])
    encounters = manifest.get("encounters", [])
    known = set(payload["metadata"]["trainSeeds"]) | set(payload["metadata"]["validationSeeds"])
    reasons: list[str] = []
    if manifest.get("format") != "azcombat.wave.v1" or manifest.get("status") != "complete" \
            or manifest.get("mode") != "evaluate" or manifest.get("gameVersion") != "v0.111.0":
        reasons.append("wave is not a complete pinned-version paired evaluation")
    if manifest.get("coverageCatalogSha256", "").lower() != sha256(catalog).lower():
        reasons.append("Combat Solver coverage catalog hash differs from collection")
    if len(set(seeds)) < 3 or len(set(encounters)) < 2 or set(seeds) & known \
            or len(seeds) != len(set(seeds)) or len(encounters) != len(set(encounters)) \
            or any(encounter not in REGISTERED_ENCOUNTERS for encounter in encounters):
        reasons.append("unseen seed/registered encounter coverage is insufficient")
    if manifest.get("startTypes") != list(STARTS) or manifest.get("budgetMilliseconds", 0) < 1000:
        reasons.append("both start types and >=1 second budget are required")
    expected = {(seed, encounter, start, policy) for seed in seeds for encounter in encounters
                for start in STARTS for policy in ("baseline", "candidate")}
    entries = manifest.get("runs", [])
    keys = [(entry.get("seed"), entry.get("encounter"), entry.get("startType"), entry.get("policy")) for entry in entries]
    if len(keys) != len(set(keys)) or set(keys) != expected:
        reasons.append("missing or duplicate paired candidate/baseline runs")
    audited = {}
    for key, entry in zip(keys, entries, strict=True):
        try:
            audited[key] = _audit_run(base, entry, model_sha)
        except (KeyError, TypeError, ValueError, OSError) as error:
            reasons.append(f"run {key}: {error}")
    pairs = []
    for seed, encounter, start in sorted({key[:3] for key in expected}):
        baseline = audited.get((seed, encounter, start, "baseline"))
        candidate = audited.get((seed, encounter, start, "candidate"))
        if baseline and candidate:
            pairs.append((baseline, candidate))
            if "unresolved" in (baseline["outcome"], candidate["outcome"]):
                reasons.append(f"unresolved evaluation pair {seed}/{encounter}/{start}")
    if len(pairs) != len(expected) // 2:
        reasons.append("incomplete audited pair coverage")
    if not any(candidate["nestedChoice"] for _, candidate in pairs):
        reasons.append("no actual multi-layer nested choice trajectory")
    if not any(candidate["settledDeath"] for _, candidate in pairs):
        reasons.append("no native settled candidate death trajectory")
    baseline_wins = sum(b["outcome"] == "win" for b, _ in pairs)
    candidate_wins = sum(c["outcome"] == "win" for _, c in pairs)
    if candidate_wins < baseline_wins:
        reasons.append("candidate win count regresses versus paired pure MCTS")
    elif candidate_wins == baseline_wins and pairs \
            and sum(c["value"] for _, c in pairs) < sum(b["value"] for b, _ in pairs):
        reasons.append("candidate reward regresses on tied paired win count")
    return {"format": "azcombat.gate.v1", "approved": not reasons, "reasons": reasons,
            "candidateOnnx": str(model), "candidateSha256": model_sha,
            "checkpointSha256": sha256(checkpoint), "waveManifest": str(manifest_path.resolve()),
            "coverageCatalogSha256": sha256(catalog),
            "waveManifestSha256": sha256(manifest_path), "evaluationSeeds": sorted(seeds),
            "trainSeeds": sorted(payload["metadata"]["trainSeeds"]),
            "validationSeeds": sorted(payload["metadata"]["validationSeeds"]),
            "pairedRuns": len(pairs), "baselineWins": baseline_wins,
            "candidateWins": candidate_wins, "auditedRuns": list(audited.values())}


def write_gate(report: dict, path: Path, champion: Path | None = None) -> None:
    """A failed gate writes diagnostics but never changes the champion alias."""
    if path.exists():
        raise FileExistsError("gate report already exists")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    if champion is None or not report["approved"]:
        return
    champion.parent.mkdir(parents=True, exist_ok=True)
    if champion.exists():
        history = champion.parent / "history"
        history.mkdir(exist_ok=True)
        old_hash = sha256(champion)
        archived = history / f"champion-{old_hash}.json"
        if not archived.exists():
            shutil.copy2(champion, archived)
    alias = {"format": "azcombat.champion.v1", "onnx": report["candidateOnnx"],
             "onnxSha256": report["candidateSha256"], "checkpointSha256": report["checkpointSha256"],
             "gateReport": str(path.resolve()), "gateReportSha256": sha256(path),
             "usedSeeds": sorted(set(report["trainSeeds"] + report["validationSeeds"] + report["evaluationSeeds"]))}
    temporary = champion.parent / (champion.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        temporary.write_text(json.dumps(alias, indent=2), encoding="utf-8")
        os.replace(temporary, champion)
    finally:
        temporary.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wave", required=True, type=Path)
    parser.add_argument("--checkpoint", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--champion", type=Path, help="Opt-in atomic promotion; denied gates leave alias untouched")
    args = parser.parse_args()
    report = audit_wave(args.wave, args.checkpoint)
    write_gate(report, args.report, args.champion)
    print(json.dumps({"approved": report["approved"], "reasons": report["reasons"]}, indent=2))
    return 0 if report["approved"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
