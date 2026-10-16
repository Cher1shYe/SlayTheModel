"""Materialize the reviewed content, schema, generator and held-out manifest."""
from dataclasses import asdict
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sts2_env.az.coordinator import TrainingConfig
from sts2_env.az.config import atomic_json, content_hash
from sts2_env.az.content import DECK_CONTENT
from sts2_env.az.decks import FACTORIES, FAMILIES, FAMILY_CARDS
from sts2_env.az.deck_observation import prototype, TOKENS
from sts2_env.az.encoder import schema_for
from sts2_env.az.generation import GENERATOR_CONFIG, frozen_manifest
from sts2_env.az.rewards import V3
from sts2_env.az.scenarios import save_manifest


def prepare():
    cards = {}
    for token in TOKENS:
        c = prototype(token)
        cards[token] = dict(cost=c.cost, damage=c.base_damage, block=c.base_block, effects=c.effect_vars,
                            keywords=sorted(c.keywords), card_type=c.card_type.name, target=c.target_type.name,
                            factory=f"sts2_env.cards.ironclad.{FACTORIES[c.card_id.name].__name__}")
    content = dict(version=DECK_CONTENT, cards=cards,
                   families={k: dict(required=list(v), allowed=list(FAMILY_CARDS[k])) for k, v in FAMILIES.items()},
                   min_deck_size=6, max_deck_size=20, max_copies_across_upgrades=5,
                   excluded=["choice", "card generation", "temporary costs", "temporary powers", "random targets",
                             "healing", "relics", "potions", "multiplayer", "additional enemies"])
    atomic_json("configs/az_decks_v3/content_manifest.json", content)
    atomic_json("configs/az_decks_v3/generator.json", GENERATOR_CONFIG)
    schema = schema_for("observable", V3, DECK_CONTENT)
    atomic_json("configs/az_decks_v3/encoder_schema.json", dict(schema=schema, sha256=content_hash(schema)))
    for seed in (42, 43):
        atomic_json(f"configs/az_decks_v3/seed-{seed}.json", asdict(TrainingConfig(
            seed=seed, workers=8, reward_version=V3, content_version=DECK_CONTENT)))
    save_manifest("data/az/decks_v3_manifest.json", frozen_manifest())


if __name__ == "__main__":
    prepare()
