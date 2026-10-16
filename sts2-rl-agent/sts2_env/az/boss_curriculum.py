"""Versioned full-fight curriculum; no HP edits, phase skips or teacher labels."""
from dataclasses import replace
import numpy as np

from .content import BOSS_CONTENT
from .scenarios import DeckEntry

VERSION = "boss-course-v1"
VARIANTS = ((3, 2, 1), (5, 3, 1), (2, 3, 1))  # Shrug, Body Slam, Purity
HELDOUT_MASTERS = {"validation": 187, "test": 285}


def configuration():
    return dict(version=VERSION, content=BOSS_CONTENT, episodes_per_iteration=180,
                training_mix={"retained":90,"focused_boss":90},
                retained_rotation="90 of 180 original strata per round; all within two rounds",
                focused_family="ironclad-block", focused_hp=[40,60,80],
                variants=[list(v) for v in VARIANTS], all_focused_cards_upgraded=True,
                phases="ordinary first-form start; native full fight only",
                heldout_master_seeds=HELDOUT_MASTERS, validation_count=256, final_test_count=216,
                train_master_offset=4, initial_weights="same-schema previous Boss champion; fresh optimizer")


def profile(scenario_id):
    return "focused" if scenario_id.startswith((VERSION + "-focus-", "boss-search-course-v1-focus-")) else "retained"


def generate(master, iteration, job, split="train"):
    from .generation import generate_recipe
    if (type(job) is not int or not 0 <= job < (180 if split == "train" else 256 if split == "validation" else 216)
            or split not in ("train","validation","test") or type(master) is not int
            or (split == "train" and not 0 <= master < 124)):
        raise ValueError("Unsupported curriculum coordinates")
    focused = job >= (90 if split == "train" else 180)
    # The inherited generator adds iteration to its stratum index itself.
    slot = (iteration * 90 + job - iteration) % 180 if not focused and split == "train" else job
    source_master = master + 4 if split == "train" else master
    recipe = generate_recipe(source_master, iteration, slot, split, BOSS_CONTENT)
    offset = job - (90 if split == "train" else 180)
    if focused:
        shrugs, slams, purity = VARIANTS[(offset // 3) % len(VARIANTS)]
        counts = dict(BODY_SLAM=slams, IRON_WAVE=1, IMPERVIOUS=1, ARMAMENTS=1,
                      EQUILIBRIUM=1, SHRUG_IT_OFF=shrugs, PURITY=purity)
        recipe = replace(recipe, family_id="ironclad-block", encounter_id="setup_test_subject_boss",
                         player_hp=(40,60,80)[offset % 3],
                         deck=tuple(DeckEntry(n, True, c) for n,c in sorted(counts.items())))
    env_seed = (7 * 2**27 + source_master * 2**20 + iteration * 1024 + job if split == "train"
                else 2**30 + (1_000_000 if split == "test" else 0) + master * 1024 + job)
    return replace(recipe, environment_seed=env_seed,
                   scenario_id=f"{VERSION}-{'focus' if focused else 'retained'}-{split}-{master}-{iteration}-{job}")


def manifest():
    return ([generate(42,0,j) for j in range(180)]
            + [generate(187,0,j,"validation") for j in range(256)]
            + [generate(285,0,j,"test") for j in range(216)])


def block_rule_action(info):
    """Restricted public baseline for curated block decks, not a PUCT heuristic."""
    from sts2_env.gym_env.action_space import action_to_card_and_target
    admitted = {"BODY_SLAM","IRON_WAVE","IMPERVIOUS","ARMAMENTS","EQUILIBRIUM","SHRUG_IT_OFF","PURITY"}
    if (info.content_version != BOSS_CONTENT or info.monster_id != "TEST_SUBJECT"
            or any(t.removesuffix("+") not in admitted for t in info.known_deck)):
        raise ValueError("Block rule baseline only supports curated Boss decks")
    actions = list(map(int,np.flatnonzero(info.legal_mask)))
    if info.choice:
        names = [o.card.token.removesuffix("+") for o in info.choice.options]
        if info.choice.mechanism.removesuffix("+") == "PURITY":
            return max(actions,key=lambda a:(sum(10 if names[i] in ("BURN","WOUND","DAZED") else -1
                                                for i in range(len(names)) if a & (1 << i)), -a))
        return actions[0]
    def rank(action):
        if action == 0:
            return (0,0)
        slot,_ = action_to_card_and_target(action)
        name = info.hand[slot].removesuffix("+")
        score = {"SHRUG_IT_OFF":80,"IMPERVIOUS":65,"IRON_WAVE":60,"ARMAMENTS":50,"EQUILIBRIUM":40,"PURITY":90}.get(name,20)
        if name == "BODY_SLAM":
            score = 30 if info.player_block else -1
        if name == "PURITY" and not any(t in ("BURN","WOUND","DAZED") for t in info.hand):
            score = -1
        return (score,-action)
    return max(actions,key=rank)
