"""Parity tests for Act 2 DollRoom behavior."""

import sts2_env.events.act2  # noqa: F401

from sts2_env.cards.ironclad import create_ironclad_starter_deck
from sts2_env.events.act2 import DollRoom
from sts2_env.run.run_state import RunState


def _make_run_state(seed: int) -> RunState:
    run_state = RunState(seed=seed, character_id="Ironclad")
    run_state.initialize_run()
    run_state.player.deck = create_ironclad_starter_deck()
    return run_state


def _doll_ids() -> set[str]:
    return {relic_id for relic_id, _ in DollRoom._DOLLS}  # noqa: SLF001


class _NoopShuffleFirstChoiceRng:
    def __init__(self) -> None:
        self.choice_calls = 0
        self.shuffle_calls = 0
        self.shuffle_inputs = []

    def choice(self, seq):
        self.choice_calls += 1
        return seq[0]

    def shuffle(self, seq) -> None:
        self.shuffle_calls += 1
        self.shuffle_inputs.append(list(seq))
        pass


class _LastChoiceNicheRng:
    def choice(self, seq):
        return seq[-1]


def test_doll_room_is_act2_only_and_initial_options_reset_followup_choices():
    run_state = _make_run_state(1001)
    event = DollRoom()

    assert event.is_allowed(run_state) is False
    run_state.current_act_index = 1
    assert event.is_allowed(run_state) is True

    event._doll_choices = {"stale": "MR_STRUGGLES"}  # noqa: SLF001
    options = event.generate_initial_options(run_state)

    assert event._doll_choices == {}  # noqa: SLF001
    assert [option.option_id for option in options] == ["random", "take_time", "examine"]


def test_doll_room_random_finishes_and_grants_one_doll_relic():
    run_state = _make_run_state(1002)
    run_state.current_act_index = 1
    event = DollRoom()
    event.rng = _NoopShuffleFirstChoiceRng()
    relics_before = set(run_state.player.relics)

    result = event.choose(run_state, "random")

    assert result.finished
    gained = set(run_state.player.relics) - relics_before
    assert len(gained) == 1
    assert next(iter(gained)) in _doll_ids()


def test_doll_room_random_uses_niche_rng_instead_of_event_rng():
    run_state = _make_run_state(10021)
    run_state.current_act_index = 1
    run_state.rng.niche = _LastChoiceNicheRng()
    event = DollRoom()
    event.rng = _NoopShuffleFirstChoiceRng()

    result = event.choose(run_state, "random")

    assert result.finished
    assert "BING_BONG" in run_state.player.relics
    assert event.rng.choice_calls == 0
    assert event.rng.shuffle_calls == 0


def test_doll_room_take_some_time_damages_and_selected_option_grants_that_relic():
    run_state = _make_run_state(1003)
    run_state.current_act_index = 1
    event = DollRoom()
    event.rng = _NoopShuffleFirstChoiceRng()
    hp_before = run_state.player.current_hp
    relics_before = set(run_state.player.relics)

    first = event.choose(run_state, "take_time")

    assert not first.finished
    assert run_state.player.current_hp == hp_before - DollRoom.TAKE_TIME_HP_LOSS
    assert len(first.next_options) == DollRoom.TAKE_TIME_DOLL_COUNT
    assert set(event._doll_choices) == {"doll_1", "doll_2"}  # noqa: SLF001
    assert {option.option_id for option in first.next_options} == set(event._doll_choices)  # noqa: SLF001
    assert set(event._doll_choices.values()).issubset(_doll_ids())  # noqa: SLF001

    chosen_option = first.next_options[0].option_id
    expected_relic = event._doll_choices[chosen_option]  # noqa: SLF001
    second = event.choose(run_state, chosen_option)

    assert second.finished
    assert expected_relic in run_state.player.relics
    assert len(set(run_state.player.relics) - relics_before) == 1


def test_doll_room_examine_damages_and_selected_option_grants_that_relic():
    run_state = _make_run_state(1004)
    run_state.current_act_index = 1
    event = DollRoom()
    event.rng = _NoopShuffleFirstChoiceRng()
    hp_before = run_state.player.current_hp
    relics_before = set(run_state.player.relics)

    first = event.choose(run_state, "examine")

    assert not first.finished
    assert run_state.player.current_hp == hp_before - DollRoom.EXAMINE_HP_LOSS
    assert len(first.next_options) == DollRoom.EXAMINE_DOLL_COUNT
    assert set(event._doll_choices) == {"doll_1", "doll_2", "doll_3"}  # noqa: SLF001
    assert {option.option_id for option in first.next_options} == set(event._doll_choices)  # noqa: SLF001
    assert set(event._doll_choices.values()) == _doll_ids()  # noqa: SLF001

    chosen_option = first.next_options[-1].option_id
    expected_relic = event._doll_choices[chosen_option]  # noqa: SLF001
    second = event.choose(run_state, chosen_option)

    assert second.finished
    assert expected_relic in run_state.player.relics
    assert len(set(run_state.player.relics) - relics_before) == 1


def test_doll_room_invalid_followup_option_finishes_without_granting_relic():
    run_state = _make_run_state(1005)
    run_state.current_act_index = 1
    event = DollRoom()
    relics_before = set(run_state.player.relics)

    first = event.choose(run_state, "take_time")
    assert not first.finished

    second = event.choose(run_state, "not_a_real_doll")

    assert second.finished
    assert set(run_state.player.relics) == relics_before


def test_doll_room_uses_expected_rng_streams_without_advancing_up_front_rng():
    run_state = _make_run_state(1006)
    run_state.current_act_index = 1
    event = DollRoom()
    event.rng = _NoopShuffleFirstChoiceRng()
    up_front_counter = run_state.rng.up_front.counter

    random_result = event.choose(run_state, "random")
    take_time_result = event.choose(run_state, "take_time")
    examine_result = event.choose(run_state, "examine")

    assert random_result.finished
    assert take_time_result.finished is False
    assert examine_result.finished is False
    assert event.rng.choice_calls == 0
    assert event.rng.shuffle_calls == 2
    assert run_state.rng.up_front.counter == up_front_counter


def test_doll_room_sorts_dolls_before_choice_shuffle_like_stable_shuffle():
    run_state = _make_run_state(1007)
    run_state.current_act_index = 1
    event = DollRoom()
    event.rng = _NoopShuffleFirstChoiceRng()

    take_time_result = event.choose(run_state, "take_time")
    examine_result = event.choose(run_state, "examine")

    assert take_time_result.finished is False
    assert examine_result.finished is False
    assert event.rng.shuffle_inputs == [sorted(DollRoom._DOLLS), sorted(DollRoom._DOLLS)]  # noqa: SLF001
