// Source-exact fixtures extracted from the target native 41cef1ea decompile.
// This is an act/routing contract, not a full-run native parity claim.
#include "sts2/run.h"
#include "sts2/monsters.h"
#include <nlohmann/json.hpp>
#include <cassert>
#include <cctype>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <set>
using namespace sts2;
using nlohmann::json;
namespace {
std::string compact(std::string value) {
    std::string result;
    for (unsigned char c : value) if (c != '_') result += static_cast<char>(std::toupper(c));
    return result;
}
Encounter native_encounter(const std::string &name) {
    for (int id = 1; id < static_cast<int>(Encounter::COUNT); ++id)
        if (compact(encounter_def(id).key) == "SETUP" + compact(name)) return static_cast<Encounter>(id);
    return Encounter::INVALID;
}
MapPointType native_point(const std::string &name) {
    if (name == "Monster") return MapPointType::MONSTER;
    if (name == "Unknown") return MapPointType::UNKNOWN;
    if (name == "RestSite") return MapPointType::REST;
    if (name == "Treasure") return MapPointType::TREASURE;
    if (name == "Shop") return MapPointType::SHOP;
    if (name == "Elite") return MapPointType::ELITE;
    assert(false); return MapPointType::UNASSIGNED;
}
void mark_seen(NativeProgressContext &p, Encounter encounter) {
    const int id = static_cast<int>(encounter);
    p.seenEncounters[id / 64] |= std::uint64_t{1} << (id % 64);
}
}
int main() {
    static_assert(MAP_MAX_POINTS == 119, "Golden Path must not resize network node slots");
    std::ifstream input(std::filesystem::path(__FILE__).parent_path() / "fixtures/native_act_41cef1ea.json");
    json fixture; input >> fixture;
    assert(fixture["golden_path_rooms"].size() == 16);
    RunContext golden; golden.init(42, 0); golden.start_act(1);
    const auto beforeNiche = golden.runRng[RNG_NICHE].counter;
    const auto beforeUpfront = golden.runRng[RNG_UP_FRONT].counter;
    const int beforeFloor = golden.floor;
    assert(golden.add_relic(RelicId::GOLDEN_COMPASS));
    assert(golden.goldenPathAct == 1 && golden.map.rooms == 16 && golden.map.mapLength == 17);
    assert(golden.map.pointCount == 18 && golden.map.secondBossIdx == -1);
    assert(golden.floor == beforeFloor && golden.curRow == 0 && golden.curCol == 3);
    assert((golden.visitedLo & 1u) == 1u);
    assert(golden.runRng[RNG_NICHE].counter == beforeNiche);
    assert(golden.runRng[RNG_UP_FRONT].counter == beforeUpfront);
    for (int row = 0; row < 18; ++row) {
        const int node = golden.map.at(row, 3);
        assert(node >= 0);
        const auto &actual = golden.map.nodes[node];
        const auto type = row == 0 ? MapPointType::ANCIENT : row == 17 ? MapPointType::BOSS
            : native_point(fixture["golden_path_rooms"][row - 1].get<std::string>());
        assert(actual.type == static_cast<int>(type));
        assert(actual.childCount == (row < 17 ? 1 : 0));
        assert(actual.parentCount == (row > 0 ? 1 : 0));
        if (row < 17) assert(actual.children[0] == golden.map.at(row + 1, 3));
        if (row > 0) assert(actual.parents[0] == golden.map.at(row - 1, 3));
        for (int col = 0; col < 7; ++col) if (col != 3) assert(golden.map.at(row, col) == -1);
    }
    golden.unknownMonsterOdds = 0.45f; golden.unknownTreasureOdds = 0.12f;
    golden.unknownShopOdds = 0.18f;
    const auto beforeUnknown = golden.runRng[RNG_UNKNOWN_MAP_POINT].counter;
    for (int i = 0; i < 10; ++i) assert(golden.roll_unknown_room_type() == static_cast<int>(RoomType::EVENT));
    assert(golden.runRng[RNG_UNKNOWN_MAP_POINT].counter == beforeUnknown + 10);
    assert(golden.unknownMonsterOdds == 0.45f && golden.unknownTreasureOdds == 0.12f && golden.unknownShopOdds == 0.18f);
    RunContext restored;
    assert(RunContext::restore(golden.serialize(), restored));
    assert(restored.serialize() == golden.serialize());
    auto old = golden.serialize(); old[4] = 5;
    const auto untouched = restored.serialize();
    assert(!RunContext::restore(old, restored) && untouched == restored.serialize());
    auto malformed = golden; malformed.map.nodes[malformed.map.at(3, 3)].type = static_cast<int>(MapPointType::SHOP);
    assert(!RunContext::restore(malformed.serialize(), restored));
    golden.start_act(2);
    assert(golden.map.rooms == 13 && golden.goldenPathAct == 1);
    assert(golden.unknownMonsterOdds == 0.1f && golden.unknownTreasureOdds == 0.02f);

    NativeProgressContext progress; progress.underdocksUnlocked = true;
    std::set<int> nativeUnder;
    for (const auto &name : fixture["underdocks_encounters"]) {
        const auto id = native_encounter(name.get<std::string>());
        assert(id != Encounter::INVALID); nativeUnder.insert(static_cast<int>(id));
    }
    assert(nativeUnder.size() == 20);
    bool sawSeapunkNormal = false;
    for (int seed = 0; seed < 32; ++seed) {
        RunContext run; run.init_with_context(seed, 0, 3, progress);
        assert(run.act == 0 && run.actTypes[0] == ActType::UNDERDOCKS && run.map.rooms == 15);
        assert(std::string(event_info(run.ancientId)->name) == "NEOW");
        for (int i = 0; i < run.normalBagN; ++i) {
            assert(nativeUnder.count(run.normalBag[i]));
            assert(run.normalBag[i] != static_cast<int>(Encounter::SETUP_TOADPOLES_NORMAL));
            sawSeapunkNormal |= run.normalBag[i] == static_cast<int>(Encounter::SETUP_SEAPUNK_NORMAL);
        }
        for (int i = 0; i < run.eliteBagN; ++i) assert(nativeUnder.count(run.eliteBag[i]));
        assert(nativeUnder.count(run.bossEncounter));
        for (int i = 0; i < run.eventBagN; ++i) {
            const std::string name = event_info(run.eventBag[i])->name;
            assert(name != "AROMA_OF_CHAOS" && name != "DENSE_VEGETATION" && name != "SAPPHIRE_SEED");
        }
        assert(RunContext::restore(run.serialize(), restored));
    }
    assert(sawSeapunkNormal);
    const auto &seapunk = encounter_def(static_cast<int>(Encounter::SETUP_SEAPUNK_NORMAL));
    const auto &roster = encounter_pattern(seapunk.patternOff);
    assert(roster.count == 2 && roster.ids[0] == static_cast<int>(MonsterId::CALCIFIED_CULTIST)
        && roster.ids[1] == static_cast<int>(MonsterId::SEAPUNK));
    assert(encounters_share_tags(Encounter::SETUP_SEAPUNK_NORMAL, Encounter::SETUP_SEAPUNK_WEAK));

    progress.applyDiscoveryOrder = true;
    for (auto &word : progress.seenEncounters) word = 0;
    const auto underBosses = fixture["boss_discovery_order"]["Underdocks"];
    for (const auto &name : underBosses) {
        RunContext run; run.init_with_context(37, 0, 3, progress);
        const auto expected = native_encounter(name.get<std::string>());
        assert(run.bossEncounter == static_cast<int>(expected));
        mark_seen(progress, expected);
    }
    progress.underdocksDiscovered = false;
    for (int seed = 0; seed < 8; ++seed) {
        RunContext run; run.init_with_context(seed, 0, -1, progress);
        assert(run.actTypes[0] == ActType::UNDERDOCKS);
    }
    progress.underdocksDiscovered = true;
    for (int seed = 0; seed < 8; ++seed) {
        Rng selector(seed, "act_selection");
        const auto expected = selector.next_int_exclusive(2) ? ActType::UNDERDOCKS : ActType::OVERGROWTH;
        RunContext run; run.init_with_context(seed, 0, -1, progress); assert(run.actTypes[0] == expected);
    }
    progress.neowUnlocked = false; progress.darvUnlocked = false; progress.orobasUnlocked = false;
    RunContext noNeow; noNeow.init_with_context(17, 0, 3, progress);
    assert(noNeow.ancientId == -1 && noNeow.inBattle && noNeow.combatsFought == 1);
    assert(!noNeow.sharedAncientInAct[1] && !noNeow.sharedAncientInAct[2]);
    assert(RunContext::restore(noNeow.serialize(), restored));
    noNeow.inBattle = false; noNeow.screen = RunScreen::MAP; noNeow.start_act(1);
    assert(std::string(event_info(noNeow.ancientId)->name) != "OROBAS");

    progress.numberOfRuns = 0;
    RunContext first; first.init_with_context(17, 0, 3, progress);
    const auto startCounter = first.runRng[RNG_UNKNOWN_MAP_POINT].counter;
    assert(first.roll_unknown_room_type() == static_cast<int>(RoomType::EVENT));
    assert(first.roll_unknown_room_type() == static_cast<int>(RoomType::EVENT));
    assert(first.roll_unknown_room_type() == static_cast<int>(RoomType::MONSTER));
    assert(first.runRng[RNG_UNKNOWN_MAP_POINT].counter == startCounter);
    first.roll_unknown_room_type(); assert(first.runRng[RNG_UNKNOWN_MAP_POINT].counter == startCounter + 1);
    bool rejected = false;
    try { RunContext invalid; invalid.init_with_context(17, 0, 0, progress); }
    catch (const std::invalid_argument &) { rejected = true; }
    assert(rejected); // Explicit boundary: mandatory ByrdonisNest is not ported.
    progress.numberOfRuns = 1; progress.aeonglassSeen = false;
    mark_seen(progress, Encounter::SETUP_QUEEN_BOSS); mark_seen(progress, Encounter::SETUP_TEST_SUBJECT_BOSS);
    rejected = false;
    try { RunContext invalid; invalid.init_with_context(17, 0, 3, progress); }
    catch (const std::invalid_argument &) { rejected = true; }
    assert(rejected);
    std::cout << "native act source fixtures: GoldenCompass/Underdocks/progress/snapshot v6 passed\n";
}
