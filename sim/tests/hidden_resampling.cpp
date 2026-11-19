#include "sts2/observe.h"

#include <algorithm>
#include <array>
#include <cmath>
#include <iostream>

using namespace sts2;

int main() {
    Card deck[10];
    for (int i = 0; i < 10; ++i)
        deck[i] = make_card(CardId::STRIKE_IRONCLAD, false, i + 1);
    BattleContext a;
    a.init(Encounter::SETUP_CEREMONIAL_BEAST_BOSS, 123, deck, 10, 0, 80, 80);
    a.drawCount = 5;
    a.knownTopCount = 1;
    const std::array<CardId, 4> hidden = {CardId::STRIKE_IRONCLAD,
        CardId::DEFEND_IRONCLAD, CardId::BASH, CardId::INFLAME};
    for (int i = 0; i < 4; ++i) a.draw[i] = make_card(hidden[i], false, 100 + i);
    a.draw[4] = make_card(CardId::DEFEND_IRONCLAD, true, 104);
    a.discardCount = 2;
    a.discard[0] = make_card(CardId::BASH, false, 105);
    a.discard[1] = make_card(CardId::INFLAME, false, 106);
    BattleContext b = a;
    std::reverse(b.draw, b.draw + 4);
    std::swap(b.discard[0], b.discard[1]);
    b.monsterAiRng = Rng(998877);
    b.shuffleRng = Rng(112233);
    b.cardGenerationRng = Rng(445566);
    b.rng = Rng(1);
    b.potionRng = Rng(2);
    b.cardSelectionRng = Rng(3);
    b.energyCostRng = Rng(4);
    b.targetRng = Rng(5);
    b.nicheRng = Rng(6);
    const auto original = public_combat_observation(a);
    if (original != public_combat_observation(b)) {
        std::cerr << "initial publicly indistinguishable states differ\n";
        return 1;
    }
    constexpr int samples = 6000;
    std::array<int, 4> count_a{}, count_b{};
    for (int seed = 0; seed < samples; ++seed) {
        BattleContext x = a, y = b;
        x.resample_hidden(seed + 12591);
        y.resample_hidden(seed + 12591);
        for (int i = 0; i < x.drawCount; ++i) {
            if (x.draw[i].uid != y.draw[i].uid) {
                std::cerr << "same sampled seed depends on original hidden draw order\n";
                return 1;
            }
        }
        for (int i = 0; i < x.discardCount; ++i) {
            if (x.discard[i].uid != y.discard[i].uid) {
                std::cerr << "same sampled seed depends on original hidden discard order\n";
                return 1;
            }
        }
        if (public_combat_observation(x) != original ||
            public_combat_observation(y) != original || x.draw[4].uid != 104 || y.draw[4].uid != 104 ||
            x.monsters[0].intentType != a.monsters[0].intentType ||
            x.monsters[0].intentDamage != a.monsters[0].intentDamage ||
            x.monsters[0].intentHits != a.monsters[0].intentHits) {
            std::cerr << "resampling changed public state or known top\n";
            return 1;
        }
        if (x.monsterAiRng.next_int(0, 100000) != y.monsterAiRng.next_int(0, 100000) ||
            x.shuffleRng.next_int(0, 100000) != y.shuffleRng.next_int(0, 100000) ||
            x.cardGenerationRng.next_int(0, 100000) != y.cardGenerationRng.next_int(0, 100000) ||
            x.rng.next_int(0, 100000) != y.rng.next_int(0, 100000) ||
            x.potionRng.next_int(0, 100000) != y.potionRng.next_int(0, 100000) ||
            x.cardSelectionRng.next_int(0, 100000) != y.cardSelectionRng.next_int(0, 100000) ||
            x.energyCostRng.next_int(0, 100000) != y.energyCostRng.next_int(0, 100000) ||
            x.targetRng.next_int(0, 100000) != y.targetRng.next_int(0, 100000) ||
            x.nicheRng.next_int(0, 100000) != y.nicheRng.next_int(0, 100000)) {
            std::cerr << "resampled future random streams depend on the original streams\n";
            return 1;
        }
        for (int i = 0; i < 4; ++i) {
            count_a[i] += x.draw[3].id == hidden[i];
            count_b[i] += y.draw[3].id == hidden[i];
        }
    }
    for (int i = 0; i < 4; ++i) {
        if (a.draw[i].id != hidden[i] || b.draw[3 - i].id != hidden[i]) {
            std::cerr << "original battle state was mutated\n";
            return 1;
        }
    }
    for (int i = 0; i < 4; ++i) {
        if (std::abs(count_a[i] - samples / 4) > 180 ||
            std::abs(count_b[i] - samples / 4) > 180 ||
            std::abs(count_a[i] - count_b[i]) > 220) {
            std::cerr << "hidden top distribution out of expected bounds: " << i
                      << " " << count_a[i] << " " << count_b[i] << '\n';
            return 1;
        }
    }
    // Identical public copies with different UIDs remain observationally
    // equivalent; UIDs must not be used as a policy feature or sorting key.
    BattleContext c = a;
    c.handCount = 0;
    c.draw[0] = make_card(CardId::STRIKE_IRONCLAD, false, 200);
    c.draw[1] = make_card(CardId::STRIKE_IRONCLAD, false, 201);
    BattleContext d = c;
    std::swap(d.draw[0], d.draw[1]);
    for (int seed = 1; seed <= 100; ++seed) {
        BattleContext x = c, y = d;
        x.resample_hidden(seed);
        y.resample_hidden(seed);
        x.draw_cards(3);
        y.draw_cards(3);
        if (public_combat_observation(x) != public_combat_observation(y)) {
            std::cerr << "duplicate-card UIDs altered visible outcome\n";
            return 1;
        }
    }
    std::cout << "public state and known top preserved across " << samples
              << " resamplings; hidden next-card distributions in bounds\n";
    return 0;
}
