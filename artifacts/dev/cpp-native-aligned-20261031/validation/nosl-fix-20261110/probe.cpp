// Read-only NoSL audit of the current engine. FAIL is an audit finding,
// not an assertion weakened to fit the implementation. No game rules patched.
#include "sts2/observe.h"
#include "sts2/search.h"
#include "sts2/defect.h"
#include <algorithm>
#include <iostream>
#include <memory>
#include <string>
#include <vector>

using namespace sts2;
int failures = 0, checks = 0;
void check(const char *name, bool ok) {
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
using ActionFeatures = std::vector<std::vector<float>>;
ActionFeatures options(const BattleContext &b) {
    ActionFeatures out;
    for (const auto &a : b.legal_actions()) out.push_back(combat_action_features(b, a));
    std::sort(out.begin(), out.end());
    return out;
}
void searches(const char *name, const BattleContext &a, const BattleContext &b) {
    check((std::string(name) + ": same public root and legal choices").c_str(),
          public_combat_observation(a) == public_combat_observation(b) && options(a) == options(b));
    const auto before = public_combat_observation(a);
    int mismatches = 0;
    for (unsigned seed = 1; seed <= 24; ++seed) {
        auto x = mcts(a, 128, 4.242640687, seed, true, false, .05);
        auto y = mcts(b, 128, 4.242640687, seed, true, false, .05);
        const bool valid = x.simulations == 128 && y.simulations == 128 &&
            x.actions.size() == 1 && y.actions.size() == 1 && !x.victory && !y.victory;
        if (!valid) { check("hidden MCTS returns one real action, never a simulated victory", false); return; }
        if (combat_action_features(a, x.actions[0]) != combat_action_features(b, y.actions[0])) {
            ++mismatches;
            std::cout << "DETAIL " << name << " mismatch search_seed=" << seed
                      << " left_type=" << int(x.actions[0].type) << " left_hand=" << int(x.actions[0].hand)
                      << " right_type=" << int(y.actions[0].type) << " right_hand=" << int(y.actions[0].hand) << '\n';
        }
    }
    std::cout << "DETAIL " << name << " action_mismatches=" << mismatches << "/24\n";
    check((std::string(name) + ": root decision independent of hidden state").c_str(), mismatches == 0);
    check((std::string(name) + ": source unchanged").c_str(), public_combat_observation(a) == before);
}
int main() {
    // Control: ordinary distinct cards, all nine previously covered RNG streams.
    auto a = base();
    a->drawCount = 4;
    const CardId ids[] = {CardId::BASH, CardId::DEFEND_IRONCLAD, CardId::INFLAME, CardId::STRIKE_IRONCLAD};
    for (int i = 0; i < 4; ++i) a->draw[i] = make_card(ids[i], false, 200 + i);
    auto b = std::make_unique<BattleContext>(*a);
    std::reverse(b->draw, b->draw + b->drawCount);
    b->rng = Rng(1); b->shuffleRng = Rng(2); b->cardGenerationRng = Rng(3);
    b->potionRng = Rng(4); b->cardSelectionRng = Rng(5); b->energyCostRng = Rng(6);
    b->targetRng = Rng(7); b->monsterAiRng = Rng(8); b->nicheRng = Rng(9);
    searches("distinct_cards_control", *a, *b);

    // Same-name cards whose visible growth differs; only hidden order changes.
    a = base(); a->drawCount = 2;
    a->draw[0] = make_card(CardId::THRASH, false, 200);
    a->draw[1] = make_card(CardId::THRASH, false, 201);
    a->draw[0].bonusDamage = 0; a->draw[1].bonusDamage = 30;
    b = std::make_unique<BattleContext>(*a); std::swap(b->draw[0], b->draw[1]);
    int sameSeedDifferentDraws = 0;
    for (unsigned seed = 1; seed <= 100; ++seed) {
        auto x = std::make_unique<BattleContext>(*a), y = std::make_unique<BattleContext>(*b);
        x->resample_hidden(seed); y->resample_hidden(seed);
        if (x->draw[1].bonusDamage != y->draw[1].bonusDamage) ++sameSeedDifferentDraws;
    }
    std::cout << "DETAIL growth_cards same_seed_different_draws=" << sameSeedDifferentDraws << "/100\n";
    check("growth_cards: same sample independent of true order", sameSeedDifferentDraws == 0);
    searches("growth_cards", *a, *b);

    // Public pile encoding must be permutation invariant for all visible fields.
    a = base(); a->drawCount = 2;
    a->draw[0] = make_card(CardId::DEFEND_IRONCLAD, false, 200);
    a->draw[1] = make_card(CardId::DEFEND_IRONCLAD, false, 201);
    a->draw[1].bonusBlock = 7;
    b = std::make_unique<BattleContext>(*a); std::swap(b->draw[0], b->draw[1]);
    check("bonusBlock: public draw bag independent of true order",
          public_combat_observation(*a) == public_combat_observation(*b));
    a->draw[1].bonusBlock = 0; a->draw[1].retainThisTurn = true;
    *b = *a; std::swap(b->draw[0], b->draw[1]);
    check("retainThisTurn: public draw bag independent of true order",
          public_combat_observation(*a) == public_combat_observation(*b));

    // The new orb RNG is invisible, and must not survive determinization.
    a = base(); a->orbRng = Rng(1); a->defect.orbCapacity = 3;
    a->hand[0] = make_card(CardId::CHAOS, true, 100);
    a->drawCount = 2;
    a->draw[0] = make_card(CardId::STRIKE_IRONCLAD, false, 200);
    a->draw[1] = make_card(CardId::DEFEND_IRONCLAD, false, 201);
    b = std::make_unique<BattleContext>(*a); b->orbRng = Rng(2);
    auto x = std::make_unique<BattleContext>(*a), y = std::make_unique<BattleContext>(*b);
    x->resample_hidden(42); y->resample_hidden(42);
    const int ox = x->orbRng.next_int(0, 1000000), oy = y->orbRng.next_int(0, 1000000);
    std::cout << "DETAIL orb_rng same_sample_outputs=" << ox << ',' << oy << '\n';
    check("orb_rng: replaced independently of real stream", ox == oy);
    int orbTypes = 0;
    for (unsigned seed = 1; seed <= 100; ++seed) {
        *x = *a; x->resample_hidden(seed); defect_channel_random(*x);
        orbTypes |= 1 << int(x->defect.orbs[0].id);
    }
    int uniqueOrbs = 0;
    for (int bits = orbTypes; bits; bits >>= 1) uniqueOrbs += bits & 1;
    std::cout << "DETAIL orb_rng unique_next_orbs_across_100_samples=" << uniqueOrbs << '\n';
    check("orb_rng: simulations sample alternative orb outcomes", uniqueOrbs > 1);
    searches("orb_rng", *a, *b);

    // Legitimately known top cards are retained, not treated as a leak.
    a = base(); a->drawCount = 3; a->knownTopCount = 1;
    for (int i = 0; i < 3; ++i) a->draw[i] = make_card(ids[i], false, 200 + i);
    b = std::make_unique<BattleContext>(*a); std::swap(b->draw[0], b->draw[1]);
    bool kept = true;
    for (unsigned seed = 1; seed <= 100; ++seed) {
        *x = *a; *y = *b; x->resample_hidden(seed); y->resample_hidden(seed);
        kept &= x->draw[2].uid == 202 && y->draw[2].uid == 202 &&
                public_combat_observation(*x) == public_combat_observation(*y);
    }
    check("known_top: preserves legitimately visible top", kept);
    std::cout << "SUMMARY checks=" << checks << " failures=" << failures << '\n';
    return failures ? 1 : 0;
}
