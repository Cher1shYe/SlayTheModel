"""Step-2 rule regressions added 2026-11-04.

Evidence level: the target DLL for the differential fixtures
(9cb4f1ad...) is not present on this machine. These checks pin behaviour read
from the reference decompilation of the locally installed game build
(0861bfa1...); they are not target-DLL differential results.
"""
from __future__ import annotations

import pytest

from agent.common import sim

RACT = sim.RunActionType


def card_id(name: str) -> int:
    for i in range(1, sim.card_count()):
        if sim.card_name(i) == name:
            return i
    raise KeyError(name)


def event_id(name: str) -> int:
    for i in range(sim.event_count()):
        if sim.event_info(i)[0] == name:
            return i
    raise KeyError(name)


def battle(deck, encounter, ascension=0, hp=500, mask=31):
    bc = sim.BattleContext()
    bc.init(getattr(sim.Encounter, encounter), 1234, deck, [False] * len(deck),
            ascension, hp, hp)
    bc.unlocked_character_mask = mask
    return bc


def end_turn(bc):
    action = [a for a in bc.legal_actions()
              if a[0] == int(sim.ActionType.END_TURN)][0]
    assert bc.step(*action)


def test_potion_belt_keeps_physical_holes():
    """Native Player.PotionSlots is a List<PotionModel?> with null holes."""
    rc = sim.RunContext()
    rc.init_seed("potion holes", 0)
    rc.add_potion(sim.PotionId.BloodPotion)
    rc.add_potion(sim.PotionId.FirePotion)
    assert rc.potion_slot_ids == [int(sim.PotionId.BloodPotion),
                                  int(sim.PotionId.FirePotion), 0]

    use = [a for a in rc.legal_actions() if a[0] == int(RACT.USE_POTION)][0]
    assert rc.step(*use)
    # Using slot 0 leaves a hole; slot 1 does not shift down.
    assert rc.potion_slot_ids == [0, int(sim.PotionId.FirePotion), 0]
    assert rc.potions == [int(sim.PotionId.FirePotion)]

    rc.add_potion(sim.PotionId.EnergyPotion)
    assert rc.potion_slot_ids == [int(sim.PotionId.EnergyPotion),
                                  int(sim.PotionId.FirePotion), 0]

    restored = sim.RunContext()
    assert restored.restore(rc.snapshot())
    assert restored.potion_slot_ids == rc.potion_slot_ids
    assert restored.state_hash() == rc.state_hash()


def test_splash_offers_unlocked_non_owner_attack_pools():
    """Splash: CharacterCardPools minus the owner pool (only when >1 exist),
    combat-generatable Attacks, distinct 3, skippable, chosen card free."""
    splash = card_id("Splash")
    bc = battle([splash] * 10, "SETUP_CEREMONIAL_BEAST_BOSS")
    play = [a for a in bc.legal_actions() if a[0] == int(sim.ActionType.PLAY_CARD)][0]
    assert bc.step(*play)
    offers = bc.pending_cards
    assert len(offers) == 3
    assert all(sim.card_type_name(c[0]) == "ATTACK" for c in offers)
    assert all(sim.card_pool_name(c[0]) != "IRONCLAD" for c in offers)
    assert len({c[0] for c in offers}) == 3

    choose = [a for a in bc.legal_actions() if a[0] == int(sim.ActionType.CHOOSE)][0]
    assert bc.step(*choose)
    chosen = [c for c in bc.hand if c[0] != splash]
    assert len(chosen) == 1 and chosen[0][3] == 0  # SetToFreeThisTurn

    skip_bc = battle([splash] * 10, "SETUP_CEREMONIAL_BEAST_BOSS")
    play = [a for a in skip_bc.legal_actions()
            if a[0] == int(sim.ActionType.PLAY_CARD)][0]
    assert skip_bc.step(*play)
    skip = [a for a in skip_bc.legal_actions() if a[0] == int(sim.ActionType.CONFIRM)][0]
    hand_before = len(skip_bc.hand)
    assert skip_bc.step(*skip)
    assert len(skip_bc.hand) == hand_before


def test_splash_keeps_owner_pool_when_only_character_unlocked():
    splash = card_id("Splash")
    bc = battle([splash] * 10, "SETUP_CEREMONIAL_BEAST_BOSS", mask=1)
    play = [a for a in bc.legal_actions() if a[0] == int(sim.ActionType.PLAY_CARD)][0]
    assert bc.step(*play)
    assert len(bc.pending_cards) == 3
    assert all(sim.card_pool_name(c[0]) == "IRONCLAD" for c in bc.pending_cards)


def test_aeonglass_boss_cycle_and_withering_presence():
    """Aeonglass: 512 HP, Ebb(22 + 33 block) -> EyeLasers(11x2) ->
    IncreasingIntensity(add Wither, +3 Strength) -> Ebb."""
    defend = card_id("Defend")
    wither = card_id("Wither")

    bc = battle([defend] * 10, "SETUP_AEONGLASS_BOSS")
    assert bc.monsters[0][1:3] == (512, 512)
    assert bc.monsters[0][4:6] == (22, 1)
    assert (int(sim.PowerId.WITHERING_PRESENCE), 6) in bc.player_powers

    end_turn(bc)
    assert bc.player_hp == 478 and bc.monsters[0][3] == 33
    assert bc.monsters[0][4:6] == (11, 2)
    end_turn(bc)
    assert bc.player_hp == 456
    end_turn(bc)
    assert bc.monsters[0][10] == 3
    assert any(c[0] == wither for c in bc.discard_cards)
    assert all(c[3] == 1 for c in bc.discard_cards if c[0] == wither)

    assert battle([defend] * 10, "SETUP_AEONGLASS_BOSS", ascension=8).monsters[0][2] == 535
    assert battle([defend] * 10, "SETUP_AEONGLASS_BOSS", ascension=9).monsters[0][4] == 26


def test_aeonglass_state_survives_clone_and_hidden_resampling():
    """The new monster aux/Wither/presence state must be part of clone and
    snapshot identity, and invisible hidden resampling must not change the
    public observation."""
    defend = card_id("Defend")
    bc = battle([defend] * 10, "SETUP_AEONGLASS_BOSS")
    for _ in range(3):
        end_turn(bc)
    assert bc.monsters[0][10] == 3  # accumulated Strength from aux[0]
    obs = bc.observation_public()
    clone = bc.clone()
    assert clone.observation_public() == obs
    for seed in range(8):
        sampled = bc.clone()
        sampled.resample_hidden(seed)
        assert sampled.observation_public() == obs
    end_turn(bc)
    end_turn(clone)
    assert bc.observation_public() == clone.observation_public()
    assert bc.monsters[0] == clone.monsters[0]


def test_withering_presence_adds_wither_after_six_cards():
    defend = card_id("Defend")
    wither = card_id("Wither")
    bc = battle([defend] * 10, "SETUP_AEONGLASS_BOSS")
    played = 0
    for _ in range(2):
        while True:
            cards = [a for a in bc.legal_actions()
                     if a[0] == int(sim.ActionType.PLAY_CARD)]
            if not cards:
                break
            assert bc.step(*cards[0])
            played += 1
        if any(c[0] == wither for c in bc.hand):
            break
        end_turn(bc)
    assert played == 6
    assert any(c[0] == wither for c in bc.hand)
    assert (int(sim.PowerId.WITHERING_PRESENCE), 6) in bc.player_powers
    # Wither is unplayable (cost -1): it never becomes a legal play action.
    for idx, card in enumerate(bc.hand):
        if card[0] != wither:
            continue
        assert all(not (a[0] == int(sim.ActionType.PLAY_CARD) and a[1] == idx)
                   for a in bc.legal_actions())


def test_byrdonis_nest_take_and_eat():
    cid = event_id("BYRDONIS_NEST")
    assert sim.event_info(cid)[1] == int(sim.EventStatus.IMPLEMENTED)

    rc = sim.RunContext()
    rc.init_seed("byrdonis take", 0)
    assert rc.begin_event(cid)
    assert rc.event_name == "BYRDONIS_NEST"
    assert rc.event_choices == 2
    deck_before = rc.deck_count
    assert rc.step(int(RACT.EVENT_CHOICE), 1)  # TAKE
    assert rc.deck_count == deck_before + 1
    assert rc.deck[-1][0] == card_id("Byrdonis Egg")

    rc = sim.RunContext()
    rc.init_seed("byrdonis eat", 0)
    assert rc.begin_event(cid)
    max_hp = rc.max_hp
    assert rc.step(int(RACT.EVENT_CHOICE), 0)  # EAT
    assert rc.max_hp == max_hp + 7


def test_first_run_overgrowth_places_byrdonis_nest():
    progress = sim.NativeProgressContext()
    progress.apply_discovery_order = True
    progress.number_of_runs = 0
    rc = sim.RunContext()
    rc.init_with_context(17, 0, int(sim.ActType.OVERGROWTH), progress)
    assert rc.event_bag[0] == event_id("BYRDONIS_NEST")


def test_hive_encounter_bag_matches_native_declaration():
    """Hive.GenerateAllEncounters (20 entries) has no TunnelerNormal and puts
    InfestedPrismsElite after KaiserCrabBoss; the bag must use that list."""
    native = {
        "SETUP_BOWLBUGS_NORMAL", "SETUP_BOWLBUGS_WEAK", "SETUP_CHOMPERS_NORMAL",
        "SETUP_DECIMILLIPEDE_ELITE", "SETUP_ENTOMANCER_ELITE",
        "SETUP_EXOSKELETONS_NORMAL", "SETUP_EXOSKELETONS_WEAK",
        "SETUP_HUNTER_KILLER_NORMAL", "SETUP_KAISER_CRAB_BOSS",
        "SETUP_INFESTED_PRISMS_ELITE", "SETUP_KNOWLEDGE_DEMON_BOSS",
        "SETUP_LOUSE_PROGENITOR_NORMAL", "SETUP_MYTES_NORMAL",
        "SETUP_OVICOPTER_NORMAL", "SETUP_SLUMBERING_BEETLE_NORMAL",
        "SETUP_SPINY_TOAD_NORMAL", "SETUP_THE_INSATIABLE_BOSS",
        "SETUP_THE_OBSCURA_NORMAL", "SETUP_THIEVING_HOPPER_WEAK",
        "SETUP_TUNNELER_WEAK"}
    for seed in range(16):
        rc = sim.RunContext()
        rc.init_seed(f"hive {seed}", 0)
        rc.start_act(1)
        assert rc.act == 1
        normal = [sim.encounter_info(i)[0] for i in rc.normal_encounters]
        elite = [sim.encounter_info(i)[0] for i in rc.elite_encounters]
        assert set(normal) | set(elite) <= native
        assert "SETUP_TUNNELER_NORMAL" not in normal + elite
        assert all("WEAK" in name for name in normal[:2])
        assert all("ELITE" in name for name in elite)


def test_event_bags_follow_native_declaration_order():
    """ActModel.GenerateRooms concatenates AllEvents then AllSharedEvents in
    model declaration order before the up-front shuffle."""
    unsupported = int(sim.EventStatus.UNSUPPORTED)
    shared = ["BRAIN_LEECH", "CRYSTAL_SPHERE", "DOLL_ROOM", "FAKE_MERCHANT",
              "POTION_COURIER", "RANWID_THE_ELDER", "RELIC_TRADER",
              "ROOM_FULL_OF_CHEESE", "SELF_HELP_BOOK", "SLIPPERY_BRIDGE",
              "STONE_OF_ALL_TIME", "SYMBIOTE", "TEA_MASTER",
              "THE_FUTURE_OF_POTIONS", "THE_LEGENDS_WERE_TRUE",
              "THIS_OR_THAT", "WAR_HISTORIAN_REPY", "WELCOME_TO_WONGOS"]
    acts = {
        int(sim.ActType.OVERGROWTH): [
            "AROMA_OF_CHAOS", "BYRDONIS_NEST", "DENSE_VEGETATION",
            "JUNGLE_MAZE_ADVENTURE", "LUMINOUS_CHOIR", "MORPHIC_GROVE",
            "SAPPHIRE_SEED", "SUNKEN_STATUE", "TABLET_OF_TRUTH",
            "UNREST_SITE", "WELLSPRING", "WHISPERING_HOLLOW", "WOOD_CARVINGS"],
        int(sim.ActType.HIVE): [
            "AMALGAMATOR", "BUGSLAYER", "COLORFUL_PHILOSOPHERS",
            "COLOSSAL_FLOWER", "FIELD_OF_MAN_SIZED_HOLES",
            "INFESTED_AUTOMATON", "LOST_WISP", "SPIRIT_GRAFTER",
            "THE_LANTERN_KEY", "ZEN_WEAVER"],
        int(sim.ActType.GLORY): [
            "BATTLEWORN_DUMMY", "GRAVE_OF_THE_FORGOTTEN",
            "HUNGRY_FOR_MUSHROOMS", "REFLECTIONS", "ROUND_TEA_PARTY",
            "TRIAL", "TINKER_TIME"],
        int(sim.ActType.UNDERDOCKS): [
            "ABYSSAL_BATHS", "DROWNING_BEACON", "ENDLESS_CONVEYOR",
            "PUNCH_OFF", "SPIRALING_WHIRLPOOL", "SUNKEN_STATUE",
            "SUNKEN_TREASURY", "DOORS_OF_LIGHT_AND_DARK", "TRASH_HEAP",
            "WATERLOGGED_SCRIPTORIUM"],
    }
    for act, names in acts.items():
        expected = []
        for name in names + shared:
            eid = event_id(name)
            if sim.event_info(eid)[1] != unsupported:
                expected.append(eid)
        assert sim.event_pool_type(act) == expected, act
    # The three target-build events previously absent from the manifest are
    # registered so ordering/inventory reflects the whole act list.
    # WhisperingHollow, ZenWeaver, WoodCarvings and SelfHelpBook are now
    # implemented (C++ rules checks cover them).
    for name in ("WHISPERING_HOLLOW", "ZEN_WEAVER", "WOOD_CARVINGS", "SELF_HELP_BOOK"):
        assert sim.event_info(event_id(name))[1] == int(sim.EventStatus.IMPLEMENTED)


def test_glory_discovery_order_includes_aeonglass():
    progress = sim.NativeProgressContext()
    progress.apply_discovery_order = True
    progress.number_of_runs = 1
    progress.seen_encounters = []
    progress.seen_encounters = [int(sim.Encounter.SETUP_QUEEN_BOSS),
                                int(sim.Encounter.SETUP_TEST_SUBJECT_BOSS)]
    rc = sim.RunContext()
    rc.init_with_context(17, 0, int(sim.ActType.OVERGROWTH), progress)
    rc.start_act(2)
    assert rc.boss_encounter == int(sim.Encounter.SETUP_AEONGLASS_BOSS)
