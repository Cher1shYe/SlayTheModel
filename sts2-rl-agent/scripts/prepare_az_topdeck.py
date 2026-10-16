"""Freeze twenty-one cards, seven encounters and network-only promotion configs."""
from dataclasses import asdict
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sts2_env.az.config import atomic_json, content_hash
from sts2_env.az.content import TOP_CONTENT, EXPANDED_PROFILES
from sts2_env.az.coordinator import TrainingConfig
from sts2_env.az.decks import TOP_FACTORIES, TOP_FAMILIES, TOP_FAMILY_CARDS
from sts2_env.az.encoder import schema_for
from sts2_env.az.generation import generator_config, frozen_manifest
from sts2_env.az.rewards import V3
from sts2_env.az.scenarios import save_manifest


def prepare():
    root = Path("configs/az_g1_topdeck_v1")
    cards = {}
    for name, factory in TOP_FACTORIES.items():
        for upgraded in (False, True):
            card = factory(upgraded)
            cards[name + ("+" if upgraded else "")] = dict(
                factory=f"{factory.__module__}.{factory.__name__}", cost=card.cost,
                damage=card.base_damage, block=card.base_block, effects=card.effect_vars,
                keywords=sorted(card.keywords), card_type=card.card_type.name, target=card.target_type.name)
    content = dict(version=TOP_CONTENT, cards=cards, encounters=EXPANDED_PROFILES,
                   families={k:dict(required=list(v), allowed=list(TOP_FAMILY_CARDS[k]))
                             for k,v in TOP_FAMILIES.items()},
                   min_deck_size=6, max_deck_size=20, max_copies_across_upgrades=5,
                   promotion_policy="network-only-v1", search_role="observation",
                   enemy_powers=["STRENGTH", "VULNERABLE", "SLOW", "TERRITORIAL", "ARTIFACT"],
                   player_powers=["SHRINK", "STRENGTH", "VULNERABLE"],
                   supported_choices=["HEADBUTT", "HEADBUTT+","ARMAMENTS","TRUE_GRIT+", "BURNING_PACT", "BURNING_PACT+"],
                   excluded=["other choices", "generated cards other than Anger", "temporary costs", "other powers", "relics",
                             "potions", "multiplayer", "multiple enemies"],
                   audit_sources=["sts2_env/cards/ironclad.py", "sts2_env/monsters/act1.py",
                                  "sts2_env/encounters/act1.py", "sts2_env/powers/common.py",
                                  "decompiled/MegaCrit.Sts2.Core.Models.Monsters/Mawler.cs",
                                  "decompiled/MegaCrit.Sts2.Core.Models.Monsters/CubexConstruct.cs"])
    atomic_json(root / "content_manifest.json", content)
    atomic_json(root / "generator.json", generator_config(TOP_CONTENT))
    schema = schema_for("observable", V3, TOP_CONTENT)
    atomic_json(root / "encoder_schema.json", dict(schema=schema, sha256=content_hash(schema)))
    for seed in (42, 43):
        atomic_json(root / f"seed-{seed}.json", asdict(TrainingConfig(seed=seed, workers=8, iterations=3, episodes_per_iteration=126, simulations=8, eval_simulations=8, updates=16, batch_size=64,
                                                                  content_version=TOP_CONTENT, reward_version=V3)))
    save_manifest("data/az/g1_topdeck_v1_manifest.json", frozen_manifest(TOP_CONTENT))


if __name__ == "__main__":
    prepare()
