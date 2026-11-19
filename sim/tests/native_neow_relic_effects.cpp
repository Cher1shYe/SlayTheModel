// Source-port regression cases for v0.111.0 Neow relics. These assertions are
// derived from the native methods; they are not a substitute for DLL fixtures.
#include "sts2/run.h"
#include "sts2/relics.h"
#include "sts2/card_candidates.h"
#include "sts2/relic_card_rewards.h"
#include <cassert>
#include <iostream>
#include <memory>
#include <set>

using namespace sts2;

namespace {
std::unique_ptr<RunContext> base() {
    auto run = std::make_unique<RunContext>();
    run->init_seed("NEOWRELICPORT", 10);
    run->screen = RunScreen::SHOP;
    return run;
}
int slot(const RunContext &run, RelicId id) {
    for (int i = 0; i < run.relicCount; ++i)
        if (run.relics[i] == static_cast<int>(id)) return i;
    assert(false); return -1;
}
void roundtrip(RunContext &run) {
    const auto bytes = run.serialize();
    auto restored = std::make_unique<RunContext>();
    assert(RunContext::restore(bytes, *restored));
    assert(restored->serialize() == bytes);
    run = *restored;
}
void simple_pickups() {
    auto run = base();
    const int before = run->deckCount;
    assert(run->add_relic(RelicId::DOWSING_ROD));
    assert(run->deckCount == before + 1);
    assert(run->deck[before].id == CardId::DOWSING);
    assert(card_type(run->deck[before]) == CardType::QUEST);

    run = base();
    run->deckCount = 0;
    for (const auto id : {CardId::STRIKE_IRONCLAD, CardId::DEFEND_IRONCLAD,
                          CardId::STRIKE_IRONCLAD, CardId::DEFEND_IRONCLAD})
        run->deck[run->deckCount++] = run->make_run_card(id, false);
    card_apply_upgrade(run->deck[2]);
    assert(run->add_relic(RelicId::NEOWS_TALISMAN));
    assert(!run->deck[0].upgraded && !run->deck[1].upgraded);
    assert(run->deck[2].upgraded && run->deck[3].upgraded);
    roundtrip(*run);

    run = base();
    const int gold = run->gold;
    assert(run->add_relic(RelicId::SCROLL_BOXES));
    assert(run->gold == gold && run->cardGrid.kind == 5);
}
void tablet_choice() {
    auto run = base();
    const int before = run->deckCount;
    const int randomBefore = run->playerRng[PRNG_REWARDS].counter;
    assert(run->add_relic(RelicId::HEFTY_TABLET));
    assert(run->deckCount == before); // no curse before the choice is resolved
    assert(run->cardGrid.kind == 16 && run->cardGrid.count == 3);
    assert(run->cardGrid.minSelect == 0 && run->cardGrid.maxSelect == 1);
    assert(run->playerRng[PRNG_REWARDS].counter == randomBefore + 3); // no upgrade draws
    std::set<CardId> ids;
    for (int i = 0; i < 3; ++i) {
        const auto &card = run->cardGrid.cards[i];
        assert(card_def(card.id).rarity == Rarity::RARE);
        assert(card_def(card.id).pool == CardPool::IRONCLAD);
        assert(!card.upgraded);
        ids.insert(card.id);
    }
    assert(ids.size() == 3 && card_grid_valid(*run));
    roundtrip(*run);
    auto skipped = std::make_unique<RunContext>(*run);
    assert(confirm_card_grid(*skipped));
    assert(skipped->deckCount == before + 1 && skipped->deck[before].id == CardId::INJURY);
    assert(skipped->cardGrid.kind == 0);
    const CardId chosen = run->cardGrid.cards[1].id;
    assert(select_card_grid(*run, 1));
    assert(run->cardGrid.kind == 0 && run->deckCount == before + 2);
    assert(run->deck[before].id == chosen && run->deck[before + 1].id == CardId::INJURY);
    roundtrip(*run);
}
void kaleidoscope_rewards() {
    auto run = base();
    const int before = run->deckCount;
    const int rewardsBefore = run->playerRng[PRNG_REWARDS].counter;
    const int nicheBefore = run->runRng[RNG_NICHE].counter;
    const float pityBefore = run->cardRarityOdds;
    assert(run->add_relic(RelicId::KALEIDOSCOPE));
    assert(run->deckCount == before && run->screen == RunScreen::REWARDS);
    assert(run->playerRng[PRNG_REWARDS].counter == rewardsBefore + 18);
    assert(run->runRng[RNG_NICHE].counter == nicheBefore + 6);
    assert(run->cardRarityOdds == pityBefore);
    int sets = 0;
    for (int i = 0; i < MAX_CARD_REWARDS; ++i) {
        if (!run->rewardCardPending[i]) continue;
        ++sets;
        assert(run->rewardCardCounts[i] == 3);
        std::set<CardPool> pools;
        for (int j = 0; j < 3; ++j) {
            const auto pool = card_def(run->rewardCards[i][j].id).pool;
            assert(pool != CardPool::IRONCLAD && pool != CardPool::COLORLESS);
            pools.insert(pool);
        }
        assert(pools.size() == 3);
    }
    assert(sets == 2);
    roundtrip(*run);
}
void fishing_rod() {
    auto run = base();
    assert(run->add_relic(RelicId::FISHING_ROD));
    const int rod = slot(*run, RelicId::FISHING_ROD);
    assert(relic_aux_persistent(RelicId::FISHING_ROD));
    run->deckCount = 1;
    run->deck[0] = run->make_run_card(CardId::BASH, false);
    run->battle.encounter = Encounter::SETUP_BATTLEWORN_DUMMY_V1;
    const int nicheBefore = run->runRng[RNG_NICHE].counter;
    relics_after_combat_end_lifecycle(*run);
    relics_after_combat_end_lifecycle(*run);
    assert(run->relicAux[rod] == 2 && !run->deck[0].upgraded);
    // The encounter's native room type wins over map/event routing flags.
    run->battle.encounter = Encounter::SETUP_BYRDONIS_ELITE;
    run->combatIsElite = false;
    relics_after_combat_end_lifecycle(*run);
    assert(run->relicAux[rod] == 2);
    run->battle.encounter = Encounter::SETUP_NIBBITS_WEAK;
    relics_after_combat_end_lifecycle(*run);
    assert(run->relicAux[rod] == 3 && run->deck[0].upgraded);
    assert(run->runRng[RNG_NICHE].counter == nicheBefore + 1);
    for (int i = 0; i < 3; ++i) relics_after_combat_end_lifecycle(*run);
    assert(run->relicAux[rod] == 6);
    assert(run->runRng[RNG_NICHE].counter == nicheBefore + 1); // empty eligible list
    roundtrip(*run);

    // Hook enumeration snapshots active relics: the rod gets its final hook on
    // the very combat Toy Box melts it, then stops on subsequent combats.
    run = base();
    assert(run->add_relic(RelicId::FISHING_ROD));
    const int rod2 = slot(*run, RelicId::FISHING_ROD);
    run->relicWax[rod2] = true;
    const int toy = run->relicCount++;
    run->relics[toy] = static_cast<int>(RelicId::TOY_BOX);
    // Put Toy Box before the rod, keeping the rod wax flag with its object.
    std::swap(run->relics[rod2], run->relics[toy]);
    std::swap(run->relicWax[rod2], run->relicWax[toy]);
    run->toyBoxCombats = 2;
    run->battle.encounter = Encounter::SETUP_NIBBITS_WEAK;
    relics_after_combat_end_lifecycle(*run);
    assert(run->relicMelted[toy] && run->relicAux[toy] == 1);
    relics_after_combat_end_lifecycle(*run);
    assert(run->relicAux[toy] == 1);
}
}

int main() {
    simple_pickups();
    tablet_choice();
    kaleidoscope_rewards();
    fishing_rod();
    std::cout << "native_neow_relic_effects: source-port regression passed\n";
}
