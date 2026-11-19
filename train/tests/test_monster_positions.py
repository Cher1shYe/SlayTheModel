"""Public position adapter regressions, derived from native Encounter.Slots.

monster_positions is aligned with the simulator's reusable target-index array;
enemy_order_index is the current native Enemies list rank, not an entity UUID.
Removed rows have no rank. Reviving rows retain a rank but adapters may reject
that transitional state. No-slot encounters, including ToadpolesWeak, have None
slot names and use list order to distinguish identical monster copies.
"""
import pytest

from spire_rl.sim import sim


def _battle(encounter, card_name="Defend"):
    card = next(i for i in range(1, sim.CARD_COUNT)
                if sim.card_native_available(i) and sim.card_name(i) == card_name)
    battle = sim.BattleContext()
    battle.init(int(getattr(sim.Encounter, encounter)), 111, [card] * 10, [False] * 10,
                10, 999, 999)
    return battle


def test_identical_toadpoles_keep_order_and_removed_rows_do_not_shift_targets():
    battle = _battle("SETUP_TOADPOLES_WEAK", "Bludgeon")
    assert sim.MONSTER_POSITION_VERSION == 1
    positions = battle.monster_positions
    assert [p["index"] for p in positions] == [0, 1]
    assert [p["slot_name"] for p in positions] == [None, None]
    assert [p["enemy_order_index"] for p in positions] == [0, 1]
    assert battle.monster_turn_order == [0, 1]
    assert all(p["alive"] and not p["reviving"] for p in positions)
    action = next(a for a in battle.legal_actions()
                  if a[0] == int(sim.ActionType.PLAY_CARD) and a[2] == 0)
    assert battle.step(*action)
    positions = battle.monster_positions
    assert positions[0]["enemy_order_index"] is None and not positions[0]["alive"]
    assert positions[1]["index"] == 1 and positions[1]["enemy_order_index"] == 0
    assert battle.monster_turn_order == [1]


def test_summoned_front_slot_reorders_native_list_without_changing_target_index():
    battle = _battle("SETUP_FOGMOG_NORMAL")
    assert battle.monster_positions[0]["slot_name"] == "fogmog"
    action = next(a for a in battle.legal_actions() if a[0] == int(sim.ActionType.END_TURN))
    assert battle.step(*action)
    positions = battle.monster_positions
    assert [(p["index"], p["slot_name"], p["enemy_order_index"]) for p in positions] == [
        (0, "fogmog", 1), (1, "illusion", 0)]
    assert battle.monster_turn_order == [1, 0]
    clone = battle.clone()
    clone.resample_hidden(54321)
    assert clone.monster_positions == positions
    assert clone.monster_turn_order == [1, 0]


def test_decimillipede_concrete_ids_survive_knockout_reattach_and_clone():
    battle = _battle("SETUP_DECIMILLIPEDE_ELITE", "Bludgeon")
    expected = ["MONSTER.DECIMILLIPEDE_SEGMENT_" + suffix
                for suffix in ("FRONT", "MIDDLE", "BACK")]
    assert [p["native_model_id"] for p in battle.monster_positions] == expected
    for _ in range(12):
        actions = battle.legal_actions()
        attack = next((a for a in actions
                       if a[0] == int(sim.ActionType.PLAY_CARD) and a[2] == 0), None)
        action = attack or next(a for a in actions if a[0] == int(sim.ActionType.END_TURN))
        assert battle.step(*action)
        assert [p["native_model_id"] for p in battle.monster_positions] == expected
        if battle.monster_positions[0]["reviving"]:
            break
    assert battle.monster_positions[0]["reviving"]
    clone = battle.clone()
    clone.resample_hidden(54321)
    assert clone.monster_positions == battle.monster_positions
    for _ in range(3):
        end = next(a for a in battle.legal_actions() if a[0] == int(sim.ActionType.END_TURN))
        assert battle.step(*end)
        assert [p["native_model_id"] for p in battle.monster_positions] == expected
        if not battle.monster_positions[0]["reviving"]:
            break
    assert not battle.monster_positions[0]["reviving"]
    assert battle.monsters[0][1] > 0


# All 19 native slot overrides. The current roster may leave summon slots empty.
@pytest.mark.parametrize("encounter,slots", [
    ("SETUP_AXEBOTS_NORMAL", ["front"]),
    ("SETUP_DECIMILLIPEDE_ELITE", ["segment1", "segment2", "segment3"]),
    ("SETUP_DENSE_VEGETATION", ["wriggler1", "wriggler2", "wriggler3", "wriggler4"]),
    ("SETUP_EXOSKELETONS_NORMAL", ["first", "second", "third", "fourth"]),
    ("SETUP_EXOSKELETONS_WEAK", ["first", "second", "third"]),
    ("SETUP_FABRICATOR_NORMAL", ["bot1", "bot2", "fabricator", "bot3", "bot4"]),
    ("SETUP_FAKE_MERCHANT", ["merchant"]),
    ("SETUP_FOGMOG_NORMAL", ["illusion", "fogmog"]),
    ("SETUP_KAISER_CRAB_BOSS", ["crusher", "rocket"]),
    ("SETUP_LIVING_FOG_NORMAL", ["bomb1", "bomb2", "bomb3", "bomb4", "bomb5", "livingFog"]),
    ("SETUP_MYTES_NORMAL", ["first", "second"]),
    ("SETUP_NIBBITS_NORMAL", ["front", "back"]),
    ("SETUP_OVICOPTER_NORMAL", ["egg1", "egg2", "egg3", "egg4", "egg5", "ovicopter"]),
    ("SETUP_PHANTASMAL_GARDENERS_ELITE", ["first", "second", "third", "fourth"]),
    ("SETUP_PHROG_PARASITE_ELITE", ["phrog", "wriggler1", "wriggler2", "wriggler3", "wriggler4"]),
    ("SETUP_QUEEN_BOSS", ["amalgam", "queen"]),
    ("SETUP_THE_KIN_BOSS", ["slot1", "slot2", "leaderSlot"]),
    ("SETUP_THE_OBSCURA_NORMAL", ["illusion", "obscura"]),
    ("SETUP_TWO_TAILED_RATS_NORMAL", ["first", "second", "third", "fourth", "fifth"]),
])
def test_named_encounter_positions_follow_native_slot_order(encounter, slots):
    battle = _battle(encounter)
    positions = battle.monster_positions
    assert positions and len(positions) == len(battle.monsters)
    names = [positions[i]["slot_name"] for i in battle.monster_turn_order]
    assert all(name in slots for name in names)
    assert [slots.index(name) for name in names] == sorted(slots.index(name) for name in names)
    assert [positions[i]["enemy_order_index"] for i in battle.monster_turn_order] == list(range(len(names)))
