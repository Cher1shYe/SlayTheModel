#include "sts2/battle.h"
#include "sts2/effects.h"
#include <cassert>
#include <iostream>
#include <memory>
using namespace sts2;

int main() {
    auto battle = std::make_unique<BattleContext>();
    auto &b = *battle;
    Card deck[10];
    for (int i = 0; i < 10; ++i) deck[i] = make_card(CardId::DEFEND_IRONCLAD, false, i + 1);
    b.init(Encounter::SETUP_AXEBOTS_NORMAL, 111, deck, 10, 10, 80, 80,
           nullptr, 0, nullptr, 0, 2);
    Card abundance = make_card(CardId::ABUNDANCE, false, b.require_card_uid());
    assert(colorless_effect(b, abundance, -1));
    assert(b.pending.op == ChoiceOp::OFFER_TO_HAND && b.pending.count == 3 && !b.pending.optional);
    for (int i = 0; i < b.pending.count; ++i) {
        const auto &c = b.pending.cards[i];
        assert(c.upgraded && card_def(c.id).pool == CardPool::IRONCLAD && card_type(c) == CardType::POWER);
        for (int j = 0; j < i; ++j) assert(c.id != b.pending.cards[j].id);
    }
    for (const auto &a : b.legal_actions()) assert(a.type != ActionType::CONFIRM);
    std::cout << "Abundance mandatory upgraded Power offer passed\n";
}
