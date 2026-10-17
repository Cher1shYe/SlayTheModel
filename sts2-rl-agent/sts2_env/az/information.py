"""Observable starter/Shrinker sufficient state and independently sampled worlds.

No world, recipe, environment seed, instance ID or simulator RNG is retained in
InformationState. Unknown draw composition is inferred by card conservation.
Only the observer sees a real world; the belief sampler cannot accept one.
"""
from collections import Counter
from dataclasses import asdict, dataclass, replace

from .config import CONTENT_VERSION, RULES_VERSION, EpisodeLimits, canonical_json
from .actions import MAX_SUMMON_CARDS, action_size, public_mask
from .selection_batch import TurnPayment, validate_payments, validate_choice_shape, MAX_PUBLIC_ENERGY, SIMPLE_MAX_PUBLIC_ENERGY
from .card_upgrades import CardUpgrade, upgrades_after, inventory
from .card_generation import CardGeneration, generated_tokens
from .rewards import V1, terminal_reward, validate_reward
from .content import M6_CONTENT, M6_INFORMATION, DECK_CONTENT, HARD_CONTENT, EXPANDED_CONTENT, G1_CONTENT, GEN_CONTENT, UP_CONTENT, TOP_CONTENT, LIFE_CONTENT, SEL_CONTENT, SET_CONTENT, MORPH_CONTENT, MULTI_CONTENT, SUMMON_CONTENT, PROFILES, profiles, moves, intent_after, expected_strength
from .content import BOSS_CONTENT, EXPANSION_CONTENT, ALL_CONTENT
from .decks import card_token, make_token, FACTORIES as DECK_FACTORIES
from .encoder import _card_index  # registration order and strict public card validation
from .scenarios import STARTER
from .content import mawler_move, validate_mawler_history
from sts2_env.cards import base as card_base
from sts2_env.cards.ironclad import make_strike_ironclad, make_defend_ironclad, make_bash
from sts2_env.core.combat import CombatState
from sts2_env.core.enums import CombatSide, PowerId
from sts2_env.core.rng import Rng
from sts2_env.gym_env.action_space import action_to_card_and_target, get_action_mask
from sts2_env.monsters.act1_weak import create_shrinker_beetle
from sts2_env.search.mcts import apply_action

INFORMATION_VERSION = "shrinker-information-v1"
FACTORIES = {"STRIKE_IRONCLAD": make_strike_ironclad, "DEFEND_IRONCLAD": make_defend_ironclad, "BASH": make_bash}


def expected_moves(count):
    return tuple("SHRINKER_MOVE" if i == 0 else "CHOMP_MOVE" if i % 2 else "STOMP_MOVE" for i in range(count))


@dataclass(frozen=True)
class PublicHistory:
    boss_events: tuple = ()
    decisions: int = 0
    enemy_moves: tuple[str, ...] = ()
    roster_moves: tuple = ()
    pending_target: int | None = None
    played_this_turn: tuple[str, ...] = ()
    removed_powers: tuple[str, ...] = ()
    generated: tuple[CardGeneration, ...] = ()
    upgraded: tuple[CardUpgrade, ...] = ()
    known_top: tuple[str, ...] = ()
    payments: tuple[TurnPayment, ...] = ()
    retain_turns: int = 0
    transformed: tuple = ()
    known_bottom: tuple[str, ...] = ()
    exhausted_this_turn: tuple = ()  # Visible exhaust events since the latest player turn start.
    public_events: tuple = ()
    position_states: str = ""
    basic_plays: tuple = ()
    ability_plays: tuple = ()  # (public token, observed turn), ordered plays.
    dominate_strength: int = 0  # Public accumulated gain, preserved across turns.

    def after_action(self, before, action, *, combat_ended=False, after_hand=None):
        if before.history != self or before.terminal_value() is not None:
            raise ValueError("History must advance from its current public decision")
        if type(action) is not int or not 0 <= action < action_size(before.content_version) or not before.legal_mask[action]:
            raise ValueError("Invalid public action")
        top, bottom, transformed = self.known_top, self.known_bottom, self.transformed
        if before.content_version in (MORPH_CONTENT, MULTI_CONTENT, SUMMON_CONTENT, BOSS_CONTENT, EXPANSION_CONTENT, ALL_CONTENT):
            from .morph import advance_positions, transformations_after
            if before.content_version != EXPANSION_CONTENT:
                top, bottom = advance_positions(before, action, after_hand, combat_ended)
            transformed += transformations_after(before, action, combat_ended)
        elif before.content_version in (TOP_CONTENT, LIFE_CONTENT, SEL_CONTENT, SET_CONTENT, MORPH_CONTENT, MULTI_CONTENT, SUMMON_CONTENT, BOSS_CONTENT, EXPANSION_CONTENT, ALL_CONTENT):
            from .known_draw import advance_top
            top = advance_top(before, action, after_hand, combat_ended)
        upgraded = self.upgraded + (upgrades_after(before, action, combat_ended) if before.content_version in (UP_CONTENT, TOP_CONTENT, LIFE_CONTENT, SEL_CONTENT, SET_CONTENT, MORPH_CONTENT, MULTI_CONTENT, SUMMON_CONTENT, BOSS_CONTENT, EXPANSION_CONTENT, ALL_CONTENT) else ())
        if before.choice is not None:
            return replace(self, decisions=self.decisions + 1, known_top=top, known_bottom=bottom, transformed=transformed, upgraded=upgraded, pending_target=None)
        if action == 0:
            if before.content_version == ALL_CONTENT:
                from .roster import after_round
                histories = after_round(before.enemies, combat_ended)
                return replace(self, decisions=self.decisions + 1, known_top=top, known_bottom=bottom,
                               transformed=transformed, enemy_moves=histories[0], roster_moves=histories,
                               played_this_turn=(), payments=(),
                               retain_turns=max(0, self.retain_turns - 1), pending_target=None)
            if before.content_version in (SUMMON_CONTENT, BOSS_CONTENT, EXPANSION_CONTENT, ALL_CONTENT):
                # One completed enemy round: public moves plus exactly three
                # Dazed per actually performed Eye DISTRACT_MOVE.
                if before.content_version in (BOSS_CONTENT, EXPANSION_CONTENT, ALL_CONTENT):
                    from .boss import after_round, generation_after
                else:
                    from .summon import after_round, generation_after
                histories = after_round(before, combat_ended)
                return replace(self, decisions=self.decisions + 1, known_top=top, known_bottom=bottom, transformed=transformed,
                               enemy_moves=histories[0], roster_moves=histories, played_this_turn=(), payments=(),
                               retain_turns=max(0, self.retain_turns - 1), pending_target=None,
                               generated=self.generated + generation_after(before, combat_ended, self.decisions + 1))
            if before.content_version == MULTI_CONTENT:
                from .multi import after_round
                histories = after_round(before, combat_ended)
                return replace(self, decisions=self.decisions + 1, known_top=top, known_bottom=bottom, transformed=transformed,
                               enemy_moves=histories[0], roster_moves=histories, played_this_turn=(), payments=(),
                               retain_turns=max(0, self.retain_turns - 1), pending_target=None)
            move = (mawler_move(before.intent) if before.monster_id == "MAWLER"
                    else moves(before.monster_id, len(self.enemy_moves) + 1)[-1])
            return replace(self, decisions=self.decisions + 1, known_top=top, known_bottom=bottom, transformed=transformed, enemy_moves=self.enemy_moves + (move,), played_this_turn=(),
                           payments=(), retain_turns=max(0, self.retain_turns - 1))
        index, target = action_to_card_and_target(action)
        from .deck_observation import prototype
        name = before.hand[index]
        from .foundation import FACTORIES as BASIC_FACTORIES
        BASIC_FACTORIES={**BASIC_FACTORIES,"BRAND":None}
        basic_plays = self.basic_plays + (((name,before.turn),) if before.content_version in (EXPANSION_CONTENT, ALL_CONTENT) and name.removesuffix("+") in BASIC_FACTORIES and not combat_ended else ())
        from .player_abilities import CARD_POWER as POWER_FACTORIES
        ability_plays = self.ability_plays + (((name, before.turn),) if before.content_version in (EXPANSION_CONTENT, ALL_CONTENT) and name.removesuffix('+') in POWER_FACTORIES else ())
        dominate_strength = self.dominate_strength
        if before.content_version in (EXPANSION_CONTENT, ALL_CONTENT) and name.removesuffix('+') == 'DOMINATE' and not combat_ended:
            # Read the chosen public slot, never the world or hidden AI state.
            multiplier = dict(before.hand_states[index].effect_vars)['strength_per_vulnerable']
            dominate_strength += before.enemies[target].vulnerable * multiplier
        payments, retain_turns = self.payments, self.retain_turns
        if before.content_version in (SEL_CONTENT, SET_CONTENT, MORPH_CONTENT, MULTI_CONTENT, SUMMON_CONTENT, BOSS_CONTENT, EXPANSION_CONTENT, ALL_CONTENT):
            paid = before.energy if name.removesuffix("+") in ("WHIRLWIND","VOLLEY","CASCADE") else before.hand_states[index].cost
            payments += (TurnPayment(name, paid),)
            if (name.removesuffix("+") == "EQUILIBRIUM" or
                    (before.content_version in (EXPANSION_CONTENT, ALL_CONTENT) and name.removesuffix("+") == "SALVO")) and not combat_ended:
                retain_turns += 1
        return replace(self, decisions=self.decisions + 1, known_top=top, known_bottom=bottom, transformed=transformed,
                       pending_target=(target if before.content_version in (MULTI_CONTENT, SUMMON_CONTENT, BOSS_CONTENT, EXPANSION_CONTENT, ALL_CONTENT) and (name.removesuffix("+") == "HEADBUTT" and len(before.discard) >= 2 or name.removesuffix("+") == "SEEKER_STRIKE" and len(before.draw_composition)>=2) and not combat_ended else None),
                       payments=payments, retain_turns=retain_turns, dominate_strength=dominate_strength, ability_plays=ability_plays, basic_plays=basic_plays,
                       upgraded=upgraded, played_this_turn=self.played_this_turn + (name,),
                       generated=self.generated + (((CardGeneration(self.decisions + 1, name, "SOUL+" if name.endswith("+") else "SOUL", "draw_bottom", "reave-soul-v1"),)
                           if before.content_version in (MORPH_CONTENT, MULTI_CONTENT, SUMMON_CONTENT, BOSS_CONTENT, EXPANSION_CONTENT, ALL_CONTENT) and name in ("REAVE", "REAVE+") else
                           (CardGeneration(self.decisions + 1, name, name),) if before.content_version in (GEN_CONTENT, UP_CONTENT, TOP_CONTENT, LIFE_CONTENT, SEL_CONTENT, SET_CONTENT, MORPH_CONTENT, MULTI_CONTENT, SUMMON_CONTENT, BOSS_CONTENT, EXPANSION_CONTENT, ALL_CONTENT) and name in ("ANGER", "ANGER+") else ()) if not combat_ended else ()),
                       removed_powers=self.removed_powers + ((name,) if name.removesuffix("+") == "INFLAME" or (before.content_version in (EXPANSION_CONTENT, ALL_CONTENT) and name.removesuffix("+") in (*POWER_FACTORIES,*BASIC_FACTORIES) and prototype(name).is_power) else ()))


@dataclass(frozen=True)
class InformationState:
    player_hp: int
    player_max_hp: int
    player_block: int
    energy: int
    max_energy: int
    turn: int
    hand: tuple[str, ...]
    draw_composition: tuple[str, ...]
    discard: tuple[str, ...]
    exhaust: tuple[str, ...]
    shrink: int
    enemy_hp: int
    enemy_max_hp: int
    enemy_block: int
    vulnerable: int
    intent: tuple[str, int, int]
    history: PublicHistory
    legal_mask: tuple[bool, ...]
    limits: EpisodeLimits
    termination_reason: str | None = None
    known_top: tuple[str, ...] = ()
    known_bottom: tuple[str, ...] = ()
    information_version: str = INFORMATION_VERSION
    rules_version: str = RULES_VERSION
    content_version: str = CONTENT_VERSION
    initial_hp: int = 80
    reward_version: str = V1
    monster_id: str = "SHRINKER_BEETLE"
    enemy_strength: int = 0
    known_deck: tuple[str, ...] = ()
    player_strength: int = 0
    execution: str = ""
    card_memory: str = ""
    power_memory: str = ""
    basic_statuses: tuple = ()
    player_abilities: tuple = ()  # Ordered public (ability name, amount), no simulator objects.
    enemy_initial_hp: int | None = None
    enemy_slow: int = 0
    enemy_territorial: int = 0
    enemy_artifact: int = 0
    player_vulnerable: int = 0
    hand_states: tuple = ()
    pending_card: object = None
    choice: object = None
    retain_hand: int = 0
    enemies: tuple = ()
    boss: object = None
    encounter: str = ''

    def key(self):
        # Exact, unnormalized structure rather than a lossy tensor/hash cache key.
        fields = asdict(self)
        # Mask is derived, not identity: a disagreement must fail at the node,
        # rather than silently becoming a distinct information branch.
        del fields["legal_mask"]
        return canonical_json(fields)

    def terminal_value(self):
        if self.content_version == ALL_CONTENT:
            from .all_content import terminal_value_all
            return terminal_value_all(self)
        if self.content_version in (BOSS_CONTENT, EXPANSION_CONTENT, ALL_CONTENT):
            if self.termination_reason is None:
                return None
            from .boss import phase_rows, rows_summary
            from .summon import ledger_from_slots, ledger_rows
            rows = phase_rows(self.boss.phase) if self.boss else ledger_rows(ledger_from_slots(self.enemies))
            initial, hp, maximum = rows_summary(rows)
            from .risk_reward import public_risk
            return terminal_reward(self.termination_reason, self.player_hp, self.initial_hp, hp, maximum, self.reward_version, enemy_initial_hp=initial, enemy_roster=rows,
                                   player_max_hp=self.player_max_hp, incoming_risk=public_risk(self))
        if self.content_version == SUMMON_CONTENT:
            # The frozen primary-roster-hp-v5 contract: the ledger decides the
            # terminal budget, and scalar HP never includes minion HP.
            if self.termination_reason is None:
                return None
            from .summon import terminal_ledger
            ledger, rows, (initial, final, maximum) = terminal_ledger(self)
            return terminal_reward(self.termination_reason, self.player_hp, self.initial_hp, final, maximum,
                                   self.reward_version, enemy_initial_hp=initial, enemy_roster=rows)
        if self.content_version == MULTI_CONTENT:
            if self.termination_reason is None:
                return None
            from .multi import health_rows, validate_health
            roster = health_rows(self.enemies)
            initial, final, maximum = validate_health(roster)
            return terminal_reward(self.termination_reason, self.player_hp, self.initial_hp, final, maximum,
                                   self.reward_version, enemy_initial_hp=initial, enemy_roster=roster)
        return None if self.termination_reason is None else terminal_reward(
            self.termination_reason, self.player_hp, self.initial_hp, self.enemy_hp, self.enemy_max_hp, self.reward_version,
            enemy_initial_hp=self.enemy_initial_hp)

    def validate(self):
        if self.content_version == ALL_CONTENT:
            from .all_content import validate_all
            return validate_all(self)
        validate_reward(self.reward_version)
        if type(self.history) is not PublicHistory:
            raise ValueError("Explicit public history required")
        from .player_abilities import validate as validate_abilities
        validate_abilities(self)
        from .foundation import validate as validate_basic
        validate_basic(self)
        events = self.history.exhausted_this_turn
        if (type(events) is not tuple or any(type(t) is not str for t in events)
                or (self.content_version != EXPANSION_CONTENT and events)
                or Counter(events) - Counter(self.exhaust)):
            raise ValueError('Invalid public current-turn exhaust events')
        if (type(self.history.dominate_strength) is not int or self.history.dominate_strength < 0
                or (self.content_version != EXPANSION_CONTENT and self.history.dominate_strength)):
            raise ValueError('Dominate history outside its versioned contract')
        if self.content_version not in (BOSS_CONTENT, EXPANSION_CONTENT, ALL_CONTENT) and (self.boss is not None or self.history.boss_events):
            raise ValueError("Boss state in legacy content")
        if self.content_version in (BOSS_CONTENT, EXPANSION_CONTENT, ALL_CONTENT):
            from .boss import validate as validate_boss
            if self.content_version == EXPANSION_CONTENT:
                from .foundation import validate_enemies
                validate_enemies(self,validate_boss)
            else: validate_boss(self)
        elif self.content_version == SUMMON_CONTENT:
            from .summon import validate_slots
            validate_slots(self)
        elif self.content_version == MULTI_CONTENT:
            from .multi import validate_enemies
            validate_enemies(self)
        elif self.enemies or self.history.roster_moves or self.history.pending_target is not None:
            raise ValueError("Multi-enemy public state in legacy content")
        if self.content_version in (SEL_CONTENT, SET_CONTENT, MORPH_CONTENT, MULTI_CONTENT, SUMMON_CONTENT, BOSS_CONTENT, EXPANSION_CONTENT, ALL_CONTENT):
            validate_payments(self.history, SIMPLE_MAX_PUBLIC_ENERGY if self.content_version == EXPANSION_CONTENT else MAX_PUBLIC_ENERGY)
            if (type(self.retain_hand) is not int or not 0 <= self.retain_hand <= 400
                    or (self.retain_hand != self.history.retain_turns and not (self.termination_reason == "death" and self.retain_hand == 0))):
                raise ValueError("Retain power disagrees with public lifecycle")
        elif self.history.payments or self.history.retain_turns or self.retain_hand:
            raise ValueError("Selection-batch state in legacy content")
        expanded = self.content_version in (DECK_CONTENT, HARD_CONTENT, EXPANDED_CONTENT, G1_CONTENT, GEN_CONTENT, UP_CONTENT, TOP_CONTENT, LIFE_CONTENT, SEL_CONTENT, SET_CONTENT, MORPH_CONTENT, MULTI_CONTENT, SUMMON_CONTENT, BOSS_CONTENT, EXPANSION_CONTENT, ALL_CONTENT)
        if self.content_version not in (EXPANDED_CONTENT, G1_CONTENT, GEN_CONTENT, UP_CONTENT, TOP_CONTENT, LIFE_CONTENT, SEL_CONTENT, SET_CONTENT, MORPH_CONTENT, MULTI_CONTENT, SUMMON_CONTENT, BOSS_CONTENT, EXPANSION_CONTENT, ALL_CONTENT) and (self.enemy_artifact or self.player_vulnerable):
            raise ValueError("New powers require expanded content")
        if (type(self.enemy_artifact) is not int or self.enemy_artifact not in (0, 1)
                or (self.enemy_artifact and self.monster_id != "CUBEX_CONSTRUCT")
                or type(self.player_vulnerable) is not int or not 0 <= self.player_vulnerable <= 3
                or (self.player_vulnerable and self.monster_id not in ("MAWLER", "TEST_SUBJECT"))):
            raise ValueError("Invalid expanded powers")
        if self.content_version not in (HARD_CONTENT, EXPANDED_CONTENT, G1_CONTENT, GEN_CONTENT, UP_CONTENT, TOP_CONTENT, LIFE_CONTENT, SEL_CONTENT, SET_CONTENT, MORPH_CONTENT, MULTI_CONTENT, SUMMON_CONTENT, BOSS_CONTENT, EXPANSION_CONTENT, ALL_CONTENT) and (self.enemy_slow or self.enemy_territorial):
            raise ValueError("Elite powers require hard content")
        if self.content_version in (HARD_CONTENT, EXPANDED_CONTENT, G1_CONTENT, GEN_CONTENT, UP_CONTENT, TOP_CONTENT, LIFE_CONTENT, SEL_CONTENT, SET_CONTENT, MORPH_CONTENT, MULTI_CONTENT, SUMMON_CONTENT, BOSS_CONTENT, EXPANSION_CONTENT, ALL_CONTENT):
            for amount, monster in ((self.enemy_slow, "BYGONE_EFFIGY"), (self.enemy_territorial, "BYRDONIS")):
                if type(amount) is not int or amount != int(self.monster_id == monster and self.enemy_hp > 0):
                    raise ValueError("Elite public power mismatch")
        if self.monster_id not in profiles(self.content_version) or self.content_version not in (CONTENT_VERSION, M6_CONTENT, DECK_CONTENT, HARD_CONTENT, EXPANDED_CONTENT, G1_CONTENT, GEN_CONTENT, UP_CONTENT, TOP_CONTENT, LIFE_CONTENT, SEL_CONTENT, SET_CONTENT, MORPH_CONTENT, MULTI_CONTENT, SUMMON_CONTENT, BOSS_CONTENT, EXPANSION_CONTENT, ALL_CONTENT):
            raise ValueError("Unsupported encounter content")
        if self.content_version == CONTENT_VERSION and (self.monster_id != "SHRINKER_BEETLE" or self.enemy_strength):
            raise ValueError("Legacy content cannot represent new monsters/powers")
        hp_min, hp_max = (100, 300) if self.monster_id == "TEST_SUBJECT" else profiles(self.content_version)[self.monster_id]["hp"]
        if type(self.initial_hp) is not int or not 0 < self.initial_hp <= 80:
            raise ValueError("Invalid public initial HP")
        if type(self.history) is not PublicHistory or type(self.limits) is not EpisodeLimits:
            raise ValueError("Invalid public memory/limits")
        integers = (self.player_hp, self.player_max_hp, self.player_block, self.energy, self.max_energy,
                    self.turn, self.shrink, self.enemy_hp, self.enemy_max_hp, self.enemy_block,
                    self.vulnerable, self.history.decisions, self.enemy_strength, self.player_strength)
        if any(type(n) is not int for n in integers):
            raise ValueError("Public numeric fields must be exact integers")
        if (not 0 <= self.energy <= (SIMPLE_MAX_PUBLIC_ENERGY if self.content_version == EXPANSION_CONTENT else MAX_PUBLIC_ENERGY if self.content_version in (SEL_CONTENT, SET_CONTENT, MORPH_CONTENT, MULTI_CONTENT, SUMMON_CONTENT, BOSS_CONTENT, EXPANSION_CONTENT, ALL_CONTENT) else 100 if expanded else 3) or self.turn < 1 or self.player_block < 0 or self.enemy_block < 0
                or not hp_min <= self.enemy_max_hp <= hp_max or self.enemy_hp > self.enemy_max_hp or (self.enemy_strength < 0 and self.content_version not in (EXPANSION_CONTENT, ALL_CONTENT))
                or not self.player_hp <= self.player_max_hp or self.vulnerable < 0 or self.shrink not in (0, -1)
                or (self.history.decisions < len(self.history.enemy_moves) + len(self.history.played_this_turn) and not self.history.public_events)):
            raise ValueError("Invalid public numeric ranges/history")
        expected_info_version = "ironclad-colorless-information-v5" if self.content_version == EXPANSION_CONTENT else "boss-information-v1" if self.content_version in (BOSS_CONTENT, EXPANSION_CONTENT, ALL_CONTENT) else "summon-information-v1" if self.content_version == SUMMON_CONTENT else "multi-information-v1" if self.content_version == MULTI_CONTENT else "morph-information-v1" if self.content_version in (MORPH_CONTENT, MULTI_CONTENT, SUMMON_CONTENT, BOSS_CONTENT, EXPANSION_CONTENT, ALL_CONTENT) else "selection-information-v2" if self.content_version in (SET_CONTENT, MORPH_CONTENT, MULTI_CONTENT, SUMMON_CONTENT, BOSS_CONTENT, EXPANSION_CONTENT, ALL_CONTENT) else "selection-information-v1" if self.content_version in (SEL_CONTENT, SET_CONTENT, MORPH_CONTENT, MULTI_CONTENT, SUMMON_CONTENT, BOSS_CONTENT, EXPANSION_CONTENT, ALL_CONTENT) else "lifecycle-information-v1" if self.content_version == LIFE_CONTENT else "topdeck-information-v1" if self.content_version == TOP_CONTENT else "upgrades-information-v1" if self.content_version == UP_CONTENT else "generated-information-v1" if self.content_version == GEN_CONTENT else "g1-information-v1" if self.content_version in (G1_CONTENT, GEN_CONTENT, UP_CONTENT, TOP_CONTENT, LIFE_CONTENT, SEL_CONTENT, SET_CONTENT, MORPH_CONTENT, MULTI_CONTENT, SUMMON_CONTENT, BOSS_CONTENT, EXPANSION_CONTENT, ALL_CONTENT) else "expanded-information-v3" if self.content_version in (EXPANDED_CONTENT, G1_CONTENT, GEN_CONTENT, UP_CONTENT, TOP_CONTENT, LIFE_CONTENT, SEL_CONTENT, SET_CONTENT, MORPH_CONTENT, MULTI_CONTENT, SUMMON_CONTENT, BOSS_CONTENT, EXPANSION_CONTENT, ALL_CONTENT) else "hard-information-v2" if self.content_version in (HARD_CONTENT, EXPANDED_CONTENT, G1_CONTENT, GEN_CONTENT, UP_CONTENT, TOP_CONTENT, LIFE_CONTENT, SEL_CONTENT, SET_CONTENT, MORPH_CONTENT, MULTI_CONTENT, SUMMON_CONTENT, BOSS_CONTENT, EXPANSION_CONTENT, ALL_CONTENT) else "decks-information-v1" if expanded else M6_INFORMATION if self.content_version == M6_CONTENT else INFORMATION_VERSION
        if (self.information_version, self.rules_version) != (expected_info_version, RULES_VERSION):
            raise ValueError("Unsupported information versions")
        if self.content_version in (TOP_CONTENT, LIFE_CONTENT, SEL_CONTENT, SET_CONTENT, MORPH_CONTENT, MULTI_CONTENT, SUMMON_CONTENT, BOSS_CONTENT, EXPANSION_CONTENT, ALL_CONTENT):
            if (self.limits.max_decisions > 400 or type(self.known_top) is not tuple
                    or type(self.known_bottom) is not tuple or self.known_top != self.history.known_top or (self.known_bottom and self.content_version not in (MORPH_CONTENT, MULTI_CONTENT, SUMMON_CONTENT, BOSS_CONTENT, EXPANSION_CONTENT, ALL_CONTENT))
                    or Counter(self.known_top + self.known_bottom) - Counter(self.draw_composition)
                    or len(self.known_top) + len(self.known_bottom) > len(self.draw_composition)
                    or len(self.draw_composition) + len(self.hand) + len(self.discard) + len(self.exhaust)
                    > (2145 if self.content_version in (BOSS_CONTENT, EXPANSION_CONTENT, ALL_CONTENT) else MAX_SUMMON_CARDS if self.content_version == SUMMON_CONTENT else 420)):
                raise ValueError("Invalid known draw prefix/capacity")
        elif self.known_top or self.known_bottom or self.history.known_top:
            raise ValueError("Known-position effects require a new content/encoder schema")
        if (self.exhaust and not expanded) or len(self.hand) > 10 or not 80 <= self.player_max_hp <= 80 + 1000 or (self.max_energy != 3 and self.content_version not in (EXPANSION_CONTENT, ALL_CONTENT)):
            raise ValueError("Unsupported starter state")
        if expanded:
            from .deck_observation import validate_memory
            validate_memory(self)
        elif self.known_deck or self.player_strength or self.history.removed_powers:
            raise ValueError("Expanded memory in legacy content")
        if (type(self.history.known_bottom) is not tuple or type(self.known_bottom) is not tuple
                or self.known_bottom != self.history.known_bottom
                or (self.content_version not in (MORPH_CONTENT, MULTI_CONTENT, SUMMON_CONTENT, BOSS_CONTENT, EXPANSION_CONTENT, ALL_CONTENT) and (self.history.transformed or self.history.known_bottom))):
            raise ValueError("Invalid bottom/transform history")
        generated = generated_tokens(self.history.generated, self.history.decisions, self.content_version)
        if self.content_version not in (GEN_CONTENT, UP_CONTENT, TOP_CONTENT, LIFE_CONTENT, SEL_CONTENT, SET_CONTENT, MORPH_CONTENT, MULTI_CONTENT, SUMMON_CONTENT, BOSS_CONTENT, EXPANSION_CONTENT, ALL_CONTENT) and generated:
            raise ValueError("Generated cards in legacy content")
        if self.content_version not in (UP_CONTENT, TOP_CONTENT, LIFE_CONTENT, SEL_CONTENT, SET_CONTENT, MORPH_CONTENT, MULTI_CONTENT, SUMMON_CONTENT, BOSS_CONTENT, EXPANSION_CONTENT, ALL_CONTENT) and self.history.upgraded:
            raise ValueError("Upgrade ledger in legacy content")
        expected_deck = Counter(self.known_deck) if expanded else Counter({c: n for c, _, n in STARTER})
        if self.content_version in (G1_CONTENT, GEN_CONTENT, UP_CONTENT, TOP_CONTENT, LIFE_CONTENT, SEL_CONTENT, SET_CONTENT, MORPH_CONTENT, MULTI_CONTENT, SUMMON_CONTENT, BOSS_CONTENT, EXPANSION_CONTENT, ALL_CONTENT):
            from .g1 import codec_for
            CODEC = codec_for(self.content_version)
            from .choice_state import PublicChoiceState
            if type(self.hand_states) is not tuple or (self.choice is not None and type(self.choice) is not PublicChoiceState):
                raise ValueError("G1 public state must be immutable")
            if tuple(CODEC.validate(c).token for c in self.hand_states) != self.hand:
                raise ValueError("Public hand states mismatch")
            if self.content_version in (LIFE_CONTENT, SEL_CONTENT, SET_CONTENT, MORPH_CONTENT, MULTI_CONTENT, SUMMON_CONTENT, BOSS_CONTENT, EXPANSION_CONTENT, ALL_CONTENT):
                from .lifecycle import validate_state
                for state in self.hand_states + ((self.pending_card,) if self.pending_card else ()):
                    validate_state(state, self.history)
            if self.choice is not None:
                from .g1 import allowed_choices
                self.choice.validate(CODEC, action_size(self.content_version))
                power_choice = self.content_version == EXPANSION_CONTENT and self.choice.mechanism == "power:STRATAGEM"
                if not power_choice and (self.pending_card is None or self.pending_card.token not in allowed_choices(self.content_version)):
                    raise ValueError("Invalid public pending card")
                from .extended_choices import CHOICES, validate as validate_extended
                if power_choice:
                    from .power_choices import validate
                    validate(self,CODEC)
                elif self.content_version == EXPANSION_CONTENT and self.pending_card.token.removesuffix('+') in CHOICES:
                    validate_extended(self)
                else:
                    discard_choice = self.pending_card.token.removesuffix("+") == "HEADBUTT"
                    pile_name = "discard" if discard_choice else "hand"
                    states = self.discard if discard_choice else self.hand_states
                    indices = tuple(i for i,c in enumerate(states) if self.pending_card.token != "ARMAMENTS" or not c.token.endswith("+"))
                    validate_choice_shape(self.pending_card, self.choice)
                    if (self.choice.mechanism != self.pending_card.token
                            or not self.history.played_this_turn or self.history.played_this_turn[-1] != self.pending_card.token
                            or len(self.choice.options) != len(indices)
                            or any(o.pile != pile_name or o.index != i or o.card.token != (states[i] if discard_choice else states[i].token) for i,o in zip(indices,self.choice.options))):
                        raise ValueError("Invalid public continuation")
                    if self.content_version in (LIFE_CONTENT, SEL_CONTENT, SET_CONTENT, MORPH_CONTENT, MULTI_CONTENT, SUMMON_CONTENT, BOSS_CONTENT, EXPANSION_CONTENT, ALL_CONTENT):
                        from .lifecycle import validate_state
                        for option in self.choice.options:
                            validate_state(option.card, self.history)
                            if not discard_choice and option.card != self.hand_states[option.index]:
                                raise ValueError("Choice mutable state differs from hand")
                    CODEC.validate(self.pending_card)
                    from .choice_sets import public_choice_mask
                    if self.terminal_value() is None and public_choice_mask(self.choice, CODEC, self.content_version) != self.legal_mask:
                        raise ValueError("Choice mask mismatch")
            elif self.pending_card is not None:
                raise ValueError("Pending card without choice")
        elif self.hand_states or self.pending_card is not None or self.choice is not None:
            raise ValueError("G1 state in legacy content")
        expected_deck.update(generated)
        if self.content_version in (UP_CONTENT, TOP_CONTENT, LIFE_CONTENT, SEL_CONTENT, SET_CONTENT, MORPH_CONTENT, MULTI_CONTENT, SUMMON_CONTENT, BOSS_CONTENT, EXPANSION_CONTENT, ALL_CONTENT):
            if self.content_version != EXPANSION_CONTENT:
                expected_deck = inventory(self.known_deck, self.history.generated, self.history.upgraded, self.history.decisions, self.content_version, self.history.transformed)
        pending = (self.pending_card.token,) if self.pending_card else ()
        if self.content_version == EXPANSION_CONTENT:
            from .execution import inventory as event_inventory, validate as validate_execution, states
            expected_deck=event_inventory(self.known_deck,self.history.public_events,CODEC)
            validate_execution(self,CODEC)
            from .card_memory import validate as validate_card_memory
            validate_card_memory(self,CODEC)
            from .power_memory import read as read_power_memory
            read_power_memory(self)
            if self.execution:pending=tuple(c.token for c in states(self.execution,CODEC)[1])
        elif self.execution or self.history.public_events or self.card_memory or self.power_memory:raise ValueError('Execution state outside version')
        if Counter(pending + self.hand + self.draw_composition + self.discard + self.exhaust + self.history.removed_powers) != expected_deck:
            raise ValueError("Card conservation violated")
        if any(tuple(sorted(pile)) != pile for pile in (self.draw_composition, self.exhaust) + (() if self.content_version in (TOP_CONTENT, LIFE_CONTENT, SEL_CONTENT, SET_CONTENT, MORPH_CONTENT, MULTI_CONTENT, SUMMON_CONTENT, BOSS_CONTENT, EXPANSION_CONTENT, ALL_CONTENT) else (self.discard,))):
            raise ValueError("Pile compositions must be canonical")
        if (len(self.legal_mask) != action_size(self.content_version) or any(type(v) is not bool for v in self.legal_mask)
                or (self.choice is None and any(self.legal_mask[61:])) or (self.terminal_value() is None and not any(self.legal_mask))):
            raise ValueError("Invalid public legal mask")
        if self.content_version in (MULTI_CONTENT, SUMMON_CONTENT, BOSS_CONTENT, EXPANSION_CONTENT, ALL_CONTENT):
            return self
        if self.monster_id == "MAWLER":
            validate_mawler_history(self.history.enemy_moves,
                                   mawler_move(self.intent) if self.terminal_value() is None else None)
        elif self.history.enemy_moves != moves(self.monster_id, len(self.history.enemy_moves)):
            raise ValueError("Unsupported public enemy history")
        if self.termination_reason not in (None, "win", "death", "time_limit"):
            raise ValueError("Invalid terminal reason")
        if self.terminal_value() is None:
            if self.player_hp <= 0 or self.enemy_hp <= 0 or self.history.decisions >= self.limits.max_decisions or self.turn > self.limits.max_turns:
                raise ValueError("Missing terminal reason")
            expected_shrink = -1 if self.monster_id == "SHRINKER_BEETLE" and self.turn > 1 else 0
            if (self.turn != len(self.history.enemy_moves) + 1 or self.shrink != expected_shrink
                    or self.enemy_strength != expected_strength(self.monster_id, self.history.enemy_moves)):
                raise ValueError("Public history and power state disagree")
            expected_intent = self.intent if self.monster_id == "MAWLER" else intent_after(self.monster_id, len(self.history.enemy_moves))
            if self.intent != expected_intent:
                raise ValueError("Intent disagrees with the public deterministic cycle")
        return self


def observe(world, history, limits=None, initial_hp=80, reward_version=V1, content_version=CONTENT_VERSION,
            known_deck=(), enemy_initial_hp=None, encounter=''):
    """Project only visible fields; never inspect draw_pile, RNG or private AI history.

Only validated starter worlds are supported. Power flags/appliers are inferred:
Shrink is applied by the sole enemy and remains -1; enemy Vulnerable is from
Bash and has no skipped tick. No hidden AI state exists in this audited cycle.
"""
    if content_version == ALL_CONTENT:
        from .all_content import observe_all
        return observe_all(world, history, limits, initial_hp, reward_version, content_version,
                           known_deck, enemy_initial_hp, encounter)
    if type(history) is not PublicHistory:
        raise TypeError("Explicit public history is required")
    limits = limits or EpisodeLimits()
    expanded = content_version in (DECK_CONTENT, HARD_CONTENT, EXPANDED_CONTENT, G1_CONTENT, GEN_CONTENT, UP_CONTENT, TOP_CONTENT, LIFE_CONTENT, SEL_CONTENT, SET_CONTENT, MORPH_CONTENT, MULTI_CONTENT, SUMMON_CONTENT, BOSS_CONTENT, EXPANSION_CONTENT, ALL_CONTENT)
    if ((world.pending_choice is not None and content_version not in (G1_CONTENT, GEN_CONTENT, UP_CONTENT, TOP_CONTENT, LIFE_CONTENT, SEL_CONTENT, SET_CONTENT, MORPH_CONTENT, MULTI_CONTENT, SUMMON_CONTENT, BOSS_CONTENT, EXPANSION_CONTENT, ALL_CONTENT)) or world.relics or any(p is not None for p in world.potions)
            or world.is_multiplayer or world.ascension_level != 0 or (world.play_pile and not world.is_over and not (content_version in (G1_CONTENT, GEN_CONTENT, UP_CONTENT, TOP_CONTENT, LIFE_CONTENT, SEL_CONTENT, SET_CONTENT, MORPH_CONTENT, MULTI_CONTENT, SUMMON_CONTENT, BOSS_CONTENT, EXPANSION_CONTENT, ALL_CONTENT) and world.pending_choice is not None))
            or (len(world.enemies) != 1 and content_version not in (MULTI_CONTENT, SUMMON_CONTENT, BOSS_CONTENT, EXPANSION_CONTENT, ALL_CONTENT)) or not world.enemies or world.enemies[0].monster_id not in profiles(content_version)):
        raise ValueError("Unsupported observable scope")
    if not world.is_over and world.current_side != CombatSide.PLAYER:
        raise ValueError("Not a public player decision")
    def cards(pile):
        for card in pile:
            if expanded:
                from .deck_observation import validate_card
                validate_card(card, content_version)
                if content_version in (LIFE_CONTENT, SEL_CONTENT, SET_CONTENT, MORPH_CONTENT, MULTI_CONTENT, SUMMON_CONTENT, BOSS_CONTENT, EXPANSION_CONTENT, ALL_CONTENT):
                    from .g1 import codec_for
                    from .lifecycle import validate_state
                    validate_state(codec_for(content_version).capture(card), history)
            else:
                _card_index(card)
        return tuple(card_token(card) if expanded else card.card_id.name for card in pile)
    hand = cards(world.hand)
    pending_card, choice, hand_states = None, None, ()
    if content_version in (G1_CONTENT, GEN_CONTENT, UP_CONTENT, TOP_CONTENT, LIFE_CONTENT, SEL_CONTENT, SET_CONTENT, MORPH_CONTENT, MULTI_CONTENT, SUMMON_CONTENT, BOSS_CONTENT, EXPANSION_CONTENT, ALL_CONTENT):
        from .g1 import codec_for, observe_choice
        CODEC = codec_for(content_version)
        hand_states = tuple(CODEC.capture(c) for c in world.hand)
        pending_card, choice = observe_choice(world, content_version)
    # A killing card can remain in the engine's play zone after the terminal
    # short-circuit. Include that public card in terminal discard composition;
    # terminal states are never reconstructed or passed to the value network.
    played_cards = world.play_pile if choice is None and content_version!=EXPANSION_CONTENT else []
    played = tuple(token for token, card in zip(cards(played_cards), played_cards) if not card.is_power)
    discard = cards(world.discard_pile) + played
    if content_version not in (TOP_CONTENT, LIFE_CONTENT, SEL_CONTENT, SET_CONTENT, MORPH_CONTENT, MULTI_CONTENT, SUMMON_CONTENT, BOSS_CONTENT, EXPANSION_CONTENT, ALL_CONTENT):
        discard = tuple(sorted(discard))
    exhaust = tuple(sorted(cards(world.exhaust_pile)))
    remaining = Counter(known_deck) if expanded else Counter({c: n for c, _, n in STARTER})
    remaining.update(generated_tokens(history.generated, history.decisions, content_version))
    if content_version in (UP_CONTENT, TOP_CONTENT, LIFE_CONTENT, SEL_CONTENT, SET_CONTENT, MORPH_CONTENT, MULTI_CONTENT, SUMMON_CONTENT, BOSS_CONTENT, EXPANSION_CONTENT, ALL_CONTENT):
        if content_version != EXPANSION_CONTENT:
            remaining = inventory(known_deck, history.generated, history.upgraded, history.decisions, content_version, history.transformed)
    execution=''
    pending_tokens=(pending_card.token,) if pending_card else ()
    if content_version == EXPANSION_CONTENT:
        from .execution import capture as capture_execution, inventory as event_inventory, states
        execution=capture_execution(world,CODEC)
        remaining=event_inventory(known_deck,history.public_events,CODEC)
        if execution:pending_tokens=tuple(c.token for c in states(execution,CODEC)[1])
    remaining.subtract(pending_tokens + hand + discard + exhaust + history.removed_powers)
    if any(n < 0 for n in remaining.values()):
        raise ValueError("Visible cards exceed known deck")
    draw = tuple(sorted(remaining.elements()))
    enemies, boss = (), None
    if content_version in (BOSS_CONTENT, EXPANSION_CONTENT, ALL_CONTENT):
        from .boss import capture
        if content_version == EXPANSION_CONTENT:
            from .foundation import capture_enemies
            enemies,boss = capture_enemies(world,history,enemy_initial_hp,capture)
        else: enemies, boss = capture(world, history, enemy_initial_hp)
        enemy_initial_hp = enemies[0].initial_hp
    elif content_version == SUMMON_CONTENT:
        from .summon import capture_slots
        enemies = capture_slots(world, history, enemy_initial_hp)
        enemy_initial_hp = enemies[0].initial_hp
    elif content_version == MULTI_CONTENT:
        from .multi import capture_enemies
        enemies = capture_enemies(world, history, enemy_initial_hp)
        enemy_initial_hp = enemies[0].initial_hp
    player, enemy = world.player, world.enemies[0]
    allowed_player = (PowerId.SHRINK, PowerId.STRENGTH) if expanded else (PowerId.SHRINK,)
    allowed_enemy = (PowerId.VULNERABLE, PowerId.STRENGTH, PowerId.SLOW, PowerId.TERRITORIAL) if content_version in (HARD_CONTENT, EXPANDED_CONTENT, G1_CONTENT, GEN_CONTENT, UP_CONTENT, TOP_CONTENT, LIFE_CONTENT, SEL_CONTENT, SET_CONTENT, MORPH_CONTENT, MULTI_CONTENT, SUMMON_CONTENT, BOSS_CONTENT, EXPANSION_CONTENT, ALL_CONTENT) else (PowerId.VULNERABLE, PowerId.STRENGTH)
    if content_version in (EXPANDED_CONTENT, G1_CONTENT, GEN_CONTENT, UP_CONTENT, TOP_CONTENT, LIFE_CONTENT, SEL_CONTENT, SET_CONTENT, MORPH_CONTENT, MULTI_CONTENT, SUMMON_CONTENT, BOSS_CONTENT, EXPANSION_CONTENT, ALL_CONTENT):
        allowed_player += (PowerId.VULNERABLE,)
        allowed_enemy += (PowerId.ARTIFACT,)
    if content_version in (SEL_CONTENT, SET_CONTENT, MORPH_CONTENT, MULTI_CONTENT, SUMMON_CONTENT, BOSS_CONTENT, EXPANSION_CONTENT, ALL_CONTENT):
        allowed_player += (PowerId.RETAIN_HAND,)
    if content_version in (BOSS_CONTENT, EXPANSION_CONTENT, ALL_CONTENT):
        allowed_enemy += (PowerId.ILLUSION, PowerId.MINION, PowerId.ADAPTABLE, PowerId.ENRAGE, PowerId.PAINFUL_STABS, PowerId.NEMESIS, PowerId.INTANGIBLE)
    if content_version == SUMMON_CONTENT:
        # Visible minion flags only; every slot is validated by capture_slots.
        allowed_enemy += (PowerId.ILLUSION, PowerId.MINION)
    if content_version == EXPANSION_CONTENT:
        from .player_abilities import POWER_IDS
        allowed_player += tuple(POWER_IDS.values())
        from .foundation import PLAYER, ENEMY
        allowed_player += tuple(PowerId[n] for n in PLAYER)
        allowed_enemy += tuple(PowerId[n] for n in ENEMY)
    if any(p not in allowed_player for p in player.powers) or any(p not in allowed_enemy for p in enemy.powers):
        raise ValueError("Unsupported public powers")
    shrink = player.powers.get(PowerId.SHRINK)
    vulnerable = enemy.powers.get(PowerId.VULNERABLE)
    strength = enemy.powers.get(PowerId.STRENGTH)
    # Intent is public. _current_state_id / state_log / performed flags are not read.
    intents = world.enemy_ais[enemy.combat_id].current_move.intents
    attack_buff = (content_version in (EXPANDED_CONTENT, G1_CONTENT, GEN_CONTENT, UP_CONTENT, TOP_CONTENT, LIFE_CONTENT, SEL_CONTENT, SET_CONTENT, MORPH_CONTENT, MULTI_CONTENT, SUMMON_CONTENT, BOSS_CONTENT, EXPANSION_CONTENT, ALL_CONTENT)
                   and enemy.monster_id in ("CUBEX_CONSTRUCT", "FOGMOG")
                   and tuple(i.intent_type.name for i in intents) == ("ATTACK", "BUFF"))
    if len(intents) != 1 and not attack_buff and enemy.monster_id != "TEST_SUBJECT":
        raise ValueError("Unsupported public intent")
    intent = intents[0]
    reason = ("win" if world.player_won else "death") if world.is_over else None
    if reason is None and (history.decisions >= limits.max_decisions or world.turn_count > limits.max_turns):
        reason = "time_limit"
    mask = tuple(bool(v) for v in public_mask(world, content_version)) if reason is None else (False,) * action_size(content_version)
    return InformationState(player.current_hp, player.max_hp, player.block, world.energy, world.max_energy,
                            world.turn_count, hand, draw, discard, exhaust, shrink.amount if shrink else 0,
                            enemy.current_hp, enemy.max_hp, enemy.block, vulnerable.amount if vulnerable else 0,
                            enemies[0].intent if enemies else ("ATTACK_BUFF" if attack_buff else intent.intent_type.name, intent.damage, intent.hits), history, mask, limits, reason,
                            enemies=enemies, boss=boss, execution=execution,
                            power_memory=__import__('sts2_env.az.power_memory',fromlist=['capture']).capture(world) if content_version==EXPANSION_CONTENT else '',
                            card_memory=__import__("sts2_env.az.card_memory",fromlist=["capture"]).capture(world,history,known_deck,CODEC,execution) if content_version==EXPANSION_CONTENT else "",
                            basic_statuses=__import__("sts2_env.az.foundation",fromlist=["capture"]).capture(world) if content_version == EXPANSION_CONTENT else (),
                            retain_hand=player.powers[PowerId.RETAIN_HAND].amount if PowerId.RETAIN_HAND in player.powers else 0,
                            known_top=history.known_top, known_bottom=history.known_bottom, hand_states=hand_states, pending_card=pending_card, choice=choice,
                            initial_hp=initial_hp, reward_version=reward_version, content_version=content_version,
                            information_version="ironclad-colorless-information-v5" if content_version == EXPANSION_CONTENT else "boss-information-v1" if content_version in (BOSS_CONTENT, EXPANSION_CONTENT, ALL_CONTENT) else "summon-information-v1" if content_version == SUMMON_CONTENT else "multi-information-v1" if content_version == MULTI_CONTENT else "morph-information-v1" if content_version in (MORPH_CONTENT, MULTI_CONTENT, SUMMON_CONTENT, BOSS_CONTENT, EXPANSION_CONTENT, ALL_CONTENT) else "selection-information-v2" if content_version in (SET_CONTENT, MORPH_CONTENT, MULTI_CONTENT, SUMMON_CONTENT, BOSS_CONTENT, EXPANSION_CONTENT, ALL_CONTENT) else "selection-information-v1" if content_version in (SEL_CONTENT, SET_CONTENT, MORPH_CONTENT, MULTI_CONTENT, SUMMON_CONTENT, BOSS_CONTENT, EXPANSION_CONTENT, ALL_CONTENT) else "lifecycle-information-v1" if content_version == LIFE_CONTENT else "topdeck-information-v1" if content_version == TOP_CONTENT else "upgrades-information-v1" if content_version == UP_CONTENT else "generated-information-v1" if content_version == GEN_CONTENT else "g1-information-v1" if content_version in (G1_CONTENT, GEN_CONTENT, UP_CONTENT, TOP_CONTENT, LIFE_CONTENT, SEL_CONTENT, SET_CONTENT, MORPH_CONTENT, MULTI_CONTENT, SUMMON_CONTENT, BOSS_CONTENT, EXPANSION_CONTENT, ALL_CONTENT) else "expanded-information-v3" if content_version == EXPANDED_CONTENT else "hard-information-v2" if content_version in (HARD_CONTENT, EXPANDED_CONTENT, G1_CONTENT, GEN_CONTENT, UP_CONTENT, TOP_CONTENT, LIFE_CONTENT, SEL_CONTENT, SET_CONTENT, MORPH_CONTENT, MULTI_CONTENT, SUMMON_CONTENT, BOSS_CONTENT, EXPANSION_CONTENT, ALL_CONTENT) else "decks-information-v1" if expanded else M6_INFORMATION if content_version == M6_CONTENT else INFORMATION_VERSION,
                            monster_id=enemy.monster_id, enemy_strength=strength.amount if strength else 0,
                            known_deck=known_deck, enemy_initial_hp=enemy_initial_hp,
                            enemy_slow=enemy.powers[PowerId.SLOW].amount if PowerId.SLOW in enemy.powers else 0,
                            enemy_territorial=enemy.powers[PowerId.TERRITORIAL].amount if PowerId.TERRITORIAL in enemy.powers else 0,
                            enemy_artifact=enemy.powers[PowerId.ARTIFACT].amount if PowerId.ARTIFACT in enemy.powers else 0,
                            player_vulnerable=player.powers[PowerId.VULNERABLE].amount if PowerId.VULNERABLE in player.powers else 0,
                            player_abilities=tuple((p.name, obj.amount) for p, obj in player.powers.items() if content_version == EXPANSION_CONTENT and p in POWER_IDS.values()),
                            player_strength=player.powers[PowerId.STRENGTH].amount if PowerId.STRENGTH in player.powers else 0).validate()


class SearchParticle:
    """One causal hypothetical world; keep its sampled deck and RNG for the path."""
    def __init__(self, world, info, next_card_id):
        self.world, self.info, self.next_card_id = world, info, next_card_id
        self.enemy_slots = tuple(world.enemies)

    def step(self, action):
        saved_id = card_base._next_instance_id
        try:
            card_base._next_instance_id = self.next_card_id
            if self.world.pending_choice is not None:
                from .choice_sets import resolve_choice
                if not resolve_choice(self.world, action, self.info.content_version):
                    raise ValueError("Particle choice rejected")
            else:
                apply_action(self.world, action)
            if self.info.content_version in (BOSS_CONTENT, EXPANSION_CONTENT, ALL_CONTENT):
                from .boss import check_transition
                check_transition(self.info, self.world, self.enemy_slots)
                self.enemy_slots = tuple(self.world.enemies)
            elif self.info.content_version == MULTI_CONTENT:
                from .multi import check_transition
                check_transition(self.info, self.world, self.enemy_slots)
            elif self.info.content_version == SUMMON_CONTENT:
                from .summon import check_transition
                check_transition(self.info, self.world, self.enemy_slots)
                self.enemy_slots = tuple(self.world.enemies)
            history = self.info.history.after_action(self.info, action, combat_ended=self.world.is_over, after_hand=tuple(card_token(c) for c in self.world.hand))
            if self.info.content_version in (BOSS_CONTENT, EXPANSION_CONTENT, ALL_CONTENT):
                from .boss import finish_history
                history = finish_history(self.info, self.world, history, action)
            self.next_card_id = card_base._next_instance_id
            # Initial roster HP only: a summoned slot is identified by its own
            # public spawned flag, never by a shifted initial-HP tuple.
            initial_hp = (tuple(e.initial_hp for e in self.info.enemies)
                          if self.info.content_version == MULTI_CONTENT else
                          tuple(e.initial_hp for e in self.info.enemies if not e.spawned)
                          if self.info.content_version in (SUMMON_CONTENT, BOSS_CONTENT, EXPANSION_CONTENT, ALL_CONTENT) else self.info.enemy_initial_hp)
            self.info = observe(self.world, history, self.info.limits, self.info.initial_hp, self.info.reward_version, self.info.content_version,
                                self.info.known_deck, initial_hp)
            return self.info
        finally:
            card_base._next_instance_id = saved_id


class BeliefSampler:
    def sample(self, info, search_rng):
        if type(info) is not InformationState:
            raise TypeError("BeliefSampler accepts only InformationState, never WorldState/recipe")
        info.validate()
        if info.terminal_value() is not None:
            raise ValueError("Cannot sample a terminal information state")
        saved_id = card_base._next_instance_id
        try:
            # Local IDs cannot encode the environment's allocator/seed.
            card_base._next_instance_id = 0
            rng = Rng(int(search_rng.integers(0, 2**31)))
            world = CombatState(info.player_hp, info.player_max_hp, [], 0, relics=[], potions=[], character_id="Ironclad")
            from sts2_env.monsters.act1_weak import create_fuzzy_wurm_crawler, create_nibbit
            from sts2_env.monsters.act1 import (create_bygone_effigy, create_byrdonis, create_cubex_construct,
                                               create_mawler, create_fogmog, create_eye_with_teeth)
            from sts2_env.monsters.act3 import create_test_subject
            factory = {"SHRINKER_BEETLE": create_shrinker_beetle, "FUZZY_WURM_CRAWLER": create_fuzzy_wurm_crawler,
                       "NIBBIT": create_nibbit, "BYGONE_EFFIGY": create_bygone_effigy,
                       "BYRDONIS": create_byrdonis, "CUBEX_CONSTRUCT": create_cubex_construct,
                       "MAWLER": create_mawler, "FOGMOG": create_fogmog,
                       "EYE_WITH_TEETH": create_eye_with_teeth,
                       "TEST_SUBJECT": create_test_subject}[info.monster_id]
            enemy, ai = factory(Rng(0))  # factory only; overwrite public HP; Nibbit is_alone=True
            if info.content_version in (BOSS_CONTENT, EXPANSION_CONTENT, ALL_CONTENT):
                from .boss import create_enemies
                create_enemies(world, info, rng)
                enemy = world.enemies[0]
                ai = world.enemy_ais[enemy.combat_id]
            elif info.content_version == SUMMON_CONTENT:
                from .summon import create_enemies
                create_enemies(world, info, rng)
                enemy = world.enemies[0]
                ai = world.enemy_ais[enemy.combat_id]
            elif info.content_version == MULTI_CONTENT:
                from .multi import create_enemies
                create_enemies(world, info)
                enemy = world.enemies[0]
                ai = world.enemy_ais[enemy.combat_id]
            else:
                world.add_enemy(enemy, ai)
            world.start_combat()  # empty deck: no hidden historical draw is copied or guessed
            world.rng = rng
            world.player.block = info.player_block
            world.energy = info.energy
            world.turn_count = world.round_number = info.turn
            enemy.current_hp, enemy.max_hp, enemy.block = info.enemy_hp, info.enemy_max_hp, info.enemy_block
            if info.content_version in (MULTI_CONTENT, SUMMON_CONTENT, BOSS_CONTENT, EXPANSION_CONTENT, ALL_CONTENT):
                pass  # All slots restored together below.
            elif info.monster_id == "MAWLER":
                # Infer the hypothetical AI memory from public moves/intent only.
                # Never replay random draws or access the real AI log/RNG.
                ai.state_log = list(info.history.enemy_moves)
                ai._current_state_id = mawler_move(info.intent)
                ai._performed_first_move = bool(info.history.enemy_moves)
            else:
                for _ in info.history.enemy_moves:
                    ai.on_move_performed()
                    ai.roll_move(rng)  # deterministic audited cycle consumes no random draws
            for attr, names in (("hand", info.hand), ("draw_pile", info.draw_composition),
                                ("discard_pile", info.discard), ("exhaust_pile", info.exhaust)):
                cards = [] if info.content_version in (SUMMON_CONTENT, BOSS_CONTENT, EXPANSION_CONTENT, ALL_CONTENT) else [make_token(name) if info.content_version in (DECK_CONTENT, HARD_CONTENT, EXPANDED_CONTENT, G1_CONTENT, GEN_CONTENT, UP_CONTENT, TOP_CONTENT, LIFE_CONTENT, SEL_CONTENT, SET_CONTENT, MORPH_CONTENT, MULTI_CONTENT, SUMMON_CONTENT, BOSS_CONTENT, EXPANSION_CONTENT, ALL_CONTENT) else FACTORIES[name]() for name in names]
                if info.content_version in (BOSS_CONTENT, EXPANSION_CONTENT, ALL_CONTENT):
                    from .lifecycle import restore_token
                    cards = [restore_token(name, info.history) for name in names]
                elif info.content_version == SUMMON_CONTENT:
                    # DAZED is generated-only; its card state is still public.
                    from .summon import restore_card
                    cards = [restore_card(name, info.history) for name in names]
                elif info.content_version in (LIFE_CONTENT, SEL_CONTENT, SET_CONTENT, MORPH_CONTENT, MULTI_CONTENT, SUMMON_CONTENT, BOSS_CONTENT, EXPANSION_CONTENT, ALL_CONTENT):
                    from .lifecycle import restore_token
                    cards = [restore_token(name, info.history) for name in names]
                for card in cards:
                    card.owner = world.player
                setattr(world, attr, cards)
            # One shared stream, also used by every future shuffle/AI/target event.
            prefix = []
            for token in info.known_top:
                card = next(c for c in world.draw_pile if card_token(c) == token)
                world.draw_pile.remove(card)
                prefix.append(card)
            suffix = []
            for token in info.known_bottom:
                card = next(c for c in world.draw_pile if card_token(c) == token)
                world.draw_pile.remove(card)
                suffix.append(card)
            rng.shuffle(world.draw_pile)
            world.draw_pile = prefix + world.draw_pile + suffix
            if info.content_version==EXPANSION_CONTENT:
                from .card_memory import restore as restore_card_memory
                from .content_expansion import CODEC as MEMORY_CODEC
                restore_card_memory(world,info,MEMORY_CODEC)
                from .all_cards import RETURNING
                # One returning face per play made this turn.  Played copies sit
                # in the discard pile first; a redrawn copy is matched in hand by
                # its identical public face, so no hidden instance identity is used.
                for token in set(info.history.played_this_turn):
                    remaining = info.history.played_this_turn.count(token)
                    if token.removesuffix('+') not in RETURNING or not remaining:
                        continue
                    # Played copies are appended to the discard pile in play
                    # order, so the most recent matching faces are exactly the
                    # ones that carry the return marker.  Pile order matters for
                    # the next shuffle, so this is not interchangeable with an
                    # arbitrary same-face choice.
                    for card in reversed(list(world.discard_pile)):
                        if remaining <= 0:
                            break
                        if card_token(card) == token:
                            card.combat_vars['_return_before_hand_draw_round'] = info.turn + 1
                            remaining -= 1
                    for card in list(world.hand):
                        if remaining <= 0:
                            break
                        if card_token(card) == token:
                            card.combat_vars['_return_before_hand_draw_round'] = info.turn + 1
                            remaining -= 1
                # Combat-wide play count is public through the start/finish
                # journal; only counts and card types are ever read from it.
                world._played_cards_combat = [make_token(e[1]) for e in info.history.public_events
                                              if e[0] == 'start']
                for card in world._played_cards_combat:
                    card.owner = world.player
            all_cards = world.hand + world.draw_pile + world.discard_pile + world.exhaust_pile
            state = world.current_player_state
            state.starting_deck = list(all_cards)
            state.player_state.deck = list(all_cards)
            if info.content_version in (SEL_CONTENT, SET_CONTENT, MORPH_CONTENT, MULTI_CONTENT, SUMMON_CONTENT, BOSS_CONTENT, EXPANSION_CONTENT, ALL_CONTENT):
                world._energy_spent_this_turn[world.player] = sum(p.energy for p in info.history.payments)
                if info.retain_hand:
                    world.apply_power_to(world.player, PowerId.RETAIN_HAND, info.retain_hand, applier=world.player)
            if info.shrink:
                world.apply_power_to(world.player, PowerId.SHRINK, info.shrink, applier=enemy)
            if info.vulnerable:
                world.apply_power_to(enemy, PowerId.VULNERABLE, info.vulnerable, applier=world.player)
            if info.enemy_strength:
                enemy.apply_power(PowerId.STRENGTH, info.enemy_strength)
            if info.player_strength:
                world.apply_power_to(world.player, PowerId.STRENGTH, info.player_strength, applier=world.player)
            if info.history.exhausted_this_turn:
                pool = list(world.exhaust_pile)
                for token in info.history.exhausted_this_turn:
                    card = next(c for c in pool if card_token(c) == token)
                    pool.remove(card); world._exhaust_events_this_turn.append(card)
            if info.player_abilities:
                from .player_abilities import POWER_IDS
                for name, amount in info.player_abilities:
                    world.apply_power_to(world.player, POWER_IDS[name], amount, applier=world.player)
            if info.enemy_artifact:
                world.apply_power_to(enemy, PowerId.ARTIFACT, info.enemy_artifact, applier=enemy)
            if info.player_vulnerable:
                world.apply_power_to(world.player, PowerId.VULNERABLE, info.player_vulnerable, applier=enemy)
                # Mawler applied it before the preceding enemy turn ended;
                # that public boundary already consumed the first skipped tick.
                world.player.powers[PowerId.VULNERABLE].skip_next_tick = False
            if info.enemy_slow:
                # This public counter is fully determined by observed card plays,
                # including skills/powers; never copied from a real private object.
                enemy.powers[PowerId.SLOW]._slow_amount = len(info.history.played_this_turn) - int(info.choice is not None)
            # Only the number/type of current-turn plays matters in this scope;
            # reuse the public discarded card objects rather than inventing cards.
            available = list(world.discard_pile)
            for name in (info.history.played_this_turn[:-1] if info.choice else info.history.played_this_turn):
                if info.content_version in (DECK_CONTENT, HARD_CONTENT, EXPANDED_CONTENT, G1_CONTENT, GEN_CONTENT, UP_CONTENT, TOP_CONTENT, LIFE_CONTENT, SEL_CONTENT, SET_CONTENT, MORPH_CONTENT, MULTI_CONTENT, SUMMON_CONTENT, BOSS_CONTENT, EXPANSION_CONTENT, ALL_CONTENT):
                    # Draw/shuffle can move or replay the same card in a turn.
                    # Supported hooks inspect play types/counts, never identity.
                    card = make_token(name)
                    card.owner = world.player
                    world._played_cards_this_turn.append(card)
                    continue
                card = next((c for c in available if c.card_id.name == name), None)
                if card is None:
                    raise ValueError("Played-card memory inconsistent with public discard")
                available.remove(card)
                world._played_cards_this_turn.append(card)
            if info.content_version in (G1_CONTENT, GEN_CONTENT, UP_CONTENT, TOP_CONTENT, LIFE_CONTENT, SEL_CONTENT, SET_CONTENT, MORPH_CONTENT, MULTI_CONTENT, SUMMON_CONTENT, BOSS_CONTENT, EXPANSION_CONTENT, ALL_CONTENT):
                from .g1 import codec_for, restore_continuation
                CODEC = codec_for(info.content_version)
                world.hand = [CODEC.restore(c) for c in info.hand_states]
                for card in world.hand:
                    card.owner = world.player
                restore_continuation(world, info)
                all_cards = world.hand + world.draw_pile + world.discard_pile + world.exhaust_pile + world.play_pile
                state.starting_deck = list(all_cards)
                state.player_state.deck = list(all_cards)
            if info.content_version in (BOSS_CONTENT, EXPANSION_CONTENT, ALL_CONTENT):
                from .boss import restore_enemies
                restore_enemies(world, info, rng)
            elif info.content_version == SUMMON_CONTENT:
                from .summon import restore_enemies
                restore_enemies(world, info, rng)
            elif info.content_version == MULTI_CONTENT:
                from .multi import restore_enemies
                restore_enemies(world, info, rng)
            if info.content_version == EXPANSION_CONTENT:
                from .foundation import restore
                restore(world,info)
                from .execution import restore as restore_execution
                restore_execution(world,info,CODEC)
                from .power_memory import restore as restore_power_memory
                restore_power_memory(world,info)
            projected = observe(world, info.history, info.limits, info.initial_hp, info.reward_version, info.content_version,
                                info.known_deck,
                                tuple(e.initial_hp for e in info.enemies) if info.content_version == MULTI_CONTENT
                                else tuple(e.initial_hp for e in info.enemies if not e.spawned)
                                if info.content_version in (SUMMON_CONTENT, BOSS_CONTENT, EXPANSION_CONTENT, ALL_CONTENT) else info.enemy_initial_hp)
            if projected != info:
                raise ValueError("Particle does not reproduce the root public state/legal actions")
            return SearchParticle(world, projected, card_base._next_instance_id)
        finally:
            card_base._next_instance_id = saved_id



