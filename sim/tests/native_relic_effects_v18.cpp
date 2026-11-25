// Source-port regressions for the v18 relic-effect audit (docs/content-audit.md §11):
// Amethyst Aubergine, Orichalcum timing, Permafrost, Parrying Shield timing, Bread, Belt
// Buckle discard, Fairy -> AfterPotionUsed, Booming Conch energy, Brilliant Scarf (late),
// Spiked Gauntlets (0-cost Powers), Diamond Diadem, Fiddle, Signet Ring, Fur Coat,
// Philosopher's Stone summons, Whispering Earring, Lord's Parasol.
// Expectations come from the v0.111.0 decompilation, not from a DLL trace.
#include "sts2/run.h"
#include "sts2/relics.h"
#include "sts2/monsters.h"
#include "sts2/card_candidates.h"
#include <cassert>
#include <iostream>
#include <memory>
#include <string>
#include <algorithm>

using namespace sts2;

namespace {
std::unique_ptr<RunContext> run(const std::string &seed = "V18RELICS") {
    auto r = std::make_unique<RunContext>();
    r->init_seed(seed, 10);
    r->screen = RunScreen::MAP;
    return r;
}
std::unique_ptr<RunContext> fight(std::initializer_list<RelicId> relics, Encounter e = Encounter::SETUP_SLIMES_WEAK,
                                  const std::string &seed = "V18RELICS") {
    auto r = run(seed);
    for (RelicId id : relics) assert(r->add_relic(id));
    r->begin_combat(e);
    return r;
}
bool has(const RunContext &r, RunActionType type) {
    for (auto a : r.legal_actions()) if (a.type == type) return true;
    return false;
}
void roundtrip(const RunContext &r) {
    auto saved = std::make_unique<RunContext>();
    assert(RunContext::restore(r.serialize(), *saved));
    assert(saved->serialize() == r.serialize());
}
int extra_gold_total(const RunContext &r) {
    int n = 0;
    for (int g : r.extraGoldRewards) n += g == 15;
    return n;
}

void amethyst_aubergine() {
    auto r = fight({RelicId::AMETHYST_AUBERGINE});
    const int gold = r->gold;
    r->combatIsElite = r->combatIsBoss = false;
    r->battle.outcome = Outcome::PLAYER_VICTORY;
    r->finish_combat();
    assert(r->gold == gold && extra_gold_total(*r) == 1);  // a GoldReward(15), not 10 gold
    assert(r->step({RunActionType::TAKE_GOLD_REWARD, 2}) && r->gold == gold + 15);
}

void orichalcum_and_permafrost() {
    auto r = fight({RelicId::ORICHALCUM});
    BattleContext &b = r->battle;
    b.player.block = 4;                  // e.g. Plating resolved after the VeryEarly check
    relics_turn_end(b, true);
    assert(b.player.block == 10);
    b.player.block = 4;
    relics_turn_end(b, false);
    assert(b.player.block == 4);

    auto p = fight({RelicId::PERMAFROST});
    BattleContext &c = p->battle;
    c.player.block = 0;
    relics_card_played(c, make_card(CardId::INFLAME, false, 900));
    assert(c.player.block == 7);
}

void parrying_shield_after_turn_end() {
    auto r = fight({RelicId::PARRYING_SHIELD, RelicId::CLOAK_CLASP});
    BattleContext &b = r->battle;
    int before = 0;
    for (int m = 0; m < b.monsterCount; ++m) before += b.monsters[m].hp;
    b.player.block = 9;  // Cloak Clasp raises it to >= 10 at BeforeSideTurnEnd
    relics_turn_end(b, false);
    int mid = 0;
    for (int m = 0; m < b.monsterCount; ++m) mid += b.monsters[m].hp;
    assert(mid == before && b.player.block >= 10);
    relics_after_side_turn_end(b);
    int after = 0;
    for (int m = 0; m < b.monsterCount; ++m) after += b.monsters[m].hp;
    assert(after < before);
}

void bread_energy() {
    auto r = fight({RelicId::BREAD});
    BattleContext &b = r->battle;
    // v29: ModifyMaxEnergy (+1 except turn 1) at the reset; turn-1 LoseEnergy(2) at AfterSideTurnStart.
    b.turn = 1; b.player.energy = relics_energy_for_turn(b, 3); assert(b.player.energy == 3);
    relics_after_side_turn_start(b); assert(b.player.energy == 1);
    b.turn = 2; b.player.energy = relics_energy_for_turn(b, 3); assert(b.player.energy == 4);
    relics_after_side_turn_start(b); assert(b.player.energy == 4);
}

void belt_buckle_and_fairy() {
    auto r = run();
    assert(r->add_relic(RelicId::BELT_BUCKLE) && r->add_relic(RelicId::REPTILE_TRINKET));
    r->add_potion(PotionId::FAIRY_IN_ABOTTLE);
    r->begin_combat(Encounter::SETUP_SLIMES_WEAK);
    BattleContext &b = r->battle;
    const int dex = b.player.dexterity;
    assert(b.potionCount == 1);
    // Fairy is a real use: AfterPotionUsed (Belt Buckle re-applies, Reptile Trinket +3).
    b.player.hp = 0;
    assert(b.try_fairy_revive() && b.player.hp > 0 && b.potionCount == 0);
    assert(b.player.dexterity == dex + 2 && b.player.tempStrength == 3);

    auto d = run("V18BUCKLE");
    assert(d->add_relic(RelicId::BELT_BUCKLE));
    d->add_potion(PotionId::FIRE_POTION);
    d->begin_combat(Encounter::SETUP_SLIMES_WEAK);
    BattleContext &e = d->battle;
    const int dex0 = e.player.dexterity;
    assert(e.step(Action{ActionType::DISCARD_POTION, 0, 0, 0}) && e.potionCount == 0);
    assert(e.player.dexterity == dex0 + 2);  // AfterPotionDiscarded
}

void booming_conch() {
    auto r = fight({RelicId::BOOMING_CONCH}, Encounter::SETUP_PHROG_PARASITE_ELITE);
    BattleContext &b = r->battle;
    assert(b.turn == 1);
    b.player.energy = relics_energy_for_turn(b, 3); relics_after_side_turn_start(b);   // v29: energy at AfterSideTurnStart
    assert(b.player.energy == 4 && relics_modify_draw(b, 5) == 7);
    auto n = fight({RelicId::BOOMING_CONCH});
    BattleContext &c = n->battle;
    c.player.energy = relics_energy_for_turn(c, 3); relics_after_side_turn_start(c);
    assert(c.player.energy == 3 && relics_modify_draw(c, 5) == 5);
}

void scarf_and_gauntlets() {
    auto r = fight({RelicId::SPIKED_GAUNTLETS, RelicId::BRILLIANT_SCARF});
    BattleContext &b = r->battle;
    const Card inflame = make_card(CardId::INFLAME, false, 901);  // 1-cost Power
    Card zero = inflame; card_modify_cost(zero, 0, true, 2 | 4);  // free this turn
    b.manualCardsPlayedThisTurn = 0;
    assert(b.energy_cost_in_combat(inflame) == 2);
    assert(b.energy_cost_in_combat(zero) == 1);  // 0-cost Powers also cost 1 more
    b.manualCardsPlayedThisTurn = 4;             // the fifth play: Late hook zeroes it
    assert(b.energy_cost_in_combat(inflame) == 0);
}

void diamond_diadem() {
    auto r = fight({RelicId::DIAMOND_DIADEM});
    BattleContext &b = r->battle;
    assert(b.turn == 1 && b.player.block >= 20 && b.player_power(PowerId::BLUR) == 1);
}

void fiddle() {
    auto r = fight({RelicId::FIDDLE});
    BattleContext &b = r->battle;
    assert(relics_modify_draw(b, 5) == 7);
    const int hand = b.handCount;
    b.draw_cards(1);                 // a card effect during the player's turn
    assert(b.handCount == hand);
    b.inMonsterTurn = true;          // draws on the enemy side are allowed
    b.draw_cards(1);
    assert(b.handCount == hand + 1 || b.drawCount + b.discardCount == 0);
}

void signet_ring() {
    auto r = run();
    const int gold = r->gold;
    assert(r->add_relic(RelicId::SIGNET_RING) && r->gold == gold + 888);
}

void fur_coat() {
    auto r = run("V18FURCOAT");
    assert(r->add_relic(RelicId::FUR_COAT));
    assert(r->furCoatAct == r->act && r->furCoatCount == 8);
    for (int i = 0; i < r->furCoatCount; ++i) {
        const int idx = r->map.at(r->furCoatRow[i], r->furCoatCol[i]);
        assert(idx >= 0);
        const auto t = static_cast<MapPointType>(r->map.nodes[idx].type);
        assert(t == MapPointType::MONSTER || t == MapPointType::ELITE);
    }
    roundtrip(*r);
    // Deterministic: Rng(Seed + hash("FUR_COAT")) on the same map.
    auto again = run("V18FURCOAT");
    assert(again->add_relic(RelicId::FUR_COAT));
    for (int i = 0; i < 8; ++i)
        assert(again->furCoatRow[i] == r->furCoatRow[i] && again->furCoatCol[i] == r->furCoatCol[i]);
    // A combat on a marked coordinate starts every enemy at 1 HP; elsewhere unchanged.
    r->curRow = r->furCoatRow[0]; r->curCol = r->furCoatCol[0];
    r->begin_combat(Encounter::SETUP_SLIMES_WEAK);
    for (int m = 0; m < r->battle.monsterCount; ++m)
        if (r->battle.monsters[m].alive) assert(r->battle.monsters[m].hp == 1);
    assert(r->battle.furCoatActive);
    auto u = run("V18FURCOAT");
    assert(u->add_relic(RelicId::FUR_COAT));
    u->curRow = -1; u->curCol = -1;
    u->begin_combat(Encounter::SETUP_SLIMES_WEAK);
    for (int m = 0; m < u->battle.monsterCount; ++m)
        if (u->battle.monsters[m].alive) assert(u->battle.monsters[m].hp > 1);
}

void philosophers_stone_summons() {
    auto r = fight({RelicId::PHILOSOPHERS_STONE});
    BattleContext &b = r->battle;
    assert(b.turn >= 1);
    const int before = b.monsterCount;
    spawn_monster(b, MonsterId::SHRINKER_BEETLE, -1);
    assert(b.monsterCount == before + 1 || b.monsters[before - 1].id == MonsterId::SHRINKER_BEETLE);
    int idx = -1;
    for (int m = 0; m < b.monsterCount; ++m) if (b.monsters[m].id == MonsterId::SHRINKER_BEETLE) idx = m;
    assert(idx >= 0 && b.monsters[idx].strength >= 1);
}

void whispering_earring() {
    for (int s = 0; s < 6; ++s) {
        auto r = fight({RelicId::WHISPERING_EARRING}, Encounter::SETUP_SLIMES_WEAK, "V18EARRING" + std::to_string(s));
        BattleContext &b = r->battle;
        // Energy was really spent; nothing playable remains unless 13 cards were played.
        assert(b.player.energy >= 0 && b.pending.op == ChoiceOp::NONE && !b.vakuuSelecting);
        bool playable = false;
        for (int i = 0; i < b.handCount; ++i) playable |= b.hand_card_playable_now(i);
        assert(!playable || b.cardsPlayedThisTurn >= 13 || b.outcome != Outcome::UNDECIDED);
        assert(b.manualCardsPlayedThisTurn == 0);
        roundtrip(*r);
    }
}

void lords_parasol() {
    auto r = run("V18PARASOL");
    assert(r->add_relic(RelicId::LORDS_PARASOL) && r->add_relic(RelicId::MAW_BANK));
    const int gold = r->gold + 12;  // Maw Bank pays on entering the room
    const int removals = r->cardShopRemovalsUsed, deck = r->deckCount;
    r->map.nodes[r->map.startIdx].type = static_cast<int>(MapPointType::SHOP);
    r->enter_map_point(r->map.startIdx);
    assert(r->screen == RunScreen::SHOP && r->gold == gold && !r->mawBankPurchased);
    for (int i = 0; i < r->shopCount; ++i) assert(r->shopSold[i]);
    const int deckAfterCards = r->deckCount;
    assert(deckAfterCards >= deck + r->shopCount);
    // Choices opened by bought relics (e.g. Gnarled Hammer) come first -- v29: the remaining relics
    // and the potions are bought only after each choice -- then the removal.
    for (int guard = 0; guard < 16 && r->cardGrid.kind && r->cardGrid.service != 5; ++guard) {
        assert(!has(*r, RunActionType::LEAVE_SHOP));
        if (r->cardGrid.preview) {
            if (r->cardGrid.selectedCount) assert(confirm_card_grid(*r));
            else assert(r->step({RunActionType::CANCEL_GRID_PREVIEW, 0}));
            continue;
        }
        for (int i = 0; i < r->deckCount && r->cardGrid.selectedCount < std::max(1, int(r->cardGrid.minSelect)); ++i)
            select_card_grid(*r, i);
        assert(confirm_card_grid(*r));
    }
    for (int i = 0; i < r->shopRelicCount; ++i) assert(r->shopRelicSold[i]);
    const int deckAfterBuying = r->deckCount;
    // The removal is mandatory and free.
    assert(r->parasolRemovalPending == false && r->cardGrid.kind == 6 && r->cardGrid.service == 5);
    assert(!has(*r, RunActionType::CANCEL_GRID_SELECTION) && !has(*r, RunActionType::LEAVE_SHOP));
    roundtrip(*r);
    assert(select_card_grid(*r, 0));
    while (r->cardGrid.kind) assert(confirm_card_grid(*r));
    assert(r->removalUsed && r->cardShopRemovalsUsed == removals + 1 && r->gold == gold && !r->mawBankPurchased);
    assert(r->deckCount == deckAfterBuying - 1);
}
}  // namespace

int main() {
    amethyst_aubergine();
    orichalcum_and_permafrost();
    parrying_shield_after_turn_end();
    bread_energy();
    belt_buckle_and_fairy();
    booming_conch();
    scarf_and_gauntlets();
    diamond_diadem();
    fiddle();
    signet_ring();
    fur_coat();
    philosophers_stone_summons();
    whispering_earring();
    lords_parasol();
    std::cout << "native_relic_effects_v18 ok\n";
    return 0;
}
