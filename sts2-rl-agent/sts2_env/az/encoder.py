"""M1 debug encoder. No instance IDs, RNG or unknown draw order are features.

The world-facing entry point is deliberately named encode_debug: public-state
projection and sufficiency are a separate M2 contract, not implied by this API.
"""
from dataclasses import dataclass
import numpy as np

from .scenarios import STARTER  # engine registration order
from .config import ACTION_VERSION, CONTENT_VERSION, atomic_json, content_hash
from .rewards import V1, V2, V3, V4, V5, V6, V7, validate_reward
from .content import M6_CONTENT, M6_INFORMATION, DECK_CONTENT, HARD_CONTENT, EXPANDED_CONTENT, G1_CONTENT, GEN_CONTENT, UP_CONTENT, TOP_CONTENT, LIFE_CONTENT, SEL_CONTENT, SET_CONTENT, MORPH_CONTENT, MULTI_CONTENT, SUMMON_CONTENT, PROFILES, EXTRA_MOVES, validate_content
from .content import BOSS_CONTENT
from sts2_env.gym_env.action_space import get_action_mask
from sts2_env.core.enums import CombatSide

ENCODER_VERSION = "az-debug-encoder-v1"
MODE = "full_state_debug"
CARDS = ("PAD", "STRIKE_IRONCLAD", "DEFEND_IRONCLAD", "BASH")
POWERS = ("SHRINK", "VULNERABLE")
MOVES = ("SHRINKER_MOVE", "CHOMP_MOVE", "STOMP_MOVE")
CARD_FEATURES = ("present", "upgraded", "cost/3", "original_cost/3", "x_cost",
                 "base_damage/10", "base_block/10", "vulnerable/3")


def _numeric_names():
    names = ["player.hp/80", "player.max_hp/80", "player.block/100", "energy/3",
             "max_energy/3", "turn/100", "decisions/400", "played_this_turn/10",
             "phase.normal", "phase.choice"]
    for owner in ("player", "enemy"):
        for power in POWERS:
            names.extend(f"{owner}.{power}.{field}" for field in
                         ("present", "amount/10", "skip_next_tick", "ignore_next_instance",
                          "applier.none", "applier.player", "applier.enemy"))
    names.extend(("enemy.SHRINKER_BEETLE", "enemy.alive", "enemy.hp/80", "enemy.max_hp/80",
                  "enemy.block/100", "intent.attack", "intent.debuff_strong", "intent.damage/20", "intent.hits/5"))
    names.extend(f"observed_moves.{move}/100" for move in MOVES)
    for pile in ("draw", "discard", "exhaust"):
        names.extend(f"{pile}.{card}/10" for card in CARDS[1:])
    return names


SCHEMA = {
    "encoder_version": ENCODER_VERSION, "information_mode": MODE,
    "action_schema_version": ACTION_VERSION, "content_manifest_version": CONTENT_VERSION,
    "card_vocabulary": list(CARDS), "power_vocabulary": list(POWERS),
    "monster_vocabulary": ["SHRINKER_BEETLE"], "card_features": list(CARD_FEATURES),
    "numeric_features": _numeric_names(), "hand_slots": 10, "action_size": 115,
    "shapes": {"card_ids": [10], "card_features": [10, len(CARD_FEATURES)],
               "numeric": [len(_numeric_names())], "legal_mask": [115]},
    "normalization": "Divisors are explicit in feature names; no clipping",
    "constraints": "No known-position effects in starter scope; unordered pile composition only",
    "unsupported": ["choice", "upgraded", "relics", "potions", "card_modifications", "other_encounters"],
}
SCHEMA_HASH = content_hash(SCHEMA)


@dataclass
class EncodedObservation:
    card_ids: np.ndarray
    card_features: np.ndarray
    numeric: np.ndarray
    legal_mask: np.ndarray
    information_mode: str = MODE
    reward_version: str = V1
    content_version: str = CONTENT_VERSION

    def to_dict(self):
        return {key: getattr(self, key).tolist() for key in SCHEMA["shapes"]}


def save_schema(path):
    atomic_json(path, {"schema": SCHEMA, "sha256": SCHEMA_HASH})


def _card_index(card):
    name = card.card_id.name
    if name not in CARDS[1:] or card.upgraded:
        raise ValueError(f"Unsupported card: {name}, upgraded={card.upgraded}")
    expected = {"STRIKE_IRONCLAD": (1, 6, None, {}), "DEFEND_IRONCLAD": (1, None, 5, {}),
                "BASH": (2, 8, None, {"vulnerable": 2})}[name]
    if (card.cost, card.base_damage, card.base_block, card.effect_vars) != expected:
        raise ValueError("Unsupported card numeric modifications")
    # The engine stamps this zero-valued bookkeeping key on every played card,
    # including Ironclad cards. It has no effect in the no-star scope.
    combat_vars = {key: value for key, value in card.combat_vars.items()
                   if not (key == "_stars_spent_for_play" and value == 0)}
    if (card.original_cost != card.cost or card.keywords or card.enchantments or combat_vars
            or card.has_energy_cost_x or card.star_cost or card.has_star_cost_x
            or card.single_turn_retain or card.bound or card.base_replay_count):
        raise ValueError("Unsupported card temporary state/keywords")
    return CARDS.index(name)


def _power_features(creature, world):
    if any(p.name not in POWERS for p in creature.powers):
        raise ValueError("Unsupported power")
    values = []
    for name in POWERS:
        power = next((p for key, p in creature.powers.items() if key.name == name), None)
        if power is None:
            values.extend([0] * 7)
        else:
            sources = (None, world.player, world.enemies[0])
            if not any(power.applier is source for source in sources):
                raise ValueError("Unknown power applier")
            values.extend([1, power.amount / 10, power.skip_next_tick, power.ignore_next_instance,
                           *(power.applier is source for source in sources)])
    return values


def encode_debug(world, decisions=0):
    if world.pending_choice is not None or world.current_side != CombatSide.PLAYER:
        raise ValueError("Unsupported decision phase")
    if world.relics or any(p is not None for p in world.potions) or world.is_multiplayer:
        raise ValueError("Unsupported resources/multiplayer")
    if len(world.enemies) != 1 or world.enemies[0].monster_id != "SHRINKER_BEETLE":
        raise ValueError("Unsupported enemy schema")
    if len(world.hand) > 10 or world.ascension_level != 0:
        raise ValueError("Hand capacity/ascension unsupported")
    ids = np.zeros(10, dtype=np.int64)
    hand = np.zeros((10, len(CARD_FEATURES)), dtype=np.float32)
    for i, card in enumerate(world.hand):
        ids[i] = _card_index(card)
        hand[i] = [1, card.upgraded, card.cost / 3, card.original_cost / 3,
                   card.has_energy_cost_x, (card.base_damage or 0) / 10,
                   (card.base_block or 0) / 10, card.effect_vars.get("vulnerable", 0) / 3]
    player, enemy = world.player, world.enemies[0]
    values = [player.current_hp / 80, player.max_hp / 80, player.block / 100,
              world.energy / 3, world.max_energy / 3, world.turn_count / 100, decisions / 400,
              len(world._played_cards_this_turn) / 10, 1, 0]
    values += _power_features(player, world) + _power_features(enemy, world)
    ai = world.enemy_ais[enemy.combat_id]
    intents = ai.current_move.intents
    if len(intents) != 1 or intents[0].intent_type.name not in ("ATTACK", "DEBUFF_STRONG"):
        raise ValueError("Unsupported intent")
    intent = intents[0]
    values += [1, enemy.is_alive, enemy.current_hp / 80, enemy.max_hp / 80, enemy.block / 100,
               intent.intent_type.name == "ATTACK", intent.intent_type.name == "DEBUFF_STRONG",
               intent.damage / 20, intent.hits / 5]
    if any(move not in MOVES for move in ai.state_log):
        raise ValueError("Unsupported move history")
    values += [ai.state_log.count(move) / 100 for move in MOVES]
    for pile in (world.draw_pile, world.discard_pile, world.exhaust_pile):
        counts = [0] * 3
        for card in pile:
            counts[_card_index(card) - 1] += 1
        values += [count / 10 for count in counts]
    mask = get_action_mask(world).astype(bool)
    if world.is_over:
        mask[:] = False
    if mask.shape != (115,) or mask[61:].any() or (not world.is_over and not mask.any()):
        raise ValueError("Invalid action mask")
    numeric = np.asarray(values, dtype=np.float32)
    if not np.isfinite(numeric).all() or not np.isfinite(hand).all():
        raise ValueError("Nonfinite observation")
    return EncodedObservation(ids, hand, numeric, mask)


OBSERVABLE_SCHEMA = {
    **SCHEMA, "information_mode": "observable", "encoder_version": "az-observable-encoder-v1",
    "information_version": "shrinker-information-v1",
    "numeric_features": [*_numeric_names(), "decision_limit/400", "turn_limit/100"],
    "shapes": {**SCHEMA["shapes"], "numeric": [len(_numeric_names()) + 2]},
    "history_source": "Explicit PublicHistory; no engine AI history or private power flags",
}


def schema_for(mode, reward_version=V1, content_version=CONTENT_VERSION):
    validate_reward(reward_version)
    validate_content(content_version)
    if content_version in (DECK_CONTENT, HARD_CONTENT, EXPANDED_CONTENT, G1_CONTENT, GEN_CONTENT, UP_CONTENT, TOP_CONTENT, LIFE_CONTENT, SEL_CONTENT, SET_CONTENT, MORPH_CONTENT, MULTI_CONTENT, SUMMON_CONTENT, BOSS_CONTENT):
        expected_reward = (V6 if content_version == BOSS_CONTENT else V5 if content_version == SUMMON_CONTENT
                           else V4 if content_version == MULTI_CONTENT else V3)
        if mode != "observable" or (reward_version != expected_reward and not (content_version == BOSS_CONTENT and reward_version == V7)):
            raise ValueError("Deck content requires its versioned observable reward")
        from .deck_observation import schema
        return schema(content_version)
    if reward_version in (V3, V4, V5, V6, V7):
        raise ValueError("Reward v3 requires deck content schema")
    if content_version == M6_CONTENT:
        if mode != "observable" or reward_version != V2:
            raise ValueError("M6 requires observable HP reward v2")
        base = schema_for(mode, reward_version)
        extra = [f"monster.{m}" for m in PROFILES] + ["enemy.strength/100", "intent.buff"]
        extra += [f"observed_moves.{m}/100" for m in EXTRA_MOVES]
        return {**base, "encoder_version": "az-three-weak-encoder-v1", "content_manifest_version": M6_CONTENT,
                "information_version": M6_INFORMATION,
                "monster_vocabulary": list(PROFILES), "power_vocabulary": [*POWERS, "STRENGTH"],
                "numeric_features": [*base["numeric_features"][:-1], *extra, "initial_hp/80"],
                "shapes": {**base["shapes"], "numeric": [len(base["numeric_features"]) + len(extra)]}}
    if reward_version == V2:
        if mode != "observable":
            raise ValueError("HP reward requires observable mode")
        return {**OBSERVABLE_SCHEMA, "encoder_version": "az-observable-hp-encoder-v2",
                "reward_version": V2,
                "numeric_features": [*OBSERVABLE_SCHEMA["numeric_features"], "initial_hp/80"],
                "shapes": {**OBSERVABLE_SCHEMA["shapes"], "numeric": [len(_numeric_names()) + 3]}}
    if mode == MODE:
        return SCHEMA
    if mode == "observable":
        return OBSERVABLE_SCHEMA
    raise ValueError("Unknown information mode")


def encode_information(info):
    from .information import InformationState
    if type(info) is not InformationState:
        raise TypeError("Observable encoder accepts only InformationState")
    info.validate()
    if info.content_version in (DECK_CONTENT, HARD_CONTENT, EXPANDED_CONTENT, G1_CONTENT, GEN_CONTENT, UP_CONTENT, TOP_CONTENT, LIFE_CONTENT, SEL_CONTENT, SET_CONTENT, MORPH_CONTENT, MULTI_CONTENT, SUMMON_CONTENT, BOSS_CONTENT):
        from .deck_observation import encode
        return encode(info)
    ids = np.zeros(10, dtype=np.int64)
    hand = np.zeros((10, len(CARD_FEATURES)), dtype=np.float32)
    for i, name in enumerate(info.hand):
        ids[i] = CARDS.index(name)
        cost, damage, block, vulnerable = {"STRIKE_IRONCLAD": (1, 6, 0, 0),
                                         "DEFEND_IRONCLAD": (1, 0, 5, 0), "BASH": (2, 8, 0, 2)}[name]
        hand[i] = [1, 0, cost / 3, cost / 3, 0, damage / 10, block / 10, vulnerable / 3]
    values = [info.player_hp / 80, info.player_max_hp / 80, info.player_block / 100,
              info.energy / 3, info.max_energy / 3, info.turn / 100, info.history.decisions / 400,
              len(info.history.played_this_turn) / 10, 1, 0]
    values += ([1, info.shrink / 10, 1, 0, 0, 0, 1] if info.shrink else [0] * 7)
    values += [0] * 14  # player Vulnerable and enemy Shrink are absent in the audited scope
    values += ([1, info.vulnerable / 10, 0, 0, 0, 1, 0] if info.vulnerable else [0] * 7)
    name, damage, hits = info.intent
    values += [info.monster_id == "SHRINKER_BEETLE", info.enemy_hp > 0, info.enemy_hp / 80, info.enemy_max_hp / 80,
               info.enemy_block / 100, name == "ATTACK", name == "DEBUFF_STRONG", damage / 20, hits / 5]
    values += [info.history.enemy_moves.count(move) / 100 for move in MOVES]
    for pile in (info.draw_composition, info.discard, info.exhaust):
        values += [pile.count(card) / 10 for card in CARDS[1:]]
    values += [info.limits.max_decisions / 400, info.limits.max_turns / 100]
    if info.content_version == M6_CONTENT:
        values += [info.monster_id == m for m in PROFILES] + [info.enemy_strength / 100, name == "BUFF"]
        values += [info.history.enemy_moves.count(m) / 100 for m in EXTRA_MOVES]
    if info.reward_version == V2:
        values += [info.initial_hp / 80]
    return EncodedObservation(ids, hand, np.asarray(values, dtype=np.float32),
                              np.asarray(info.legal_mask, dtype=bool), "observable", info.reward_version, info.content_version)
