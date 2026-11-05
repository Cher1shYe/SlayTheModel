"""Explicit ArmG weight transfer to this engine, never checkpoint resumption.

Audited be401e8 and native-port-v1 inputs have an explicit named-segment
adapter to native-port-v2. New feature columns initialize to zero and have
not thereby been trained. The old binary hash is checkpoint-declared
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


# The immutable round-1 backup is a reviewed source, not a hash override.
NATIVE_PORT_V1_SOURCE_SHA256 = "2d16b21ef9ff473b63b961ca6ae7d2fe1070214c78ad276edba02e8e13d5c7a5"


def _feature_mapping(source_tree, source_digest, old_version, old_layout, new_layout):
    old_obs = old_layout["dimensions"]["PUBLIC_OBS_DIM"] - old_layout["dimensions"]["PUBLIC_COMBAT_OBS_DIM"]
    if old_version == ARMG_FEATURE_VERSION:
        if (old_layout != new_layout or sha256_file(source_tree / "agent/armg.py") != sha256_file(ROOT / "agent/armg.py")):
            raise ValueError("same-version action/feature/ID layout differs")
        return list(range(old_obs)), []
    if not (ARMG_FEATURE_VERSION == 3 and
            ((old_version == 1 and source_digest == LEGACY_BE401E8_SOURCE_SHA256) or
             (old_version == 2 and source_digest == NATIVE_PORT_V1_SOURCE_SHA256))):
        raise ValueError("no verified feature-version migration exists")
    old_source = (source_tree / "agent/armg.py").read_text()
    expected_source = old_source.replace(f"ARMG_FEATURE_VERSION = {old_version}", "ARMG_FEATURE_VERSION = 3")
    expected_source = expected_source.replace(
        "grid_kind in (3, 4)" if old_version == 1 else "grid_kind in (3, 4, 6, 7, 8)",
        "grid_kind in (3, 4, 6, 7, 8, 9, 10, 11, 12)")
    if expected_source != (ROOT / "agent/armg.py").read_text():
        raise ValueError("ArmG candidate implementation differs from the verified grid extension")
    old, new = old_layout["dimensions"], new_layout["dimensions"]
    if (old["PUBLIC_OBS_VERSION"], old["ACTION_SCHEMA_VERSION"], new["PUBLIC_OBS_VERSION"], new["ACTION_SCHEMA_VERSION"]) != (10, 9, 11, 10):
        raise ValueError("no verified observation/action schema migration exists")
    for enum, entries in old_layout["ids"].items():
        if enum not in ("Encounter", "EnchantmentId") and entries != new_layout["ids"][enum]:
            raise ValueError(f"migration requires identical IDs: {enum}")
    if new_layout["ids"]["EnchantmentId"] != (old_layout["ids"]["EnchantmentId"] | {"SPIRAL": 6, "STEADY": 7, "NIMBLE": 8}):
        raise ValueError("only the reviewed appended enchantment IDs are supported")
    previous_encounters, current_encounters = old_layout["ids"]["Encounter"], new_layout["ids"]["Encounter"]
    count = previous_encounters["COUNT"]
    if (current_encounters["COUNT"] != count + 1 or
            any(current_encounters.get(k) != v for k, v in previous_encounters.items() if k != "COUNT")):
        raise ValueError("only one appended Encounter identity is supported")
    for name in ("CARD_FEAT_DIM", "CARD_COUNT", "MAX_DECK", "MAP_MAX_POINTS"):
        if old[name] != new[name]:
            raise ValueError(f"migration requires identical dimensions: {name}")
    boundaries = new_layout["boundaries"]
    offset, extension = boundaries["PUB_RUN_BOSS_OFFSET"], boundaries["PUB_RUN_EXTENSION"]
    if (boundaries["PUBLIC_RUN_DIM"] != old_obs + 2 + extension or
            boundaries["PUBLIC_RUN_DIM"] != ARMG_OBS_DIM or not 0 < offset < old_obs - 2 * count):
        raise ValueError("run prefix/boss/extension boundaries do not match the reviewed adapter")
    mapping = (list(range(offset + count)) +
               list(range(offset + count + 1, offset + 2 * count + 1)) +
               list(range(offset + 2 * count + 2, old_obs + 2)))
    if len(mapping) != old_obs or len(set(mapping)) != old_obs:
        raise ValueError("invalid named feature mapping")
    changes = ["ArmG v10 -> v11: preserve run prefix, separately append each boss identity column, "
               "shift remaining old run fields by two, append native run context, move unchanged action block",
               "new input columns initialize to zero; old logits are preserved on corresponding old features, "
               "not a claim of trained behavior on new rules or new features",
               "ArmG feature v3 adds deck/enchantment rows for grid kinds 9/10/11/12 (and v1: 6/7/8); existing grid_kind/5 scale retained"]
    return mapping, changes


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
    new_layout = source_layout(ROOT)
    # Only the audited v10 feature implementation has a named v11 adapter.
    # Input shape alone never establishes semantic compatibility.
    mapping, changes = _feature_mapping(source_tree, source_digest, old_version,
                                         old_layout, new_layout)
    with torch.random.fork_rng(devices=[]):
        model = ArmGScorer(hidden=hidden)
    expected = checkpoint_config(model) | {"armg_feature_version": ARMG_FEATURE_VERSION,
                                           "armg_obs_dim": ARMG_OBS_DIM,
                                           "armg_action_dim": ARMG_ACTION_DIM}
    if expected["engine_contract"] != target:
        raise ValueError("target engine/source changed during migration; retry with a fixed environment")
    old_obs = old_layout["dimensions"]["PUBLIC_OBS_DIM"] - old_layout["dimensions"]["PUBLIC_COMBAT_OBS_DIM"]
    expected_old_shapes = [list(p.shape) for p in model.parameters()]
    expected_old_shapes[0][1] = old_obs + ARMG_ACTION_DIM
    if (config.get("armg_obs_dim") != old_obs or config.get("armg_action_dim") != ARMG_ACTION_DIM or
            config.get("param_shapes") != expected_old_shapes or
            config.get("in_features") != old_obs + ARMG_ACTION_DIM or
            config.get("obs_version") != old_layout["dimensions"]["PUBLIC_OBS_VERSION"] or
            config.get("action_schema_version") != old_layout["dimensions"]["ACTION_SCHEMA_VERSION"]):
        raise ValueError("source checkpoint layout mismatch: declared source features/model shape")
    weights = dict(payload["state_dict"])
    old_first = weights["net.0.weight"]
    first = torch.zeros_like(model.state_dict()["net.0.weight"])
    if old_first.shape != (first.shape[0], old_obs + ARMG_ACTION_DIM):
        raise ValueError("source first-layer weights do not match the declared source layout")
    first[:, mapping] = old_first[:, :old_obs]
    first[:, ARMG_OBS_DIM:] = old_first[:, old_obs:]
    weights["net.0.weight"] = first
    model.load_state_dict(weights, strict=True)
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
        "compatibility_evidence": "verified retained source IDs, explicitly appended IDs and named feature-segment mapping; "
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
