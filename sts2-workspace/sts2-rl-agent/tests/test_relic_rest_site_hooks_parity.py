"""Regression tests for rest-site relic hook plumbing."""

from sts2_env.core.enums import RoomType
from sts2_env.run.run_manager import RunManager
from sts2_env.run.run_state import PlayerState, RunState
from sts2_env.run.rest_site import generate_rest_site_options


def test_regal_pillow_increases_rest_heal_amount():
    run_state = RunState(seed=201, character_id="Ironclad")
    assert run_state.player.obtain_relic("REGAL_PILLOW")
    run_state.player.max_hp = 100
    run_state.player.current_hp = 40

    heal = next(option for option in generate_rest_site_options(run_state.player) if option.option_id == "HEAL")
    heal.execute(run_state.player)

    assert run_state.player.current_hp == 85


def test_dream_catcher_surfaces_card_reward_after_rest():
    mgr = RunManager(seed=202, character_id="Ironclad")
    assert mgr.run_state.player.obtain_relic("DREAM_CATCHER")
    mgr.run_state.player.current_hp = 30
    mgr._enter_rest_site()

    result = mgr._do_rest_site({"option_id": "HEAL"})

    assert result["phase"] == RunManager.PHASE_CARD_REWARD
    assert any(action["action"] == "pick_card" for action in mgr.get_available_actions())


def test_tiny_mailbox_surfaces_potion_reward_after_rest():
    mgr = RunManager(seed=203, character_id="Ironclad")
    assert mgr.run_state.player.obtain_relic("TINY_MAILBOX")
    mgr._enter_rest_site()

    result = mgr._do_rest_site({"option_id": "HEAL"})

    assert result["phase"] == RunManager.PHASE_CARD_REWARD
    assert any(action["action"] == "pick_potion" for action in mgr.get_available_actions())


def test_stone_humidifier_grants_max_hp_after_rest_heal():
    run_state = RunState(seed=204, character_id="Ironclad")
    assert run_state.player.obtain_relic("STONE_HUMIDIFIER")
    run_state.player.max_hp = 80
    run_state.player.current_hp = 20

    heal = next(option for option in generate_rest_site_options(run_state.player) if option.option_id == "HEAL")
    heal.execute(run_state.player)

    assert run_state.player.max_hp == 85


def test_stone_humidifier_matches_original_after_rest_hook_when_already_full_hp():
    run_state = RunState(seed=214, character_id="Ironclad")
    assert run_state.player.obtain_relic("STONE_HUMIDIFIER")
    run_state.player.max_hp = 80
    run_state.player.current_hp = 80

    heal = next(option for option in generate_rest_site_options(run_state.player) if option.option_id == "HEAL")
    result = heal.execute(run_state.player)

    assert result == "Healed 0 HP"
    assert run_state.player.max_hp == 85
    assert run_state.player.current_hp == 85


def test_entering_shop_triggers_meal_ticket_heal():
    mgr = RunManager(seed=205, character_id="Ironclad")
    assert mgr.run_state.player.obtain_relic("MEAL_TICKET")
    mgr.run_state.player.current_hp = 40
    mgr.run_state.player.max_hp = 80

    mgr._enter_room(RoomType.SHOP)

    assert mgr.run_state.player.current_hp == 55


def test_miniature_tent_keeps_rest_site_open_for_second_option():
    mgr = RunManager(seed=206, character_id="Ironclad")
    assert mgr.run_state.player.obtain_relic("MINIATURE_TENT")
    mgr.run_state.player.current_hp = 20
    mgr._enter_rest_site()

    result = mgr._do_rest_site({"option_id": "HEAL"})

    assert result["phase"] == RunManager.PHASE_REST_SITE
    actions = mgr.get_available_actions()
    assert all(action["option_id"] != "HEAL" for action in actions)
    assert any(action["option_id"] == "SMITH" for action in actions)


def test_miniature_tent_returns_to_rest_site_after_dream_catcher_reward():
    mgr = RunManager(seed=207, character_id="Ironclad")
    assert mgr.run_state.player.obtain_relic("MINIATURE_TENT")
    assert mgr.run_state.player.obtain_relic("DREAM_CATCHER")
    mgr.run_state.player.current_hp = 20
    mgr._enter_rest_site()

    first = mgr._do_rest_site({"option_id": "HEAL"})
    assert first["phase"] == RunManager.PHASE_CARD_REWARD

    second = mgr.take_action({"action": "pick_card", "index": 0})
    assert second["phase"] == RunManager.PHASE_REST_SITE
    actions = mgr.get_available_actions()
    assert all(action["option_id"] != "HEAL" for action in actions)
    assert any(action["option_id"] == "SMITH" for action in actions)


def test_rest_site_relic_options_come_from_hooks_without_relic_id_list():
    run_state = RunState(seed=208, character_id="Ironclad")
    assert run_state.player.obtain_relic("SHOVEL")

    options = generate_rest_site_options(run_state.player)

    assert any(option.option_id == "DIG" for option in options)


def test_multiplayer_rest_site_includes_mend_option():
    run_state = RunState(seed=209, character_id="Ironclad")
    run_state.add_player(PlayerState(player_id=2, character_id="Silent"))

    options = generate_rest_site_options(run_state.player)

    assert any(option.option_id == "MEND" for option in options)


def test_mend_option_heals_selected_ally():
    mgr = RunManager(seed=210, character_id="Ironclad")
    ally = mgr.run_state.add_player(PlayerState(player_id=2, character_id="Silent", max_hp=60, current_hp=30))
    mgr._enter_rest_site()

    result = mgr._do_rest_site({"option_id": "MEND", "target_player_id": 2})

    assert result["description"] == "Mended 18 HP"
    assert ally.current_hp == 48


def test_mend_rest_action_exposes_target_player_id():
    mgr = RunManager(seed=212, character_id="Ironclad")
    mgr.run_state.add_player(PlayerState(player_id=2, character_id="Silent", max_hp=60, current_hp=30))
    mgr._enter_rest_site()

    actions = mgr.get_available_actions()

    assert any(
        action["option_id"] == "MEND" and action["target_player_id"] == 2
        for action in actions
    )


def test_mend_option_rejects_self_target():
    mgr = RunManager(seed=213, character_id="Ironclad")
    ally = mgr.run_state.add_player(PlayerState(player_id=2, character_id="Silent", max_hp=60, current_hp=30))
    mgr._enter_rest_site()

    result = mgr._do_rest_site({"option_id": "MEND", "target_player_id": 1})

    assert result["description"] == "No ally mended"
    assert ally.current_hp == 30


def test_mend_option_requires_target_player_id():
    mgr = RunManager(seed=214, character_id="Ironclad")
    ally = mgr.run_state.add_player(PlayerState(player_id=2, character_id="Silent", max_hp=60, current_hp=30))
    mgr._enter_rest_site()

    result = mgr._do_rest_site({"option_id": "MEND"})

    assert result["description"] == "No ally mended"
    assert ally.current_hp == 30


def test_mend_does_not_trigger_rest_heal_rewards():
    mgr = RunManager(seed=211, character_id="Ironclad")
    assert mgr.run_state.player.obtain_relic("DREAM_CATCHER")
    mgr.run_state.add_player(PlayerState(player_id=2, character_id="Silent", max_hp=60, current_hp=30))
    mgr._enter_rest_site()

    result = mgr._do_rest_site({"option_id": "MEND", "target_player_id": 2})

    assert result["phase"] == RunManager.PHASE_MAP_CHOICE
    assert mgr.run_state.pending_rewards == []
