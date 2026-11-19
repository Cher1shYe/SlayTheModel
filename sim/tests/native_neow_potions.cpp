// Expectations transcribed from PhialHolster, NeowsSacrifice, Ambergris and
// CombatManager in the pinned native source. Not a DLL fixture comparison.
#include "sts2/run.h"
#include "sts2/potion_slots.h"
#include <cassert>
#include <memory>
#include <iostream>

using namespace sts2;

int main() {
    auto owned = std::make_unique<RunContext>();
    auto &r = *owned;
    r.init(123, 10);
    const int before = r.potionSlots;
    r.add_relic(RelicId::PHIAL_HOLSTER);
    assert(r.potionSlots == before + 1 && r.potionCount == 2);
    assert(r.potions[0] != r.potions[1]); // factory batch samples without replacement
    const int cards = r.deckCount;
    r.add_relic(RelicId::NEOWS_SACRIFICE);
    assert(r.potions[2] == static_cast<int>(PotionId::AMBERGRIS));
    assert(r.deckCount == cards + 1 && r.deck[cards].id == CardId::GUILTY);
    r.hp = 1; r.maxHp = 81;
    assert(r.use_potion_out_of_combat(2) && r.hp == 41);

    // Native TryToProcure simply fails on full slots; the relic still adds Guilty.
    r.init(123, 10);
    r.add_potion(PotionId::BLOCK_POTION); r.add_potion(PotionId::FIRE_POTION);
    const int fullCards = r.deckCount;
    r.add_relic(RelicId::NEOWS_SACRIFICE);
    assert(r.potionCount == 2 && r.potions[0] == static_cast<int>(PotionId::BLOCK_POTION));
    assert(r.deckCount == fullCards + 1 && r.deck[fullCards].id == CardId::GUILTY);

    r.init(123, 10);
    r.add_relic(RelicId::SOZU);
    const auto rngBefore = r.runRng[RNG_COMBAT_POTION_GENERATION].counter;
    r.add_relic(RelicId::PHIAL_HOLSTER);
    assert(r.potionSlots == 3 && r.potionCount == 0);
    assert(r.runRng[RNG_COMBAT_POTION_GENERATION].counter > rngBefore);

    auto battle = std::make_unique<BattleContext>();
    auto &b = *battle;
    Card deck[10];
    for (int i = 0; i < 10; ++i) deck[i] = make_card(CardId::DEFEND_IRONCLAD, false, i + 1);
    b.init(Encounter::SETUP_AXEBOTS_NORMAL, 111, deck, 10, 10, 1, 81,
           nullptr, 0, nullptr, 0, 2);
    assert(b.turn == 1 && b.combatRound == 1);
    // No Draw permits the ordinary start-of-turn hand draw.
    b.add_player_power(PowerId::NO_DRAW, 1);
    b.draw_cards(1, true);
    assert(b.handCount == 6);
    b.draw_cards(1, false);
    assert(b.handCount == 6);
    b.apply_potion(PotionId::AMBERGRIS, -1);
    assert(b.player.hp == 41 && b.player_power(PowerId::AMBERGRIS) == 1);
    const int move = b.monsters[0].move;
    const auto ai = b.monsterAiRng.counter;
    b.add_player_power(PowerId::INTANGIBLE, 1);
    b.add_player_power(PowerId::PLATING, 2);
    b.add_player_power(PowerId::SHRINK, 2);
    b.monsters[0].power[static_cast<int>(PowerId::PLATING)] = 3;
    const int monsterBlock = b.monsters[0].block;
    b.end_player_turn();
    assert(b.turn == 2 && b.combatRound == 1 && b.player.hp == 41);
    assert(b.player_power(PowerId::AMBERGRIS) == 0);
    assert(b.player_power(PowerId::INTANGIBLE) == 1);
    assert(b.player_power(PowerId::PLATING) == 1);
    assert(b.player_power(PowerId::SHRINK) == 1);
    assert(b.player_power(PowerId::NO_DRAW) == 0);
    // Enemy Plating's round-1 start hook also fires on extra player turns.
    assert(b.monsters[0].block == monsterBlock + 3);
    assert(b.monsters[0].move == move && b.monsterAiRng.counter == ai);
    assert(b.handCount == 5 && b.player.energy == 3);
    b.end_player_turn();
    assert(b.turn == 3 && b.combatRound == 2);
    assert(b.player_power(PowerId::PLATING) == 0);
    assert(b.player_power(PowerId::SHRINK) == 0);
    // Plating can absorb the capped hit; enemy action is proved by its fixed
    // Hammer -> One-Two transition, not by requiring unblocked HP loss.
    assert(b.monsters[0].move != move && b.player_power(PowerId::INTANGIBLE) == 0);
    std::cout << "Neow potion source regression passed\n";
}
