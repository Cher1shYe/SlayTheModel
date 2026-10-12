"""Focused Act 1 event parity tests backed by decompiled event models."""

import sts2_env.events.act1  # noqa: F401

from sts2_env.cards.factory import create_card
from sts2_env.cards.factory import eligible_registered_cards
from sts2_env.cards.ironclad import create_ironclad_starter_deck
from sts2_env.core.card_pools import CardPoolId
from sts2_env.core.enums import CardId, CardRarity
from sts2_env.events.act1 import BrainLeech, RoomFullOfCheese, TeaMaster, TheLegendsWereTrue
from sts2_env.relics.base import RelicId
from sts2_env.run.modifiers import ModifierModel
from sts2_env.run.reward_objects import CardReward, PotionReward
from sts2_env.run.rewards import CARD_CREATION_SOURCE_OTHER, CardRewardGenerationOptions
from sts2_env.run.run_manager import RunManager
from sts2_env.run.run_state import PlayerState, RunState


IRONCLAD_CHARACTER_ID = "Ironclad"
SILENT_CHARACTER_ID = "Silent"
BRAIN_LEECH_RIP_HP_LOSS = 5
BRAIN_LEECH_RIP_CARD_OPTION_COUNT = 3
BRAIN_LEECH_SHARE_FROM_CARD_CHOICE_COUNT = 5
ROOM_FULL_OF_CHEESE_SEARCH_HP_LOSS = 14
ROOM_FULL_OF_CHEESE_GORGE_CARD_CHOICE_COUNT = 2
ROOM_FULL_OF_CHEESE_GORGE_FROM_CARD_CHOICE_COUNT = 8
THE_LEGENDS_WERE_TRUE_MIN_HP = 10
THE_LEGENDS_WERE_TRUE_EXIT_HP_LOSS = 8
TEA_MASTER_BONE_TEA_COST = 50
TEA_MASTER_EMBER_TEA_COST = 150
BELOW_BONE_TEA_GOLD = TEA_MASTER_BONE_TEA_COST - 10
BETWEEN_TEA_COSTS_GOLD = TEA_MASTER_BONE_TEA_COST + 10
ABOVE_EMBER_TEA_GOLD = TEA_MASTER_EMBER_TEA_COST + 10


def _make_act1_run_state(seed: int = 401) -> RunState:
    run_state = RunState(seed=seed, character_id=IRONCLAD_CHARACTER_ID)
    run_state.initialize_run()
    run_state.player.deck = create_ironclad_starter_deck()
    return run_state


class _FirstChoiceCountingRng:
    def __init__(self) -> None:
        self.choice_calls = 0

    def choice(self, seq):
        self.choice_calls += 1
        return seq[0]


class _RareRewardModifier(ModifierModel):
    def __init__(self) -> None:
        super().__init__("rare_reward")

    def modify_card_reward_creation_options(self, player, options, reward, room, run_state):
        return CardRewardGenerationOptions(
            context=options.context,
            num_cards=options.num_cards,
            character_ids=options.character_ids,
            forced_rarities=(CardRarity.RARE,) * options.num_cards,
            include_colorless=options.include_colorless,
            use_default_character_pool=options.use_default_character_pool,
            generation_context=options.generation_context,
            roll_upgrade=options.roll_upgrade,
            card_type=options.card_type,
            card_creation_source=options.card_creation_source,
            allow_card_pool_modifications=options.allow_card_pool_modifications,
            allow_rarity_modifications=options.allow_rarity_modifications,
            allow_hook_upgrades=options.allow_hook_upgrades,
            has_custom_card_pool=options.has_custom_card_pool,
            custom_card_ids=options.custom_card_ids,
        )


def test_brain_leech_share_knowledge_uses_original_five_card_required_choice():
    run_state = _make_act1_run_state(801)
    event = BrainLeech()
    start_hp = run_state.player.current_hp

    result = event.choose(run_state, "share_knowledge")

    assert result.finished
    assert run_state.player.current_hp == start_hp
    reward = result.rewards["reward_objects"][0]
    assert isinstance(reward, CardReward)
    assert reward.option_count == BRAIN_LEECH_SHARE_FROM_CARD_CHOICE_COUNT
    assert reward.cards_to_pick == 1
    assert reward.skippable is False
    assert reward.generation_context is None
    assert reward.roll_upgrade is False
    assert reward.use_default_character_pool is True
    assert reward.include_colorless is False
    assert reward.cards == []


def test_brain_leech_rip_uses_original_hp_loss_and_colorless_reward():
    run_state = _make_act1_run_state(802)
    event = BrainLeech()
    start_hp = run_state.player.current_hp

    result = event.choose(run_state, "rip")

    assert result.finished
    assert run_state.player.current_hp == start_hp - BRAIN_LEECH_RIP_HP_LOSS
    rewards = result.rewards["reward_objects"]
    assert len(rewards) == 1
    reward = rewards[0]
    assert isinstance(reward, CardReward)
    assert reward.option_count == BRAIN_LEECH_RIP_CARD_OPTION_COUNT
    assert reward.cards_to_pick == 1
    assert reward.skippable is True
    assert reward.character_ids == ()
    assert reward.include_colorless is True
    assert reward.use_default_character_pool is False
    assert reward.generation_context is None
    assert reward.roll_upgrade is False


def test_brain_leech_share_knowledge_reward_is_populated_and_not_skippable():
    mgr = RunManager(seed=803, character_id=IRONCLAD_CHARACTER_ID)
    mgr._phase = RunManager.PHASE_EVENT
    event = BrainLeech()
    mgr._event_model = event
    mgr._event_options = event.generate_initial_options(mgr.run_state)

    result = mgr._do_event_choice({"option_id": "share_knowledge"})

    assert result["phase"] == RunManager.PHASE_CARD_REWARD
    assert isinstance(mgr._current_reward, CardReward)
    assert len(mgr._current_reward.cards) == BRAIN_LEECH_SHARE_FROM_CARD_CHOICE_COUNT
    assert not any(action["action"] == "skip" for action in mgr.get_available_actions())


def test_brain_leech_share_knowledge_uses_reward_generation_modifiers():
    mgr = RunManager(seed=804, character_id=IRONCLAD_CHARACTER_ID)
    mgr.run_state.modifiers = [_RareRewardModifier()]
    mgr._phase = RunManager.PHASE_EVENT
    event = BrainLeech()
    mgr._event_model = event
    mgr._event_options = event.generate_initial_options(mgr.run_state)

    result = mgr._do_event_choice({"option_id": "share_knowledge"})

    assert result["phase"] == RunManager.PHASE_CARD_REWARD
    assert len(mgr._current_reward.cards) == BRAIN_LEECH_SHARE_FROM_CARD_CHOICE_COUNT
    assert all(card.rarity == CardRarity.RARE for card in mgr._current_reward.cards)


def test_room_full_of_cheese_gorge_uses_original_common_two_of_eight_choice():
    run_state = _make_act1_run_state(805)
    event = RoomFullOfCheese()
    start_hp = run_state.player.current_hp

    result = event.choose(run_state, "gorge")

    assert result.finished
    assert run_state.player.current_hp == start_hp
    reward = result.rewards["reward_objects"][0]
    assert isinstance(reward, CardReward)
    assert reward.option_count == ROOM_FULL_OF_CHEESE_GORGE_FROM_CARD_CHOICE_COUNT
    assert reward.cards_to_pick == ROOM_FULL_OF_CHEESE_GORGE_CARD_CHOICE_COUNT
    assert reward.skippable is False
    assert reward.forced_rarities == ()
    assert reward.generation_context is None
    assert reward.roll_upgrade is False
    assert reward.card_creation_source == CARD_CREATION_SOURCE_OTHER
    assert reward.allow_rarity_modifications is False
    assert reward.card_pool_rarity_filter is CardRarity.COMMON
    assert reward.use_uniform_noncombat_odds is True
    assert reward.cards == []


def test_room_full_of_cheese_no_rarity_modification_limits_dingy_rug_pool():
    run_state = _make_act1_run_state(8051)
    assert run_state.player.obtain_relic(RelicId.DINGY_RUG.name)
    event = RoomFullOfCheese()

    result = event.choose(run_state, "gorge")
    reward = result.rewards["reward_objects"][0]
    reward.populate(run_state, None)

    colorless_uncommon_pool = set(
        eligible_registered_cards(
            card_pool=CardPoolId.COLORLESS,
            rarity=CardRarity.UNCOMMON,
            generation_context=None,
        )
    )
    assert not any(card.card_id in colorless_uncommon_pool for card in reward.cards)
    assert not any(card_id in colorless_uncommon_pool for card_id in reward.custom_card_ids)


def test_room_full_of_cheese_gorge_stays_on_same_reward_until_two_picks():
    mgr = RunManager(seed=806, character_id=IRONCLAD_CHARACTER_ID)
    mgr._phase = RunManager.PHASE_EVENT
    event = RoomFullOfCheese()
    mgr._event_model = event
    mgr._event_options = event.generate_initial_options(mgr.run_state)

    result = mgr._do_event_choice({"option_id": "gorge"})
    assert result["phase"] == RunManager.PHASE_CARD_REWARD
    assert isinstance(mgr._current_reward, CardReward)
    assert mgr._current_reward.cards_to_pick == ROOM_FULL_OF_CHEESE_GORGE_CARD_CHOICE_COUNT
    assert len(mgr._current_reward.cards) == ROOM_FULL_OF_CHEESE_GORGE_FROM_CARD_CHOICE_COUNT
    assert all(card.rarity == CardRarity.COMMON for card in mgr._current_reward.cards)
    assert not any(action["action"] == "skip" for action in mgr.get_available_actions())

    first = mgr.take_action({"action": "pick_card", "index": 0})
    assert first["phase"] == RunManager.PHASE_CARD_REWARD
    assert first["pending_more_picks"] is True

    second = mgr.take_action({"action": "pick_card", "index": 0})
    assert second["phase"] == RunManager.PHASE_MAP_CHOICE


def test_room_full_of_cheese_search_uses_original_hp_loss_and_chosen_cheese():
    run_state = _make_act1_run_state(807)
    event = RoomFullOfCheese()
    start_hp = run_state.player.current_hp

    result = event.choose(run_state, "search")

    assert result.finished
    assert run_state.player.current_hp == start_hp - ROOM_FULL_OF_CHEESE_SEARCH_HP_LOSS
    assert "CHOSEN_CHEESE" in run_state.player.relics


def test_the_legends_were_true_requires_original_act_deck_and_hp_conditions():
    run_state = _make_act1_run_state(808)
    event = TheLegendsWereTrue()

    assert event.is_allowed(run_state)

    run_state.player.current_hp = THE_LEGENDS_WERE_TRUE_MIN_HP - 1
    assert event.is_allowed(run_state) is False
    run_state.player.current_hp = THE_LEGENDS_WERE_TRUE_MIN_HP

    ally = run_state.add_player(
        PlayerState(
            player_id=2,
            character_id=SILENT_CHARACTER_ID,
            current_hp=THE_LEGENDS_WERE_TRUE_MIN_HP,
        )
    )
    ally.deck = []
    assert event.is_allowed(run_state) is False

    ally.deck = [create_card(CardId.STRIKE_SILENT)]
    ally.current_hp = THE_LEGENDS_WERE_TRUE_MIN_HP - 1
    assert event.is_allowed(run_state) is False

    ally.current_hp = THE_LEGENDS_WERE_TRUE_MIN_HP
    assert event.is_allowed(run_state) is True

    run_state.current_act_index = 1
    assert event.is_allowed(run_state) is False


def test_the_legends_were_true_nab_the_map_adds_spoils_map():
    run_state = _make_act1_run_state(809)
    event = TheLegendsWereTrue()
    deck_before = len(run_state.player.deck)

    result = event.choose(run_state, "nab_map")

    assert result.finished
    assert len(run_state.player.deck) == deck_before + 1
    assert run_state.player.deck[-1].card_id == CardId.SPOILS_MAP


def test_the_legends_were_true_slowly_find_exit_uses_original_hp_loss_and_potion_reward():
    run_state = _make_act1_run_state(810)
    event = TheLegendsWereTrue()
    start_hp = run_state.player.current_hp
    potions_before = len(run_state.player.held_potions())

    result = event.choose(run_state, "find_exit")

    assert result.finished
    assert run_state.player.current_hp == start_hp - THE_LEGENDS_WERE_TRUE_EXIT_HP_LOSS
    assert len(run_state.player.held_potions()) == potions_before
    rewards = result.rewards["reward_objects"]
    assert len(rewards) == 1
    assert isinstance(rewards[0], PotionReward)
    assert rewards[0].potion_id is not None


def test_the_legends_were_true_potion_uses_rewards_rng_once_before_reward_populate():
    run_state = _make_act1_run_state(811)
    run_state.rng.rewards = _FirstChoiceCountingRng()
    event = TheLegendsWereTrue()

    result = event.choose(run_state, "find_exit")
    reward = result.rewards["reward_objects"][0]

    assert reward.potion_id == "BloodPotion"
    assert run_state.rng.rewards.choice_calls == 1

    reward.populate(run_state, None)

    assert reward.potion_id == "BloodPotion"
    assert run_state.rng.rewards.choice_calls == 1


def test_tea_master_options_match_original_owner_gold_thresholds():
    run_state = _make_act1_run_state(812)
    event = TeaMaster()

    run_state.player.gold = BELOW_BONE_TEA_GOLD
    options = event.generate_initial_options(run_state)
    assert [option.option_id for option in options] == ["bone_tea", "ember_tea", "discourtesy"]
    assert [option.enabled for option in options] == [False, False, True]

    run_state.player.gold = BETWEEN_TEA_COSTS_GOLD
    options = event.generate_initial_options(run_state)
    assert [option.option_id for option in options] == ["bone_tea", "ember_tea", "discourtesy"]
    assert [option.enabled for option in options] == [True, False, True]

    run_state.player.gold = ABOVE_EMBER_TEA_GOLD
    options = event.generate_initial_options(run_state)
    assert [option.option_id for option in options] == ["bone_tea", "ember_tea", "discourtesy"]
    assert [option.enabled for option in options] == [True, True, True]


def test_tea_master_requires_every_player_to_have_ember_tea_gold_in_act_one_or_two():
    run_state = _make_act1_run_state(813)
    run_state.player.gold = TEA_MASTER_EMBER_TEA_COST
    ally = run_state.add_player(
        PlayerState(
            player_id=2,
            character_id=SILENT_CHARACTER_ID,
            gold=TEA_MASTER_EMBER_TEA_COST - 1,
        )
    )
    event = TeaMaster()

    assert event.is_allowed(run_state) is False

    ally.gold = TEA_MASTER_EMBER_TEA_COST
    assert event.is_allowed(run_state) is True

    run_state.current_act_index = 2
    assert event.is_allowed(run_state) is False


def test_tea_master_choices_use_original_gold_costs_and_relics():
    run_state = _make_act1_run_state(814)
    event = TeaMaster()

    run_state.player.gold = ABOVE_EMBER_TEA_GOLD
    result = event.choose(run_state, "bone_tea")
    assert result.finished
    assert run_state.player.gold == ABOVE_EMBER_TEA_GOLD - TEA_MASTER_BONE_TEA_COST
    assert "BONE_TEA" in run_state.player.relics

    run_state.player.gold = ABOVE_EMBER_TEA_GOLD
    result = event.choose(run_state, "ember_tea")
    assert result.finished
    assert run_state.player.gold == ABOVE_EMBER_TEA_GOLD - TEA_MASTER_EMBER_TEA_COST
    assert "EMBER_TEA" in run_state.player.relics

    gold_before = run_state.player.gold
    result = event.choose(run_state, "discourtesy")
    assert result.finished
    assert run_state.player.gold == gold_before
    assert "TEA_OF_DISCOURTESY" in run_state.player.relics
