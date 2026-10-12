"""Frozen stratified recipes with disjoint, injective environment-seed spaces."""
from collections import Counter
import random
from .config import SCHEMA_VERSION, RULES_VERSION, derive_seed
from .content import DECK_CONTENT, HARD_CONTENT, EXPANDED_CONTENT, G1_CONTENT, GEN_CONTENT, UP_CONTENT, TOP_CONTENT, LIFE_CONTENT, SEL_CONTENT, SET_CONTENT, MORPH_CONTENT, MULTI_CONTENT, MULTI_PROFILES, EXPANDED_PROFILES, HARD_PROFILES, PROFILES
from .decks import MORPH_FAMILIES, MORPH_FAMILY_CARDS, SEL_FAMILIES, SEL_FAMILY_CARDS, LIFE_FAMILIES, LIFE_FAMILY_CARDS, TOP_FAMILIES, TOP_FAMILY_CARDS, UP_FAMILIES, UP_FAMILY_CARDS, GEN_FAMILIES, GEN_FAMILY_CARDS, G1_FAMILIES, G1_FAMILY_CARDS, EXPANDED_FAMILIES, EXPANDED_FAMILY_CARDS, FAMILIES, FAMILY_CARDS, MAX_COPIES
from .scenarios import CombatScenario, DeckEntry, STARTER

HP_TIERS = (15, 25, 40)
STRATA = tuple((family, profile["encounter"], hp) for family in FAMILIES
               for profile in PROFILES.values() for hp in HP_TIERS)
GENERATOR_VERSION = "decks-generator-v1"
GENERATOR_CONFIG = dict(version=GENERATOR_VERSION, content=DECK_CONTENT, hp_tiers=list(HP_TIERS),
                        families={k: list(v) for k, v in FAMILIES.items()},
                        family_cards={k: list(v) for k, v in FAMILY_CARDS.items()},
                        min_cards=6, max_cards=20, max_copies=5, upgrade_probability=0.35,
                        weights="uniform family/encounter/HP round robin; quotas differ by <=1",
                        deletions="starter Strike/Defend counts 2..5 / 2..4 in nonstarter families",
                        starter="exact 5 Strike + 4 Defend + Bash, unupgraded",
                        seed_spaces="train [0,2^30); validation [2^30,2^30+1000000); test [2^30+1000000,2^30+2000000)")


HARD_STRATA = tuple((family, profile["encounter"], hp) for family in FAMILIES
                    for name, profile in HARD_PROFILES.items()
                    for hp in ((40, 60, 80) if name not in PROFILES else HP_TIERS))
HARD_GENERATOR_CONFIG = {**GENERATOR_CONFIG, "version": "hard-generator-v2", "content": HARD_CONTENT,
                         "elite_hp_tiers": [40, 60, 80], "encounters": list(HARD_PROFILES),
                         "strata": 60, "train_seed_offset": 2**28,
                         "heldout_master_seeds": {"validation": 174, "test": 272}}


EXPANDED_STRATA = tuple((family, profile["encounter"], hp) for family in EXPANDED_FAMILIES
                        for name, profile in EXPANDED_PROFILES.items()
                        for hp in ((40, 60, 80) if name not in PROFILES else HP_TIERS))
EXPANDED_GENERATOR_CONFIG = {**HARD_GENERATOR_CONFIG, "version": "expanded-generator-v3", "content": EXPANDED_CONTENT,
    "families": {k:list(v) for k,v in EXPANDED_FAMILIES.items()},
    "family_cards": {k:list(v) for k,v in EXPANDED_FAMILY_CARDS.items()},
    "encounters": list(EXPANDED_PROFILES), "strata": len(EXPANDED_STRATA), "train_seed_offset": 2**29,
    "heldout_master_seeds": {"validation": 175, "test": 273}}


MULTI_STRATA = tuple((family, profile["encounter"], hp) for family in MORPH_FAMILIES
                     for name, profile in MULTI_PROFILES.items()
                     for hp in ((40, 60, 80) if name not in PROFILES else HP_TIERS))


def generator_config(content_version):
    if content_version == MULTI_CONTENT:
        from .content import MULTI_PROFILES
        return {**generator_config(MORPH_CONTENT), "version": "multi-generator-v1", "content": MULTI_CONTENT,
                "encounters": list(MULTI_PROFILES), "strata": len(MULTI_STRATA),
                "train_seed_offset": 14 * 2**27, "heldout_master_seeds": {"validation": 184, "test": 282},
                "seed_spaces": "train [14*2^27,15*2^27); heldout 2^30 + split offset + master*1024 + job"}
    if content_version in (MORPH_CONTENT, MULTI_CONTENT):
        return {**generator_config(SET_CONTENT), "version": "morph-generator-v1", "content": MORPH_CONTENT,
                "families": {k:list(v) for k,v in MORPH_FAMILIES.items()},
                "family_cards": {k:list(v) for k,v in MORPH_FAMILY_CARDS.items()},
                "train_seed_offset": 13 * 2**27, "heldout_master_seeds": {"validation": 183, "test": 281},
                "seed_spaces": "train [13*2^27,14*2^27); heldout 2^30 + split offset + master*1024 + job"}

    if content_version in (SET_CONTENT, MORPH_CONTENT, MULTI_CONTENT):
        return {**generator_config(SEL_CONTENT), "version": "selection-generator-v2", "content": SET_CONTENT,
                "train_seed_offset": 9 * 2**27, "heldout_master_seeds": {"validation": 182, "test": 280},
                "seed_spaces": "train [9*2^27,10*2^27); heldout 2^30 + split offset + master*1024 + job"}

    if content_version in (SEL_CONTENT, SET_CONTENT, MORPH_CONTENT, MULTI_CONTENT):
        return {**generator_config(LIFE_CONTENT), "version": "selection-generator-v1", "content": SEL_CONTENT,
                "families": {k:list(v) for k,v in SEL_FAMILIES.items()}, "family_cards": {k:list(v) for k,v in SEL_FAMILY_CARDS.items()},
                "extra_cards": "0..4 sampled additions, stop at the explicit 20-card deck bound",
                "train_seed_offset": 11 * 2**27, "heldout_master_seeds": {"validation": 181, "test": 279},
                "seed_spaces": "train [11*2^27,12*2^27); heldout 2^30 + split offset + master*1024 + job"}

    if content_version == LIFE_CONTENT:
        return {**generator_config(TOP_CONTENT), "version": "lifecycle-generator-v1", "content": LIFE_CONTENT,
                "families": {k:list(v) for k,v in LIFE_FAMILIES.items()}, "family_cards": {k:list(v) for k,v in LIFE_FAMILY_CARDS.items()},
                "train_seed_offset": 15 * 2**27, "heldout_master_seeds": {"validation": 180, "test": 278}}

    if content_version == TOP_CONTENT:
        return {**generator_config(UP_CONTENT), "version": "topdeck-generator-v1", "content": TOP_CONTENT,
                "families": {k:list(v) for k,v in TOP_FAMILIES.items()}, "family_cards": {k:list(v) for k,v in TOP_FAMILY_CARDS.items()},
                "train_seed_offset": 7 * 2**28, "heldout_master_seeds": {"validation": 179, "test": 277}}
    if content_version == UP_CONTENT:
        return {**generator_config(GEN_CONTENT), "version": "upgrades-generator-v1", "content": UP_CONTENT,
                "families": {k:list(v) for k,v in UP_FAMILIES.items()}, "family_cards": {k:list(v) for k,v in UP_FAMILY_CARDS.items()},
                "train_seed_offset": 6 * 2**28, "heldout_master_seeds": {"validation": 178, "test": 276}}
    if content_version == GEN_CONTENT:
        return {**generator_config(G1_CONTENT), "version": "generated-generator-v1", "content": GEN_CONTENT,
                "families": {k:list(v) for k,v in GEN_FAMILIES.items()}, "family_cards": {k:list(v) for k,v in GEN_FAMILY_CARDS.items()},
                "train_seed_offset": 5 * 2**28, "heldout_master_seeds": {"validation": 177, "test": 275}}
    if content_version == G1_CONTENT:
        return {**EXPANDED_GENERATOR_CONFIG, "version": "g1-generator-v1", "content": G1_CONTENT,
                "families": {k:list(v) for k,v in G1_FAMILIES.items()}, "family_cards": {k:list(v) for k,v in G1_FAMILY_CARDS.items()},
                "train_seed_offset": 3 * 2**28, "heldout_master_seeds": {"validation": 176, "test": 274}}
    if content_version == EXPANDED_CONTENT:
        return EXPANDED_GENERATOR_CONFIG
    return HARD_GENERATOR_CONFIG if content_version == HARD_CONTENT else GENERATOR_CONFIG


def generate_recipe(master_seed, iteration, job_id, split="train", content_version=DECK_CONTENT):
    if (type(master_seed) is not int or not 0 <= master_seed < 1024 or type(iteration) is not int
            or not 0 <= iteration < 1024 or type(job_id) is not int or not 0 <= job_id < 1024
            or split not in ("train", "validation", "test")):
        raise ValueError("Unsupported generator coordinates")
    if split != "train" and iteration != 0:
        raise ValueError("Held-out recipes are fixed at iteration zero")
    families = MORPH_FAMILIES if content_version in (MORPH_CONTENT, MULTI_CONTENT) else SEL_FAMILIES if content_version in (SEL_CONTENT, SET_CONTENT, MORPH_CONTENT, MULTI_CONTENT) else LIFE_FAMILIES if content_version == LIFE_CONTENT else TOP_FAMILIES if content_version == TOP_CONTENT else UP_FAMILIES if content_version == UP_CONTENT else GEN_FAMILIES if content_version == GEN_CONTENT else G1_FAMILIES if content_version == G1_CONTENT else EXPANDED_FAMILIES if content_version == EXPANDED_CONTENT else FAMILIES
    family_cards = MORPH_FAMILY_CARDS if content_version in (MORPH_CONTENT, MULTI_CONTENT) else SEL_FAMILY_CARDS if content_version in (SEL_CONTENT, SET_CONTENT, MORPH_CONTENT, MULTI_CONTENT) else LIFE_FAMILY_CARDS if content_version == LIFE_CONTENT else TOP_FAMILY_CARDS if content_version == TOP_CONTENT else UP_FAMILY_CARDS if content_version == UP_CONTENT else GEN_FAMILY_CARDS if content_version == GEN_CONTENT else G1_FAMILY_CARDS if content_version == G1_CONTENT else EXPANDED_FAMILY_CARDS if content_version == EXPANDED_CONTENT else FAMILY_CARDS
    strata = MULTI_STRATA if content_version == MULTI_CONTENT else EXPANDED_STRATA if content_version in (EXPANDED_CONTENT, G1_CONTENT, GEN_CONTENT, UP_CONTENT, TOP_CONTENT, LIFE_CONTENT, SEL_CONTENT, SET_CONTENT, MORPH_CONTENT, MULTI_CONTENT) else HARD_STRATA if content_version == HARD_CONTENT else STRATA
    family, encounter, hp = strata[(job_id + iteration) % len(strata)]
    rng = random.Random(derive_seed(master_seed, iteration, str(job_id), f"{split}-recipe"))
    if family == "ironclad-starter":
        deck = tuple(DeckEntry(*entry) for entry in STARTER)
    else:
        counts = Counter(STRIKE_IRONCLAD=rng.randint(2, 5), DEFEND_IRONCLAD=rng.randint(2, 4), BASH=1)
        counts.update(families[family])
        for _ in range(rng.randint(0, 4)):
            name = rng.choice(family_cards[family])
            if counts[name] < MAX_COPIES and (content_version not in (SEL_CONTENT, SET_CONTENT, MORPH_CONTENT, MULTI_CONTENT) or sum(counts.values()) < 20):
                counts[name] += 1
        variants = Counter()
        for name, count in sorted(counts.items()):
            for _ in range(count):
                variants[name, rng.random() < 0.35] += 1
        deck = tuple(DeckEntry(name, upgraded, count) for (name, upgraded), count in sorted(variants.items()))
    seed = (master_seed * 1024 * 1024 + iteration * 1024 + job_id if split == "train"
            else 2**30 + (0 if split == "validation" else 1_000_000) + master_seed * 1024 + job_id)
    if content_version in (HARD_CONTENT, EXPANDED_CONTENT, G1_CONTENT, GEN_CONTENT, UP_CONTENT, TOP_CONTENT, LIFE_CONTENT, SEL_CONTENT, SET_CONTENT, MORPH_CONTENT, MULTI_CONTENT) and split == "train":
        if master_seed >= 128:
            raise ValueError("Hard training seed coordinates require master <128")
        seed += 14 * 2**27 if content_version == MULTI_CONTENT else 13 * 2**27 if content_version in (MORPH_CONTENT, MULTI_CONTENT) else 9 * 2**27 if content_version in (SET_CONTENT, MORPH_CONTENT, MULTI_CONTENT) else 11 * 2**27 if content_version in (SEL_CONTENT, SET_CONTENT, MORPH_CONTENT, MULTI_CONTENT) else 15 * 2**27 if content_version == LIFE_CONTENT else 7 * 2**28 if content_version == TOP_CONTENT else 6 * 2**28 if content_version == UP_CONTENT else 5 * 2**28 if content_version == GEN_CONTENT else 3 * 2**28 if content_version == G1_CONTENT else 2**29 if content_version == EXPANDED_CONTENT else 2**28
    # Held-out master coordinates must stay inside their reserved million-slot space.
    if split != "train" and master_seed * 1024 + job_id >= 1_000_000:
        raise ValueError("Held-out seed space exceeded")
    prefix = "multi" if content_version == MULTI_CONTENT else "morph" if content_version in (MORPH_CONTENT, MULTI_CONTENT) else "set" if content_version in (SET_CONTENT, MORPH_CONTENT, MULTI_CONTENT) else "sel" if content_version in (SEL_CONTENT, SET_CONTENT, MORPH_CONTENT, MULTI_CONTENT) else "life" if content_version == LIFE_CONTENT else "top" if content_version == TOP_CONTENT else "up" if content_version == UP_CONTENT else "gen" if content_version == GEN_CONTENT else "g1" if content_version == G1_CONTENT else "expanded" if content_version == EXPANDED_CONTENT else "hard" if content_version == HARD_CONTENT else "decks"
    return CombatScenario(SCHEMA_VERSION, f"{prefix}-{split}-{master_seed}-{iteration}-{job_id}", family, split,
                          "Ironclad", 0, encounter, deck, hp, 80, (), (), seed, RULES_VERSION, content_version)


def frozen_manifest(content_version=DECK_CONTENT):
    offset = 11 if content_version == MULTI_CONTENT else 10 if content_version in (MORPH_CONTENT, MULTI_CONTENT) else 9 if content_version in (SET_CONTENT, MORPH_CONTENT, MULTI_CONTENT) else 8 if content_version in (SEL_CONTENT, SET_CONTENT, MORPH_CONTENT, MULTI_CONTENT) else 7 if content_version == LIFE_CONTENT else 6 if content_version == TOP_CONTENT else 5 if content_version == UP_CONTENT else 4 if content_version == GEN_CONTENT else 3 if content_version == G1_CONTENT else 2 if content_version == EXPANDED_CONTENT else int(content_version == HARD_CONTENT)
    return ([generate_recipe(42, 0, j, content_version=content_version) for j in range(256)]
            + [generate_recipe(173 + offset, 0, j, "validation", content_version) for j in range(256)]
            + [generate_recipe(271 + offset, 0, j, "test", content_version) for j in range(150)])
