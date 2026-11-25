// Ironclad cards and powers checked against the v0.111.0 decompilation (DEVLOG 44).
#include <cassert>
#include <iostream>
#include <memory>
#include <vector>

#include "sts2/battle.h"

using namespace sts2;

namespace {

std::unique_ptr<BattleContext> battle(int slots = 1) {
    auto b = std::make_unique<BattleContext>();
    std::vector<Card> deck;
    for (int i = 0; i < 20; ++i) deck.push_back(make_card(CardId::DEFEND_IRONCLAD, false, static_cast<std::uint16_t>(i + 1)));
    for (int e = 1; e < 400; ++e) {
        try {
            b->init(static_cast<Encounter>(e), 13, deck.data(), 20, 10, 500, 500, nullptr, 0, nullptr, 0, 3, 0, 3, 0, 0);
            if (b->monsterCount == 1 && b->monsters[0].hp > 30 && b->pending.op == ChoiceOp::NONE) break;
        } catch (const std::exception &) {}
    }
    b->monsters[0].hp = b->monsters[0].maxHp = 5000;
    for (int i = 1; i < slots; ++i) b->monsters[i] = b->monsters[0];
    b->monsterCount = slots;
    b->handCount = 0;
    b->player.energy = 9;
    return b;
}

Card put(BattleContext &b, CardId id, bool upgraded = false) {
    const Card c = make_card(id, upgraded, b.require_card_uid());
    b.hand[b.handCount++] = c;
    return c;
}

bool play(BattleContext &b, std::uint16_t uid) {
    for (const Action &a : b.legal_actions())
        if (a.type == ActionType::PLAY_CARD && b.hand[a.hand].uid == uid) return b.step(a);
    return false;
}

int count_in_hand(const BattleContext &b, CardId id) {
    int n = 0;
    for (int i = 0; i < b.handCount; ++i) n += b.hand[i].id == id;
    return n;
}

void armaments_only_touches_upgradable_cards() {
    auto b = battle();
    const Card a = put(*b, CardId::ARMAMENTS, true);
    put(*b, CardId::ASCENDERS_BANE);
    put(*b, CardId::STRIKE_IRONCLAD);
    assert(play(*b, a.uid));
    for (int i = 0; i < b->handCount; ++i)
        assert(b->hand[i].upgraded == (b->hand[i].id == CardId::STRIKE_IRONCLAD));
    auto c = battle();
    const Card plain = put(*c, CardId::ARMAMENTS);
    put(*c, CardId::ASCENDERS_BANE);
    const Card strike = put(*c, CardId::STRIKE_IRONCLAD);
    put(*c, CardId::DEFEND_IRONCLAD);
    assert(play(*c, plain.uid));
    assert(c->pending.op == ChoiceOp::UPGRADE && c->pending.count == 2);
    for (int i = 0; i < c->pending.count; ++i) assert(c->pending.cards[i].id != CardId::ASCENDERS_BANE);
    (void)strike;
}

void area_attacks_skip_reviving_enemies() {
    auto b = battle(2);
    b->monsters[1].reviving = true;
    int targets[MAX_MONSTERS];
    assert(b->living_enemies(targets) == 1 && targets[0] == 0);
    const Card t = put(*b, CardId::THUNDERCLAP);
    assert(play(*b, t.uid));
    assert(b->monsters[0].vulnerable == 1 && b->monsters[1].vulnerable == 0);
}

void pillage_continues_through_hellraiser_strikes() {
    auto b = battle();
    b->drawCount = 0;
    b->draw[b->drawCount++] = make_card(CardId::SHRUG_IT_OFF, false, b->require_card_uid());  // stays
    b->draw[b->drawCount++] = make_card(CardId::DEFEND_IRONCLAD, false, b->require_card_uid());
    b->draw[b->drawCount++] = make_card(CardId::STRIKE_IRONCLAD, false, b->require_card_uid());
    b->draw[b->drawCount++] = make_card(CardId::STRIKE_IRONCLAD, false, b->require_card_uid());  // top
    b->add_player_power(PowerId::HELLRAISER, 1);
    const Card p = put(*b, CardId::PILLAGE);
    assert(play(*b, p.uid));
    assert(count_in_hand(*b, CardId::DEFEND_IRONCLAD) == 1 && b->drawCount == 1);
    assert(b->draw[0].id == CardId::SHRUG_IT_OFF);
}

void juggling_clones_before_the_third_attack_resolves() {
    auto b = battle();
    b->add_player_power(PowerId::JUGGLING, 1);
    const Card first = put(*b, CardId::STRIKE_IRONCLAD), second = put(*b, CardId::STRIKE_IRONCLAD);
    const Card rampage = put(*b, CardId::RAMPAGE);
    assert(play(*b, first.uid) && play(*b, second.uid) && play(*b, rampage.uid));
    assert(count_in_hand(*b, CardId::RAMPAGE) == 1);
    for (int i = 0; i < b->handCount; ++i) if (b->hand[i].id == CardId::RAMPAGE) assert(b->hand[i].bonusDamage == 0);
}

void free_attack_is_spent_by_every_play_iteration() {
    auto b = battle();
    b->add_player_power(PowerId::FREE_ATTACK, 2);
    Card c = make_card(CardId::STRIKE_IRONCLAD, false, b->require_card_uid());
    c.bonusReplay = 1;
    b->hand[b->handCount++] = c;
    const int energy = b->player.energy;
    assert(play(*b, c.uid));
    assert(b->player.energy == energy && b->player_power(PowerId::FREE_ATTACK) == 0);
}

void corruption_is_applied_after_cost_increases() {
    auto b = battle();
    b->add_player_power(PowerId::CORRUPTION, 1);
    const Card shrug = put(*b, CardId::SHRUG_IT_OFF);
    assert(b->energy_cost_in_combat(shrug) == 0);
    const Card whirl = put(*b, CardId::WHIRLWIND);
    b->add_player_power(PowerId::FREE_ATTACK, 1);
    assert(b->energy_cost_in_combat(whirl) == -1);   // X costs still spend all energy
}

}  // namespace

int main() {
    armaments_only_touches_upgradable_cards();
    area_attacks_skip_reviving_enemies();
    pillage_continues_through_hellraiser_strikes();
    juggling_clones_before_the_third_attack_resolves();
    free_attack_is_spent_by_every_play_iteration();
    corruption_is_applied_after_cost_increases();
    std::cout << "native Ironclad effects: ok\n";
    return 0;
}
