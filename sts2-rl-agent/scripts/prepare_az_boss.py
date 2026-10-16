"""Freeze the isolated G2 Boss content and short validation budgets."""
from dataclasses import asdict
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sts2_env.az.boss_cards import CODEC, MAX_CARDS, ACTION_SIZE
from sts2_env.az.config import atomic_json, content_hash
from sts2_env.az.content import BOSS_CONTENT, BOSS_PROFILES
from sts2_env.az.coordinator import TrainingConfig
from sts2_env.az.encoder import schema_for
from sts2_env.az.generation import generator_config, frozen_manifest
from sts2_env.az.rewards import V6
from sts2_env.az.scenarios import save_manifest


def prepare():
    root = Path("configs/az_g2_boss_v1")
    cards = {}
    for token in CODEC.factories:
        card = CODEC.factories[token]()
        cards[token] = dict(cost=card.cost, damage=card.base_damage, block=card.base_block,
                            keywords=sorted(card.keywords), effects=card.effect_vars,
                            card_type=card.card_type.name, target=card.target_type.name)
    atomic_json(root / "content_manifest.json", dict(
        version=BOSS_CONTENT, cards=cards, encounters=BOSS_PROFILES,
        generated_only=["GIANT_ROCK", "SOUL", "DAZED", "BURN", "WOUND"],
        player="Ironclad", ascension=0, max_cards=MAX_CARDS, action_size=ACTION_SIZE,
        reward=V6, boss_forms=[100, 200, 300], fixed_boss_hp_budget=600,
        promotion_policy="network-only-v1", search_role="observation",
        unsupported=["other bosses", "arbitrary primary summons", "relics", "potions", "multiplayer", "other characters"],
        audit_sources=[f"decompiled/MegaCrit.Sts2.Core.Models.{kind}/{name}.cs" for kind,name in (
            ("Monsters","TestSubject"),("Powers","AdaptablePower"),("Powers","EnragePower"),
            ("Powers","PainfulStabsPower"),("Powers","NemesisPower"),("Powers","IntangiblePower"),
            ("Cards","Burn"),("Cards","Wound"))]))
    atomic_json(root / "generator.json", generator_config(BOSS_CONTENT))
    schema = schema_for("observable", V6, BOSS_CONTENT)
    atomic_json(root / "encoder_schema.json", dict(schema=schema, sha256=content_hash(schema)))
    for seed in (42, 43):
        atomic_json(root / f"seed-{seed}.json", asdict(TrainingConfig(
            seed=seed, workers=8, iterations=3, episodes_per_iteration=180, simulations=8,
            eval_simulations=8, updates=16, batch_size=64, content_version=BOSS_CONTENT, reward_version=V6)))
    save_manifest("data/az/g2_boss_v1_manifest.json", frozen_manifest(BOSS_CONTENT))


if __name__ == "__main__":
    prepare()
