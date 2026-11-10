// Extra NoSL checks added with the 2026-11-10 fix. They cover fields the first
// audit named but did not execute (Sly), state the player cannot see (cost
// modifier stack), and the CombatOrbs run stream wiring. FAIL = finding.
#include "sts2/observe.h"
#include "sts2/search.h"
#include <algorithm>
#include <functional>
#include <iostream>
#include <memory>
#include <string>

using namespace sts2;
int failures = 0, checks = 0;
void check(const std::string &name, bool ok) {
    ++checks;
    if (!ok) ++failures;
    std::cout << (ok ? "PASS " : "FAIL ") << name << '\n' << std::flush;
}
std::unique_ptr<BattleContext> base() {
    auto b = std::make_unique<BattleContext>();
    Card deck[10];
    for (int i = 0; i < 10; ++i)
        deck[i] = make_card(i % 2 ? CardId::DEFEND_IRONCLAD : CardId::STRIKE_IRONCLAD, false, i + 1);
    b->init(Encounter::SETUP_CEREMONIAL_BEAST_BOSS, 1234, deck, 10, 0, 40, 80);
    b->handCount = b->drawCount = b->discardCount = b->exhaustCount = b->knownTopCount = 0;
    b->turn = 2;
    b->player.energy = 2;
    b->monsters[0].hp = 30;
    b->hand[b->handCount++] = make_card(CardId::POMMEL_STRIKE, false, 100);
    b->hand[b->handCount++] = make_card(CardId::STRIKE_IRONCLAD, false, 101);
    b->hand[b->handCount++] = make_card(CardId::DEFEND_IRONCLAD, false, 102);
    return b;
}
// Field-by-field equality except the UID (operator== compares UIDs only).
bool same_card(const Card &x, const Card &y) {
    return !card_canonical_less(x, y) && !card_canonical_less(y, x);
}
// Two piles that differ only by the order of `first` and `second`.
void pile_case(const std::string &name, CardId id, const std::function<void(Card &)> &mark) {
    auto a = base();
    a->drawCount = 3;
    a->draw[0] = make_card(id, false, 200);
    a->draw[1] = make_card(id, false, 201);
    a->draw[2] = make_card(CardId::BASH, false, 202);
    mark(a->draw[1]);
    auto b = std::make_unique<BattleContext>(*a);
    std::swap(b->draw[0], b->draw[1]);
    check(name + ": public draw bag independent of true order",
          public_combat_observation(*a) == public_combat_observation(*b));
    int diff = 0;
    for (unsigned seed = 1; seed <= 100; ++seed) {
        BattleContext x(*a), y(*b);
        x.resample_hidden(seed); y.resample_hidden(seed);
        for (int i = 0; i < x.drawCount; ++i) diff += same_card(x.draw[i], y.draw[i]) ? 0 : 1;
    }
    std::cout << "DETAIL " << name << " differing_sampled_positions=" << diff << '\n';
    check(name + ": same resample independent of true order", diff == 0);
    // Discard is resampled the same way.
    BattleContext c(*a), d(*b);
    std::swap(c.draw, c.discard); std::swap(c.drawCount, c.discardCount);
    std::swap(d.draw, d.discard); std::swap(d.drawCount, d.discardCount);
    diff = 0;
    for (unsigned seed = 1; seed <= 100; ++seed) {
        BattleContext x(c), y(d);
        x.resample_hidden(seed); y.resample_hidden(seed);
        for (int i = 0; i < x.discardCount; ++i) diff += same_card(x.discard[i], y.discard[i]) ? 0 : 1;
    }
    check(name + ": discard resample independent of true order", diff == 0);
}
int main() {
    pile_case("slyThisTurn", CardId::STRIKE_IRONCLAD, [](Card &c) { c.slyThisTurn = true; });
    pile_case("slyThisCombat", CardId::STRIKE_IRONCLAD, [](Card &c) { c.slyThisCombat = true; });
    pile_case("bonusBlock", CardId::DEFEND_IRONCLAD, [](Card &c) { c.bonusBlock = 7; });
    pile_case("retainThisTurn", CardId::DEFEND_IRONCLAD, [](Card &c) { c.retainThisTurn = true; });
    pile_case("bonusDamage", CardId::THRASH, [](Card &c) { c.bonusDamage = 30; });
    // Same visible cost, different (hidden) modifier expiry: still canonical.
    pile_case("cost_modifier_expiry", CardId::BASH, [](Card &c) {
        c.costModifierCount = 1;
        c.costModifiers[0].amount = 0;
        c.costModifiers[0].expiration = 2;
    });

    // CombatOrbs: combat starts from the run's stream (RunRngType index 10).
    {
        Rng runRngs[12];
        for (int i = 0; i < 12; ++i) runRngs[i] = Rng(1000 + i);
        Card deck[5];
        for (int i = 0; i < 5; ++i) deck[i] = make_card(CardId::STRIKE_IRONCLAD, false, i + 1);
        BattleContext b;
        b.init(Encounter::SETUP_CEREMONIAL_BEAST_BOSS, 99, deck, 5, 0, 80, 80, nullptr, 0, nullptr, 0,
               3, 3, 3, 0, 0, nullptr, runRngs);
        Rng expect = runRngs[10];
        check("orb_rng: combat uses the run CombatOrbs stream",
              b.orbRng.next_int(0, 1 << 30) == expect.next_int(0, 1 << 30));
        BattleContext s(b), t(b);
        s.resample_hidden(7);
        check("orb_rng: resample replaces the real stream",
              s.orbRng.next_int(0, 1 << 30) != t.orbRng.next_int(0, 1 << 30));
    }
    std::cout << "SUMMARY checks=" << checks << " failures=" << failures << '\n';
    return failures ? 1 : 0;
}
