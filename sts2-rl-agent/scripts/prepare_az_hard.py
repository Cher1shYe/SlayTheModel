"""Freeze the five-encounter/two-elite content and explicit ten-round configs."""
from dataclasses import asdict
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sts2_env.az.config import atomic_json, content_hash
from sts2_env.az.content import HARD_CONTENT, HARD_PROFILES
from sts2_env.az.coordinator import TrainingConfig
from sts2_env.az.encoder import schema_for
from sts2_env.az.generation import generator_config, frozen_manifest
from sts2_env.az.rewards import V3
from sts2_env.az.scenarios import save_manifest


if __name__ == "__main__":
    root = Path("configs/az_hard_v2")
    content = json.loads(Path("configs/az_decks_v3/content_manifest.json").read_text())
    content.update(version=HARD_CONTENT, encounters=HARD_PROFILES,
                   enemy_powers=["SHRINK", "STRENGTH", "VULNERABLE", "SLOW", "TERRITORIAL"],
                   audit_sources=["sts2_env/monsters/act1.py", "sts2_env/powers/remaining_c.py",
                                  "sts2_env/powers/monster.py", "decompiled/MegaCrit.Sts2.Core.Models.Monsters/BygoneEffigy.cs",
                                  "decompiled/MegaCrit.Sts2.Core.Models.Monsters/Byrdonis.cs"])
    atomic_json(root / "content_manifest.json", content)
    atomic_json(root / "generator.json", generator_config(HARD_CONTENT))
    schema = schema_for("observable", V3, HARD_CONTENT)
    atomic_json(root / "encoder_schema.json", dict(schema=schema, sha256=content_hash(schema)))
    for seed in (42, 43):
        atomic_json(root / f"seed-{seed}.json", asdict(TrainingConfig(seed=seed, workers=8, iterations=10,
                                                                   content_version=HARD_CONTENT, reward_version=V3)))
    save_manifest("data/az/hard_v2_manifest.json", frozen_manifest(HARD_CONTENT))
