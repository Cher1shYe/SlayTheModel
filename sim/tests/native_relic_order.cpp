// v29 (DEVLOG 54): player-turn start runs relics in the native hook stages, in relic-bar order.
// CombatManager.StartTurn: BeforeSideTurnStart -> enemy rolls -> block clear -> AfterBlockCleared
// -> SetupPlayerTurn (energy reset, AfterEnergyReset, BeforeHandDraw, draw, AfterPlayerTurnStart,
// ...Late) -> AfterSideTurnStart -> OrbQueue.AfterTurnStart. Listeners: the player's powers, then
// relics (bar order), then enemy powers. Expectations come from the v0.111.0 decompilation.
// Each case is chosen so the old placement gives a different result.
#include "sts2/run.h"
#include "sts2/relics.h"
#include "sts2/card_candidates.h"
#include <cassert>
#include <iostream>
#include <memory>
#include <string>

using namespace sts2;

namespace {
int failures = 0;
void check(const char *name, bool ok) {
    if (!ok) { ++failures; std::cout << "FAIL " << name << "\n"; }
}
std::unique_ptr<RunContext> fight(std::initializer_list<RelicId> relics, Encounter e = Encounter::SETUP_SLIMES_WEAK,
                                  const std::string &seed = "V29ORDER") {
    auto r = std::make_unique<RunContext>();
    r->init_seed(seed, 10);
    r->screen = RunScreen::MAP;
    for (RelicId id : relics) assert(r->add_relic(id));
    r->begin_combat(e);
    return r;
}
int count_in(const Card *pile, int n, CardId id) {
    int k = 0;
    for (int i = 0; i < n; ++i) k += pile[i].id == id;
    return k;
}

// Blood Vial is AfterPlayerTurnStartLate: after the player's AfterPlayerTurnStart powers.
// At full HP with Inferno (3 self-damage): native max - 3 + 2. Before v29 the heal came first
// (capped at max), so the result was max - 3.
void blood_vial_after_inferno() {
    auto r = fight({RelicId::BLOOD_VIAL});
    BattleContext &b = r->battle;
    b.turn = 0;                                   // replay the turn-1 setup with Inferno active
    b.player.hp = b.player.maxHp;
    b.add_player_power(PowerId::INFERNO, 1);
    b.player.infernoSelfDamage = 3;
    b.start_player_turn();
    check("Blood Vial heals after Inferno's self-damage", b.player.hp == b.player.maxHp - 1);
}

// Lantern is AfterSideTurnStart: not yet in the energy while the turn-1 Gambling Chip choice
// (AfterPlayerTurnStart) is open; the observation must show 3, then 4 after the choice.
void lantern_after_gambling_chip_choice() {
    auto r = fight({RelicId::GAMBLING_CHIP, RelicId::LANTERN});
    BattleContext &b = r->battle;
    check("Gambling Chip choice is open on turn 1", b.pending.op == ChoiceOp::GAMBLING_CHIP);
    check("energy during the choice excludes Lantern", b.player.energy == 3);
    check("confirming the choice", b.step(Action{ActionType::CONFIRM, 0, 0, 0}));
    check("Lantern energy after AfterSideTurnStart", b.player.energy == 4 && b.pending.op == ChoiceOp::NONE);
}

// Bone Tea (AfterPlayerTurnStart) upgrades the hand before Crossbow (AfterSideTurnStart) adds
// its attack. Before v29 Bone Tea ran after AfterSideTurnStart and upgraded the Crossbow card too.
void bone_tea_before_crossbow() {
    auto r = fight({RelicId::BONE_TEA, RelicId::CROSSBOW});
    BattleContext &b = r->battle;
    int drawnUpgraded = 0, upgradable = 0;
    for (int i = 0; i + 1 < b.handCount; ++i) {
        drawnUpgraded += b.hand[i].upgraded;
        upgradable += b.hand[i].upgraded || card_upgradable(b.hand[i]);
    }
    const Card &crossbow = b.hand[b.handCount - 1];   // added last
    check("Bone Tea upgraded the drawn hand", drawnUpgraded == upgradable && upgradable > 0);
    check("Crossbow's card arrives after Bone Tea (not upgraded)",
          card_type(crossbow) == CardType::ATTACK && !crossbow.upgraded);
}

// Twisted Funnel applies Poison through PowerCmd (Artifact blocks it) to hittable enemies;
// Bag of Marbles skips reviving enemies. Before v29: Poison written directly, alive enemies.
void turn_one_debuffs_respect_artifact_and_hittable() {
    auto r = fight({RelicId::TWISTED_FUNNEL, RelicId::BAG_OF_MARBLES}, Encounter::SETUP_SLIMES_WEAK);
    BattleContext &b = r->battle;
    check("turn-1 funnel poison applied", b.monsterCount >= 2 && b.monsters[0].power[static_cast<int>(PowerId::POISON)] == 4);
    for (int m = 0; m < b.monsterCount; ++m) {
        b.monsters[m].power[static_cast<int>(PowerId::POISON)] = 0;
        b.monsters[m].power[static_cast<int>(PowerId::VULNERABLE)] = 0;
    }
    b.monsters[0].power[static_cast<int>(PowerId::ARTIFACT)] = 1;
    b.monsters[1].reviving = true;
    b.turn = 1;
    relics_before_side_turn_start(b);
    check("Artifact blocks Twisted Funnel's poison", b.monsters[0].power[static_cast<int>(PowerId::POISON)] == 0 &&
                                                       b.monsters[0].power[static_cast<int>(PowerId::ARTIFACT)] == 0);
    check("reviving enemies are not hittable", b.monsters[1].power[static_cast<int>(PowerId::VULNERABLE)] == 0 &&
                                               b.monsters[1].power[static_cast<int>(PowerId::POISON)] == 0);
    b.turn = 2;
    b.monsters[0].power[static_cast<int>(PowerId::VULNERABLE)] = 0;
    relics_before_side_turn_start(b);
    check("only turn 1", b.monsters[0].power[static_cast<int>(PowerId::VULNERABLE)] == 0);
}

// Horn Cleat (AfterBlockCleared, turn 2), Blessed Antler (BeforeHandDraw, turn 1, 3 generated
// Dazed), Festive Popper (AfterPlayerTurnStart, turn 1, 9 Unpowered to hittable enemies).
void stage_regressions() {
    auto h = fight({RelicId::HORN_CLEAT});
    BattleContext &b = h->battle;
    b.player.hp = 999; b.player.maxHp = 999;      // survive the enemy turn
    check("end turn 1", b.step(Action{ActionType::END_TURN, 0, 0, 0}));
    check("Horn Cleat block on turn 2", b.turn == 2 && b.player.block == 14);

    auto a = fight({RelicId::BLESSED_ANTLER});
    BattleContext &c = a->battle;
    check("Blessed Antler adds 3 Dazed before the draw",
          count_in(c.draw, c.drawCount, CardId::DAZED) + count_in(c.hand, c.handCount, CardId::DAZED) == 3);

    auto none = fight({});
    auto pop = fight({RelicId::FESTIVE_POPPER});
    int lost = 0;
    for (int m = 0; m < pop->battle.monsterCount; ++m) lost += none->battle.monsters[m].hp - pop->battle.monsters[m].hp;
    check("Festive Popper deals 9 to each hittable enemy once", lost == 9 * pop->battle.monsterCount);
}

// AfterCardPlayed in relic-bar order: Iron Club's draw before Mummified Hand's random pick makes
// the drawn card eligible; the other bar order leaves it costed. The hand holds only 0-cost cards.
void iron_club_and_mummified_hand_follow_bar_order() {
    for (bool clubFirst : {true, false}) {
        auto r = clubFirst ? fight({RelicId::IRON_CLUB, RelicId::MUMMIFIED_HAND})
                           : fight({RelicId::MUMMIFIED_HAND, RelicId::IRON_CLUB});
        BattleContext &b = r->battle;
        b.handCount = 0;
        for (int k = 0; k < 3; ++k) b.hand[b.handCount++] = make_card(CardId::ANGER, false, b.require_card_uid());
        const Card bash = make_card(CardId::BASH, false, b.require_card_uid());
        b.draw[b.drawCount++] = bash;                                // top of the draw pile
        for (int i = 0; i < b.relicCount; ++i)                       // slot 0 is the starter relic
            if (b.relics[i] == static_cast<int>(RelicId::IRON_CLUB)) b.relicAux[i] = 3;   // next card is the 4th
        relics_card_played(b, make_card(CardId::INFLAME, false, b.require_card_uid()));
        const Card *drawn = b.find_in_hand(bash.uid);
        check("Iron Club drew the top card", drawn != nullptr);
        if (drawn) check(clubFirst ? "club first: the drawn Bash is made free" : "hand first: the drawn Bash keeps its cost",
                         (b.energy_cost_in_combat(*drawn) == 0) == clubFirst);
    }
}

// The player's AfterCardPlayed powers run before relics: Panache's damage kills the 1-HP enemy, so
// Kusarigama's random target can only be the other one (before v29 relics went first).
void powers_before_relics_on_card_played() {
    auto r = fight({RelicId::KUSARIGAMA}, Encounter::SETUP_SLIMES_WEAK);
    BattleContext &b = r->battle;
    if (b.monsterCount < 2) { check("two enemies", false); return; }
    for (int m = 2; m < b.monsterCount; ++m) b.monsters[m].alive = false;
    b.monsters[0].hp = 1; b.monsters[0].block = 0;
    b.monsters[1].hp = 100; b.monsters[1].maxHp = 100; b.monsters[1].block = 0;
    b.panacheCount = 1; b.panachePrimed[0] = true; b.panacheLeft[0] = 1; b.panacheDamage[0] = 3;
    b.attacksPlayedThisTurn = 3;                                     // Kusarigama's third attack
    b.after_card_played(make_card(CardId::STRIKE_IRONCLAD, false, b.require_card_uid()));
    check("Panache killed the 1-HP enemy first", !b.monsters[0].alive || b.monsters[0].hp <= 0);
    check("Kusarigama then hit the survivor (3 + 6)", b.monsters[1].hp == 100 - 3 - 6);
}

// AfterCardExhausted in relic-bar order: Charon's Ashes (all enemies, 3) left of Forgotten Soul
// kills the 3-HP enemy first, so the random 1 damage can only land on the survivor.
void exhaust_relics_follow_bar_order() {
    auto r = fight({RelicId::CHARONS_ASHES, RelicId::FORGOTTEN_SOUL}, Encounter::SETUP_SLIMES_WEAK);
    BattleContext &b = r->battle;
    if (b.monsterCount < 2) { check("two enemies", false); return; }
    for (int m = 2; m < b.monsterCount; ++m) b.monsters[m].alive = false;
    b.monsters[0].hp = 3; b.monsters[0].block = 0;
    b.monsters[1].hp = 100; b.monsters[1].maxHp = 100; b.monsters[1].block = 0;
    relics_exhausted(b, make_card(CardId::DEFEND_IRONCLAD, false, b.require_card_uid()), false);
    check("Charon's Ashes killed the 3-HP enemy", !b.monsters[0].alive || b.monsters[0].hp <= 0);
    check("Forgotten Soul then hit the survivor", b.monsters[1].hp == 100 - 3 - 1);
}

// Lord's Parasol awaits each relic's Obtain (v29). Astrolabe's transform choice comes before Potion
// Belt and the potions: with 2 potions in 3 slots all three shop potions fit once the belt is
// owned. Before v29 the potions were bought at once (1 fit) and the belt was obtained afterwards.
std::unique_ptr<RunContext> parasol_shop(std::initializer_list<RelicId> stock) {
    auto r = std::make_unique<RunContext>();
    r->init_seed("V29PARASOL", 10);
    r->screen = RunScreen::SHOP;
    assert(r->add_relic(RelicId::LORDS_PARASOL));
    r->shopCount = 0;                                   // cards are not under test
    r->shopRelicCount = 0;
    for (RelicId id : stock) { r->shopRelics[r->shopRelicCount] = static_cast<int>(id); r->shopRelicSold[r->shopRelicCount++] = false; }
    r->shopPotionCount = 3;
    for (int i = 0; i < 3; ++i) { r->shopPotions[i] = static_cast<int>(PotionId::FIRE_POTION); r->shopPotionSold[i] = false; }
    return r;
}
void lords_parasol_awaits_relic_choices() {
    auto r = parasol_shop({RelicId::ASTROLABE, RelicId::POTION_BELT});
    r->potionSlots = 3;
    r->add_potion(PotionId::BLOCK_POTION); r->add_potion(PotionId::BLOCK_POTION);
    r->lords_parasol_purchase_everything();
    check("Astrolabe's choice suspends the purchases", r->cardGrid.kind != 0 && !r->shopRelicSold[1] &&
                                                       r->potionCount == 2 && r->potionSlots == 3);
    for (int guard = 0; guard < 8 && r->cardGrid.kind && r->cardGrid.service != 5; ++guard) {
        for (int i = 0; i < r->deckCount && r->cardGrid.selectedCount < std::max(1, int(r->cardGrid.minSelect)); ++i)
            select_card_grid(*r, i);
        confirm_card_grid(*r);
    }
    check("Potion Belt is owned before the potions are bought", r->shopRelicSold[1] && r->potionSlots == 5);
    check("all three shop potions fit", r->potionCount == 5 && r->shopPotionSold[0] && r->shopPotionSold[2]);
    check("then the free removal opens", r->cardGrid.kind == 6 && r->cardGrid.service == 5);
}
void lords_parasol_courier_checked_per_purchase() {
    auto r = parasol_shop({RelicId::THE_COURIER, RelicId::VAJRA, RelicId::ANCHOR});
    r->lords_parasol_purchase_everything();
    check("The Courier bought first", r->shopRelicSold[0] == false || run_has_relic(*r, RelicId::THE_COURIER));
    check("relics bought after The Courier restock their slot",
          run_has_relic(*r, RelicId::VAJRA) && run_has_relic(*r, RelicId::ANCHOR) &&
          !r->shopRelicSold[1] && !r->shopRelicSold[2] &&
          r->shopRelics[1] != static_cast<int>(RelicId::VAJRA) && r->shopRelics[2] != static_cast<int>(RelicId::ANCHOR));
}

// v30 (DEVLOG 55). Tea of Discourtesy: AddToCombatAndPreview<Dazed>(Draw, 2, Random). Before v30
// both went on top of the draw pile, so both were always in the opening hand.
void tea_of_discourtesy_random_positions() {
    int bothInHand = 0, total = 0;
    for (int k = 0; k < 12; ++k) {
        auto r = std::make_unique<RunContext>();
        r->init_seed("V30TEA" + std::to_string(k), 10);
        r->screen = RunScreen::MAP;
        assert(r->add_relic(RelicId::TEA_OF_DISCOURTESY));
        r->begin_combat(Encounter::SETUP_SLIMES_WEAK);
        const BattleContext &b = r->battle;
        const int inHand = count_in(b.hand, b.handCount, CardId::DAZED);
        total += inHand + count_in(b.draw, b.drawCount, CardId::DAZED) + count_in(b.discard, b.discardCount, CardId::DAZED);
        bothInHand += inHand == 2;
    }
    check("Tea of Discourtesy adds 2 Dazed per run", total == 24);
    check("its Dazed are shuffled in, not always drawn first", bothInHand < 12);
}

// Fur Coat compares only the map coordinate (native FurCoat.BeforeCombatStart has no act check):
// a later act's fight on a coordinate marked in an earlier act also starts at 1 HP.
void fur_coat_coordinate_only() {
    auto r = std::make_unique<RunContext>();
    r->init_seed("V30FUR", 10);
    r->screen = RunScreen::MAP;
    assert(r->add_relic(RelicId::FUR_COAT));
    r->furCoatAct = 0;                       // marked in act 1 ...
    r->furCoatCount = 1; r->furCoatRow[0] = 5; r->furCoatCol[0] = 2;
    r->act = 2;                              // ... a fight in act 3 on the same (row, col)
    r->curRow = 5; r->curCol = 2;
    r->begin_combat(Encounter::SETUP_SLIMES_WEAK);
    bool allOne = r->battle.monsterCount > 0;
    for (int m = 0; m < r->battle.monsterCount; ++m) allOne = allOne && (!r->battle.monsters[m].alive || r->battle.monsters[m].hp == 1);
    check("Fur Coat's coordinate also applies in a later act (native)", allOne);
    r->curRow = 6;
    r->begin_combat(Encounter::SETUP_SLIMES_WEAK);
    check("other coordinates are unaffected", r->battle.monsters[0].hp > 1);
}

// v30 (DEVLOG 56): these relics add cards through AddGeneratedCard(s)ToCombat natively, so the
// generated-card hooks run (counted by CardGeneratedEntry, here regent.generatedThisCombat).
// Before, the cards were added without the notification.
void relic_cards_are_generated() {
    auto pearl = fight({RelicId::RADIANT_PEARL});
    check("Radiant Pearl's Luminesce is generated", pearl->battle.regent.generatedThisCombat >= 1);
    auto box = fight({RelicId::VEXING_PUZZLEBOX});
    check("Vexing Puzzlebox's card is generated", box->battle.regent.generatedThisCombat >= 1);

    auto music = fight({RelicId::MUSIC_BOX});
    BattleContext &m = music->battle;
    const int m0 = m.regent.generatedThisCombat;
    relics_card_played(m, make_card(CardId::STRIKE_IRONCLAD, false, m.require_card_uid()));
    check("Music Box's copy is generated", m.regent.generatedThisCombat == m0 + 1);

    auto sticks = fight({RelicId::BURNING_STICKS});
    BattleContext &b = sticks->battle;
    const int b0 = b.regent.generatedThisCombat;
    relics_exhausted(b, make_card(CardId::DEFEND_IRONCLAD, false, b.require_card_uid()), false);
    check("Burning Sticks' copy is generated", b.regent.generatedThisCombat == b0 + 1);

    auto hug = fight({RelicId::BIIIG_HUG});
    BattleContext &h = hug->battle;
    const int h0 = h.regent.generatedThisCombat;
    relics_shuffled(h);
    check("Biiig Hug's Soot is generated", h.regent.generatedThisCombat == h0 + 1 &&
                                           count_in(h.draw, h.drawCount, CardId::SOOT) >= 1);
}

void snapshot_roundtrip() {
    auto r = fight({RelicId::GAMBLING_CHIP, RelicId::LANTERN, RelicId::SAI});
    auto saved = std::make_unique<RunContext>();
    check("snapshot mid-turn-start choice restores", RunContext::restore(r->serialize(), *saved) &&
                                                     saved->serialize() == r->serialize());
    check("resume after restore", saved->battle.step(Action{ActionType::CONFIRM, 0, 0, 0}) &&
                                  saved->battle.player.energy == 4 && saved->battle.player.block == 7);
}
}  // namespace

int main() {
    blood_vial_after_inferno();
    lantern_after_gambling_chip_choice();
    bone_tea_before_crossbow();
    turn_one_debuffs_respect_artifact_and_hittable();
    stage_regressions();
    iron_club_and_mummified_hand_follow_bar_order();
    powers_before_relics_on_card_played();
    exhaust_relics_follow_bar_order();
    lords_parasol_awaits_relic_choices();
    lords_parasol_courier_checked_per_purchase();
    tea_of_discourtesy_random_positions();
    fur_coat_coordinate_only();
    relic_cards_are_generated();
    snapshot_roundtrip();
    std::cout << "native relic order: " << failures << " failures\n";
    return failures ? 1 : 0;
}
