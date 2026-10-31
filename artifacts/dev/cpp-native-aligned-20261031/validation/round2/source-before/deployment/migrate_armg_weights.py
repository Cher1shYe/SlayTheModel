"""Explicit ArmG weight transfer to this engine, never checkpoint resumption.

The only legacy layout accepted is the audited be401e8 ArmG v1 source. Its
unchanged IDs/dimensions permit initializing v2's added grid kinds 6/7/8; they
have not thereby been trained. The old binary hash is checkpoint-declared
provenance, not evidence that its rules match the native game.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import re

import torch

from agent.armg import ARMG_ACTION_DIM, ARMG_FEATURE_VERSION, ARMG_OBS_DIM, ArmGScorer
from agent.engine_identity import (ROOT, current_engine_contract, sha256_file,
                                   source_content_digest, source_layout)
from agent.nets import checkpoint_config, read_checkpoint

# Digest covers the reference C++ sources/generated content and Python features.
# An arbitrary same-shaped checkpoint or edited legacy source is not an adapter.
LEGACY_BE401E8_SOURCE_SHA256 = "3b27384f75e2212fdc45318ed526fba2ac3f5196e7031101a07a21e248adbbb8"


def migrate_weights(*, source, output, source_sha256: str, old_engine_sha256: str,
                    new_engine_sha256: str, source_tree, hidden=(128, 128)) -> dict:
    source, output, source_tree = Path(source).resolve(), Path(output).resolve(), Path(source_tree).resolve()
    if output == source or output.exists():
        raise FileExistsError("migration requires a new output file; source is never overwritten")
    for name, value in (("source", source_sha256), ("old engine", old_engine_sha256),
                        ("new engine", new_engine_sha256)):
        if not re.fullmatch(r"[0-9a-f]{64}", value):
            raise ValueError(f"{name} SHA-256 must be 64 lowercase hexadecimal characters")
    source_bytes = source.read_bytes()
    if hashlib.sha256(source_bytes).hexdigest() != source_sha256:
        raise ValueError("source checkpoint SHA-256 mismatch")
    target = current_engine_contract()
    if new_engine_sha256 != target["simulator_sha256"]:
        raise ValueError("new engine SHA-256 does not match the loaded engine")
    if old_engine_sha256 == new_engine_sha256:
        raise ValueError("migration requires distinct source and target engine hashes")
    payload = read_checkpoint(io.BytesIO(source_bytes))
    config = payload.get("config", {})
    if payload.get("settings", {}).get("simulator_sha256") != old_engine_sha256:
        raise ValueError("old engine SHA-256 does not match checkpoint training settings")
    old_contract = config.get("engine_contract")
    source_digest = source_content_digest(source_tree)
    old_version = config.get("armg_feature_version")
    if old_contract is None:
        if (source_digest != LEGACY_BE401E8_SOURCE_SHA256 or old_version != 1 or
                config.get("format") != 2):
            raise ValueError("legacy source/layout is not the verified be401e8 ArmG v1 migration")
    elif (old_contract.get("simulator_sha256") != old_engine_sha256 or
          old_contract.get("source_content_sha256") != source_digest):
        raise ValueError("source engine contract does not match the declared source tree/hash")
    old_layout = source_layout(source_tree)
    for key in ("id_layout_sha256", "schema_layout_sha256", "dimensions"):
        if old_layout[key] != target[key]:
            raise ValueError(f"migration requires identical action/feature/ID layout: {key}")
    if old_version == ARMG_FEATURE_VERSION:
        if sha256_file(source_tree / "agent/armg.py") != sha256_file(ROOT / "agent/armg.py"):
            raise ValueError("same-version ArmG feature implementation differs")
        changes = []
    elif old_version == 1 and ARMG_FEATURE_VERSION == 2 and source_digest == LEGACY_BE401E8_SOURCE_SHA256:
        verified_extension = (source_tree / "agent/armg.py").read_text().replace(
            "ARMG_FEATURE_VERSION = 1", "ARMG_FEATURE_VERSION = 2").replace(
            "grid_kind in (3, 4)", "grid_kind in (3, 4, 6, 7, 8)")
        if verified_extension != (ROOT / "agent/armg.py").read_text():
            raise ValueError("ArmG v1 -> v2 feature code differs from the verified grid extension")
        changes = ["ArmG v1 -> v2: grid kinds 6/7/8 encode selected deck card and enchantment; "
                   "same IDs/dimensions and existing grid_kind/5 scale; new choices are untrained",
                   "public run state for grid kinds >=6 uses the previously empty first grid-card "
                   "row's first two features for pending damage/16 and curse ID/CardId::COUNT"]
    else:
        raise ValueError("no verified feature-version migration exists")
    # Preserve the caller's RNG even though creating a model initializes tensors.
    with torch.random.fork_rng(devices=[]):
        model = ArmGScorer(hidden=hidden)
    expected = checkpoint_config(model) | {"armg_feature_version": ARMG_FEATURE_VERSION,
                                           "armg_obs_dim": ARMG_OBS_DIM,
                                           "armg_action_dim": ARMG_ACTION_DIM}
    if expected["engine_contract"] != target:
        raise ValueError("target engine/source changed during migration; retry with a fixed environment")
    for key, value in expected.items():
        if key not in ("format", "engine_contract", "armg_feature_version") and config.get(key) != value:
            raise ValueError(f"source checkpoint layout mismatch: {key}")
    model.load_state_dict(payload["state_dict"], strict=True)
    if not all(torch.isfinite(t).all().item() for t in model.state_dict().values()):
        raise ValueError("source has non-finite weights")
    provenance = {
        "mode": "explicit_weights_only", "created_utc": datetime.now(timezone.utc).isoformat(),
        "source_checkpoint": str(source), "source_checkpoint_sha256": source_sha256,
        "old_engine_sha256": old_engine_sha256, "new_engine_sha256": new_engine_sha256,
        "old_engine_hash_evidence": "checkpoint settings; original training binary not executed",
        "source_tree": str(source_tree), "source_content_sha256": source_digest,
        "source_engine_contract": old_contract, "target_engine_contract": target,
        "source_settings": payload.get("settings"), "source_progress": payload.get("progress"),
        "previous_migration": payload.get("migration"), "feature_changes": changes,
        "compatibility_evidence": "matching source ID maps, dimension formulas and binding counts; "
                                  "explicit feature adapter only; not a complete feature/native parity audit",
        "training_games_in_target_environment": 0,
        "reset_fields": ["optimizer_state_dict", "progress", "torch_rng_state",
                         "python_rng_state", "numpy_rng_state"],
    }
    migrated = {"state_dict": model.state_dict(), "config": expected,
                "checkpoint_kind": "weights_only_migration",
                "settings": {"simulator_sha256": new_engine_sha256}, "migration": provenance}
    # Serialize before claiming a new filename; never replace an existing artifact.
    buffer = io.BytesIO()
    torch.save(migrated, buffer)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("xb") as stream:
        stream.write(buffer.getbuffer())
    return {"output": str(output), "sha256": sha256_file(output), "migration": provenance}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--source-sha256", required=True)
    parser.add_argument("--old-engine-sha256", required=True)
    parser.add_argument("--new-engine-sha256", required=True)
    parser.add_argument("--source-tree", required=True)
    parser.add_argument("--hidden", nargs="+", type=int, default=[128, 128])
    args = vars(parser.parse_args(argv))
    print(json.dumps(migrate_weights(**args), indent=2))


if __name__ == "__main__":
    main()
