"""Parity tests for shared event reward and choice handling."""

import sts2_env.events.shared  # noqa: F401

from sts2_env.cards.factory import create_card
from sts2_env.cards.factory import eligible_registered_cards
from sts2_env.cards.ironclad import create_ironclad_starter_deck
from sts2_env.core.card_pools import CardPoolId
from sts2_env.core.enums import CardId, CardRarity
from sts2_env.events.shared import (
    ColorfulPhilosophers,
    SunkenTreasury,
    TabletOfTruth,
    TinkerTime,
    ThisOrThat,
    Wellspring,
)
from sts2_env.relics.base import RelicId
from sts2_env.run.reward_objects import CardReward
from sts2_env.run.rewards import CARD_CREATION_SOURCE_OTHER
from sts2_env.run.run_state import RunState


def _make_run_state(seed: int = 401, character_id: str = "Ironclad") -> RunState:
    run_state = RunState(seed=seed, character_id=character_id)
    run_state.initialize_run()
    run_state.player.deck = create_ironclad_starter_deck()
    return run_state


class _ExclusiveRollsRng:
    def __init__(self, rolls: list[int]):
        self._rolls = iter(rolls)

    def next_int_exclusive(self, low: int, high: int) -> int:
        return next(self._rolls)


class _NoopShuffleRng:
    def shuffle(self, seq) -> None:
        pass


class _SwapFirstTwoRng:
    def __init__(self) -> None:
        self.shuffle_calls = 0

    def shuffle(self, seq) -> None:
        self.shuffle_calls += 1
        seq[0], seq[1] = seq[1], seq[0]


class _FixedRemovalRng:
    def __init__(self, rolls: list[int]):
        self._rolls = iter(rolls)

    def next_int_exclusive(self, low: int, high: int) -> int:
        return next(self._rolls)


class _FirstChoiceUpgradeRng:
    def choice(self, values):
        return list(values)[0]

    def next_float(self, upper: float = 1.0) -> float:
        return 0.0


def _count_card(deck, card_id: CardId) -> int:
    return sum(1 for card in deck if card.card_id == card_id)


def _card_reward_with_rarity(rewards: list[CardReward], rarity: CardRarity) -> CardReward:
    return next(reward for reward in rewards if reward.card_pool_rarity_filter is rarity)


def test_colorful_philosophers_choice_surfaces_three_rarity_tiered_card_rewards():
    run_state = _make_run_state(401, character_id="Defect")
    event = ColorfulPhilosophers()
    event.rng = _FixedRemovalRng([1])

    options = event.generate_initial_options(run_state)
    assert len(options) == 3
    assert list(event._choices.values()) == ["Necrobinder", "Regent", "Silent"]
    chosen_option_id = options[0].option_id
    chosen_pool = event._choices[chosen_option_id]

    result = event.choose(run_state, chosen_option_id)
    assert result.finished
    rewards = result.rewards["reward_objects"]
    assert len(rewards) == 3
    assert all(isinstance(reward, CardReward) for reward in rewards)
    assert all(reward.character_ids == (chosen_pool,) for reward in rewards)
    assert all(reward.use_default_character_pool is False for reward in rewards)
    assert all(reward.card_creation_source == CARD_CREATION_SOURCE_OTHER for reward in rewards)
    assert all(reward.roll_upgrade is True for reward in rewards)
    assert all(reward.allow_rarity_modifications is False for reward in rewards)
    assert all(reward.use_uniform_noncombat_odds is True for reward in rewards)
    assert [reward.card_pool_rarity_filter for reward in rewards] == [
        CardRarity.COMMON,
        CardRarity.UNCOMMON,
        CardRarity.RARE,
    ]
    assert all(reward.forced_rarities == () for reward in rewards)


def test_colorful_philosophers_no_rarity_modification_limits_dingy_rug_pool():
    run_state = _make_run_state(413, character_id="Defect")
    assert run_state.player.obtain_relic(RelicId.DINGY_RUG.name)
    event = ColorfulPhilosophers()
    event.rng = _FixedRemovalRng([1])
    event.generate_initial_options(run_state)

    result = event.choose(run_state, "pool_1")
    reward = _card_reward_with_rarity(result.rewards["reward_objects"], CardRarity.UNCOMMON)
    reward.populate(run_state, None)

    colorless_uncommon_pool = set(
        eligible_registered_cards(
            card_pool=CardPoolId.COLORLESS,
            rarity=CardRarity.UNCOMMON,
            generation_context=None,
        )
    )
    colorless_rare_pool = set(
        eligible_registered_cards(
            card_pool=CardPoolId.COLORLESS,
            rarity=CardRarity.RARE,
            generation_context=None,
        )
    )
    assert any(card_id in reward.custom_card_ids for card_id in colorless_uncommon_pool)
    assert not any(card_id in reward.custom_card_ids for card_id in colorless_rare_pool)


def test_colorful_philosophers_uniform_rewards_still_roll_card_upgrades():
    run_state = _make_run_state(414, character_id="Defect")
    run_state.current_act_index = 1
    run_state.rng.rewards = _FirstChoiceUpgradeRng()
    event = ColorfulPhilosophers()
    event.rng = _FixedRemovalRng([1])
    event.generate_initial_options(run_state)

    result = event.choose(run_state, "pool_1")
    reward = _card_reward_with_rarity(result.rewards["reward_objects"], CardRarity.UNCOMMON)
    reward.populate(run_state, None)

    assert len(reward.cards) == 3
    assert all(card.upgraded for card in reward.cards)


def test_colorful_philosophers_uses_event_rng_without_advancing_up_front_rng():
    run_state = _make_run_state(411, character_id="Defect")
    event = ColorfulPhilosophers()
    up_front_counter = run_state.rng.up_front.counter

    options = event.generate_initial_options(run_state)

    assert len(options) == 3
    assert run_state.rng.up_front.counter == up_front_counter


def test_colorful_philosophers_filters_to_unlocked_character_card_pools():
    run_state = _make_run_state(412, character_id="Ironclad")
    run_state.player.unlock_state["character_card_pools"] = ["Ironclad", "Silent", "Defect"]
    event = ColorfulPhilosophers()

    options = event.generate_initial_options(run_state)

    assert [option.option_id for option in options] == ["pool_1", "pool_2"]
    assert list(event._choices.values()) == ["Silent", "Defect"]


def test_sunken_treasury_first_and_second_chests_apply_gold_and_greed_curse():
    first_state = _make_run_state(402)
    first_event = SunkenTreasury()
    first_event.rng = _ExclusiveRollsRng([8, 30])
    first_event.generate_initial_options(first_state)
    first_start_gold = first_state.player.gold

    first = first_event.choose(first_state, "first_chest")
    assert first.finished
    assert first_state.player.gold == first_start_gold + 60

    second_state = _make_run_state(403)
    second_event = SunkenTreasury()
    second_event.rng = _ExclusiveRollsRng([8, 30])
    second_event.generate_initial_options(second_state)
    second_start_gold = second_state.player.gold
    greed_before = _count_card(second_state.player.deck, CardId.GREED)

    second = second_event.choose(second_state, "second_chest")
    assert second.finished
    assert second_state.player.gold == second_start_gold + 333
    assert _count_card(second_state.player.deck, CardId.GREED) == greed_before + 1


def test_tablet_of_truth_decipher_chain_costs_max_hp_and_ends_with_no_upgradable_cards():
    run_state = _make_run_state(404)
    event = TabletOfTruth()
    event.generate_initial_options(run_state)

    assert run_state.player.upgradable_deck_cards()
    for _ in range(4):
        result = event.choose(run_state, "decipher")
        assert result.finished is False

    assert run_state.player.max_hp == 35
    fifth = event.choose(run_state, "decipher")
    assert fifth.finished
    assert run_state.player.max_hp == 1
    assert run_state.player.current_hp == 1
    assert run_state.is_over is False
    assert run_state.player.upgradable_deck_cards() == []


def test_tablet_of_truth_non_final_decipher_uses_event_rng_for_upgrade_selection():
    run_state = _make_run_state(4041)
    first = create_card(CardId.DEFEND_IRONCLAD)
    second = create_card(CardId.STRIKE_IRONCLAD)
    run_state.player.deck = [first, second]
    event = TabletOfTruth()
    event.rng = _SwapFirstTwoRng()
    rewards_counter = run_state.rng.rewards.counter

    result = event.choose(run_state, "decipher")

    assert result.finished is False
    assert event.rng.shuffle_calls == 1
    assert run_state.rng.rewards.counter == rewards_counter
    assert first.upgraded is False
    assert second.upgraded is True


def test_tablet_of_truth_final_decipher_upgrades_all_without_random_selection():
    run_state = _make_run_state(4042)
    run_state.player.deck = [
        create_card(CardId.DEFEND_IRONCLAD),
        create_card(CardId.STRIKE_IRONCLAD),
        create_card(CardId.BASH),
    ]
    event = TabletOfTruth()
    event.rng = _SwapFirstTwoRng()
    event._decipher_count = 4  # noqa: SLF001
    rewards_counter = run_state.rng.rewards.counter
    niche_counter = run_state.rng.niche.counter

    result = event.choose(run_state, "decipher")

    assert result.finished
    assert event.rng.shuffle_calls == 0
    assert run_state.rng.rewards.counter == rewards_counter
    assert run_state.rng.niche.counter == niche_counter
    assert all(card.upgraded for card in run_state.player.deck)


def test_tablet_of_truth_give_up_does_not_heal():
    run_state = _make_run_state(405)
    run_state.player.current_hp = 20
    event = TabletOfTruth()
    event.generate_initial_options(run_state)

    first = event.choose(run_state, "decipher")
    assert first.finished is False
    hp_before_give_up = run_state.player.current_hp
    give_up = event.choose(run_state, "give_up")
    assert give_up.finished
    assert run_state.player.current_hp == hp_before_give_up


def test_this_or_that_plain_and_ornate_apply_hp_gold_relic_and_clumsy():
    plain_state = _make_run_state(406)
    plain_event = ThisOrThat()
    plain_event.rng = _ExclusiveRollsRng([55])
    plain_event.generate_initial_options(plain_state)
    plain_start_hp = plain_state.player.current_hp
    plain_start_gold = plain_state.player.gold

    plain = plain_event.choose(plain_state, "plain")
    assert plain.finished
    assert plain_state.player.current_hp == plain_start_hp - 6
    assert plain_state.player.gold == plain_start_gold + 55

    ornate_state = _make_run_state(407)
    ornate_event = ThisOrThat()
    ornate_event.generate_initial_options(ornate_state)
    relics_before = len(ornate_state.player.relics)
    clumsy_before = _count_card(ornate_state.player.deck, CardId.CLUMSY)

    ornate = ornate_event.choose(ornate_state, "ornate")
    assert ornate.finished
    assert len(ornate_state.player.relics) == relics_before + 1
    assert _count_card(ornate_state.player.deck, CardId.CLUMSY) == clumsy_before + 1


def test_wellspring_bathe_pending_choice_removes_selected_card_and_adds_guilty():
    run_state = _make_run_state(408)
    event = Wellspring()
    guilty_before = _count_card(run_state.player.deck, CardId.GUILTY)
    deck_size_before = len(run_state.player.deck)

    bathe = event.choose(run_state, "bathe")
    assert bathe.finished is False
    assert event.pending_choice is not None
    assert event.pending_choice.allow_skip is False

    removed = event.pending_choice.options[0].card
    resolved = event.resolve_pending_choice(0)
    assert resolved.finished
    assert event.pending_choice is None
    assert len(run_state.player.deck) == deck_size_before
    assert all(card.instance_id != removed.instance_id for card in run_state.player.deck)
    assert _count_card(run_state.player.deck, CardId.GUILTY) == guilty_before + 1


def test_tinker_time_creates_configured_mad_science_card():
    run_state = _make_run_state(409)
    event = TinkerTime()
    event.rng = _NoopShuffleRng()

    initial = event.generate_initial_options(run_state)
    assert [option.option_id for option in initial] == ["choose_card_type"]

    first = event.choose(run_state, "choose_card_type")
    assert first.finished is False
    assert {option.option_id for option in first.next_options}
    chosen_type = first.next_options[0].option_id
    second = event.choose(run_state, chosen_type)
    assert second.finished is False
    rider = second.next_options[0].option_id
    final = event.choose(run_state, rider)
    assert final.finished
    mad_science = run_state.player.deck[-1]
    assert mad_science.card_id == CardId.MAD_SCIENCE
    assert mad_science.card_type.name == chosen_type.upper()
    assert mad_science.effect_vars["rider"] > 0


def test_tinker_time_uses_event_rng_without_advancing_up_front_rng():
    run_state = _make_run_state(410)
    event = TinkerTime()
    up_front_counter = run_state.rng.up_front.counter

    first = event.choose(run_state, "choose_card_type")
    chosen_type = first.next_options[0].option_id
    second = event.choose(run_state, chosen_type)

    assert first.finished is False
    assert second.finished is False
    assert run_state.rng.up_front.counter == up_front_counter
