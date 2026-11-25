// RNG call sites checked line by line against the v0.111.0 decompilation (DEVLOG 42):
// which stream each effect uses, how many values it consumes, and the card pool it reads.
#include <cassert>
#include <cstring>
#include <iostream>
#include <memory>
#include <vector>

#include "sts2/battle.h"

using namespace sts2;

namespace {

using BattlePtr = std::unique_ptr<BattleContext>;

BattlePtr battle(const std::vector<CardId> &cards, std::uint64_t seed = 7, const std::vector<int> &relics = {}) {
    auto b = std::make_unique<BattleContext>();
    std::vector<Card> deck;
    for (std::size_t i = 0; i < cards.size(); ++i)
        deck.push_back(make_card(cards[i], false, static_cast<std::uint16_t>(i + 1)));
    for (int e = 1; e < 400; ++e) {
        try {
            b->init(static_cast<Encounter>(e), seed, deck.data(), static_cast<int>(deck.size()), 10, 500, 500,
                    relics.empty() ? nullptr : relics.data(), static_cast<int>(relics.size()),
                    nullptr, 0, 3, 0, 3, 0, 0);
            if (b->monsterCount == 1 && b->monsters[0].hp > 30 && b->pending.op == ChoiceOp::NONE) {
                b->monsters[0].hp = b->monsters[0].maxHp = 5000;
                return b;
            }
        } catch (const std::exception &) {}
    }
    assert(false);
    return b;
}

bool play(BattleContext &b, CardId id) {
    for (const Action &a : b.legal_actions())
        if (a.type == ActionType::PLAY_CARD && b.hand[a.hand].id == id) return b.step(a);
    return false;
}

void end_turn(BattleContext &b) {
    for (const Action &a : b.legal_actions())
        if (a.type == ActionType::END_TURN) { assert(b.step(a)); return; }
    assert(false);
}

void put_in_hand(BattleContext &b, CardId id) {
    b.hand[b.handCount++] = make_card(id, false, b.require_card_uid());
}

void pools_and_consumption() {
    auto b = battle(std::vector<CardId>(12, CardId::STRIKE_IRONCLAD));
    CardId options[static_cast<int>(CardId::COUNT)];
    const int n = b->combat_card_options(CardPool::IRONCLAD, options);
    assert(n > 1 && options[0] == CardId::AGGRESSION_CARD);
    for (int i = 0; i < n; ++i) {
        const CardDef &d = card_def(options[i]);
        assert(d.pool == CardPool::IRONCLAD && d.rarity != Rarity::BASIC && d.rarity != Rarity::ANCIENT &&
               d.rarity != Rarity::EVENT);
        if (i) assert(card_def(options[i - 1]).nativePoolOrder < d.nativePoolOrder);
    }
    assert(std::strcmp(card_native_entry(CardId::AGGRESSION_CARD), "AGGRESSION") == 0);
    // TakeRandom shuffles the whole list even for one card; NextItem consumes one value.
    int before = b->cardGenerationRng.counter;
    Card one;
    assert(b->distinct_for_combat(options, n, 1, &one) == 1);
    assert(b->cardGenerationRng.counter - before == n - 1);
    before = b->cardGenerationRng.counter;
    assert(b->next_for_combat(options, n).id != CardId::INVALID);
    assert(b->cardGenerationRng.counter - before == 1);
    before = b->cardGenerationRng.counter;
    assert(b->next_for_combat(options, 0).id == CardId::INVALID && b->cardGenerationRng.counter == before);
}

void infernal_blade_and_calamity_use_character_attacks() {
    for (std::uint64_t seed = 1; seed <= 120; ++seed) {
        auto b = battle(std::vector<CardId>(12, CardId::DEFEND_IRONCLAD), seed);
        b->handCount = 0;
        put_in_hand(*b, CardId::INFERNAL_BLADE);
        b->player.energy = 3;
        assert(play(*b, CardId::INFERNAL_BLADE) && b->handCount == 1);
        const CardDef &d = card_def(b->hand[0].id);
        assert(d.pool == CardPool::IRONCLAD && d.type == CardType::ATTACK);
    }
    auto b = battle(std::vector<CardId>(12, CardId::DEFEND_IRONCLAD), 3);
    b->handCount = 0;
    put_in_hand(*b, CardId::STRIKE_IRONCLAD);
    b->player.energy = 3;
    b->add_player_power(PowerId::CALAMITY, 2);
    assert(play(*b, CardId::STRIKE_IRONCLAD) && b->handCount == 2);
    for (int i = 0; i < 2; ++i) {
        assert(card_def(b->hand[i].id).pool == CardPool::IRONCLAD && card_is_attack(b->hand[i]));
        assert(!b->hand[i].freeCombat);
    }
}

void aggression_moves_amount_once() {
    auto b = battle(std::vector<CardId>(30, CardId::DEFEND_IRONCLAD));
    b->handCount = 0;
    for (int i = 0; i < 3; ++i) b->discard[b->discardCount++] = make_card(CardId::STRIKE_IRONCLAD, false, b->require_card_uid());
    b->add_player_power(PowerId::AGGRESSION, 1);
    end_turn(*b);
    int strikes = 0, upgraded = 0;
    for (int i = 0; i < b->handCount; ++i)
        if (b->hand[i].id == CardId::STRIKE_IRONCLAD) { ++strikes; upgraded += b->hand[i].upgraded; }
    assert(strikes == 1 && upgraded == 1);
}

void stampede_and_beat_down_use_shuffle_stream() {
    {
        auto b = battle(std::vector<CardId>(30, CardId::DEFEND_IRONCLAD));
        b->handCount = 0;
        put_in_hand(*b, CardId::STRIKE_IRONCLAD);
        b->add_player_power(PowerId::STAMPEDE, 1);
        const int selection = b->cardSelectionRng.counter, shuffle = b->shuffleRng.counter;
        end_turn(*b);
        assert(b->cardSelectionRng.counter == selection && b->shuffleRng.counter == shuffle + 1);
    }
    {
        auto b = battle(std::vector<CardId>(30, CardId::DEFEND_IRONCLAD));
        b->handCount = 0;
        put_in_hand(*b, CardId::BEAT_DOWN);
        b->player.energy = 9;
        for (int i = 0; i < 4; ++i) b->discard[b->discardCount++] = make_card(CardId::STRIKE_IRONCLAD, false, b->require_card_uid());
        const int selection = b->cardSelectionRng.counter, shuffle = b->shuffleRng.counter;
        assert(play(*b, CardId::BEAT_DOWN));
        assert(b->cardSelectionRng.counter == selection && b->shuffleRng.counter == shuffle + 3);
    }
}

void generated_draw_cards_use_shuffle_stream() {
    const std::vector<CardId> deck(20, CardId::DEFEND_IRONCLAD);
    auto plain = battle(deck, 5);
    auto antler = battle(deck, 5, {static_cast<int>(RelicId::BLESSED_ANTLER)});
    assert(antler->shuffleRng.counter == plain->shuffleRng.counter + 3);
    assert(antler->cardGenerationRng.counter == plain->cardGenerationRng.counter);
}

void reshuffle_is_independent_of_pile_order() {
    const CardId ids[] = {CardId::STRIKE_IRONCLAD, CardId::DEFEND_IRONCLAD, CardId::BASH, CardId::ANGER,
                          CardId::AGGRESSION_CARD, CardId::DEMON_FORM_CARD, CardId::SHRUG_IT_OFF, CardId::POMMEL_STRIKE};
    std::vector<CardId> sequence[2];
    for (int pass = 0; pass < 2; ++pass) {
        auto b = battle(std::vector<CardId>(8, CardId::DEFEND_IRONCLAD), 11);
        b->drawCount = b->handCount = b->discardCount = 0;
        for (int i = 0; i < 8; ++i)
            b->discard[b->discardCount++] = make_card(ids[pass ? 7 - i : i], false, static_cast<std::uint16_t>(900 + i));
        b->shuffle_discard_into_draw();
        for (int i = 0; i < b->drawCount; ++i) sequence[pass].push_back(b->draw[i].id);
    }
    assert(sequence[0] == sequence[1] && sequence[0].size() == 8);
}

void bottled_potential_shuffles_the_discard_too() {
    auto b = battle(std::vector<CardId>(12, CardId::DEFEND_IRONCLAD));
    for (int i = 0; i < 6; ++i) b->discard[b->discardCount++] = make_card(CardId::STRIKE_IRONCLAD, false, b->require_card_uid());
    const int total = b->handCount + b->drawCount + b->discardCount;
    b->apply_potion(PotionId::BOTTLED_POTENTIAL, 0);
    assert(b->discardCount == 0 && b->handCount == 5 && b->handCount + b->drawCount == total);
}

void alchemize_consumes_rng_with_a_full_belt() {
    auto b = battle(std::vector<CardId>(12, CardId::DEFEND_IRONCLAD));
    for (int i = 0; i < b->potionSlots; ++i) b->potions[i] = static_cast<int>(PotionId::BLOCK_POTION);
    b->potionCount = b->potionSlots;
    const int before = b->potionRng.counter;
    assert(b->gain_random_combat_potion() == PotionId::INVALID);
    assert(b->potionRng.counter == before + 2);
}

}  // namespace

int main() {
    pools_and_consumption();
    infernal_blade_and_calamity_use_character_attacks();
    aggression_moves_amount_once();
    stampede_and_beat_down_use_shuffle_stream();
    generated_draw_cards_use_shuffle_stream();
    reshuffle_is_independent_of_pile_order();
    bottled_potential_shuffles_the_discard_too();
    alchemize_consumes_rng_with_a_full_belt();
    std::cout << "native RNG usage: ok\n";
    return 0;
}
