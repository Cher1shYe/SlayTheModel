"""Focused tests for shared event parity improvements."""

import sts2_env.events.shared  # noqa: F401

from sts2_env.cards.factory import create_card
from sts2_env.cards.ironclad import create_ironclad_starter_deck
from sts2_env.core.enums import CardId
from sts2_env.cards.silent import make_backstab
from sts2_env.cards.status import make_clumsy, make_decay, make_doubt, make_exterminate, make_greed, make_guilty, make_injury, make_lantern_key, make_metamorphosis, make_poor_sleep, make_regret, make_squash
from sts2_env.relics.base import RelicId
from sts2_env.run.run_manager import RunManager
from sts2_env.run.reward_objects import UpgradeCardsReward
from sts2_env.run.run_state import PlayerState, RunState
from sts2_env.events.shared import Amalgamator, BattlewornDummy, Bugslayer, ColorfulPhilosophers, ColossalFlower, Darv, DenseVegetation, DoorsOfLightAndDark, DrowningBeacon, GraveOfTheForgotten, HungryForMushrooms, InfestedAutomaton, LostWisp, Nonupeipe, Orobas, Pael, PunchOff, RoundTeaParty, SpiritGrafter, SunkenStatue, SunkenTreasury, Tanx, Tezcatara, TheLanternKey, ThisOrThat, Trial, TrashHeap, UnrestSite, Vakuu, Wellspring, _event_potion_options


class _ExclusiveHighRng:
    def next_int(self, low: int, high: int) -> int:
        raise AssertionError(f"expected exclusive RNG call, got inclusive {low}, {high}")

    def next_int_exclusive(self, low: int, high: int) -> int:
        return high - 1


class _FixedIntRng:
    def __init__(self, value: int):
        self.value = value

    def next_int(self, low: int, high: int) -> int:
        return self.value


class _DarvRng:
    def __init__(self) -> None:
        self.shuffle_inputs = []

    def choice(self, seq):
        return seq[-1]

    def shuffle(self, seq) -> None:
        self.shuffle_inputs.append(list(seq))
        seq.reverse()

    def next_int(self, low: int, high: int) -> int:
        return 0


class _SwapFirstTwoRng:
    def __init__(self) -> None:
        self.shuffle_calls = 0

    def shuffle(self, seq) -> None:
        self.shuffle_calls += 1
        seq[0], seq[1] = seq[1], seq[0]

    def next_int(self, low: int, high: int) -> int:
        return 0


class _LastChoiceRng:
    def choice(self, seq):
        return seq[-1]


class _FirstChoiceCountingRng:
    def __init__(self) -> None:
        self.choice_calls = 0

    def choice(self, seq):
        self.choice_calls += 1
        return seq[0]


class _DeckSizeOnAddModifier:
    def __init__(self) -> None:
        self.deck_sizes: list[int] = []

    def after_card_added_to_deck(self, player, card, source=None) -> None:
        self.deck_sizes.append(len(player.deck))


def test_shared_event_random_gold_uses_exclusive_upper_bounds():
    run_state = RunState(seed=6, character_id="Ironclad")
    run_state.initialize_run()
    run_state.rng.up_front = _ExclusiveHighRng()

    lost_wisp = LostWisp()
    lost_wisp.rng = _ExclusiveHighRng()
    lost_wisp.calculate_vars(run_state)
    assert lost_wisp._gold == 75

    punch_off = PunchOff()
    punch_off.rng = _ExclusiveHighRng()
    punch_off.calculate_vars(run_state)
    assert punch_off._gold == 98

    statue = SunkenStatue()
    statue.rng = _ExclusiveHighRng()
    statue.calculate_vars(run_state)
    assert statue._gold == 121

    treasury = SunkenTreasury()
    treasury.rng = _ExclusiveHighRng()
    treasury.calculate_vars(run_state)
    assert treasury._small_gold == 67
    assert treasury._large_gold == 363

    this_or_that = ThisOrThat()
    this_or_that.rng = _ExclusiveHighRng()
    this_or_that.calculate_vars(run_state)
    assert this_or_that._gold == 68


def test_round_tea_party_pick_fight_is_multi_page_and_grants_relic():
    run_state = RunState(seed=7, character_id="Ironclad")
    run_state.initialize_run()
    event = RoundTeaParty()

    result = event.choose(run_state, "pick_fight")
    assert not result.finished
    assert result.next_options[0].option_id == "continue_fight"

    starting_hp = run_state.player.current_hp
    starting_relics = len(run_state.player.relics)
    result = event.choose(run_state, "continue_fight")
    assert result.finished
    assert run_state.player.current_hp == starting_hp - 11
    assert len(run_state.player.relics) == starting_relics + 1


def test_trial_accept_randomizes_variant_and_merchant_guilty_adds_rewards():
    run_state = RunState(seed=11, character_id="Ironclad")
    run_state.initialize_run()
    event = Trial()
    event.rng = _FixedIntRng(0)
    event.generate_initial_options(run_state)

    result = event.choose(run_state, "accept")
    assert not result.finished
    option_ids = {option.option_id for option in result.next_options}
    assert option_ids == {"merchant_guilty", "merchant_innocent"}

    starting_relics = len(run_state.player.relics)
    result = event.choose(run_state, "merchant_guilty")
    assert result.finished
    assert any(card.card_id == make_regret().card_id for card in run_state.player.deck)
    assert len(run_state.player.relics) == starting_relics + 2


def test_trial_nondescript_guilty_surfaces_card_rewards_through_run_manager():
    mgr = RunManager(seed=13, character_id="Ironclad")
    mgr._phase = RunManager.PHASE_EVENT
    event = Trial()
    mgr._event_model = event
    mgr._event_options = event.generate_initial_options(mgr.run_state)
    mgr.run_state.rng.niche.next_int = lambda low, high: 2  # nondescript branch

    first = mgr._do_event_choice({"option_id": "accept"})
    assert first["phase"] == RunManager.PHASE_EVENT

    second = mgr._do_event_choice({"option_id": "nondescript_guilty"})
    assert second["phase"] == RunManager.PHASE_CARD_REWARD
    assert any(card.card_id == make_doubt().card_id for card in mgr.run_state.player.deck)
    rewards = [mgr._current_reward, *mgr._pending_rewards]
    assert all(getattr(reward, "roll_upgrade", True) is False for reward in rewards)

    actions = mgr.get_available_actions()
    reward_actions = [action for action in actions if action["action"] == "pick_card"]
    assert len(reward_actions) == 3


def test_trial_merchant_innocent_uses_run_level_upgrade_reward_chain():
    mgr = RunManager(seed=41, character_id="Ironclad")
    mgr.run_state.player.deck = create_ironclad_starter_deck()
    mgr._phase = RunManager.PHASE_EVENT
    event = Trial()
    mgr._event_model = event
    mgr._event_options = event.generate_initial_options(mgr.run_state)
    mgr.run_state.rng.niche.next_int = lambda low, high: 0

    mgr._do_event_choice({"option_id": "accept"})
    result = mgr._do_event_choice({"option_id": "merchant_innocent"})
    assert result["phase"] == RunManager.PHASE_CARD_REWARD

    actions = mgr.get_available_actions()
    choose_actions = [action for action in actions if action["action"] == "choose"]
    assert choose_actions

    mgr.take_action({"action": "choose", "index": 0})
    mgr.take_action({"action": "choose", "index": 1})
    final = mgr.take_action({"action": "confirm_choice"})
    assert final["phase"] == RunManager.PHASE_MAP_CHOICE


def test_trial_double_down_ends_run():
    mgr = RunManager(seed=17, character_id="Ironclad")
    mgr._phase = RunManager.PHASE_EVENT
    event = Trial()
    mgr._event_model = event
    mgr._event_options = event.generate_initial_options(mgr.run_state)

    first = mgr._do_event_choice({"option_id": "reject"})
    assert first["phase"] == RunManager.PHASE_EVENT

    second = mgr._do_event_choice({"option_id": "double_down"})
    assert second["phase"] == RunManager.PHASE_RUN_OVER


def test_battleworn_dummy_and_trash_heap_surface_real_rewards():
    run_state = RunState(seed=19, character_id="Ironclad")
    run_state.initialize_run()

    dummy = BattlewornDummy()
    result = dummy.choose(run_state, "setting_1")
    rewards = result.rewards["reward_objects"]
    assert result.event_combat_setup == "battleworn_dummy_v1"
    assert len(rewards) == 1
    assert rewards[0].reward_type.name == "POTION"

    heap = TrashHeap()
    result = heap.choose(run_state, "dive_in")
    assert result.finished
    assert run_state.player.relics[-1] in TrashHeap._RELICS  # noqa: SLF001


def test_deferred_remove_then_damage_events_remove_card_before_lethal_hp_loss():
    mgr = RunManager(seed=1930, character_id="Ironclad")
    mgr.run_state.player.current_hp = 9
    mgr._phase = RunManager.PHASE_EVENT
    event = SpiritGrafter()
    mgr._event_model = event
    mgr._event_options = event.generate_initial_options(mgr.run_state)
    deck_before = len(mgr.run_state.player.deck)

    result = mgr._do_event_choice({"option_id": "rejection"})

    assert result["phase"] == RunManager.PHASE_CARD_REWARD
    assert mgr.run_state.pending_choice is not None
    assert mgr.run_state.player.current_hp == 9

    final = mgr.take_action({"action": "choose", "index": 0})

    assert final["phase"] == RunManager.PHASE_RUN_OVER
    assert len(mgr.run_state.player.deck) == deck_before - 1
    assert mgr.run_state.player.current_hp == 0


def test_deferred_dense_vegetation_trudge_removes_card_before_lethal_hp_loss():
    mgr = RunManager(seed=19301, character_id="Ironclad")
    mgr.run_state.player.current_hp = 11
    mgr._phase = RunManager.PHASE_EVENT
    event = DenseVegetation()
    mgr._event_model = event
    mgr._event_options = event.generate_initial_options(mgr.run_state)
    deck_before = len(mgr.run_state.player.deck)

    result = mgr._do_event_choice({"option_id": "trudge_on"})

    assert result["phase"] == RunManager.PHASE_CARD_REWARD
    assert mgr.run_state.pending_choice is not None
    assert mgr.run_state.player.current_hp == 11

    final = mgr.take_action({"action": "choose", "index": 0})

    assert final["phase"] == RunManager.PHASE_RUN_OVER
    assert len(mgr.run_state.player.deck) == deck_before - 1
    assert mgr.run_state.player.current_hp == 0


def test_deferred_amalgamator_adds_ultimate_card_after_removing_selected_cards():
    mgr = RunManager(seed=19302, character_id="Ironclad")
    modifier = _DeckSizeOnAddModifier()
    mgr.run_state.modifiers = [modifier]
    mgr._phase = RunManager.PHASE_EVENT
    event = Amalgamator()
    mgr._event_model = event
    mgr._event_options = event.generate_initial_options(mgr.run_state)
    deck_before = len(mgr.run_state.player.deck)

    result = mgr._do_event_choice({"option_id": "combine_strikes"})

    assert result["phase"] == RunManager.PHASE_CARD_REWARD
    assert mgr.run_state.pending_choice is not None

    mgr.take_action({"action": "choose", "index": 0})
    mgr.take_action({"action": "choose", "index": 1})
    final = mgr.take_action({"action": "confirm_choice"})

    assert final["phase"] == RunManager.PHASE_MAP_CHOICE
    assert modifier.deck_sizes[-1] == deck_before - 1
    assert any(card.card_id == CardId.ULTIMATE_STRIKE for card in mgr.run_state.player.deck)


def test_trash_heap_uses_event_rng_fixed_relic_and_card_pools():
    run_state = RunState(seed=1931, character_id="Ironclad")
    run_state.initialize_run()
    event = TrashHeap()
    event.rng = _LastChoiceRng()
    hp_before = run_state.player.current_hp
    gold_before = run_state.player.gold
    deck_before = len(run_state.player.deck)
    up_front_counter = run_state.rng.up_front.counter
    rewards_counter = run_state.rng.rewards.counter

    dive = event.choose(run_state, "dive_in")
    grab = event.choose(run_state, "grab")

    assert dive.finished
    assert grab.finished
    assert run_state.player.current_hp == hp_before - 8
    assert run_state.player.relics[-1] == "THE_BOOT"
    assert run_state.player.gold == gold_before + 100
    assert len(run_state.player.deck) == deck_before + 1
    assert run_state.player.deck[-1].card_id == CardId.STACK
    assert run_state.rng.up_front.counter == up_front_counter
    assert run_state.rng.rewards.counter == rewards_counter


def test_trash_heap_requires_all_players_above_spawn_hp_threshold():
    run_state = RunState(seed=1932, character_id="Ironclad")
    run_state.initialize_run()
    run_state.player.current_hp = 6
    ally = run_state.add_player(PlayerState(player_id=2, character_id="Silent", current_hp=5))
    event = TrashHeap()

    assert event.is_allowed(run_state) is False

    ally.current_hp = 6
    assert event.is_allowed(run_state) is True


def test_battleworn_dummy_setting_two_enters_combat_with_upgrade_reward():
    run_state = RunState(seed=191, character_id="Ironclad")
    run_state.initialize_run()
    run_state.player.deck = create_ironclad_starter_deck()
    dummy = BattlewornDummy()

    result = dummy.choose(run_state, "setting_2")

    assert result.finished
    assert result.event_combat_setup == "battleworn_dummy_v2"
    reward = result.rewards["reward_objects"][0]
    assert isinstance(reward, UpgradeCardsReward)
    assert reward.count == 2
    assert len(reward.cards) == 2
    assert sum(1 for card in run_state.player.deck if card.upgraded) == 0


def test_battleworn_dummy_setting_three_enters_combat_with_relic_reward():
    run_state = RunState(seed=1903, character_id="Ironclad")
    run_state.initialize_run()
    dummy = BattlewornDummy()
    starting_relics = len(run_state.player.relics)

    result = dummy.choose(run_state, "setting_3")

    assert result.finished
    assert result.event_combat_setup == "battleworn_dummy_v3"
    assert len(run_state.player.relics) == starting_relics
    assert result.rewards["reward_objects"][0].reward_type.name == "RELIC"


def test_event_specific_potion_rewards_are_rolled_before_reward_population():
    run_state = RunState(seed=1910, character_id="Ironclad")
    run_state.initialize_run()
    run_state.rng.rewards = _FirstChoiceCountingRng()

    assert [model.potion_id for model in _event_potion_options(run_state)[:4]] == [
        "BloodPotion",
        "SoldiersStew",
        "Ashwater",
        "AttackPotion",
    ]

    dummy = BattlewornDummy()
    dummy_reward = dummy.choose(run_state, "setting_1").rewards["reward_objects"][0]
    assert dummy_reward.potion_id == "BloodPotion"

    spring = Wellspring()
    spring_reward = spring.choose(run_state, "bottle").rewards["reward_objects"][0]
    assert spring_reward.potion_id == "BloodPotion"

    assert run_state.rng.rewards.choice_calls == 2

    dummy_reward.populate(run_state, None)
    spring_reward.populate(run_state, None)

    assert dummy_reward.potion_id == "BloodPotion"
    assert spring_reward.potion_id == "BloodPotion"
    assert run_state.rng.rewards.choice_calls == 2


def test_event_specific_potion_options_follow_unlocked_epoch_filtering():
    locked_state = RunState(seed=1911, character_id="Ironclad")
    locked_state.initialize_run()
    locked_state.player.unlock_state["unlocked_epochs"] = []

    locked_ids = [model.potion_id for model in _event_potion_options(locked_state)]

    assert "BloodPotion" not in locked_ids
    assert "SoldiersStew" not in locked_ids
    assert "Ashwater" not in locked_ids
    assert "BeetleJuice" not in locked_ids
    assert "MazalethsGift" not in locked_ids
    assert "DropletOfPrecognition" not in locked_ids
    assert "PowderedDemise" not in locked_ids
    assert "ShipInABottle" not in locked_ids
    assert "TouchOfInsanity" not in locked_ids
    assert "AttackPotion" in locked_ids

    unlocked_state = RunState(seed=1912, character_id="Ironclad")
    unlocked_state.initialize_run()
    unlocked_state.player.unlock_state["unlocked_epochs"] = [
        "IRONCLAD4_EPOCH",
        "POTION1_EPOCH",
        "POTION2_EPOCH",
    ]

    unlocked_ids = [model.potion_id for model in _event_potion_options(unlocked_state)]

    assert unlocked_ids[:3] == ["BloodPotion", "SoldiersStew", "Ashwater"]
    assert "BeetleJuice" in unlocked_ids
    assert "MazalethsGift" in unlocked_ids
    assert "DropletOfPrecognition" in unlocked_ids
    assert "PowderedDemise" in unlocked_ids
    assert "ShipInABottle" in unlocked_ids
    assert "TouchOfInsanity" in unlocked_ids


def test_battleworn_dummy_setting_two_uses_niche_rng_for_upgrade_selection():
    run_state = RunState(seed=1911, character_id="Ironclad")
    run_state.initialize_run()
    first = create_card(CardId.DEFEND_IRONCLAD)
    second = create_card(CardId.STRIKE_IRONCLAD)
    third = create_card(CardId.BASH)
    run_state.player.deck = [first, second, third]
    run_state.rng.niche = _SwapFirstTwoRng()
    rewards_counter = run_state.rng.rewards.counter
    dummy = BattlewornDummy()

    result = dummy.choose(run_state, "setting_2")

    assert result.finished
    assert run_state.rng.niche.shuffle_calls == 1
    assert run_state.rng.rewards.counter == rewards_counter
    reward = result.rewards["reward_objects"][0]
    assert isinstance(reward, UpgradeCardsReward)
    assert reward.cards == [first, third]
    assert first.upgraded is False
    assert second.upgraded is False
    assert third.upgraded is False


def test_doors_of_light_and_dark_light_and_dark_apply_real_effects():
    run_state = RunState(seed=192, character_id="Ironclad")
    run_state.initialize_run()
    run_state.player.deck = create_ironclad_starter_deck()
    event = DoorsOfLightAndDark()
    starting_deck = len(run_state.player.deck)

    light = event.choose(run_state, "light")
    assert light.finished
    assert sum(1 for card in run_state.player.deck if card.upgraded) >= 2

    dark = event.choose(run_state, "dark")
    assert dark.finished is False
    assert event.pending_choice is not None
    resolved = event.resolve_pending_choice(0)
    assert resolved.finished
    assert len(run_state.player.deck) == starting_deck - 1


def test_unrest_site_rest_adds_poor_sleep_curse():
    run_state = RunState(seed=23, character_id="Ironclad")
    run_state.initialize_run()
    event = UnrestSite()

    result = event.choose(run_state, "rest")
    assert result.finished
    assert any(card.card_id == make_poor_sleep().card_id for card in run_state.player.deck)


def test_unrest_site_requires_all_players_below_hp_threshold():
    run_state = RunState(seed=231, character_id="Ironclad")
    run_state.initialize_run()
    run_state.player.current_hp = 56
    ally = run_state.add_player(
        PlayerState(player_id=2, character_id="Silent", max_hp=70, current_hp=50)
    )
    event = UnrestSite()

    assert event.is_allowed(run_state) is False

    ally.current_hp = 49
    assert event.is_allowed(run_state) is True


def test_bugslayer_adds_real_reward_cards_to_deck():
    run_state = RunState(seed=29, character_id="Ironclad")
    run_state.initialize_run()
    event = Bugslayer()

    exterminate = event.choose(run_state, "exterminate")
    assert exterminate.finished
    assert any(card.card_id == make_exterminate().card_id for card in run_state.player.deck)

    squash = event.choose(run_state, "squash")
    assert squash.finished
    assert any(card.card_id == make_squash().card_id for card in run_state.player.deck)


def test_dense_vegetation_spirit_grafter_and_wellspring_apply_real_state_changes():
    run_state = RunState(seed=61, character_id="Ironclad")
    run_state.initialize_run()
    run_state.player.deck = create_ironclad_starter_deck()
    starting_deck = len(run_state.player.deck)

    vegetation = DenseVegetation()
    result = vegetation.choose(run_state, "trudge_on")
    assert not result.finished
    result = vegetation.resolve_pending_choice(0)
    assert result.finished
    assert len(run_state.player.deck) == starting_deck - 1

    grafter = SpiritGrafter()
    healed_before = run_state.player.current_hp
    result = grafter.choose(run_state, "let_it_in")
    assert result.finished
    assert any(card.card_id == make_metamorphosis().card_id for card in run_state.player.deck)
    assert run_state.player.current_hp >= healed_before

    result = grafter.choose(run_state, "rejection")
    assert not result.finished
    hp_before = run_state.player.current_hp
    deck_before = len(run_state.player.deck)
    result = grafter.resolve_pending_choice(0)
    assert result.finished
    assert len(run_state.player.deck) == deck_before - 1
    assert run_state.player.current_hp == hp_before - 9

    spring = Wellspring()
    bottle = spring.choose(run_state, "bottle")
    rewards = bottle.rewards["reward_objects"]
    assert rewards and rewards[0].reward_type.name == "POTION"

    deck_before = len(run_state.player.deck)
    bathe = spring.choose(run_state, "bathe")
    assert not bathe.finished
    bathe = spring.resolve_pending_choice(0)
    assert bathe.finished
    assert len(run_state.player.deck) == deck_before
    assert any(card.card_id == make_guilty().card_id for card in run_state.player.deck)


def test_shared_events_apply_real_relic_potion_card_and_curse_effects():
    run_state = RunState(seed=62, character_id="Ironclad")
    run_state.initialize_run()
    run_state.player.deck = create_ironclad_starter_deck()
    start_relics = len(run_state.player.relics)

    beacon = DrowningBeacon()
    bottle = beacon.choose(run_state, "bottle")
    rewards = bottle.rewards["reward_objects"]
    assert rewards and rewards[0].reward_type.name == "POTION"
    climb = beacon.choose(run_state, "climb")
    assert climb.finished
    assert len(run_state.player.relics) == start_relics + 1

    forgotten = GraveOfTheForgotten()
    run_state.player.deck.append(make_backstab())
    result = forgotten.choose(run_state, "confront")
    assert not result.finished
    result = forgotten.resolve_pending_choice(0)
    assert result.finished
    assert any(card.card_id == make_decay().card_id for card in run_state.player.deck)
    accept = forgotten.choose(run_state, "accept")
    assert accept.finished

    mushrooms = HungryForMushrooms()
    before_relics = len(run_state.player.relics)
    mushrooms.choose(run_state, "big")
    mushrooms.choose(run_state, "fragrant")
    assert len(run_state.player.relics) >= before_relics + 2

    automaton = InfestedAutomaton()
    deck_before = len(run_state.player.deck)
    automaton.choose(run_state, "study")
    automaton.choose(run_state, "touch_core")
    assert len(run_state.player.deck) >= deck_before + 2

    wisp = LostWisp()
    before_relics = len(run_state.player.relics)
    wisp.choose(run_state, "claim")
    assert len(run_state.player.relics) == before_relics + 1
    assert any(card.card_id == make_decay().card_id for card in run_state.player.deck)

    statue = SunkenStatue()
    before_relics = len(run_state.player.relics)
    statue.choose(run_state, "grab_sword")
    assert len(run_state.player.relics) == before_relics + 1


def test_ancient_option_pool_events_obtain_real_relics():
    run_state = RunState(seed=63, character_id="Ironclad")
    run_state.initialize_run()
    run_state.player.deck = create_ironclad_starter_deck()

    nonu = Nonupeipe()
    options = nonu.generate_initial_options(run_state)
    before_relics = len(run_state.player.relics)
    result = nonu.choose(run_state, options[0].option_id)
    assert result.finished
    assert len(run_state.player.relics) == before_relics + 1

    tanx = Tanx()
    options = tanx.generate_initial_options(run_state)
    before_relics = len(run_state.player.relics)
    result = tanx.choose(run_state, options[0].option_id)
    assert result.finished
    assert len(run_state.player.relics) == before_relics + 1

    for event_cls in (Orobas, Pael, Tezcatara, Vakuu):
        event = event_cls()
        before_relics = len(run_state.player.relics)
        options = event.generate_initial_options(run_state)
        result = event.choose(run_state, options[0].option_id)
        assert result.finished
        assert len(run_state.player.relics) == before_relics + 1


def test_darv_uses_act_conditioned_boss_relic_pool():
    run_state = RunState(seed=64, character_id="Ironclad")
    run_state.initialize_run()
    darv = Darv()
    darv.rng = _DarvRng()

    run_state.current_act_index = 1
    options = darv.generate_initial_options(run_state)
    labels = {option.label for option in options}
    assert any("SOZU" in label or "Sozu" in label for label in labels)

    run_state.current_act_index = 2
    darv.rng = _DarvRng()
    options = darv.generate_initial_options(run_state)
    labels = {option.label for option in options}
    assert any("VELVET" in label or "Velvet" in label for label in labels)


def test_darv_preserves_csharp_boss_relic_set_order_before_shuffle():
    run_state = RunState(seed=641, character_id="Ironclad")
    run_state.initialize_run()
    run_state.current_act_index = 1
    rng = _DarvRng()
    darv = Darv()
    darv.rng = rng

    darv.generate_initial_options(run_state)

    assert rng.shuffle_inputs == [[
        RelicId.ASTROLABE.name,
        RelicId.BLACK_STAR.name,
        RelicId.CALLING_BELL.name,
        RelicId.EMPTY_CAGE.name,
        RelicId.PANDORAS_BOX.name,
        RelicId.RUNIC_PYRAMID.name,
        RelicId.SNECKO_EYE.name,
        RelicId.SOZU.name,
    ]]


def test_shared_reward_and_curse_events_apply_real_state_changes():
    run_state = RunState(seed=65, character_id="Ironclad")
    run_state.initialize_run()
    run_state.player.deck = create_ironclad_starter_deck()

    philosophers = ColorfulPhilosophers()
    result = philosophers.choose(run_state, philosophers.generate_initial_options(run_state)[0].option_id)
    rewards = result.rewards["reward_objects"]
    assert len(rewards) == 3
    assert all(reward.reward_type.name == "CARD" for reward in rewards)
    assert all(getattr(reward, "generation_context", "combat") is None for reward in rewards)
    assert all(getattr(reward, "roll_upgrade", False) is True for reward in rewards)

    flower = ColossalFlower()
    result = flower.choose(run_state, "reach_deeper")
    assert not result.finished
    result = flower.choose(run_state, "reach_deeper")
    assert not result.finished
    before_relics = len(run_state.player.relics)
    result = flower.choose(run_state, "pollinous_core")
    assert result.finished
    assert len(run_state.player.relics) == before_relics + 1

    treasury = SunkenTreasury()
    result = treasury.choose(run_state, "second_chest")
    assert result.finished
    assert any(card.card_id == make_greed().card_id for card in run_state.player.deck)

    this_or_that = ThisOrThat()
    before_relics = len(run_state.player.relics)
    result = this_or_that.choose(run_state, "ornate")
    assert result.finished
    assert len(run_state.player.relics) == before_relics + 1
    assert any(card.card_id == make_clumsy().card_id for card in run_state.player.deck)

    punch = PunchOff()
    nab = punch.choose(run_state, "nab")
    rewards = nab.rewards["reward_objects"]
    assert any(card.card_id == make_injury().card_id for card in run_state.player.deck)
    assert len(rewards) == 1 and rewards[0].reward_type.name == "RELIC"

    take_them = punch.choose(run_state, "take_them")
    assert not take_them.finished
    fight = punch.choose(run_state, "fight")
    rewards = fight.rewards["reward_objects"]
    assert [reward.reward_type.name for reward in rewards] == ["RELIC", "POTION"]

    lantern = TheLanternKey()
    keep = lantern.choose(run_state, "keep_key")
    assert not keep.finished
    fight = lantern.choose(run_state, "fight")
    rewards = fight.rewards["reward_objects"]
    assert len(rewards) == 1 and rewards[0].reward_type.name == "ADD_CARD"
    assert fight.event_combat_setup == "mysterious_knight"


def test_shared_event_combat_branches_expose_event_combat_setups():
    run_state = RunState(seed=67, character_id="Ironclad")
    run_state.initialize_run()
    run_state.player.deck = create_ironclad_starter_deck()

    dummy = BattlewornDummy()
    assert dummy.choose(run_state, "setting_1").event_combat_setup == "battleworn_dummy_v1"
    assert dummy.choose(run_state, "setting_2").event_combat_setup == "battleworn_dummy_v2"
    assert dummy.choose(run_state, "setting_3").event_combat_setup == "battleworn_dummy_v3"

    vegetation = DenseVegetation()
    rest = vegetation.choose(run_state, "rest")
    assert not rest.finished
    fight = vegetation.choose(run_state, "fight")
    assert fight.finished
    assert fight.event_combat_setup == "dense_vegetation"

    punch = PunchOff()
    punch.before_event_started(run_state)
    assert run_state.player.can_remove_potions is False
    take_them = punch.choose(run_state, "take_them")
    assert not take_them.finished
    fight = punch.choose(run_state, "fight")
    assert fight.finished
    assert fight.event_combat_setup == "punch_off"
    assert run_state.player.can_remove_potions is True


def test_run_manager_enters_combat_for_shared_event_combat_branches():
    mgr = RunManager(seed=68, character_id="Ironclad")
    mgr.run_state.player.deck = create_ironclad_starter_deck()
    mgr._phase = RunManager.PHASE_EVENT
    dummy = BattlewornDummy()
    mgr._event_model = dummy
    mgr._event_options = dummy.generate_initial_options(mgr.run_state)

    dummy_result = mgr._do_event_choice({"option_id": "setting_2"})
    assert dummy_result["phase"] == RunManager.PHASE_COMBAT
    assert mgr._current_room.encounter_id == "battleworn_dummy_v2"

    mgr = RunManager(seed=68, character_id="Ironclad")
    mgr.run_state.player.deck = create_ironclad_starter_deck()
    mgr._phase = RunManager.PHASE_EVENT
    event = DenseVegetation()
    mgr._event_model = event
    mgr._event_options = event.generate_initial_options(mgr.run_state)

    first = mgr._do_event_choice({"option_id": "rest"})
    assert first["phase"] == RunManager.PHASE_EVENT

    second = mgr._do_event_choice({"option_id": "fight"})
    assert second["phase"] == RunManager.PHASE_COMBAT
