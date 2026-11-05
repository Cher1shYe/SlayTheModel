"""Selection grids preserve decisions across Python bindings and snapshots."""
from agent.common import sim
from agent.heuristics import run_policy


def event_id(name):
    return next(i for i in range(sim.event_count()) if sim.event_info(i)[0] == name)


def test_cheese_requires_two_distinct_cards_and_restores_selection():
    run = sim.RunContext()
    run.init(123, 0)
    assert run.begin_event(event_id("ROOM_FULL_OF_CHEESE"))
    assert run.step(int(sim.RunActionType.EVENT_CHOICE), 0)
    assert len(run.card_grid_cards) == 8
    assert len({card[0] for card in run.card_grid_cards}) == 8
    before = run.observe_public()
    assert run.step(int(sim.RunActionType.SELECT_GRID_CARD), 0)
    assert run.observe_public() != before
    assert run.step(int(sim.RunActionType.SELECT_GRID_CARD), 0)
    assert not run.card_grid_selected[0]
    assert run.step(int(sim.RunActionType.SELECT_GRID_CARD), 0)
    assert not run.step(int(sim.RunActionType.CONFIRM_GRID_CARDS), 0)
    restored = sim.RunContext()
    assert restored.restore(run.snapshot())
    assert restored.card_grid_selected[0]
    assert restored.step(int(sim.RunActionType.SELECT_GRID_CARD), 1)
    assert restored.card_grid_kind == 0
    assert restored.deck_count == 12


def test_claws_can_confirm_with_no_transformations():
    run = sim.RunContext()
    run.init(123, 0)
    original_screen = run.screen
    original_deck = run.deck
    assert run.add_relic(int(sim.RelicId.CLAWS))
    assert run.card_grid_kind == 3
    assert run.step(int(sim.RunActionType.CONFIRM_GRID_CARDS), 0)
    assert run.card_grid_preview
    assert run.step(int(sim.RunActionType.CONFIRM_GRID_CARDS), 0)
    assert run.screen == original_screen
    assert run.deck == original_deck


def test_policy_makes_progress_on_required_two_card_grid():
    run = sim.RunContext()
    run.init(123, 0)
    assert run.begin_event(event_id("ROOM_FULL_OF_CHEESE"))
    assert run.step(int(sim.RunActionType.EVENT_CHOICE), 0)
    assert run.step(*run_policy(run))
    assert run.step(*run_policy(run))
    assert run.card_grid_kind == 0 and run.deck_count == 12


def test_paels_growth_selects_one_deck_card_without_exposing_grid_buffer():
    run = sim.RunContext()
    run.init(123, 0)
    assert run.deck_count > 8
    assert run.add_relic(int(sim.RelicId.PAELS_GROWTH))
    assert run.card_grid_kind == 4
    assert run.card_grid_cards == []
    assert len(run.card_grid_selected) == run.deck_count
    assert len(run.observe_public()) == int(sim.PUBLIC_OBS_DIM)
    action = run_policy(run)
    assert action[0] == int(sim.RunActionType.SELECT_GRID_CARD)
    assert run.step(*action)
    assert run.card_grid_kind == 0
    assert run.deck_enchantments[action[1]][:2] == (5, 4)


def test_scroll_boxes_choose_a_bundle_and_confirm():
    run = sim.RunContext()
    run.init(123, 0)
    old_count = run.deck_count
    assert run.add_relic(int(sim.RelicId.SCROLL_BOXES))
    assert run.gold == 0 and run.card_grid_kind == 5
    cards = run.card_grid_cards
    assert len(cards) == 6 and len({c[0] for c in cards}) == 6
    assert all(not card[1] for card in cards)
    assert run.step(*run_policy(run))
    assert run.card_grid_preview
    restored = sim.RunContext()
    assert restored.restore(run.snapshot()) and restored.card_grid_preview
    assert restored.step(int(sim.RunActionType.CANCEL_GRID_PREVIEW), 0)
    assert restored.step(int(sim.RunActionType.SELECT_GRID_CARD), 1)
    assert restored.step(*run_policy(restored))
    assert restored.card_grid_kind == 0 and restored.deck_count == old_count + 3
    assert [card[0] for card in restored.deck[-3:]] == [card[0] for card in cards[3:6]]
