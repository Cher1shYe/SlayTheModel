"""Explicit, narrowly whitelisted world recipes. Never pass recipes to a planner."""
from dataclasses import asdict, dataclass
import json
from pathlib import Path

# Preserve the engine's content-registration import order.
from sts2_env.gym_env.combat_env import STS2CombatEnv  # noqa: F401
import sts2_env.powers  # noqa: F401
from sts2_env.cards.ironclad import create_ironclad_starter_deck
from sts2_env.core.combat import CombatState
from sts2_env.core.rng import Rng
from sts2_env.encounters.act1 import setup_shrinker_beetle_weak
from .config import SCHEMA_VERSION, RULES_VERSION, CONTENT_VERSION, atomic_json, content_hash
from .content import M6_CONTENT, DECK_CONTENT, HARD_CONTENT, EXPANDED_CONTENT, G1_CONTENT, GEN_CONTENT, UP_CONTENT, TOP_CONTENT, LIFE_CONTENT, SEL_CONTENT, SET_CONTENT, MORPH_CONTENT, MULTI_CONTENT, PROFILES, profiles, validate_content
from .decks import create_deck, validate_deck

STARTER = (("STRIKE_IRONCLAD", False, 5), ("DEFEND_IRONCLAD", False, 4), ("BASH", False, 1))


@dataclass(frozen=True)
class DeckEntry:
    card_id: str
    upgraded: bool
    count: int


@dataclass(frozen=True)
class CombatScenario:
    schema_version: str
    scenario_id: str
    family_id: str
    split: str
    character_id: str
    ascension: int
    encounter_id: str
    deck: tuple[DeckEntry, ...]
    player_hp: int
    player_max_hp: int
    relics: tuple
    potions: tuple
    environment_seed: int
    rules_version: str
    content_manifest_version: str

    def __post_init__(self):
        validate_content(self.content_manifest_version)
        if (self.schema_version, self.rules_version) != (SCHEMA_VERSION, RULES_VERSION):
            raise ValueError("Incompatible scenario versions")
        if self.character_id != "Ironclad" or type(self.ascension) is not int or self.ascension != 0:
            raise ValueError("Only Ironclad ascension 0 is supported")
        allowed = ([p["encounter"] for p in profiles(self.content_manifest_version).values()] if self.content_manifest_version in (M6_CONTENT, DECK_CONTENT, HARD_CONTENT, EXPANDED_CONTENT, G1_CONTENT, GEN_CONTENT, UP_CONTENT, TOP_CONTENT, LIFE_CONTENT, SEL_CONTENT, SET_CONTENT, MORPH_CONTENT, MULTI_CONTENT)
                   else ["setup_shrinker_beetle_weak"])
        if self.encounter_id not in allowed or self.relics or self.potions:
            raise ValueError("Unsupported encounter, relics or potions")
        if self.split not in ("train", "validation", "test") or not self.scenario_id:
            raise ValueError("Invalid scenario identity/split")
        if self.content_manifest_version in (DECK_CONTENT, HARD_CONTENT, EXPANDED_CONTENT, G1_CONTENT, GEN_CONTENT, UP_CONTENT, TOP_CONTENT, LIFE_CONTENT, SEL_CONTENT, SET_CONTENT, MORPH_CONTENT, MULTI_CONTENT):
            validate_deck(self.deck, self.family_id, self.content_manifest_version)
        elif self.family_id != "ironclad-starter":
            raise ValueError("Unsupported deck family")
        if self.content_manifest_version not in (DECK_CONTENT, HARD_CONTENT, EXPANDED_CONTENT, G1_CONTENT, GEN_CONTENT, UP_CONTENT, TOP_CONTENT, LIFE_CONTENT, SEL_CONTENT, SET_CONTENT, MORPH_CONTENT, MULTI_CONTENT) and tuple((c.card_id, c.upgraded, c.count) for c in self.deck) != STARTER:
            raise ValueError("Only the ordered, unupgraded starter recipe is supported")
        if any(type(c.upgraded) is not bool or type(c.count) is not int for c in self.deck):
            raise ValueError("Invalid deck field types")
        if any(type(n) is not int for n in (self.player_hp, self.player_max_hp, self.environment_seed)):
            raise ValueError("HP and seed must be integers")
        if not 0 < self.player_hp <= self.player_max_hp == 80 or not 0 <= self.environment_seed < 2**31:
            raise ValueError("Unsupported HP or seed")

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, value):
        value = dict(value)
        value["deck"] = tuple(DeckEntry(**entry) for entry in value["deck"])
        for name in ("relics", "potions"):
            value[name] = tuple(value[name])
        return cls(**value)


def starter_scenario(seed, split="train", hp=80):
    return CombatScenario(SCHEMA_VERSION, f"shrinker-{split}-{seed}", "ironclad-starter", split,
                          "Ironclad", 0, "setup_shrinker_beetle_weak",
                          tuple(DeckEntry(*entry) for entry in STARTER), hp, 80, (), (), seed,
                          RULES_VERSION, CONTENT_VERSION)


def make_scenario(recipe):
    # Revalidate at the boundary; never implicitly add character relics.
    recipe = CombatScenario.from_dict(recipe.to_dict())
    world = CombatState(player_hp=recipe.player_hp, player_max_hp=recipe.player_max_hp,
                        deck=create_deck(recipe.deck, recipe.family_id, recipe.content_manifest_version), rng_seed=recipe.environment_seed,
                        relics=[], potions=[], character_id=recipe.character_id, ascension_level=0)
    from sts2_env.encounters import act1
    getattr(act1, recipe.encounter_id)(world, Rng(recipe.environment_seed))
    world.start_combat()
    return world


def validate_manifest(recipes):
    ids, seeds = set(), set()
    for recipe in recipes:
        CombatScenario.from_dict(recipe.to_dict())
        if recipe.scenario_id in ids or recipe.environment_seed in seeds:
            raise ValueError("Duplicate scenario ID or seed (including across splits)")
        ids.add(recipe.scenario_id)
        seeds.add(recipe.environment_seed)
    if not recipes:
        raise ValueError("Empty manifest")


def save_manifest(path, recipes):
    validate_manifest(recipes)
    records = [recipe.to_dict() for recipe in recipes]
    atomic_json(path, {"scenarios": records, "sha256": content_hash(records)})


def load_manifest(path):
    document = json.loads(Path(path).read_text(encoding="utf-8"))
    if content_hash(document["scenarios"]) != document["sha256"]:
        raise ValueError("Manifest content hash mismatch")
    recipes = [CombatScenario.from_dict(record) for record in document["scenarios"]]
    validate_manifest(recipes)
    return recipes


def balanced_selection(recipes, count):
    """Stable round-robin selection across deck-family/encounter strata."""
    groups = {}
    for recipe in recipes:
        key = (recipe.family_id, recipe.encounter_id)
        if recipe.content_manifest_version in (DECK_CONTENT, HARD_CONTENT, EXPANDED_CONTENT, G1_CONTENT, GEN_CONTENT, UP_CONTENT, TOP_CONTENT, LIFE_CONTENT, SEL_CONTENT, SET_CONTENT, MORPH_CONTENT, MULTI_CONTENT):
            key += (recipe.player_hp,)
        groups.setdefault(key, []).append(recipe)
    if count < 1 or not groups:
        raise ValueError("Nonempty strata required")
    keys = sorted(groups)
    if recipes and all(r.content_manifest_version in (DECK_CONTENT, HARD_CONTENT, EXPANDED_CONTENT, G1_CONTENT, GEN_CONTENT, UP_CONTENT, TOP_CONTENT, LIFE_CONTENT, SEL_CONTENT, SET_CONTENT, MORPH_CONTENT, MULTI_CONTENT) for r in recipes):
        if count > len(recipes):
            raise ValueError("Insufficient recipes for balanced selection")
        # Frozen strata may have unequal quotas (256 is not divisible by 36).
        # Consume every available quota without repeating or dropping scenarios.
        selected = []
        position = 0
        while len(selected) < count:
            for key in keys:
                if position < len(groups[key]):
                    selected.append(groups[key][position])
                    if len(selected) == count:
                        return selected
            position += 1
        return selected
    selected = []
    for i in range(count):
        group = groups[keys[i % len(keys)]]
        position = i // len(keys)
        if position >= len(group):
            raise ValueError("Insufficient recipes for balanced selection")
        selected.append(group[position])
    return selected
