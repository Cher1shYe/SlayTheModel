// Potion effects checked one by one against the v0.111.0 decompilation (DEVLOG 43).
#include <cassert>
#include <iostream>
#include <memory>
#include <vector>

#include "sts2/battle.h"

using namespace sts2;

namespace {

std::unique_ptr<BattleContext> battle(int slots = 1, CardId fill = CardId::DEFEND_IRONCLAD) {
    auto b = std::make_unique<BattleContext>();
    std::vector<Card> deck;
    for (int i = 0; i < 20; ++i) deck.push_back(make_card(fill, false, static_cast<std::uint16_t>(i + 1)));
    for (int e = 1; e < 400; ++e) {
        try {
            b->init(static_cast<Encounter>(e), 9, deck.data(), 20, 10, 60, 80, nullptr, 0, nullptr, 0, 3, 0, 3, 0, 0);
            if (b->monsterCount == 1 && b->monsters[0].hp > 30 && b->pending.op == ChoiceOp::NONE) break;
        } catch (const std::exception &) {}
    }
    b->monsters[0].hp = b->monsters[0].maxHp = 500;
    for (int i = 1; i < slots; ++i) b->monsters[i] = b->monsters[0];
    b->monsterCount = slots;
    return b;
}

Card put(BattleContext &b, CardId id) {
    const Card c = make_card(id, false, b.require_card_uid());
    b.hand[b.handCount++] = c;
    return c;
}

void numbers() {
    auto b = battle();
    b->apply_potion(PotionId::STRENGTH_POTION, 0); assert(b->player.strength == 2);
    b->apply_potion(PotionId::DEXTERITY_POTION, 0); assert(b->player.dexterity == 2);
    b->apply_potion(PotionId::FYSH_OIL, 0); assert(b->player.strength == 3 && b->player.dexterity == 3);
    b->apply_potion(PotionId::HEART_OF_IRON, 0); assert(b->player_power(PowerId::PLATING) == 7);
    b->apply_potion(PotionId::LIQUID_BRONZE, 0); assert(b->player_power(PowerId::THORNS) == 3);
    b->apply_potion(PotionId::REGEN_POTION, 0); assert(b->player_power(PowerId::REGEN) == 5);
    b->apply_potion(PotionId::LUCKY_TONIC, 0); assert(b->player_power(PowerId::BUFFER) == 1);
    b->apply_potion(PotionId::VULNERABLE_POTION, 0); assert(b->monsters[0].vulnerable == 3);
    b->apply_potion(PotionId::WEAK_POTION, 0); assert(b->monsters[0].weak == 3);
    const int hp = b->player.hp;
    b->apply_potion(PotionId::BLOOD_POTION, 0); assert(b->player.hp == std::min(80, hp + 16));
}

void blessing_skips_cards_that_cannot_upgrade() {
    auto b = battle();
    b->handCount = 0;
    put(*b, CardId::STRIKE_IRONCLAD);
    put(*b, CardId::ASCENDERS_BANE);
    b->apply_potion(PotionId::BLESSING_OF_THE_FORGE, 0);
    assert(b->hand[0].upgraded && !b->hand[1].upgraded);
}

void touch_of_insanity_offers_only_cards_that_cost_something() {
    auto b = battle();
    b->handCount = 0;
    put(*b, CardId::ANGER);
    put(*b, CardId::ASCENDERS_BANE);
    const Card strike = put(*b, CardId::STRIKE_IRONCLAD);
    b->apply_potion(PotionId::TOUCH_OF_INSANITY, 0);
    assert(b->pending.op == ChoiceOp::MAKE_FREE && b->pending.count == 1 && b->pending.cards[0].uid == strike.uid);
}

void soldiers_stew_reaches_every_pile() {
    auto b = battle();
    b->exhaust[b->exhaustCount++] = make_card(CardId::STRIKE_IRONCLAD, false, b->require_card_uid());
    b->discard[b->discardCount++] = make_card(CardId::STRIKE_IRONCLAD, false, b->require_card_uid());
    b->apply_potion(PotionId::SOLDIERS_STEW, 0);
    assert(b->exhaust[0].bonusReplay == 1 && b->discard[0].bonusReplay == 1);
}

void area_potions_skip_reviving_enemies() {
    auto b = battle(2);
    b->monsters[1].reviving = true;
    const int hp0 = b->monsters[0].hp, hp1 = b->monsters[1].hp;
    b->apply_potion(PotionId::EXPLOSIVE_AMPOULE, 0);
    assert(b->monsters[0].hp == hp0 - 10 && b->monsters[1].hp == hp1);
    b->apply_potion(PotionId::POTION_OF_BINDING, 0);
    assert(b->monsters[0].weak == 1 && b->monsters[0].vulnerable == 1 && b->monsters[1].weak == 0);
}

void offered_cards_are_free_and_generated() {
    auto b = battle();
    b->apply_potion(PotionId::ATTACK_POTION, 0);
    assert(b->pending.op == ChoiceOp::OFFER_TO_HAND && b->pending.optional && b->pending.count == 3);
    for (int i = 0; i < 3; ++i) {
        assert(card_is_attack(b->pending.cards[i]) && card_def(b->pending.cards[i].id).pool == CardPool::IRONCLAD);
        for (int j = 0; j < i; ++j) assert(b->pending.cards[i].id != b->pending.cards[j].id);
    }
}

}  // namespace

int main() {
    numbers();
    blessing_skips_cards_that_cannot_upgrade();
    touch_of_insanity_offers_only_cards_that_cost_something();
    soldiers_stew_reaches_every_pile();
    area_potions_skip_reviving_enemies();
    offered_cards_are_free_and_generated();
    std::cout << "native potion effects: ok\n";
    return 0;
}
