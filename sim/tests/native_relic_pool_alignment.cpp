// Native declaration-order bag fixture + the actual first combat captured by
// parity/stage/reports/opening/20261118T141057Z-PARITY0001-892e4e.
#include "sts2/run.h"
#include "sts2/monsters.h"
#include "sts2/relics.h"
#include "sts2/relic_raw_rarity.h"
#include "port_root.h"
#include <nlohmann/json.hpp>
#include <cassert>
#include <fstream>
#include <iostream>
#include <memory>
#include <stdexcept>
#include <vector>
using namespace sts2;
namespace {
RelicId by_name(const std::string &name) {
    for (int i = 1; i < static_cast<int>(RelicId::COUNT); ++i)
        if (name == relic_def(static_cast<RelicId>(i)).name) return static_cast<RelicId>(i);
    throw std::logic_error("Native pool fixture names an unregistered relic: " + name);
}
std::vector<RelicId> fixture_pool(const nlohmann::json &fixture, const char *name) {
    std::vector<RelicId> out;
    for (const auto &model : fixture["pools"][name]["models"]) out.push_back(by_name(model.get<std::string>()));
    return out;
}
void check_bag(const RelicBagState &actual, const std::vector<RelicId> &source,
               bool shared, std::uint64_t epochs, Rng &rng) {
    // Independent vector/dictionary-insertion-order replay of RelicGrabBag.
    std::vector<int> rarityOrder;
    std::vector<std::vector<RelicId>> groups;
    for (RelicId id : source) {
        if (!relic_epoch_unlocked(epochs, id)) continue;
        const int rarity = relic_raw_rarity(id);
        if (!shared && (rarity < 1 || rarity > 4)) continue;
        auto found = std::find(rarityOrder.begin(), rarityOrder.end(), rarity);
        if (found == rarityOrder.end()) {
            rarityOrder.push_back(rarity); groups.push_back({id});
        } else groups[found - rarityOrder.begin()].push_back(id);
    }
    for (std::size_t i = 0; i < groups.size(); ++i) {
        auto &group = groups[i];
        rng.shuffle(group.data(), static_cast<int>(group.size()));
        const int slot = rarityOrder[i] - 1;
        if (slot < 0 || slot >= 4) continue;
        assert(actual.counts[slot] == static_cast<int>(group.size()));
        for (std::size_t j = 0; j < group.size(); ++j)
            assert(actual.entries[slot][j] == static_cast<int>(group[j]));
    }
}
}
int main() {
    std::ifstream input(port_root() / "tests/fixtures/native_relic_pools_41cef1ea.json");
    nlohmann::json fixture; input >> fixture;
    const auto shared = fixture_pool(fixture, "Shared");
    auto player = shared;
    const auto ironclad = fixture_pool(fixture, "Ironclad");
    player.insert(player.end(), ironclad.begin(), ironclad.end());
    assert(shared.size() == 118 && ironclad.size() == 8);
    assert(std::find(shared.begin(), shared.end(), RelicId::TWISTED_FUNNEL) == shared.end());
    assert(std::find(shared.begin(), shared.end(), RelicId::LOOMING_FRUIT) != shared.end());
    const auto seed = Rng::deterministic_hash_code(Rng::canonicalize_seed("PARITY0001"));
    for (std::uint64_t epochs : {~std::uint64_t{0}, std::uint64_t{0}}) {
        auto run = std::make_unique<RunContext>();
        run->seed = seed;
        run->nativeProgress.revealedEpochs = epochs;
        run->runRng[RNG_UP_FRONT] = Rng(seed, "up_front");
        run->init_relic_bags();
        Rng expected(seed, "up_front");
        check_bag(run->sharedRelicBag, shared, true, epochs, expected);
        check_bag(run->playerRelicBag, player, false, epochs, expected);
        assert(run->runRng[RNG_UP_FRONT].counter == expected.counter);
        assert(run->runRng[RNG_UP_FRONT].state() == expected.state());
        if (epochs) assert(expected.counter == 230);
    }
    NativeProgressContext progress;
    progress.numberOfRuns = 0; progress.applyDiscoveryOrder = true;
    progress.underdocksUnlocked = true; progress.underdocksDiscovered = false;
    progress.aeonglassSeen = false;
    for (auto &word : progress.seenEncounters) word = 0;
    auto run = std::make_unique<RunContext>();
    run->init_seed_with_context("PARITY0001", 10, -1, progress);
    auto restored = std::make_unique<RunContext>();
    assert(RunContext::restore(run->serialize(), *restored));
    assert(restored->serialize() == run->serialize()); // unsupported bag candidates are valid state
    assert(run->eventRelics[1] == static_cast<int>(RelicId::GOLDEN_PEARL));
    assert(run->step({RunActionType::EVENT_CHOICE, 1}));
    assert(run->step({RunActionType::EVENT_CHOICE, 0}));
    assert(run->step({RunActionType::MOVE, run->map.at(1, 0)}));
    assert(run->battle.encounter == Encounter::SETUP_TOADPOLES_WEAK);
    assert(run->battle.monsterCount == 2);
    assert(run->battle.monsters[0].id == MonsterId::TOADPOLE && run->battle.monsters[0].hp == 25);
    assert(run->battle.monsters[1].id == MonsterId::TOADPOLE && run->battle.monsters[1].hp == 26);
    const CardId nativeHand[] = {CardId::STRIKE_IRONCLAD, CardId::STRIKE_IRONCLAD,
        CardId::BASH, CardId::STRIKE_IRONCLAD, CardId::DEFEND_IRONCLAD};
    assert(run->battle.handCount == 5);
    for (int i = 0; i < 5; ++i) assert(run->battle.hand[i].id == nativeHand[i]);

    // Juzu used to be an explicit coverage stop. It remains in the same native
    // bag and is now drawn normally, with its actual rule covered separately.
    run->playerRelicBag.entries[0][0] = static_cast<int>(RelicId::JUZU_BRACELET);
    run->playerRelicBag.counts[0] = 1;
    assert(run->pull_relic(Rarity::COMMON) == RelicId::JUZU_BRACELET);
    assert(run->playerRelicBag.counts[0] == 0);
    std::cout << "native relic pool grouping, RNG and captured first encounter passed\n";
}
