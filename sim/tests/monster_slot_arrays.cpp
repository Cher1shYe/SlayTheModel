// Per-enemy play state must cover every enemy slot. With 4-entry arrays a sixth enemy read
// Necrobinder's damageTotal as Oblivion, so any character's attack applied Doom to it.
#include <cassert>
#include <iostream>
#include <memory>
#include <type_traits>

#include "sts2/battle.h"

using namespace sts2;

static_assert(std::extent_v<decltype(NecrobinderPlayState::oblivion)> == MAX_MONSTERS);
static_assert(std::extent_v<decltype(SilentPlayState::strangle)> == MAX_MONSTERS);
static_assert(std::extent_v<decltype(RegentState::hitsGivenThisTurn)> == MAX_MONSTERS);

namespace {

std::unique_ptr<BattleContext> battle_with_slots(int slots) {
    auto b = std::make_unique<BattleContext>();
    Card deck[12];
    for (int i = 0; i < 12; ++i) deck[i] = make_card(CardId::STRIKE_IRONCLAD, false, static_cast<std::uint16_t>(i + 1));
    bool ready = false;
    for (int e = 1; e < 400 && !ready; ++e) {
        try {
            b->init(static_cast<Encounter>(e), 7, deck, 12, 10, 80, 80, nullptr, 0, nullptr, 0, 3, 0, 3, 0, 0);
            ready = b->monsterCount == 1 && b->monsters[0].hp > 30 && b->monster_power(0, PowerId::DOOM) == 0;
        } catch (const std::exception &) {}
    }
    assert(ready);
    for (int i = 1; i < slots; ++i) b->monsters[i] = b->monsters[0];
    b->monsterCount = slots;
    return b;
}

void strike_first_enemy(BattleContext &b) {
    for (const Action &a : b.legal_actions()) {
        if (a.type == ActionType::PLAY_CARD && a.target == 0) {
            assert(b.step(a));
            return;
        }
    }
    assert(false);
}

}  // namespace

int main() {
    for (int slots = 1; slots <= MAX_MONSTERS; ++slots) {
        auto b = battle_with_slots(slots);
        strike_first_enemy(*b);
        for (int i = 0; i < slots; ++i) assert(b->monster_power(i, PowerId::DOOM) == 0);
    }
    {   // Oblivion on the last slot still applies its own Doom, and only there.
        auto b = battle_with_slots(MAX_MONSTERS);
        b->add_monster_power(MAX_MONSTERS - 1, PowerId::OBLIVION, 4);
        strike_first_enemy(*b);
        for (int i = 0; i + 1 < MAX_MONSTERS; ++i) assert(b->monster_power(i, PowerId::DOOM) == 0);
        assert(b->monster_power(MAX_MONSTERS - 1, PowerId::DOOM) == 4);
    }
    {   // Strangle on the last slot deals its damage after the card.
        auto b = battle_with_slots(MAX_MONSTERS);
        const int hp = b->monsters[MAX_MONSTERS - 1].hp;
        b->add_monster_power(MAX_MONSTERS - 1, PowerId::STRANGLE, 3);
        strike_first_enemy(*b);
        assert(b->monsters[MAX_MONSTERS - 1].hp == hp - 3);
    }
    std::cout << "monster slot arrays: ok\n";
    return 0;
}
