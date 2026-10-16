"""Public features for the frozen eight-card pool, including consumed powers."""
from collections import Counter
from dataclasses import fields
from functools import lru_cache
import numpy as np

from .content import DECK_CONTENT, HARD_CONTENT, EXPANDED_CONTENT, G1_CONTENT, GEN_CONTENT, UP_CONTENT, TOP_CONTENT, LIFE_CONTENT, SEL_CONTENT, SET_CONTENT, MORPH_CONTENT, MULTI_CONTENT, SUMMON_CONTENT, EXPANDED_PROFILES, EXPANDED_MOVES, HARD_PROFILES, HARD_MOVES, PROFILES, EXTRA_MOVES
from .content import BOSS_CONTENT
from .decks import EXPANDED_FACTORIES, FACTORIES, MIN_DECK_SIZE, MAX_DECK_SIZE, MAX_COPIES, make_token, card_token
from .rewards import V3, V4, V5, V6
from sts2_env.cards import base as card_base

TOKENS = tuple(name + suffix for name in FACTORIES for suffix in ("", "+"))
EXPANDED_TOKENS = tuple(name + suffix for name in EXPANDED_FACTORIES for suffix in ("", "+"))
FEATURES = ("present", "upgraded", "cost/3", "original_cost/3", "x_cost", "damage/10", "block/10",
            "vulnerable/3", "draw/5", "energy/3", "self_hp_loss/6", "strength/3", "exhaust", "power")


@lru_cache(maxsize=64)
def prototype(token):
    saved = card_base._next_instance_id
    try:
        if token in ("DAZED", "BURN", "WOUND"):
            from sts2_env.cards import status
            return getattr(status, "make_" + token.lower())()
        return make_token(token)
    finally:
        card_base._next_instance_id = saved


def generated_card_count(info):
    """Cards the public generation ledger actually added (multiplicity included)."""
    from .card_generation import generated_tokens
    return len(generated_tokens(info.history.generated, info.history.decisions, info.content_version))


def card_capacity(content_version):
    """Public combat-card ceiling for the versioned schema/encoder."""
    from .content import SUMMON_CONTENT
    from .actions import MAX_SUMMON_CARDS
    return 2145 if content_version == BOSS_CONTENT else MAX_SUMMON_CARDS if content_version == SUMMON_CONTENT else 420


def token_vocabulary(content_version):
    if content_version == BOSS_CONTENT:
        from .boss_cards import TOKENS as BOSS_TOKENS
        return BOSS_TOKENS
    """Frozen public card token vocabulary for one content version."""
    from .content import SUMMON_CONTENT
    from .g1 import (TOKENS as G1_TOKENS, GEN_TOKENS, UP_TOKENS, TOP_TOKENS, LIFE_TOKENS, SEL_TOKENS,
                     MORPH_TOKENS, SUMMON_TOKENS)
    if content_version == SUMMON_CONTENT:
        return SUMMON_TOKENS
    if content_version in (MORPH_CONTENT, MULTI_CONTENT, SUMMON_CONTENT, BOSS_CONTENT):
        return MORPH_TOKENS
    if content_version in (SEL_CONTENT, SET_CONTENT, MORPH_CONTENT, MULTI_CONTENT, SUMMON_CONTENT, BOSS_CONTENT):
        return SEL_TOKENS
    if content_version == LIFE_CONTENT:
        return LIFE_TOKENS
    if content_version == TOP_CONTENT:
        return TOP_TOKENS
    if content_version == UP_CONTENT:
        return UP_TOKENS
    if content_version == GEN_CONTENT:
        return GEN_TOKENS
    if content_version in (G1_CONTENT, GEN_CONTENT, UP_CONTENT, TOP_CONTENT, LIFE_CONTENT, SEL_CONTENT,
                           SET_CONTENT, MORPH_CONTENT, MULTI_CONTENT, SUMMON_CONTENT, BOSS_CONTENT):
        return G1_TOKENS
    return EXPANDED_TOKENS if content_version == EXPANDED_CONTENT else TOKENS


def validate_card(card, content_version=DECK_CONTENT):
    if content_version in (G1_CONTENT, GEN_CONTENT, UP_CONTENT, TOP_CONTENT, LIFE_CONTENT, SEL_CONTENT, SET_CONTENT, MORPH_CONTENT, MULTI_CONTENT, SUMMON_CONTENT, BOSS_CONTENT):
        from .g1 import codec_for
        return codec_for(content_version).capture(card).token
    token = card_token(card)
    if token not in (EXPANDED_TOKENS if content_version == EXPANDED_CONTENT else TOKENS):
        raise ValueError("Unsupported public card")
    reference = prototype(token)
    for field in fields(reference):
        if field.name not in ("instance_id", "combat_vars") and getattr(card, field.name) != getattr(reference, field.name):
            raise ValueError(f"Unsupported public card modification: {token}.{field.name}")
    if any(k != "_stars_spent_for_play" or v != 0 for k, v in card.combat_vars.items()):
        raise ValueError("Unsupported temporary card state")
    return token


def validate_memory(info):
    from .content import SUMMON_CONTENT
    expected = (V6 if info.content_version == BOSS_CONTENT else V5 if info.content_version == SUMMON_CONTENT
                else V4 if info.content_version == MULTI_CONTENT else V3)
    if info.reward_version != expected:
        raise ValueError("Deck content requires the versioned HP reward")
    if (type(info.enemy_initial_hp) is not int or not 0 < info.enemy_initial_hp <= info.enemy_max_hp
            or not MIN_DECK_SIZE <= len(info.known_deck) <= MAX_DECK_SIZE
            or tuple(sorted(info.known_deck)) != info.known_deck):
        raise ValueError("Invalid initial public deck/HP")
    if info.content_version in (MORPH_CONTENT, MULTI_CONTENT, SUMMON_CONTENT, BOSS_CONTENT) and any(t.removesuffix("+") in ("SOUL", "GIANT_ROCK", "DAZED", "BURN", "WOUND") for t in info.known_deck):
        raise ValueError("Generated tokens cannot be in the initial deck")
    vocabulary = token_vocabulary(info.content_version)
    tokens = info.known_deck + info.history.played_this_turn + info.history.removed_powers
    if any(token not in vocabulary for token in tokens):
        raise ValueError("Unknown public card memory")
    if max(Counter(t.removesuffix("+") for t in info.known_deck).values()) > MAX_COPIES:
        raise ValueError("Public deck copy capacity exceeded")
    if any(t not in ("INFLAME", "INFLAME+") for t in info.history.removed_powers):
        raise ValueError("Unsupported removed card")
    strength = sum(3 if t.endswith("+") else 2 for t in info.history.removed_powers)
    if info.player_strength != strength and not (info.termination_reason == "death" and info.player_strength == 0):
        raise ValueError("Strength does not match public power plays")


NUMERIC = ("hp/80", "max_hp/80", "block/100", "energy/20", "max_energy/3", "turn/100", "decisions/400",
           "player.shrink", "player.strength/15", "enemy.hp/80", "enemy.max_hp/80", "enemy.initial_hp/80",
           "enemy.block/100", "enemy.vulnerable/10", "enemy.strength/100", "intent.damage/20", "intent.hits/5",
           "decision_limit/400", "turn_limit/100", "phase.normal", "phase.choice")
NUMERIC += tuple(f"monster.{name}" for name in PROFILES)
NUMERIC += tuple(f"intent.{name}" for name in ("ATTACK", "DEBUFF_STRONG", "BUFF"))
ALL_MOVES = ("SHRINKER_MOVE", "CHOMP_MOVE", "STOMP_MOVE", *EXTRA_MOVES)
NUMERIC += tuple(f"history.{name}/100" for name in ALL_MOVES)
NUMERIC += tuple(f"{pile}.{token}/20" for pile in ("draw", "discard", "exhaust", "deck", "removed", "played") for token in TOKENS)
NUMERIC += ("initial_hp/80",)


HARD_NUMERIC = ("enemy.BYGONE_EFFIGY", "enemy.BYRDONIS", "enemy.slow", "enemy.slow_cards/20",
                "enemy.territorial", "intent.sleep", "intent.multi_attack") + tuple(f"history.{m}/100" for m in HARD_MOVES)


EXPANDED_FEATURES = ("hits/2", "block_scaled_damage", "exhaust_scaling/4", "all_enemies")
EXPANDED_NUMERIC = ("enemy.CUBEX_CONSTRUCT", "enemy.MAWLER", "enemy.artifact", "player.vulnerable/3",
                    "intent.attack_buff", "intent.debuff", "history.mawler_last_claw", "history.mawler_last_rip")
EXPANDED_NUMERIC += tuple(f"history.{m}/100" for m in EXPANDED_MOVES)
EXPANDED_NUMERIC += tuple(f"{pile}.{token}/20" for pile in ("draw", "discard", "exhaust", "deck", "removed", "played")
                          for token in EXPANDED_TOKENS[len(TOKENS):])


def schema(content_version=DECK_CONTENT, capacity=None):
    capacity = capacity or card_capacity(content_version)
    if content_version == BOSS_CONTENT:
        from .boss_cards import TOKENS as BOSS_TOKENS
        from .boss import numeric_names
        result = schema(MORPH_CONTENT, capacity)
        result.update(encoder_version="az-boss-encoder-v1", information_version="boss-information-v1", content_manifest_version=BOSS_CONTENT, reward_version="finite-primary-phases-v6", action_schema_version="combat-boss4096-v1", action_size=4096, card_vocabulary=["PAD", *BOSS_TOKENS], power_vocabulary=[*result["power_vocabulary"], "ILLUSION", "MINION", "ADAPTABLE", "ENRAGE", "PAINFUL_STABS", "NEMESIS", "INTANGIBLE"], monster_vocabulary=[*result["monster_vocabulary"], "FOGMOG", "EYE_WITH_TEETH", "TEST_SUBJECT"], numeric_features=[*result["numeric_features"][:-1], *numeric_names(), "initial_hp/80"], constraints="Finite TestSubject phases; 2145 cards; stable slots", unsupported=["other bosses", "other powers", "relics", "potions", "multiplayer"])
        result["shapes"]["numeric"] = [len(result["numeric_features"])]
        result["shapes"]["legal_mask"] = [4096]
        return result
    if content_version == SUMMON_CONTENT:
        from .g1 import SUMMON_TOKENS
        from .summon import SUMMON_INFORMATION, SUMMON_ACTION_VERSION, SUMMON_ACTION_SIZE, MONSTER_IDS
        from .summon import enemy_features as summon_enemy_features
        result = schema(MORPH_CONTENT, capacity)
        result.update(encoder_version="az-summon-encoder-v1", information_version=SUMMON_INFORMATION,
                      content_manifest_version=SUMMON_CONTENT, reward_version=V5,
                      monster_vocabulary=list(MONSTER_IDS),
                      power_vocabulary=[*result["power_vocabulary"], "ILLUSION", "MINION"],
                      action_schema_version=SUMMON_ACTION_VERSION, action_size=SUMMON_ACTION_SIZE,
                      card_vocabulary=["PAD", *SUMMON_TOKENS],
                      numeric_features=[*result["numeric_features"][:-1], *summon_numeric(capacity), "initial_hp/80"],
                      constraints=("28 initial card IDs, the generated-only DAZED token and the audited "
                                   f"Fogmog/Eye summon; <={capacity} cards; two stable native slots; "
                                   "known draw prefix and suffix; audited Primal Force transformations"),
                      unsupported=["other summons", "permanent enemy removal", "escape", "Boss phases",
                                   "random generation", "temporary costs other than Stomp",
                                   "per-card granted retain", "relics", "potions", "multiplayer"])
        result["shapes"]["numeric"] = [len(result["numeric_features"])]
        result["shapes"]["legal_mask"] = [SUMMON_ACTION_SIZE]
        return result
    if content_version == MULTI_CONTENT:
        from .multi import enemy_features
        result = schema(MORPH_CONTENT, capacity)
        result.update(encoder_version="az-multi-encoder-v1", information_version="multi-information-v1",
                      content_manifest_version=MULTI_CONTENT, reward_version=V4,
                      action_schema_version="combat-multi512-v3",
                      constraints="Fixed ordered roster, 1..2 enemies; dead slots persist; native target indices; no summons/revival",
                      unsupported=["summons", "revival", "escape", "Boss phases", "other G1 mechanisms", "relics", "potions"])
        result["numeric_features"] = [*result["numeric_features"][:-1], *enemy_features(), "initial_hp/80"]
        result["shapes"]["numeric"] = [len(result["numeric_features"])]
        return result
    result = dict(encoder_version="az-decks-encoder-v1", information_mode="observable",
                information_version="decks-information-v1", action_schema_version="combat-115-v1",
                content_manifest_version=DECK_CONTENT, reward_version=V3,
                card_vocabulary=["PAD", *TOKENS], power_vocabulary=["SHRINK", "VULNERABLE", "STRENGTH"],
                monster_vocabulary=list(PROFILES), card_features=list(FEATURES), numeric_features=list(NUMERIC),
                hand_slots=10, action_size=115,
                shapes=dict(card_ids=[10], card_features=[10, len(FEATURES)], numeric=[len(NUMERIC)], legal_mask=[115]),
                normalization="Divisors explicit; no clipping or deck truncation",
                unsupported=["choice", "temporary costs", "generated cards", "other powers", "known draw positions"],
                constraints="6..20 cards; <=5 copies per ID; 8 audited IDs, both upgrades; no choices in whitelist")
    if content_version == HARD_CONTENT:
        result.update(encoder_version="az-hard-encoder-v2", information_version="hard-information-v2",
                      content_manifest_version=HARD_CONTENT, monster_vocabulary=list(HARD_PROFILES),
                      power_vocabulary=["SHRINK", "VULNERABLE", "STRENGTH", "SLOW", "TERRITORIAL"],
                      numeric_features=[*NUMERIC[:-1], *HARD_NUMERIC, NUMERIC[-1]])
        result["shapes"]["numeric"] = [len(NUMERIC) + len(HARD_NUMERIC)]
    if content_version == EXPANDED_CONTENT:
        result = schema(HARD_CONTENT, capacity)
        result.update(encoder_version="az-expanded-encoder-v3", information_version="expanded-information-v3",
                      content_manifest_version=EXPANDED_CONTENT, card_vocabulary=["PAD", *EXPANDED_TOKENS],
                      card_features=[*FEATURES, *EXPANDED_FEATURES], monster_vocabulary=list(EXPANDED_PROFILES),
                      power_vocabulary=[*result["power_vocabulary"], "ARTIFACT"],
                      numeric_features=[*result["numeric_features"][:-1], *EXPANDED_NUMERIC, "initial_hp/80"],
                      constraints="6..20 cards; <=5 copies per ID; 16 audited IDs, both upgrades; no choices")
        result["shapes"]["numeric"] = [len(result["numeric_features"])]
        result["shapes"]["card_features"] = [10, len(result["card_features"])]
    if content_version in (G1_CONTENT, GEN_CONTENT, UP_CONTENT, TOP_CONTENT, LIFE_CONTENT, SEL_CONTENT, SET_CONTENT, MORPH_CONTENT, MULTI_CONTENT, SUMMON_CONTENT, BOSS_CONTENT):
        from .g1 import TOKENS as G1_TOKENS, GEN_TOKENS, UP_TOKENS, TOP_TOKENS, LIFE_TOKENS, SEL_TOKENS, MORPH_TOKENS
        result = schema(EXPANDED_CONTENT, capacity)
        result.update(encoder_version="az-g1-encoder-v1", information_version="g1-information-v1",
                      content_manifest_version=G1_CONTENT, card_vocabulary=["PAD", *G1_TOKENS],
                      card_features=[*result["card_features"], *G1_FEATURES],
                      numeric_features=[*result["numeric_features"][:-1], *g1_numeric(), "initial_hp/80"],
                      unsupported=["temporary costs in live content", "generated cards", "known draw positions", "other choices"],
                      constraints="18 cards; hand-exhaust choices only; candidates <=10; static mutable-state policy")
        result["shapes"]["numeric"] = [len(result["numeric_features"])]
        result["shapes"]["card_features"] = [10, len(result["card_features"])]
    if content_version == GEN_CONTENT:
        result = schema(G1_CONTENT, capacity)
        result.update(encoder_version="az-generated-encoder-v1", information_version="generated-information-v1",
                      content_manifest_version=GEN_CONTENT, card_vocabulary=["PAD", *GEN_TOKENS],
                      numeric_features=[*result["numeric_features"][:-1], *gen_numeric(capacity), "initial_hp/80"],
                      constraints="19 cards; Anger public generation ledger; no combat pile truncation",
                      unsupported=["other generated cards", "temporary costs", "known draw positions", "other choices"])
        result["shapes"]["numeric"] = [len(result["numeric_features"])]
    if content_version == UP_CONTENT:
        result = schema(GEN_CONTENT, capacity)
        result.update(encoder_version="az-upgrades-encoder-v1", information_version="upgrades-information-v1",
                      content_manifest_version=UP_CONTENT, card_vocabulary=["PAD", *UP_TOKENS],
                      numeric_features=[*result["numeric_features"][:-1], *up_numeric(), "initial_hp/80"],
                      constraints="20 cards; public Armaments upgrades and Anger generation ledger",
                      unsupported=["arbitrary transformations", "temporary costs", "known draw positions", "other choices"])
        result["shapes"]["numeric"] = [len(result["numeric_features"])]
    if content_version == TOP_CONTENT:
        result = schema(UP_CONTENT, capacity)
        result.update(encoder_version="az-topdeck-encoder-v1", information_version="topdeck-information-v1",
                      content_manifest_version=TOP_CONTENT, card_vocabulary=["PAD", *TOP_TOKENS],
                      action_schema_version="combat-421-v1", action_size=421,
                      numeric_features=[*result["numeric_features"][:-1], *top_numeric(capacity), "initial_hp/80"],
                      constraints="21 cards; <=400 decisions; <=420 combat cards; ordered public discard and known draw prefix",
                      unsupported=["arbitrary transformations", "temporary costs", "known bottom", "other choices"])
        result["shapes"]["numeric"] = [len(result["numeric_features"])]
        result["shapes"]["legal_mask"] = [421]
    if content_version == LIFE_CONTENT:
        result = schema(TOP_CONTENT, capacity)
        result.update(encoder_version="az-lifecycle-encoder-v1", information_version="lifecycle-information-v1",
                      content_manifest_version=LIFE_CONTENT, card_vocabulary=["PAD", *LIFE_TOKENS],
                      numeric_features=[*result["numeric_features"][:-1], *life_numeric(), "initial_hp/80"],
                      constraints="23 cards; Stomp costs derived in all piles from public attack count; Restlessness static retain",
                      unsupported=["other temporary costs", "granted retain", "arbitrary transformations", "known bottom", "other choices"])
        result["shapes"]["numeric"] = [len(result["numeric_features"])]
    if content_version in (SEL_CONTENT, SET_CONTENT, MORPH_CONTENT, MULTI_CONTENT, SUMMON_CONTENT, BOSS_CONTENT):
        result = schema(LIFE_CONTENT, capacity)
        result.update(encoder_version="az-selection-encoder-v1", information_version="selection-information-v1",
                      content_manifest_version=content_version, card_vocabulary=["PAD", *SEL_TOKENS],
                      power_vocabulary=[*result["power_vocabulary"], "RETAIN_HAND"],
                      numeric_features=[*result["numeric_features"][:-1], *selection_numeric(), "initial_hp/80"],
                      constraints="26 cards; Whirlwind X payment; Equilibrium timed retain; Purity optional multi-select",
                      unsupported=["other X effects", "per-card granted retain", "other powers", "arbitrary transformations", "known bottom"])
        result["shapes"]["numeric"] = [len(result["numeric_features"])]
    if content_version in (SET_CONTENT, MORPH_CONTENT, MULTI_CONTENT, SUMMON_CONTENT, BOSS_CONTENT):
        result.update(encoder_version="az-selection-encoder-v2", information_version="selection-information-v2",
                      action_schema_version="combat-set512-v2", action_size=512,
                      choice_actions="Purity: 9-bit complete candidate subset; zero skips; native reconcile and confirm once",
                      constraints="26 cards; <=9 Purity candidates; <=5 selected; atomic final-set choice")
        result["shapes"]["legal_mask"] = [512]
    if content_version in (MORPH_CONTENT, MULTI_CONTENT, SUMMON_CONTENT, BOSS_CONTENT):
        result.update(encoder_version="az-morph-encoder-v1", information_version="morph-information-v1",
                      card_vocabulary=["PAD", *MORPH_TOKENS],
                      numeric_features=[*result["numeric_features"][:-1], *morph_numeric(capacity), "initial_hp/80"],
                      constraints="28 initial card IDs plus Giant Rock/Soul tokens; <=420 cards; known draw prefix and suffix; audited Primal Force transformations",
                      unsupported=["random generation", "arbitrary transformations", "other powers", "per-card granted retain"])
        result["shapes"]["numeric"] = [len(result["numeric_features"])]
    return result


def morph_numeric(capacity=420):
    from .morph import MORPH_EXTRA
    return (tuple(f"{pile}.{t}/20" for pile in ("draw", "discard", "exhaust", "deck", "removed", "played") for t in MORPH_EXTRA)
            + tuple(f"upgraded.{t}/4000" for t in ("PRIMAL_FORCE", "REAVE", "GIANT_ROCK", "SOUL"))
            + ("generated.SOUL/400", "generated.SOUL+/400", "transformed.total/4000",
               f"known_bottom_count/{capacity}")
            + tuple(f"known_bottom.{i}/60" for i in range(capacity)))


def summon_numeric(capacity=720):
    """Public features added by the summon contract: DAZED, slots and primaries."""
    from .summon import enemy_features as summon_enemy_features
    result = tuple(f"{pile}.DAZED/20" for pile in ("draw", "discard", "exhaust", "deck", "removed", "played"))
    result += ("summon.slot_count/2", "summon.spawned_count/2", "summon.reviving_count/2",
               "summon.eye_distracts/400", "generated.DAZED/400", "summon.primary_initial_hp/160",
               "summon.primary_hp/160", "summon.primary_max_hp/160")
    result += summon_enemy_features()
    return result


def gen_numeric(capacity=420):
    return (tuple(f"{pile}.{token}/20" for pile in ("draw", "discard", "exhaust", "deck", "removed", "played")
                  for token in ("ANGER", "ANGER+"))
            + ("generated.ANGER/400", "generated.ANGER+/400", f"combat_card_count/{capacity}"))


def selection_numeric():
    return (tuple(f"{pile}.{token}/20" for pile in ("draw", "discard", "exhaust", "deck", "removed", "played")
                  for token in ("WHIRLWIND", "WHIRLWIND+", "PURITY", "PURITY+", "EQUILIBRIUM", "EQUILIBRIUM+"))
            + ("pending.PURITY", "pending.PURITY+", "choice.selected_count/10", "choice.can_confirm", "retain.turns/400",
               "paid.turn_total/1203", "paid.last/1203", "paid.x_total/1203", "paid.x_count/400")
            + tuple(f"upgraded.{t}/4000" for t in ("WHIRLWIND", "PURITY", "EQUILIBRIUM")))


def life_numeric():
    return (tuple(f"{pile}.{token}/20" for pile in ("draw", "discard", "exhaust", "deck", "removed", "played")
                  for token in ("STOMP", "STOMP+", "RESTLESSNESS", "RESTLESSNESS+"))
            + ("upgraded.STOMP/4000", "upgraded.RESTLESSNESS/4000", "turn.attacks/400", "stomp.turn_cost.present", "stomp.turn_cost/3"))


def top_numeric(capacity=420):
    return (tuple(f"{pile}.{token}/20" for pile in ("draw", "discard", "exhaust", "deck", "removed", "played")
                  for token in ("HEADBUTT", "HEADBUTT+"))
            + ("pending.HEADBUTT", "pending.HEADBUTT+", "upgraded.HEADBUTT/4000",
               f"known_top.count/{capacity}", f"discard.count/{capacity}")
            + tuple(f"{pile}.{i}.token_id/42" for pile in ("known_top", "discard_order") for i in range(capacity)))


def up_numeric():
    from .decks import UP_FACTORIES
    return tuple(f"{pile}.{token}/20" for pile in ("draw", "discard", "exhaust", "deck", "removed", "played")
                 for token in ("ARMAMENTS", "ARMAMENTS+")) + ("pending.ARMAMENTS",) + tuple(f"upgraded.{name}/4000" for name in UP_FACTORIES)


GEN_NUMERIC = gen_numeric()  # 420-card historical schema; see gen_numeric for the raised bound


G1_FEATURES = ("choice.option", "choice.index/10", "choice.selected", "retain", "turn_cost.present", "turn_cost/3")


def g1_numeric():
    from .g1 import TOKENS as G1_TOKENS, GEN_TOKENS, UP_TOKENS, TOP_TOKENS, LIFE_TOKENS, SEL_TOKENS, MORPH_TOKENS
    return tuple(f"{pile}.{token}/20" for pile in ("draw", "discard", "exhaust", "deck", "removed", "played")
                 for token in G1_TOKENS[len(EXPANDED_TOKENS):]) + ("choice.min/10", "choice.max/10", "choice.skip",
                 "pending.TRUE_GRIT+", "pending.BURNING_PACT", "pending.BURNING_PACT+")


def encode(info):
    from .encoder import EncodedObservation
    expanded = info.content_version in (EXPANDED_CONTENT, G1_CONTENT, GEN_CONTENT, UP_CONTENT, TOP_CONTENT, LIFE_CONTENT, SEL_CONTENT, SET_CONTENT, MORPH_CONTENT, MULTI_CONTENT, SUMMON_CONTENT, BOSS_CONTENT)
    g1 = info.content_version in (G1_CONTENT, GEN_CONTENT, UP_CONTENT, TOP_CONTENT, LIFE_CONTENT, SEL_CONTENT, SET_CONTENT, MORPH_CONTENT, MULTI_CONTENT, SUMMON_CONTENT, BOSS_CONTENT)
    tokens = token_vocabulary(info.content_version)
    cap = card_capacity(info.content_version)
    features = (*FEATURES, *EXPANDED_FEATURES) if expanded else FEATURES
    if g1:
        features = (*features, *G1_FEATURES)
    ids = np.zeros(10, dtype=np.int64)
    cards = np.zeros((10, len(features)), dtype=np.float32)
    for i, token in enumerate(info.hand):
        card = prototype(token)
        e = card.effect_vars
        ids[i] = tokens.index(token) + 1
        base = [1, card.upgraded, card.cost / 3, card.original_cost / 3, int(info.content_version in (SEL_CONTENT, SET_CONTENT, MORPH_CONTENT, MULTI_CONTENT, SUMMON_CONTENT, BOSS_CONTENT) and card.has_energy_cost_x),
                    (card.base_damage or 0) / 10, (card.base_block or 0) / 10, e.get("vulnerable", 0) / 3,
                    e.get("cards", 0) / 5, e.get("energy", 0) / 3, e.get("hp_loss", 0) / 6,
                    e.get("strength", 0) / 3, "exhaust" in card.keywords, card.is_power]
        if expanded:
            name = token.removesuffix("+")
            base += [(2 if name == "TWIN_STRIKE" else 1 if card.is_attack else 0) / 2,
                     name == "BODY_SLAM", e.get("extra_damage", 0) / 4 if name == "ASHEN_STRIKE" else 0,
                     name == "THUNDERCLAP" or (info.content_version in (LIFE_CONTENT, SEL_CONTENT, SET_CONTENT, MORPH_CONTENT, MULTI_CONTENT, SUMMON_CONTENT, BOSS_CONTENT) and name in ("STOMP", "WHIRLWIND"))]
        if info.content_version in (SEL_CONTENT, SET_CONTENT, MORPH_CONTENT, MULTI_CONTENT, SUMMON_CONTENT, BOSS_CONTENT) and card.has_energy_cost_x:
            base[14] = info.energy / 2  # potential hit count before paying X
        if g1:
            state = info.hand_states[i]
            base[2:4] = [state.cost / 3, state.original_cost / 3]
            option = next((j for j,o in enumerate(info.choice.options) if o.pile == "hand" and o.index == i), None) if info.choice else None
            base += [option is not None, (option + 1) / 10 if option is not None else 0,
                     option in info.choice.selected if option is not None else False,
                     state.single_turn_retain or (info.content_version in (LIFE_CONTENT, SEL_CONTENT, SET_CONTENT, MORPH_CONTENT, MULTI_CONTENT, SUMMON_CONTENT, BOSS_CONTENT) and card.is_retain) or (info.content_version in (SEL_CONTENT, SET_CONTENT, MORPH_CONTENT, MULTI_CONTENT, SUMMON_CONTENT, BOSS_CONTENT) and info.retain_hand > 0), state.turn_cost is not None, (state.turn_cost or 0) / 3]
        cards[i] = base
    intent, damage, hits = info.intent
    values = [info.player_hp / 80, info.player_max_hp / 80, info.player_block / 100, info.energy / 20,
              info.max_energy / 3, info.turn / 100, info.history.decisions / 400, info.shrink, info.player_strength / 15,
              info.enemy_hp / 80, info.enemy_max_hp / 80, info.enemy_initial_hp / 80, info.enemy_block / 100,
              info.vulnerable / 10, info.enemy_strength / 100, damage / 20, hits / 5,
              info.limits.max_decisions / 400, info.limits.max_turns / 100, int(info.choice is None), int(info.choice is not None)]
    values += [info.monster_id == name for name in PROFILES]
    values += [intent == name for name in ("ATTACK", "DEBUFF_STRONG", "BUFF")]
    values += [info.history.enemy_moves.count(name) / 100 for name in ALL_MOVES]
    for pile in (info.draw_composition, info.discard, info.exhaust, info.known_deck,
                 info.history.removed_powers, info.history.played_this_turn):
        counts = Counter(pile)
        values += [counts[token] / 20 for token in TOKENS]
    if info.content_version in (HARD_CONTENT, EXPANDED_CONTENT, G1_CONTENT, GEN_CONTENT, UP_CONTENT, TOP_CONTENT, LIFE_CONTENT, SEL_CONTENT, SET_CONTENT, MORPH_CONTENT, MULTI_CONTENT, SUMMON_CONTENT, BOSS_CONTENT):
        values += [info.monster_id == "BYGONE_EFFIGY", info.monster_id == "BYRDONIS", info.enemy_slow,
                   (len(info.history.played_this_turn) - int(info.choice is not None)) / 20 if info.enemy_slow else 0,
                   info.enemy_territorial, intent == "SLEEP", intent == "MULTI_ATTACK"]
        values += [info.history.enemy_moves.count(m) / 100 for m in HARD_MOVES]
    if expanded:
        last = info.history.enemy_moves[-1] if info.history.enemy_moves else ""
        values += [info.monster_id == "CUBEX_CONSTRUCT", info.monster_id == "MAWLER", info.enemy_artifact,
                   info.player_vulnerable / 3, intent == "ATTACK_BUFF", intent == "DEBUFF",
                   info.monster_id == "MAWLER" and last == "CLAW_MOVE",
                   info.monster_id == "MAWLER" and last == "RIP_AND_TEAR_MOVE"]
        values += [info.history.enemy_moves.count(m) / 100 for m in EXPANDED_MOVES]
        for pile in (info.draw_composition, info.discard, info.exhaust, info.known_deck,
                     info.history.removed_powers, info.history.played_this_turn):
            counts = Counter(pile)
            values += [counts[token] / 20 for token in EXPANDED_TOKENS[len(TOKENS):]]
    if g1:
        from .g1 import TOKENS as G1_TOKENS
        for pile in (info.draw_composition, info.discard, info.exhaust, info.known_deck,
                     info.history.removed_powers, info.history.played_this_turn):
            counts = Counter(pile)
            values += [counts[token] / 20 for token in G1_TOKENS[len(EXPANDED_TOKENS):]]
        choice = info.choice
        values += [choice.min_choices / 10 if choice else 0, choice.max_choices / 10 if choice else 0,
                   choice.allow_skip if choice else False]
        values += [bool(info.pending_card and info.pending_card.token == t) for t in ("TRUE_GRIT+", "BURNING_PACT", "BURNING_PACT+")]
    if info.content_version in (GEN_CONTENT, UP_CONTENT, TOP_CONTENT, LIFE_CONTENT, SEL_CONTENT, SET_CONTENT, MORPH_CONTENT, MULTI_CONTENT, SUMMON_CONTENT, BOSS_CONTENT):
        for pile in (info.draw_composition, info.discard, info.exhaust, info.known_deck,
                     info.history.removed_powers, info.history.played_this_turn):
            counts = Counter(pile)
            values += [counts[token] / 20 for token in ("ANGER", "ANGER+")]
        counts = Counter(e.result_token for e in info.history.generated)
        values += [counts["ANGER"] / 400, counts["ANGER+"] / 400,
                   (len(info.known_deck) + generated_card_count(info)) / cap]
    if info.content_version in (UP_CONTENT, TOP_CONTENT, LIFE_CONTENT, SEL_CONTENT, SET_CONTENT, MORPH_CONTENT, MULTI_CONTENT, SUMMON_CONTENT, BOSS_CONTENT):
        from .decks import UP_FACTORIES
        for pile in (info.draw_composition, info.discard, info.exhaust, info.known_deck,
                     info.history.removed_powers, info.history.played_this_turn):
            counts = Counter(pile)
            values += [counts[t] / 20 for t in ("ARMAMENTS", "ARMAMENTS+")]
        values += [bool(info.pending_card and info.pending_card.token == "ARMAMENTS")]
        counts = Counter(e.source_token for e in info.history.upgraded)
        values += [counts[name] / 4000 for name in UP_FACTORIES]
    if info.content_version in (TOP_CONTENT, LIFE_CONTENT, SEL_CONTENT, SET_CONTENT, MORPH_CONTENT, MULTI_CONTENT, SUMMON_CONTENT, BOSS_CONTENT):
        for pile in (info.draw_composition, info.discard, info.exhaust, info.known_deck,
                     info.history.removed_powers, info.history.played_this_turn):
            counts = Counter(pile)
            values += [counts[t] / 20 for t in ("HEADBUTT", "HEADBUTT+")]
        values += [bool(info.pending_card and info.pending_card.token == t) for t in ("HEADBUTT", "HEADBUTT+")]
        values += [sum(e.source_token == "HEADBUTT" for e in info.history.upgraded) / 4000,
                   len(info.known_top) / cap, len(info.discard) / cap]
        for pile in (info.known_top, info.discard):
            if len(pile) > cap:
                raise ValueError("Ordered public pile exceeds schema capacity")
            values += [(tokens.index(t) + 1) / 42 for t in pile] + [0] * (cap - len(pile))
    if info.content_version in (LIFE_CONTENT, SEL_CONTENT, SET_CONTENT, MORPH_CONTENT, MULTI_CONTENT, SUMMON_CONTENT, BOSS_CONTENT):
        from .lifecycle import attack_count
        for pile in (info.draw_composition, info.discard, info.exhaust, info.known_deck,
                     info.history.removed_powers, info.history.played_this_turn):
            counts = Counter(pile)
            values += [counts[t] / 20 for t in ("STOMP", "STOMP+", "RESTLESSNESS", "RESTLESSNESS+")]
        values += [sum(e.source_token == t for e in info.history.upgraded) / 4000 for t in ("STOMP", "RESTLESSNESS")]
        count = attack_count(info.history)
        values += [count / 400, bool(count), max(0, 3 - count) / 3]
    if info.content_version in (SEL_CONTENT, SET_CONTENT, MORPH_CONTENT, MULTI_CONTENT, SUMMON_CONTENT, BOSS_CONTENT):
        for pile in (info.draw_composition, info.discard, info.exhaust, info.known_deck,
                     info.history.removed_powers, info.history.played_this_turn):
            counts = Counter(pile)
            values += [counts[t] / 20 for t in ("WHIRLWIND", "WHIRLWIND+", "PURITY", "PURITY+", "EQUILIBRIUM", "EQUILIBRIUM+")]
        values += [bool(info.pending_card and info.pending_card.token == t) for t in ("PURITY", "PURITY+")]
        payments = info.history.payments
        values += [len(info.choice.selected)/10 if info.choice else 0,
                   bool(info.choice and info.legal_mask[0]), info.retain_hand/400,
                   sum(p.energy for p in payments)/1203, payments[-1].energy/1203 if payments else 0,
                   sum(p.energy for p in payments if p.token.removesuffix("+") == "WHIRLWIND")/1203,
                   sum(p.token.removesuffix("+") == "WHIRLWIND" for p in payments)/400]
        values += [sum(e.source_token == t for e in info.history.upgraded)/4000 for t in ("WHIRLWIND", "PURITY", "EQUILIBRIUM")]
    if info.content_version in (MORPH_CONTENT, MULTI_CONTENT, SUMMON_CONTENT, BOSS_CONTENT):
        from .morph import MORPH_EXTRA
        for pile in (info.draw_composition, info.discard, info.exhaust, info.known_deck,
                     info.history.removed_powers, info.history.played_this_turn):
            counts = Counter(pile)
            values += [counts[t]/20 for t in MORPH_EXTRA]
        values += [sum(e.source_token == t for e in info.history.upgraded)/4000 for t in ("PRIMAL_FORCE", "REAVE", "GIANT_ROCK", "SOUL")]
        values += [sum(e.result_token == t for e in info.history.generated)/400 for t in ("SOUL", "SOUL+")]
        values += [len(info.history.transformed)/4000, len(info.known_bottom)/cap]
        values += [(tokens.index(t)+1)/60 for t in info.known_bottom] + [0]*(cap-len(info.known_bottom))
    if info.content_version == BOSS_CONTENT:
        from .boss import encode as encode_boss
        values += encode_boss(info)
    elif info.content_version == SUMMON_CONTENT:
        from .summon import (DAZED, DAZED_MECHANISM, encode_slots, eye_distract_count,
                             primary_summary, ledger_from_slots)
        for pile in (info.draw_composition, info.discard, info.exhaust, info.known_deck,
                     info.history.removed_powers, info.history.played_this_turn):
            values += [Counter(pile)[DAZED] / 20]
        ledger = ledger_from_slots(info.enemies)
        initial, current, maximum = primary_summary(ledger)
        events = tuple(e for e in info.history.generated if getattr(e, "mechanism", None) == DAZED_MECHANISM)
        values += [len(info.enemies) / 2,
                   sum(e.spawned for e in info.enemies) / 2, sum(e.reviving for e in info.enemies) / 2,
                   eye_distract_count(info.enemies) / 400,
                   sum(e.count for e in events) / 400,
                   initial / 160, current / 160, maximum / 160]
        values += encode_slots(info)
    elif info.content_version == MULTI_CONTENT:
        from .multi import encode_enemies
        values += encode_enemies(info)
    values += [info.initial_hp / 80]
    return EncodedObservation(ids, cards, np.asarray(values, dtype=np.float32),
                              np.asarray(info.legal_mask, dtype=bool), "observable", info.reward_version, info.content_version)

